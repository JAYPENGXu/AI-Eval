import json
import logging
import re
import threading
import uuid
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import close_old_connections
from django.conf import settings
from django.db.models import Avg, Count, Q, Sum
from django.http import StreamingHttpResponse
from django.db import transaction
from django.utils import timezone
from rest_framework import generics, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .agent.services import run_ragops_agent
from .case_factory import create_regression_case_from_eval_case, create_regression_case_from_trace, create_regression_case_from_user_feedback
from .experiments import refresh_experiment_plan, start_experiment_plan
from .chunkers import list_chunk_methods
from .models import (
    ChatMessage,
    ChatSession,
    Chunk,
    Document,
    KnowledgeBase,
    ModelCallLog,
    RagAgentAction,
    RagBenchmarkCase,
    RagEvalCaseResult,
    RagEvalRun,
    RagExperimentPlan,
    RagTrace,
    RagUserFeedback,
)
from .serializers import (
    ChatMessageSerializer,
    ChatSessionSerializer,
    ChunkSerializer,
    DocumentSerializer,
    KnowledgeBaseSerializer,
    ModelCallLogSerializer,
    RagAgentActionSerializer,
    RagBenchmarkCaseSerializer,
    RagEvalRunDetailSerializer,
    RagEvalRunListSerializer,
    RagExperimentPlanSerializer,
    RagTraceDetailSerializer,
    RagTraceListSerializer,
    RagUserFeedbackSerializer,
    RegisterSerializer,
)
from .services import answer_question, index_document, preview_chunks, stream_answer_events
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
    return Response(result)


class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request):
    return Response({"id": request.user.id, "username": request.user.username})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def chunk_methods(request):
    return Response(list_chunk_methods())


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def reset_workspace(request):
    documents = list(Document.objects.filter(kb__owner=request.user).only("id", "file"))
    document_ids = [document.id for document in documents]
    deleted_files = 0

    get_vector_store().delete_documents(document_ids)

    for document in documents:
        if document.file:
            try:
                document.file.delete(save=False)
                deleted_files += 1
            except FileNotFoundError:
                pass

    with transaction.atomic():
        message_count = ChatMessage.objects.filter(session__owner=request.user).count()
        session_count = ChatSession.objects.filter(owner=request.user).count()
        chunk_count = Chunk.objects.filter(kb__owner=request.user).count()
        benchmark_case_count = RagBenchmarkCase.objects.filter(kb__owner=request.user).count()
        eval_run_count = RagEvalRun.objects.filter(kb__owner=request.user).count()
        eval_case_count = RagEvalCaseResult.objects.filter(run__kb__owner=request.user).count()
        model_call_count = ModelCallLog.objects.filter(owner=request.user).count()
        agent_action_count = RagAgentAction.objects.filter(owner=request.user).count()
        ModelCallLog.objects.filter(owner=request.user).delete()
        RagAgentAction.objects.filter(owner=request.user).delete()
        document_count = len(documents)
        kb_count = KnowledgeBase.objects.filter(owner=request.user).count()
        KnowledgeBase.objects.filter(owner=request.user).delete()

    return Response(
        {
            "status": "reset",
            "deleted": {
                "knowledge_bases": kb_count,
                "documents": document_count,
                "chunks": chunk_count,
                "chat_sessions": session_count,
                "chat_messages": message_count,
                "rag_benchmark_cases": benchmark_case_count,
                "rag_eval_runs": eval_run_count,
                "rag_eval_case_results": eval_case_count,
                "model_call_logs": model_call_count,
                "rag_agent_actions": agent_action_count,
                "uploaded_files": deleted_files,
                "vector_documents": len(document_ids),
            },
        }
    )


class KnowledgeBaseViewSet(viewsets.ModelViewSet):
    serializer_class = KnowledgeBaseSerializer

    def get_queryset(self):
        return KnowledgeBase.objects.filter(owner=self.request.user).order_by("-created_at")

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class DocumentViewSet(viewsets.ModelViewSet):
    serializer_class = DocumentSerializer

    def get_queryset(self):
        return Document.objects.filter(kb__owner=self.request.user).order_by("-created_at")

    def perform_create(self, serializer):
        uploaded = self.request.FILES.get("file")
        filename = uploaded.name if uploaded else ""
        file_type = Path(filename).suffix.lower().lstrip(".")
        serializer.save(filename=filename, file_type=file_type, status="uploaded")

    @action(detail=True, methods=["post"], url_path="chunk-preview")
    def chunk_preview(self, request, pk=None):
        document = self.get_object()
        method = request.data.get("chunk_method") or "sentence"
        options = request.data.get("options") or {}
        chunks = preview_chunks(document, method, options)
        stats = {
            "chunk_count": len(chunks),
            "avg_tokens": round(sum(c["token_count"] for c in chunks) / len(chunks), 2) if chunks else 0,
            "max_tokens": max((c["token_count"] for c in chunks), default=0),
        }
        return Response({"chunks": chunks, "stats": stats})

    @action(detail=True, methods=["post"])
    def index(self, request, pk=None):
        document = self.get_object()
        method = request.data.get("chunk_method") or "sentence"
        options = request.data.get("options") or {}
        try:
            count = index_document(document, method, options)
        except Exception as exc:
            document.status = "failed"
            document.error_message = str(exc)
            document.save(update_fields=["status", "error_message", "updated_at"])
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"chunk_count": count, "status": "indexed"})

    @action(detail=True, methods=["get"])
    def chunks(self, request, pk=None):
        document = self.get_object()
        queryset = Chunk.objects.filter(document=document)
        return Response(ChunkSerializer(queryset, many=True).data)


