import json
import logging
import re
import threading
import uuid
from pathlib import Path

from django.contrib.auth.models import User
from django.conf import settings
from django.db.models import Avg, Count, Q, Sum
from django.http import StreamingHttpResponse
from django.db import transaction
from django.utils import timezone
from rest_framework import generics, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from .access_control import (AccessDenied, audit_access, build_access_scope, filter_documents_for_user,
    filter_knowledge_bases_for_user, filter_traces_for_user, require_capability)
from .agent.actions import execute_agent_action
from .agent.services import get_ragops_agent_state, resume_ragops_agent, run_ragops_agent
from .case_factory import create_regression_case_from_eval_case, create_regression_case_from_trace, create_regression_case_from_user_feedback
from .eval_runs import reconcile_stale_eval_run, reconcile_stale_eval_runs
from .experiments import refresh_experiment_plan, start_experiment_plan
from .chunkers import list_chunk_methods
from .document_parsing.service import create_parse_run
from .indexing import ParseRunNotReadyError
from .index_lifecycle import create_index_run, index_health
from .health import health_report
from .models import (
    ChatMessage,
    ChatSession,
    Chunk,
    Document,
    DocumentIndexRun,
    DocumentParseRun,
    DocumentParseBenchmarkCase,
    DocumentParseEvalRun,
    KnowledgeBase,
    ModelCallLog,
    RagAgentAction,
    RagBenchmarkCase,
    RagEvalCaseResult,
    RagEvalRun,
    RagExperimentPlan,
    RagConfigDeployment,
    RagConfigVersion,
    RagTrace,
    RagUserFeedback,
)
from .serializers import (
    ChatMessageSerializer,
    ChatSessionSerializer,
    ChunkSerializer,
    DocumentPageSerializer,
    DocumentIndexRunSerializer,
    DocumentParseRunSerializer,
    DocumentParseBenchmarkCaseSerializer,
    DocumentParseEvalRunSerializer,
    DocumentSerializer,
    KnowledgeBaseSerializer,
    ModelCallLogSerializer,
    RagAgentActionSerializer,
    RagBenchmarkCaseSerializer,
    RagEvalRunDetailSerializer,
    RagEvalRunListSerializer,
    RagExperimentPlanSerializer,
    RagConfigDeploymentSerializer,
    RagConfigVersionSerializer,
    RagTraceDetailSerializer,
    RagTraceListSerializer,
    RagUserFeedbackSerializer,
    RegisterSerializer,
)
from .services import answer_question, preview_chunks, stream_answer_events
from .vector_store import get_vector_store

RAGAS_DEFAULT_METRICS = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]

logger = logging.getLogger(__name__)
stream_slots = threading.BoundedSemaphore(getattr(settings, "RAG_STREAM_MAX_ACTIVE_PER_PROCESS", 32))


AGENT_THREAD_ID_PATTERN = re.compile(r"^[A-Za-z0-9:_\-.]{1,180}$")


def build_agent_thread_business_key(user_id, kb_id, trace_id, eval_run_id, compare_eval_run_id):
    return (
        f"u:{user_id}|kb:{kb_id or 'none'}|trace:{trace_id or 'none'}|"
        f"eval:{eval_run_id or 'none'}|compare:{compare_eval_run_id or 'none'}"
    )


def normalize_agent_thread_id(user_id, business_key, provided):
    value = str(provided or "").strip()
    if value:
        if not AGENT_THREAD_ID_PATTERN.match(value):
            raise ValueError("thread_id contains unsupported characters.")
        return value
    compact_key = business_key.replace("|", ":").replace(":", "_")
    return f"ragops:{compact_key}:{uuid.uuid4().hex[:12]}"


def get_action_thread_id(action_obj) -> str:
    payload = action_obj.payload or {}
    return str((payload.get("agent_thread") or {}).get("thread_id") or "").strip()


def is_action_thread_awaiting_human(user, thread_id: str) -> bool:
    if not thread_id:
        return False
    try:
        state = get_ragops_agent_state(user=user, thread_id=thread_id)
    except PermissionError:
        return False
    return bool(state and state.get("awaiting_human"))


def sse_event(event: str, data: dict | list) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def model_usage_summary(request):
    queryset = ModelCallLog.objects.filter(owner=request.user).select_related("kb", "session", "message", "trace", "eval_run")
    kb_id = request.query_params.get("kb")
    trace_id = request.query_params.get("trace")
    if kb_id:
        queryset = queryset.filter(kb_id=kb_id)
    if trace_id:
        queryset = queryset.filter(trace_id=trace_id)

    totals = queryset.aggregate(
        call_count=Count("id"),
        prompt_tokens=Sum("prompt_tokens"),
        completion_tokens=Sum("completion_tokens"),
        total_tokens=Sum("total_tokens"),
        estimated_cost=Sum("estimated_cost"),
        avg_latency_ms=Avg("latency_ms"),
    )
    failed_count = queryset.filter(status="failed").count()
    slow_threshold = getattr(settings, "MODEL_SLOW_REQUEST_MS", 3000)
    slow_count = queryset.filter(latency_ms__gte=slow_threshold).count()

    by_model = list(
        queryset.values("model", "call_type", "provider")
        .annotate(
            call_count=Count("id"),
            prompt_tokens=Sum("prompt_tokens"),
            completion_tokens=Sum("completion_tokens"),
            total_tokens=Sum("total_tokens"),
            estimated_cost=Sum("estimated_cost"),
            avg_latency_ms=Avg("latency_ms"),
            failed_count=Count("id", filter=Q(status="failed")),
        )
        .order_by("-estimated_cost", "-total_tokens", "model")[:30]
    )

    trace_costs = list(
        queryset.exclude(trace__isnull=True)
        .values("trace", "trace__question")
        .annotate(
            call_count=Count("id"),
            total_tokens=Sum("total_tokens"),
            estimated_cost=Sum("estimated_cost"),
            latency_ms=Sum("latency_ms"),
        )
        .order_by("-estimated_cost", "-total_tokens", "-trace")[:20]
    )

    recent_calls = queryset.order_by("-created_at", "-id")[:20]
    slow_calls = queryset.filter(latency_ms__gte=slow_threshold).order_by("-latency_ms", "-created_at")[:10]
    failed_calls = queryset.filter(status="failed").order_by("-created_at", "-id")[:10]

    return Response(
        {
            "totals": {
                "call_count": totals["call_count"] or 0,
                "prompt_tokens": totals["prompt_tokens"] or 0,
                "completion_tokens": totals["completion_tokens"] or 0,
                "total_tokens": totals["total_tokens"] or 0,
                "estimated_cost": round(totals["estimated_cost"] or 0, 8),
                "avg_latency_ms": round(totals["avg_latency_ms"] or 0),
                "failed_count": failed_count,
                "slow_count": slow_count,
                "slow_threshold_ms": slow_threshold,
            },
            "by_model": by_model,
            "trace_costs": trace_costs,
            "recent_calls": ModelCallLogSerializer(recent_calls, many=True).data,
            "slow_calls": ModelCallLogSerializer(slow_calls, many=True).data,
            "failed_calls": ModelCallLogSerializer(failed_calls, many=True).data,
        }
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def ragops_agent_run(request):
    message = (request.data.get("message") or "").strip()
    if not message:
        return Response({"detail": "message is required"}, status=status.HTTP_400_BAD_REQUEST)

    def optional_int(name):
        value = request.data.get(name)
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ValueError(f"{name} must be an integer.")

    try:
        kb_id = optional_int("kb")
        trace_id = optional_int("trace")
        eval_run_id = optional_int("eval_run")
        compare_eval_run_id = optional_int("compare_eval_run")
        thread_business_key = build_agent_thread_business_key(
            request.user.id,
            kb_id,
            trace_id,
            eval_run_id,
            compare_eval_run_id,
        )
        thread_id = normalize_agent_thread_id(request.user.id, thread_business_key, request.data.get("thread_id"))
        result = run_ragops_agent(
            user=request.user,
            message=message,
            kb_id=kb_id,
            trace_id=trace_id,
            eval_run_id=eval_run_id,
            compare_eval_run_id=compare_eval_run_id,
            thread_id=thread_id,
            thread_business_key=thread_business_key,
        )
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    except PermissionError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
    return Response(result)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def ragops_agent_state(request):
    thread_id = str(request.query_params.get("thread_id") or "").strip()
    if not thread_id:
        return Response({"detail": "thread_id is required"}, status=status.HTTP_400_BAD_REQUEST)
    try:
        result = get_ragops_agent_state(user=request.user, thread_id=thread_id)
    except PermissionError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
    if not result:
        return Response({"detail": "Agent thread not found."}, status=status.HTTP_404_NOT_FOUND)
    return Response(result)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def ragops_agent_resume(request):
    thread_id = str(request.data.get("thread_id") or "").strip()
    if not thread_id:
        return Response({"detail": "thread_id is required"}, status=status.HTTP_400_BAD_REQUEST)

    resume_payload = request.data.get("resume")
    if not isinstance(resume_payload, dict):
        resume_payload = {
            "decision": request.data.get("decision"),
            "action_id": request.data.get("action_id"),
            "reason": request.data.get("reason") or "",
        }

    try:
        action_id = resume_payload.get("action_id")
        if action_id is not None:
            resume_payload["action_id"] = int(action_id)
        result = resume_ragops_agent(user=request.user, thread_id=thread_id, resume_payload=resume_payload)
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    except PermissionError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
    except RuntimeError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    return Response(result)


class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request):
    from .permission_serializers import OrganizationSerializer
    organizations = request.user.organization_memberships.filter(status="active").select_related("organization")
    return Response({"id": request.user.id, "username": request.user.username, "organizations": OrganizationSerializer([item.organization for item in organizations], many=True, context={"request": request}).data})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def chunk_methods(request):
    return Response(list_chunk_methods())


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def reset_workspace(request):
    organization_id = request.data.get("organization")
    membership_qs = request.user.organization_memberships.filter(status="active").select_related("organization").prefetch_related("roles")
    membership = membership_qs.filter(organization_id=organization_id).first() if organization_id else membership_qs.order_by("id").first()
    if not membership:
        return Response({"detail": "Organization not found."}, status=status.HTTP_404_NOT_FOUND)
    organization = membership.organization
    is_owner = membership.roles.filter(slug="owner").exists()
    is_shared = organization.memberships.filter(status="active").count() > 1
    if not is_owner:
        return Response({"detail": "Only an Organization Owner can reset a workspace."}, status=status.HTTP_403_FORBIDDEN)
    if is_shared and request.data.get("confirm_shared") != organization.slug:
        return Response({"detail": "Shared Organization reset requires its exact slug as confirm_shared."}, status=status.HTTP_409_CONFLICT)

    scope = require_capability(request.user, "manage_organization", organization=organization)
    kb_queryset = KnowledgeBase.objects.filter(organization=organization)
    documents = list(Document.objects.filter(kb__organization=organization).only("id", "file"))
    document_ids = [document.id for document in documents]
    deleted_files = 0
    parse_cases = list(DocumentParseBenchmarkCase.objects.filter(owner=request.user).only("id", "file")) if not is_shared else []
    get_vector_store().delete_documents(document_ids)
    for item in [*documents, *parse_cases]:
        if item.file:
            try:
                item.file.delete(save=False); deleted_files += 1
            except FileNotFoundError:
                pass

    with transaction.atomic():
        parse_case_count = len(parse_cases)
        parse_eval_run_count = DocumentParseEvalRun.objects.filter(owner=request.user).count() if not is_shared else 0
        if not is_shared:
            DocumentParseEvalRun.objects.filter(owner=request.user).delete()
            DocumentParseBenchmarkCase.objects.filter(owner=request.user).delete()
        sessions = ChatSession.objects.filter(kb__organization=organization)
        message_count = ChatMessage.objects.filter(session__in=sessions).count()
        session_count = sessions.count()
        chunk_count = Chunk.objects.filter(kb__organization=organization).count()
        benchmark_case_count = RagBenchmarkCase.objects.filter(kb__organization=organization).count()
        eval_runs = RagEvalRun.objects.filter(kb__organization=organization)
        eval_run_count = eval_runs.count()
        eval_case_count = RagEvalCaseResult.objects.filter(run__in=eval_runs).count()
        model_logs = ModelCallLog.objects.filter(kb__organization=organization)
        actions = RagAgentAction.objects.filter(kb__organization=organization)
        model_call_count = model_logs.count(); agent_action_count = actions.count()
        model_logs.delete(); actions.delete()
        document_count = len(documents); kb_count = kb_queryset.count()
        kb_queryset.delete()
    audit_access(scope, "reset_workspace", organization, True, "shared" if is_shared else "personal", {"knowledge_bases": kb_count})
    return Response({"status": "reset", "organization": organization.id, "deleted": {
        "knowledge_bases": kb_count, "documents": document_count, "chunks": chunk_count,
        "chat_sessions": session_count, "chat_messages": message_count,
        "rag_benchmark_cases": benchmark_case_count, "rag_eval_runs": eval_run_count,
        "rag_eval_case_results": eval_case_count, "document_parse_cases": parse_case_count,
        "document_parse_eval_runs": parse_eval_run_count, "model_call_logs": model_call_count,
        "rag_agent_actions": agent_action_count, "uploaded_files": deleted_files,
        "vector_documents": len(document_ids),
    }})