class ChatSessionViewSet(viewsets.ModelViewSet):
    serializer_class = ChatSessionSerializer

    def get_queryset(self):
        queryset = ChatSession.objects.filter(owner=self.request.user)
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
            return Response(ChatMessageSerializer(session.messages.all(), many=True).data)

        question = (request.data.get("content") or "").strip()
        if not question:
            return Response({"detail": "content is required"}, status=status.HTTP_400_BAD_REQUEST)
        rag_options = request.data.get("rag_options") or {}
        ChatMessage.objects.create(session=session, role="user", content=question)
        answer = answer_question(session, question, rag_options)
        session.save(update_fields=["updated_at"])
        return Response(ChatMessageSerializer(answer).data)

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
            RagTrace.objects.filter(session__owner=self.request.user)
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
        if action_obj.status == "rejected":
            return Response({"detail": "Rejected actions cannot be confirmed."}, status=status.HTTP_400_BAD_REQUEST)

        action_obj.confirmed_at = timezone.now()
        action_obj.status = "pending"
        action_obj.error_message = ""
        action_obj.save(update_fields=["confirmed_at", "status", "error_message", "updated_at"])

        try:
            if action_obj.action_type == "run_experiment_plan":
                plan_id = action_obj.payload.get("experiment_plan")
                plan = start_experiment_plan(user=request.user, plan_id=int(plan_id))
                action_obj.status = "completed"
                action_obj.completed_at = timezone.now()
                action_obj.result = {"plan_id": plan.id, "status": plan.status, "variant_count": plan.variants.count()}
                action_obj.error_message = ""
                action_obj.save(update_fields=["status", "completed_at", "result", "error_message", "updated_at"])
                return Response(RagAgentActionSerializer(action_obj).data)

            if action_obj.action_type != "create_regression_case":
                raise ValueError(f"Unsupported action type: {action_obj.action_type}")
            if action_obj.source == "trace":
                trace_id = action_obj.payload.get("trace") or action_obj.trace_id
                result = create_regression_case_from_trace(user=request.user, trace_id=int(trace_id), payload=action_obj.payload)
            elif action_obj.source == "eval_failure":
                eval_case_id = action_obj.payload.get("eval_case") or action_obj.eval_case_result_id
                result = create_regression_case_from_eval_case(user=request.user, eval_case_result_id=int(eval_case_id), payload=action_obj.payload)
            elif action_obj.source == "user_feedback":
                feedback_id = action_obj.payload.get("feedback")
                result = create_regression_case_from_user_feedback(user=request.user, feedback_id=int(feedback_id), payload=action_obj.payload)
            else:
                raise ValueError(f"Unsupported action source: {action_obj.source}")

            action_obj.status = "completed"
            action_obj.created_case = result.case
            action_obj.completed_at = timezone.now()
            action_obj.result = {"created": result.created, "case_id": result.case.case_id, "case_pk": result.case.id}
            action_obj.error_message = ""
            action_obj.save(update_fields=["status", "created_case", "completed_at", "result", "error_message", "updated_at"])
        except Exception as exc:
            action_obj.status = "failed"
            action_obj.error_message = str(exc)
            action_obj.completed_at = timezone.now()
            action_obj.save(update_fields=["status", "error_message", "completed_at", "updated_at"])
            return Response(RagAgentActionSerializer(action_obj).data, status=status.HTTP_400_BAD_REQUEST)
        return Response(RagAgentActionSerializer(action_obj).data)

    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request, pk=None):
        action_obj = self.get_object()
        if action_obj.status == "completed":
            return Response({"detail": "Completed actions cannot be rejected."}, status=status.HTTP_400_BAD_REQUEST)
        action_obj.status = "rejected"
        action_obj.rejected_reason = request.data.get("reason") or ""
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
        queryset = RagBenchmarkCase.objects.filter(kb__owner=self.request.user).order_by("case_id", "id")
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
        if kb.owner_id != self.request.user.id:
            raise PermissionDenied("Knowledge base not found.")
        serializer.save()

    def perform_update(self, serializer):
        kb = serializer.validated_data.get("kb") or serializer.instance.kb
        if kb.owner_id != self.request.user.id:
            raise PermissionDenied("Knowledge base not found.")
        serializer.save()


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
        kb = KnowledgeBase.objects.filter(id=kb_id, owner=request.user).first()
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
            RagEvalRun.objects.filter(kb__owner=self.request.user)
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

    @action(detail=False, methods=["post"], url_path="run")
    def run(self, request):
        kb_id = request.data.get("kb") or request.data.get("kb_id")
        if not kb_id:
            return Response({"detail": "kb is required"}, status=status.HTTP_400_BAD_REQUEST)
        kb = KnowledgeBase.objects.filter(id=kb_id, owner=request.user).first()
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

        eval_run = RagEvalRun.objects.create(
            kb=kb,
            baseline_run=baseline_run,
            status="running",
            metrics=RAGAS_DEFAULT_METRICS,
            settings={
                "trigger": "api_background_thread",
                "requested_options": command_options,
            },
            case_count=0,
        )
        command_options["run_id"] = eval_run.id

        def run_eval_in_background():
            close_old_connections()
            try:
                call_command("eval_ragas", **command_options)
            except Exception as exc:
                RagEvalRun.objects.filter(id=eval_run.id).update(
                    status="failed",
                    error_message=str(exc),
                    finished_at=timezone.now(),
                )
            finally:
                close_old_connections()

        threading.Thread(target=run_eval_in_background, daemon=True).start()
        return Response(RagEvalRunDetailSerializer(eval_run).data, status=status.HTTP_202_ACCEPTED)