@api_view(["GET"])
@permission_classes([AllowAny])
def health_live(request):
    return Response({"status": "ok"})


@api_view(["GET"])
@permission_classes([AllowAny])
def health_ready(request):
    report = health_report(detailed=False)
    return Response(report, status=status.HTTP_200_OK if report["ready"] else status.HTTP_503_SERVICE_UNAVAILABLE)


@api_view(["GET"])
def system_health(request):
    report = health_report(detailed=True)
    return Response(report, status=status.HTTP_200_OK if report["ready"] else status.HTTP_503_SERVICE_UNAVAILABLE)


class KnowledgeBaseViewSet(viewsets.ModelViewSet):
    serializer_class = KnowledgeBaseSerializer

    def get_queryset(self):
        return filter_knowledge_bases_for_user(self.request.user).order_by("-created_at")

    def perform_create(self, serializer):
        organization = serializer.validated_data.get("organization")
        if not organization:
            membership = self.request.user.organization_memberships.filter(status="active").select_related("organization").first()
            if not membership:
                raise PermissionDenied("Active organization membership is required.")
            organization = membership.organization
        scope = require_capability(self.request.user, "manage_knowledge_bases", organization=organization)
        policy = serializer.validated_data.get("access_policy")
        if not policy:
            policy = organization.access_policies.filter(is_active=True).order_by("id").first()
        if not policy or policy.organization_id != organization.id:
            raise PermissionDenied("A policy from the current organization is required.")
        kb = serializer.save(owner=self.request.user, organization=organization, access_policy=policy)
        audit_access(scope, "manage_knowledge_bases", kb, True, "created")
        from .config_versions import ensure_initial_config
        ensure_initial_config(kb, self.request.user)

    def perform_update(self, serializer):
        scope = require_capability(self.request.user, "manage_knowledge_bases", kb=serializer.instance)
        organization = serializer.validated_data.get("organization", serializer.instance.organization)
        policy = serializer.validated_data.get("access_policy", serializer.instance.access_policy)
        if organization.id != serializer.instance.organization_id or not policy or policy.organization_id != organization.id:
            raise PermissionDenied("Knowledge base organization is immutable and policy must belong to it.")
        kb = serializer.save()
        audit_access(scope, "manage_knowledge_bases", kb, True, "updated")

    def perform_destroy(self, instance):
        scope = require_capability(self.request.user, "manage_knowledge_bases", kb=instance)
        audit_access(scope, "manage_knowledge_bases", instance, True, "deleted")
        instance.delete()

    @action(detail=True, methods=["get"], url_path="index-health")
    def index_health_view(self, request, pk=None):
        kb = self.get_object()
        scope = build_access_scope(request.user, kb=kb)
        documents = [index_health(document) for document in scope.filter_documents(kb.documents.all())]
        return Response({"kb": kb.id, "stale_count": sum(item["stale"] for item in documents), "critical": any(item["critical"] for item in documents), "documents": documents})

    @action(detail=True, methods=["post"], url_path="reindex-stale")
    def reindex_stale(self, request, pk=None):
        kb = self.get_object(); runs = []
        scope = require_capability(request.user, "manage_documents", kb=kb)
        for document in scope.filter_documents(kb.documents.all(), capability="manage_documents"):
            if index_health(document)["stale"] and document.parse_runs.filter(status="completed").exists():
                runs.append(create_index_run(document, document.chunk_method, document.chunk_options))
        return Response(DocumentIndexRunSerializer(runs, many=True).data, status=status.HTTP_202_ACCEPTED)


class DocumentViewSet(viewsets.ModelViewSet):
    serializer_class = DocumentSerializer

    def get_queryset(self):
        return filter_documents_for_user(self.request.user).prefetch_related("parse_runs").order_by("-created_at")

    def perform_create(self, serializer):
        kb = serializer.validated_data["kb"]
        scope = require_capability(self.request.user, "manage_documents", kb=kb)
        if not scope.can_knowledge_base(kb, "manage_documents"):
            raise PermissionDenied("Permission denied.")
        uploaded = self.request.FILES.get("file")
        metadata = getattr(serializer, "_validated_file_metadata", {})
        filename = metadata.get("filename") or (uploaded.name if uploaded else "")
        file_type = Path(filename).suffix.lower().lstrip(".")
        policy = serializer.validated_data.get("access_policy") or kb.access_policy
        if not policy or policy.organization_id != kb.organization_id:
            raise PermissionDenied("A policy from the knowledge base organization is required.")
        document = serializer.save(
            access_policy=policy, inherits_policy="access_policy" not in serializer.validated_data,
            filename=filename,
            file_type=file_type,
            mime_type=metadata.get("mime_type", ""),
            size_bytes=metadata.get("size_bytes", 0),
            sha256=metadata.get("sha256", ""),
            status="uploaded",
        )
        create_parse_run(document)

    def perform_update(self, serializer):
        document = serializer.instance
        scope = require_capability(self.request.user, "manage_documents", kb=document.kb)
        if "kb" in serializer.validated_data and serializer.validated_data["kb"].id != document.kb_id:
            raise PermissionDenied("Moving a document between knowledge bases is not supported.")
        policy = serializer.validated_data.get("access_policy", document.access_policy)
        if not policy or policy.organization_id != document.kb.organization_id:
            raise PermissionDenied("Policy must belong to the knowledge base organization.")
        serializer.save()
        audit_access(scope, "manage_documents", document, True, "updated")

    def perform_destroy(self, instance):
        scope = require_capability(self.request.user, "manage_documents", kb=instance.kb)
        audit_access(scope, "manage_documents", instance, True, "deleted")
        instance.delete()

    @action(detail=True, methods=["post"], url_path="set-access-policy")
    def set_access_policy(self, request, pk=None):
        document = self.get_object()
        scope = require_capability(request.user, "manage_documents", kb=document.kb)
        policy = document.kb.organization.access_policies.filter(pk=request.data.get("access_policy"), is_active=True).first()
        if not policy:
            return Response({"detail": "Access policy not found."}, status=status.HTTP_404_NOT_FOUND)
        with transaction.atomic():
            document.access_policy = policy
            document.inherits_policy = bool(request.data.get("inherits_policy", False))
            document.save(update_fields=["access_policy", "inherits_policy", "updated_at"])
            updated = document.chunks.filter(inherits_policy=True).update(access_policy=policy)
        try:
            get_vector_store().index_chunks(list(document.chunks.filter(inherits_policy=True).select_related("kb")))
        except Exception:
            logger.warning("vector policy metadata sync deferred document=%s", document.id)
        audit_access(scope, "manage_documents", document, True, "document_policy_updated", {"inherited_chunks": updated})
        return Response({"document": DocumentSerializer(document, context={"request": request}).data, "updated_chunks": updated})

    @action(detail=True, methods=["post"], url_path="parse")
    def parse_document(self, request, pk=None):
        document = self.get_object()
        require_capability(request.user, "manage_documents", kb=document.kb)
        run = create_parse_run(document)
        run.refresh_from_db()
        if run.status == "failed" and run.error_code == "queue_unavailable":
            return Response(DocumentParseRunSerializer(run).data, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response(DocumentParseRunSerializer(run).data, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["get"], url_path="parse-status")
    def parse_status(self, request, pk=None):
        document = self.get_object()
        run = document.parse_runs.order_by("-created_at", "-id").first()
        if not run:
            return Response({"detail": "No parse run."}, status=status.HTTP_404_NOT_FOUND)
        return Response(DocumentParseRunSerializer(run).data)

    @action(detail=True, methods=["get"], url_path="parse-preview")
    def parse_preview(self, request, pk=None):
        document = self.get_object()
        run_id = request.query_params.get("parse_run_id")
        runs = document.parse_runs.filter(status__in=["completed", "needs_review"])
        if run_id:
            runs = runs.filter(id=run_id)
        run = runs.order_by("-created_at", "-id").first()
        if not run:
            return Response({"detail": "解析结果尚不可预览。"}, status=status.HTTP_409_CONFLICT)
        try:
            page_number = max(int(request.query_params.get("page") or 1), 1)
        except (TypeError, ValueError):
            return Response({"detail": "page must be an integer."}, status=status.HTTP_400_BAD_REQUEST)
        page = run.pages.filter(page_number=page_number).first()
        if not page:
            return Response({"detail": "Page not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response({
            "parse_run": DocumentParseRunSerializer(run).data,
            "page_count": run.pages.count(),
            "page": DocumentPageSerializer(page).data,
        })

    @action(detail=True, methods=["post"], url_path="accept-parse")
    def accept_parse(self, request, pk=None):
        document = self.get_object()
        require_capability(request.user, "manage_documents", kb=document.kb)
        run_id = request.data.get("parse_run_id")
        runs = document.parse_runs.filter(status="needs_review")
        if run_id:
            runs = runs.filter(id=run_id)
        run = runs.order_by("-created_at", "-id").first()
        if not run:
            return Response({"detail": "没有待确认的解析结果。"}, status=status.HTTP_409_CONFLICT)
        run.status = "completed"
        run.save(update_fields=["status", "updated_at"])
        document.status = "parsed"
        document.error_message = ""
        document.save(update_fields=["status", "error_message", "updated_at"])
        return Response(DocumentParseRunSerializer(run).data)

    @action(detail=True, methods=["post"], url_path="chunk-preview")
    def chunk_preview(self, request, pk=None):
        document = self.get_object()
        method = request.data.get("chunk_method") or "sentence"
        options = request.data.get("options") or {}
        try:
            chunks = preview_chunks(document, method, options, request.data.get("parse_run_id"))
        except ParseRunNotReadyError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        stats = {
            "chunk_count": len(chunks),
            "avg_tokens": round(sum(c["token_count"] for c in chunks) / len(chunks), 2) if chunks else 0,
            "max_tokens": max((c["token_count"] for c in chunks), default=0),
        }
        return Response({"chunks": chunks, "stats": stats})

    @action(detail=True, methods=["post"])
    def index(self, request, pk=None):
        document = self.get_object()
        require_capability(request.user, "manage_documents", kb=document.kb)
        try:
            run = create_index_run(
                document, request.data.get("chunk_method") or "sentence",
                request.data.get("options") or {}, request.data.get("parse_run_id"),
            )
        except ParseRunNotReadyError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except RuntimeError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response(DocumentIndexRunSerializer(run).data, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["get"], url_path="index-status")
    def index_status(self, request, pk=None):
        document = self.get_object()
        run = document.index_runs.order_by("-created_at", "-id").first()
        return Response({"run": DocumentIndexRunSerializer(run).data if run else None, "health": index_health(document)})

    @action(detail=True, methods=["get"])
    def chunks(self, request, pk=None):
        document = self.get_object()
        scope = build_access_scope(request.user, kb=document.kb)
        queryset = scope.filter_chunks(Chunk.objects.filter(document=document))
        return Response(ChunkSerializer(queryset, many=True).data)


class ChatSessionViewSet(viewsets.ModelViewSet):
    serializer_class = ChatSessionSerializer

    def get_queryset(self):
        allowed_kbs = filter_knowledge_bases_for_user(self.request.user).values("id")
        queryset = ChatSession.objects.filter(owner=self.request.user, kb_id__in=allowed_kbs)
        kb_id = self.request.query_params.get("kb")
        if kb_id:
            queryset = queryset.filter(kb_id=kb_id)
        return queryset.order_by("-updated_at")

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    @action(detail=True, methods=["get", "post"])
    def messages(self, request, pk=None):
        session = self.get_object()
        if request.method == "GET":
            return Response(ChatMessageSerializer(session.messages.all(), many=True, context={"request": request}).data)

        question = (request.data.get("content") or "").strip()
        if not question:
            return Response({"detail": "content is required"}, status=status.HTTP_400_BAD_REQUEST)
        rag_options = request.data.get("rag_options") or {}
        ChatMessage.objects.create(session=session, role="user", content=question)
        answer = answer_question(session, question, rag_options)
        session.save(update_fields=["updated_at"])
        return Response(ChatMessageSerializer(answer, context={"request": request}).data)

    @action(detail=True, methods=["post"], url_path="stream")
    def stream(self, request, pk=None):
        session = self.get_object()
        question = (request.data.get("content") or "").strip()
        if not question:
            return Response({"detail": "content is required"}, status=status.HTTP_400_BAD_REQUEST)
        rag_options = request.data.get("rag_options") or {}

        if not stream_slots.acquire(blocking=False):
            logger.warning("rag stream rejected max_active session=%s user=%s", session.id, request.user.id)
            return Response({"detail": "当前流式请求较多，请稍后再试"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        logger.info("rag stream slot acquired session=%s user=%s", session.id, request.user.id)

        ChatMessage.objects.create(session=session, role="user", content=question)

        def event_stream():
            try:
                yield ": stream-open\n\n"
                try:
                    for item in stream_answer_events(session, question, rag_options):
                        yield sse_event(item["event"], item["data"])
                except Exception as exc:
                    logger.exception("rag stream failed session=%s", session.id)
                    detail = str(exc) or "RAG 问答失败。"
                    if "Connection error" in detail or "Network is unreachable" in detail or "timed out" in detail:
                        detail = f"模型或向量服务网络连接失败，无法可靠回答。请检查 TUN/代理/API 网络后重试。原始错误：{detail}"
                    yield sse_event("error", {"detail": detail})
            finally:
                stream_slots.release()
                close_old_connections()
                logger.info("rag stream slot released session=%s", session.id)

        response = StreamingHttpResponse(event_stream(), content_type="text/event-stream; charset=utf-8")
        response["Cache-Control"] = "no-cache, no-transform"
        response["X-Accel-Buffering"] = "no"
        response["X-RAG-Stream-Timeout"] = str(getattr(settings, "RAG_STREAM_RESPONSE_TIMEOUT_SECONDS", 3600))
        return response


class RagTraceViewSet(viewsets.ReadOnlyModelViewSet):
    def get_serializer_class(self):
        if self.action == "list":
            return RagTraceListSerializer
        return RagTraceDetailSerializer

    def get_queryset(self):
        queryset = (
            filter_traces_for_user(self.request.user, RagTrace.objects.all())
            .select_related("session", "session__kb", "message")
            .order_by("-created_at", "-id")
        )
        kb_id = self.request.query_params.get("kb")
        session_id = self.request.query_params.get("session")
        question = (self.request.query_params.get("question") or "").strip()
        if kb_id:
            queryset = queryset.filter(session__kb_id=kb_id)
        if session_id:
            queryset = queryset.filter(session_id=session_id)
        if question:
            queryset = queryset.filter(question__icontains=question)
        return queryset


class RagUserFeedbackViewSet(viewsets.ModelViewSet):
    serializer_class = RagUserFeedbackSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        queryset = (
            RagUserFeedback.objects.filter(owner=self.request.user)
            .select_related("kb", "session", "message", "trace", "created_action")
            .order_by("-created_at", "-id")
        )
        kb_id = self.request.query_params.get("kb")
        rating = self.request.query_params.get("rating")
        if kb_id:
            queryset = queryset.filter(kb_id=kb_id)
        if rating:
            queryset = queryset.filter(rating=rating)
        return queryset

    def create(self, request, *args, **kwargs):
        message_id = request.data.get("message")
        rating = request.data.get("rating")
        reason = request.data.get("reason") or ""
        comment = request.data.get("comment") or ""
        if rating not in {"helpful", "not_helpful"}:
            return Response({"detail": "rating must be helpful or not_helpful."}, status=status.HTTP_400_BAD_REQUEST)
        if rating == "not_helpful" and not reason:
            return Response({"detail": "reason is required for not_helpful feedback."}, status=status.HTTP_400_BAD_REQUEST)

        message = (
            ChatMessage.objects.filter(id=message_id, session__owner=request.user, role="assistant")
            .select_related("session", "session__kb")
            .first()
        )
        if not message:
            return Response({"detail": "Assistant message not found."}, status=status.HTTP_404_NOT_FOUND)
        trace = getattr(message, "trace", None)
        failure_signals = []
        if trace:
            failure_signals = detect_feedback_failure_signals(trace)

        feedback, _ = RagUserFeedback.objects.update_or_create(
            owner=request.user,
            message=message,
            defaults={
                "kb": message.session.kb,
                "session": message.session,
                "trace": trace,
                "rating": rating,
                "reason": reason,
                "comment": comment,
                "failure_signals": failure_signals,
            },
        )
        if rating == "not_helpful" and trace:
            action = create_feedback_action(request.user, feedback, trace, failure_signals)
            feedback.created_action = action
            feedback.save(update_fields=["created_action", "updated_at"])
        elif rating == "helpful" and feedback.created_action_id:
            feedback.created_action = None
            feedback.save(update_fields=["created_action", "updated_at"])
        return Response(RagUserFeedbackSerializer(feedback, context={"request": request}).data, status=status.HTTP_201_CREATED)


def detect_feedback_failure_signals(trace):
    from .agent.graph import detect_trace_failure_signals

    payload = {
        "id": trace.id,
        "question": trace.question,
        "rewritten_query": trace.rewritten_query,
        "answer": trace.message.content if trace.message else "",
        "vector_results": trace.vector_results,
        "bm25_results": trace.bm25_results,
        "hybrid_results": trace.hybrid_results,
        "rerank_results": trace.rerank_results,
        "compression_results": trace.compression_results,
        "compression_stats": trace.compression_stats,
        "settings": trace.settings,
    }
    return detect_trace_failure_signals(payload)


def create_feedback_action(user, feedback, trace, failure_signals):
    if not failure_signals:
        failure_signals = [
            {
                "code": "user_negative_feedback",
                "label": "用户负反馈",
                "evidence": f"用户选择了不满意原因：{feedback.reason or '未填写'}。",
            }
        ]
    payload = {
        "feedback": feedback.id,
        "trace": trace.id,
        "reason": feedback.reason,
        "rating": feedback.rating,
        "failure_signals": failure_signals,
    }
    action, created = RagAgentAction.objects.get_or_create(
        owner=user,
        action_uid=f"feedback-{feedback.id}-to-regression",
        defaults={
            "kb": feedback.kb,
            "trace": trace,
            "action_type": "create_regression_case",
            "source": "user_feedback",
            "title": "从用户反馈创建 Regression Case",
            "description": "用户对该回答给出了负反馈。确认后会将对应 Trace 沉淀到 Regression Set，供后续回归验证。",
            "confirm_label": "确认创建",
            "payload": payload,
            "status": "pending",
        },
    )
    if not created and action.status in {"pending", "failed"}:
        action.kb = feedback.kb
        action.trace = trace
        action.source = "user_feedback"
        action.title = "从用户反馈创建 Regression Case"
        action.description = "用户对该回答给出了负反馈。确认后会将对应 Trace 沉淀到 Regression Set，供后续回归验证。"
        action.confirm_label = "确认创建"
        action.payload = payload
        action.status = "pending"
        action.error_message = ""
        action.result = {}
        action.completed_at = None
        action.save(update_fields=["kb", "trace", "source", "title", "description", "confirm_label", "payload", "status", "error_message", "result", "completed_at", "updated_at"])
    return action


class RagAgentActionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = RagAgentActionSerializer

    def get_queryset(self):
        queryset = (
            RagAgentAction.objects.filter(owner=self.request.user)
            .select_related("kb", "trace", "eval_run", "eval_case_result", "created_case")
            .order_by("-created_at", "-id")
        )
        kb_id = self.request.query_params.get("kb")
        status_value = self.request.query_params.get("status")
        if kb_id:
            queryset = queryset.filter(kb_id=kb_id)
        if status_value:
            queryset = queryset.filter(status=status_value)
        return queryset

    @action(detail=True, methods=["post"], url_path="confirm")
    def confirm(self, request, pk=None):
        action_obj = self.get_object()
        if action_obj.status == "completed":
            return Response(RagAgentActionSerializer(action_obj).data)
        if action_obj.status == "running":
            return Response({"detail": "Action is still running."}, status=status.HTTP_409_CONFLICT)
        if action_obj.status == "rejected":
            return Response({"detail": "Rejected actions cannot be confirmed."}, status=status.HTTP_400_BAD_REQUEST)

        thread_id = get_action_thread_id(action_obj)
        if is_action_thread_awaiting_human(request.user, thread_id):
            try:
                agent_result = resume_ragops_agent(
                    user=request.user,
                    thread_id=thread_id,
                    resume_payload={
                        "decision": "confirmed",
                        "action_id": action_obj.id,
                    },
                )
                action_obj.refresh_from_db()
                data = RagAgentActionSerializer(action_obj).data
                data["agent_result"] = agent_result
                return Response(data)
            except ValueError as exc:
                return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
            except PermissionError as exc:
                return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
            except Exception as exc:
                action_obj.refresh_from_db()
                data = RagAgentActionSerializer(action_obj).data
                data["error_message"] = str(exc)
                return Response(data, status=status.HTTP_400_BAD_REQUEST)

        try:
            execute_agent_action(user=request.user, action=action_obj)
            action_obj.refresh_from_db()
        except Exception as exc:
            RagAgentAction.objects.filter(id=action_obj.id).exclude(status="completed").update(
                status="failed", error_message=str(exc), completed_at=timezone.now()
            )
            action_obj.refresh_from_db()
            return Response(RagAgentActionSerializer(action_obj).data, status=status.HTTP_400_BAD_REQUEST)
        return Response(RagAgentActionSerializer(action_obj).data)

    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request, pk=None):
        action_obj = self.get_object()
        if action_obj.status == "completed":
            return Response({"detail": "Completed actions cannot be rejected."}, status=status.HTTP_400_BAD_REQUEST)

        thread_id = get_action_thread_id(action_obj)
        reason = request.data.get("reason") or ""
        if is_action_thread_awaiting_human(request.user, thread_id):
            try:
                agent_result = resume_ragops_agent(
                    user=request.user,
                    thread_id=thread_id,
                    resume_payload={
                        "decision": "rejected",
                        "action_id": action_obj.id,
                        "reason": reason,
                    },
                )
                action_obj.refresh_from_db()
                data = RagAgentActionSerializer(action_obj).data
                data["agent_result"] = agent_result
                return Response(data)
            except ValueError as exc:
                return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
            except PermissionError as exc:
                return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)

        action_obj.status = "rejected"
        action_obj.rejected_reason = reason
        action_obj.completed_at = timezone.now()
        action_obj.save(update_fields=["status", "rejected_reason", "completed_at", "updated_at"])
        return Response(RagAgentActionSerializer(action_obj).data)


class RagExperimentPlanViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = RagExperimentPlanSerializer

    def get_queryset(self):
        queryset = (
            RagExperimentPlan.objects.filter(owner=self.request.user)
            .select_related("kb", "baseline_run", "winner_variant")
            .prefetch_related("variants__eval_run__case_results")
            .order_by("-created_at", "-id")
        )
        kb_id = self.request.query_params.get("kb")
        status_value = self.request.query_params.get("status")
        if kb_id:
            queryset = queryset.filter(kb_id=kb_id)
        if status_value:
            queryset = queryset.filter(status=status_value)
        return queryset

    def retrieve(self, request, *args, **kwargs):
        plan = self.get_object()
        if plan.status == "running":
            plan = refresh_experiment_plan(plan)
        return Response(self.get_serializer(plan).data)


class RagBenchmarkCaseViewSet(viewsets.ModelViewSet):
    serializer_class = RagBenchmarkCaseSerializer

    def get_queryset(self):
        kb_ids = filter_knowledge_bases_for_user(self.request.user, capability="run_evaluations").values("id")
        queryset = RagBenchmarkCase.objects.filter(kb_id__in=kb_ids).order_by("case_id", "id")
        kb_id = self.request.query_params.get("kb")
        enabled = self.request.query_params.get("enabled")
        suite = self.request.query_params.get("suite")
        source = self.request.query_params.get("source")
        if kb_id:
            queryset = queryset.filter(kb_id=kb_id)
        if suite:
            queryset = queryset.filter(suite=suite)
        if source:
            queryset = queryset.filter(source=source)
        if enabled in {"true", "1"}:
            queryset = queryset.filter(enabled=True)
        elif enabled in {"false", "0"}:
            queryset = queryset.filter(enabled=False)
        return queryset

    def perform_create(self, serializer):
        kb = serializer.validated_data["kb"]
        require_capability(self.request.user, "run_evaluations", kb=kb)
        serializer.save()

    def perform_update(self, serializer):
        require_capability(self.request.user, "run_evaluations", kb=serializer.instance.kb)
        serializer.save()

    def perform_destroy(self, instance):
        require_capability(self.request.user, "run_evaluations", kb=instance.kb)
        instance.delete()


    @action(detail=False, methods=["post"], url_path="from-trace")
    def from_trace(self, request):
        trace_id = request.data.get("trace") or request.data.get("trace_id")
        if not trace_id:
            return Response({"detail": "trace is required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            result = create_regression_case_from_trace(user=request.user, trace_id=int(trace_id), payload=request.data)
        except (TypeError, ValueError) as exc:
            message = str(exc)
            response_status = status.HTTP_404_NOT_FOUND if "not found" in message.lower() else status.HTTP_400_BAD_REQUEST
            return Response({"detail": message}, status=response_status)
        return Response({"created": result.created, "case": RagBenchmarkCaseSerializer(result.case).data})

    @action(detail=False, methods=["post"], url_path="from-eval-case")
    def from_eval_case(self, request):
        result_id = request.data.get("eval_case") or request.data.get("eval_case_id")
        if not result_id:
            return Response({"detail": "eval_case is required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            result = create_regression_case_from_eval_case(user=request.user, eval_case_result_id=int(result_id), payload=request.data)
        except (TypeError, ValueError) as exc:
            message = str(exc)
            response_status = status.HTTP_404_NOT_FOUND if "not found" in message.lower() else status.HTTP_400_BAD_REQUEST
            return Response({"detail": message}, status=response_status)
        return Response({"created": result.created, "case": RagBenchmarkCaseSerializer(result.case).data})

    @action(detail=False, methods=["post"], url_path="import-defaults")
    def import_defaults(self, request):
        kb_id = request.data.get("kb") or request.data.get("kb_id")
        if not kb_id:
            return Response({"detail": "kb is required"}, status=status.HTTP_400_BAD_REQUEST)
        kb = filter_knowledge_bases_for_user(request.user, capability="run_evaluations").filter(id=kb_id).first()
        if not kb:
            return Response({"detail": "Knowledge base not found."}, status=status.HTTP_404_NOT_FOUND)

        cases_path = Path(__file__).resolve().parent / "eval_cases.example.json"
        with cases_path.open("r", encoding="utf-8") as file:
            default_cases = json.load(file)

        created = 0
        updated = 0
        for item in default_cases:
            case_id = item.get("id") or item.get("case_id")
            if not case_id:
                continue
            defaults = {
                "question": item.get("question", ""),
                "reference": item.get("reference") or item.get("ground_truth") or item.get("expected_answer") or "",
                "case_type": item.get("case_type") or "expert",
                "tags": item.get("tags") or ["default"],
                "expected_terms": item.get("expected_terms") or item.get("expected_keywords") or [],
                "target_chunk_ids": item.get("target_chunk_ids") or [],
                "suite": item.get("suite") or "benchmark",
                "deterministic_checks": item.get("deterministic_checks") or {},
                "rubric": item.get("rubric") or {},
                "thresholds": item.get("thresholds") or {},
                "source": item.get("source") or "default_json",
                "notes": item.get("notes") or item.get("description", ""),
                "difficulty": item.get("difficulty") or "medium",
                "enabled": item.get("enabled", True),
                "metadata": {
                    "description": item.get("description", ""),
                    "expected_keywords": item.get("expected_keywords", []),
                    "expected_chunk_keywords": item.get("expected_chunk_keywords", []),
                },
            }
            _, was_created = RagBenchmarkCase.objects.update_or_create(kb=kb, case_id=case_id, defaults=defaults)
            created += 1 if was_created else 0
            updated += 0 if was_created else 1

        queryset = RagBenchmarkCase.objects.filter(kb=kb).order_by("case_id", "id")
        return Response(
            {
                "created": created,
                "updated": updated,
                "cases": RagBenchmarkCaseSerializer(queryset, many=True).data,
            }
        )


class RagEvalRunViewSet(viewsets.ReadOnlyModelViewSet):
    def get_serializer_class(self):
        if self.action == "list":
            return RagEvalRunListSerializer
        return RagEvalRunDetailSerializer

    def get_queryset(self):
        queryset = (
            RagEvalRun.objects.filter(kb_id__in=filter_knowledge_bases_for_user(self.request.user, capability="run_evaluations").values("id"))
            .select_related("kb")
            .prefetch_related("case_results")
            .order_by("-created_at", "-id")
        )
        kb_id = self.request.query_params.get("kb")
        status_value = self.request.query_params.get("status")
        if kb_id:
            queryset = queryset.filter(kb_id=kb_id)
        if status_value:
            queryset = queryset.filter(status=status_value)
        return queryset

    def list(self, request, *args, **kwargs):
        kb_id = request.query_params.get("kb")
        allowed_ids = filter_knowledge_bases_for_user(request.user, capability="run_evaluations").values_list("id", flat=True)
        target_ids = [int(kb_id)] if kb_id and int(kb_id) in set(allowed_ids) else list(allowed_ids)
        for target_id in target_ids:
            reconcile_stale_eval_runs(kb_id=target_id)
        return super().list(request, *args, **kwargs)

    def retrieve(self, request, *args, **kwargs):
        instance = reconcile_stale_eval_run(self.get_object())
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @action(detail=False, methods=["post"], url_path="run")
    def run(self, request):
        kb_id = request.data.get("kb") or request.data.get("kb_id")
        if not kb_id:
            return Response({"detail": "kb is required"}, status=status.HTTP_400_BAD_REQUEST)
        kb = filter_knowledge_bases_for_user(request.user, capability="run_evaluations").filter(id=kb_id).first()
        if not kb:
            return Response({"detail": "Knowledge base not found."}, status=status.HTTP_404_NOT_FOUND)
        if not Chunk.objects.filter(kb=kb).exists():
            return Response({"detail": "Knowledge base has no indexed chunks."}, status=status.HTTP_400_BAD_REQUEST)

        rag_options = request.data.get("rag_options") or {}
        command_options = {"kb_id": kb.id}
        suite = request.data.get("suite") or rag_options.get("suite")
        if suite:
            allowed_suites = {choice[0] for choice in RagBenchmarkCase.SUITE_CHOICES}
            if suite not in allowed_suites:
                return Response({"detail": f"suite must be one of: {', '.join(sorted(allowed_suites))}."}, status=status.HTTP_400_BAD_REQUEST)
            command_options["suite"] = suite
        option_map = {
            "top_k": "top_k",
            "bm25_top_k": "bm25_top_k",
            "rrf_k": "rrf_k",
            "rerank_top_n": "rerank_top_n",
            "query_rewrite_strategy": "query_rewrite_strategy",
            "compression_strategy": "compression_strategy",
        }
        for source_key, command_key in option_map.items():
            value = rag_options.get(source_key, request.data.get(source_key))
            if value not in (None, ""):
                if source_key in {"top_k", "bm25_top_k", "rrf_k", "rerank_top_n"}:
                    try:
                        value = int(value)
                    except (TypeError, ValueError):
                        return Response({"detail": f"{source_key} must be an integer."}, status=status.HTTP_400_BAD_REQUEST)
                command_options[command_key] = value
        if request.data.get("limit"):
            try:
                command_options["limit"] = int(request.data.get("limit"))
            except (TypeError, ValueError):
                return Response({"detail": "limit must be an integer."}, status=status.HTTP_400_BAD_REQUEST)

        baseline_run = None
        baseline_run_id = request.data.get("baseline_run") or rag_options.get("baseline_run")
        if baseline_run_id:
            try:
                baseline_run_id = int(baseline_run_id)
            except (TypeError, ValueError):
                return Response({"detail": "baseline_run must be an integer."}, status=status.HTTP_400_BAD_REQUEST)
            baseline_run = RagEvalRun.objects.filter(id=baseline_run_id, kb=kb).first()
            if not baseline_run:
                return Response({"detail": "Baseline run not found in this knowledge base."}, status=status.HTTP_404_NOT_FOUND)

        reconcile_stale_eval_runs(kb_id=kb.id)

        eval_run = RagEvalRun.objects.create(
            kb=kb,
            baseline_run=baseline_run,
            status="queued",
            metrics=RAGAS_DEFAULT_METRICS,
            settings={
                "trigger": "celery",
                "requested_options": command_options,
            },
            case_count=0,
        )
        from .tasks import run_eval_task
        try:
            result = run_eval_task.apply_async(args=[eval_run.id, command_options], queue="evaluations")
            eval_run.celery_task_id = result.id
            eval_run.save(update_fields=["celery_task_id"])
        except Exception as exc:
            eval_run.status = "failed"
            eval_run.error_message = f"评测任务无法进入队列，请检查 Celery/Redis：{exc}"
            eval_run.finished_at = timezone.now()
            eval_run.save(update_fields=["status", "error_message", "finished_at"])
            return Response({"detail": eval_run.error_message}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response(RagEvalRunDetailSerializer(eval_run).data, status=status.HTTP_202_ACCEPTED)


class DocumentParseBenchmarkCaseViewSet(viewsets.ModelViewSet):
    serializer_class = DocumentParseBenchmarkCaseSerializer

    def get_queryset(self):
        queryset = DocumentParseBenchmarkCase.objects.filter(owner=self.request.user)
        suite = self.request.query_params.get("suite")
        if suite: queryset = queryset.filter(suite=suite)
        return queryset

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class DocumentParseEvalRunViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = DocumentParseEvalRunSerializer

    def get_queryset(self):
        queryset = DocumentParseEvalRun.objects.filter(owner=self.request.user).prefetch_related("case_results__case")
        suite = self.request.query_params.get("suite")
        if suite: queryset = queryset.filter(suite=suite)
        return queryset

    @action(detail=False, methods=["post"], url_path="run")
    def run(self, request):
        suite = request.data.get("suite") or "benchmark"
        allowed = {choice[0] for choice in RagBenchmarkCase.SUITE_CHOICES}
        if suite not in allowed: return Response({"detail": "Invalid suite."}, status=status.HTTP_400_BAD_REQUEST)
        count = DocumentParseBenchmarkCase.objects.filter(owner=request.user, suite=suite, enabled=True).count()
        if not count: return Response({"detail": "该 suite 没有启用的解析评测 Case。"}, status=status.HTTP_409_CONFLICT)
        run = DocumentParseEvalRun.objects.create(owner=request.user, suite=suite, case_count=count)
        from .tasks import parse_eval_run_task
        try:
            result = parse_eval_run_task.apply_async(args=[run.id], queue="evaluations")
            run.celery_task_id = result.id; run.save(update_fields=["celery_task_id"])
        except Exception as exc:
            run.status="failed"; run.error_message=str(exc); run.finished_at=timezone.now()
            run.save(update_fields=["status","error_message","finished_at"])
            return Response({"detail": "解析评测任务无法进入队列。"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response(self.get_serializer(run).data, status=status.HTTP_202_ACCEPTED)


class RagConfigVersionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = RagConfigVersionSerializer

    def get_queryset(self):
        queryset = RagConfigVersion.objects.filter(kb_id__in=filter_knowledge_bases_for_user(self.request.user, capability="use_agent").values("id"))
        kb = self.request.query_params.get("kb")
        return queryset.filter(kb_id=kb) if kb else queryset

    @action(detail=True, methods=["post"], url_path="request-publish")
    def request_publish(self, request, pk=None):
        version = self.get_object()
        if version.validation_status != "release_passed":
            return Response({"detail": "配置尚未通过 release gate。"}, status=status.HTTP_409_CONFLICT)
        action_obj, _ = RagAgentAction.objects.get_or_create(
            owner=request.user, action_uid=f"publish-config-{version.id}",
            defaults={"kb": version.kb, "action_type": "publish_rag_config", "source": "config_release",
                      "title": f"发布配置 v{version.version}", "description": "Release suite 已通过。确认后切换知识库活跃配置。",
                      "confirm_label": "确认发布", "payload": {"config_version": version.id}, "status": "pending"},
        )
        return Response(RagAgentActionSerializer(action_obj).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="request-rollback")
    def request_rollback(self, request, pk=None):
        version = self.get_object()
        if version.validation_status != "release_passed":
            return Response({"detail": "只能回滚到通过 release gate 的版本。"}, status=status.HTTP_409_CONFLICT)
        was_deployed = version.source == "initial" or RagConfigDeployment.objects.filter(kb=version.kb, target_version=version).exists()
        if not was_deployed:
            return Response({"detail": "只能回滚到历史上实际部署过的版本。"}, status=status.HTTP_409_CONFLICT)
        action_obj, _ = RagAgentAction.objects.get_or_create(
            owner=request.user, action_uid=f"rollback-config-{version.kb_id}-{version.id}",
            defaults={"kb": version.kb, "action_type": "rollback_rag_config", "source": "config_history",
                      "title": f"回滚到配置 v{version.version}", "description": "确认后原子切换配置并保留完整审计记录。",
                      "confirm_label": "确认回滚", "payload": {"config_version": version.id, "reason": request.data.get("reason", "")}, "status": "pending"},
        )
        return Response(RagAgentActionSerializer(action_obj).data, status=status.HTTP_201_CREATED)


class RagConfigDeploymentViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = RagConfigDeploymentSerializer
    def get_queryset(self):
        queryset = RagConfigDeployment.objects.filter(kb_id__in=filter_knowledge_bases_for_user(self.request.user, capability="use_agent").values("id")).select_related("previous_version","target_version")
        kb = self.request.query_params.get("kb")
        return queryset.filter(kb_id=kb) if kb else queryset
