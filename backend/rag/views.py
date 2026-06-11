import json
import threading
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

from .chunkers import list_chunk_methods
from .models import (
    ChatMessage,
    ChatSession,
    Chunk,
    Document,
    KnowledgeBase,
    ModelCallLog,
    RagBenchmarkCase,
    RagEvalCaseResult,
    RagEvalRun,
    RagTrace,
)
from .serializers import (
    ChatMessageSerializer,
    ChatSessionSerializer,
    ChunkSerializer,
    DocumentSerializer,
    KnowledgeBaseSerializer,
    ModelCallLogSerializer,
    RagBenchmarkCaseSerializer,
    RagEvalRunDetailSerializer,
    RagEvalRunListSerializer,
    RagTraceDetailSerializer,
    RagTraceListSerializer,
    RegisterSerializer,
)
from .services import answer_question, index_document, preview_chunks, stream_answer_events
from .vector_store import get_vector_store

RAGAS_DEFAULT_METRICS = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]


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
        ModelCallLog.objects.filter(owner=request.user).delete()
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
        return ChatSession.objects.filter(owner=self.request.user).order_by("-updated_at")

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

        ChatMessage.objects.create(session=session, role="user", content=question)

        def event_stream():
            try:
                for item in stream_answer_events(session, question, rag_options):
                    yield sse_event(item["event"], item["data"])
            except Exception as exc:
                yield sse_event("error", {"detail": str(exc)})

        response = StreamingHttpResponse(event_stream(), content_type="text/event-stream; charset=utf-8")
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
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
        trace = (
            RagTrace.objects.filter(id=trace_id, session__owner=request.user)
            .select_related("session", "session__kb", "message")
            .first()
        )
        if not trace:
            return Response({"detail": "Trace not found."}, status=status.HTTP_404_NOT_FOUND)

        case_id = request.data.get("case_id") or f"trace_{trace.id}"
        trace_answer = trace.message.content if trace.message else ""
        reference = request.data.get("reference") or trace_answer or "TODO: ???????"
        defaults = {
            "question": trace.question,
            "reference": reference,
            "tags": request.data.get("tags") or ["trace", "regression"],
            "expected_terms": request.data.get("expected_terms") or [],
            "target_chunk_ids": request.data.get("target_chunk_ids") or [],
            "suite": request.data.get("suite") or "regression",
            "source": "trace",
            "notes": request.data.get("notes") or f"Created from Trace #{trace.id}. Please review reference and target chunks.",
            "difficulty": request.data.get("difficulty") or "medium",
            "enabled": request.data.get("enabled", False),
            "metadata": {
                "trace_id": trace.id,
                "session_id": trace.session_id,
                "message_id": trace.message_id,
                "created_from": "trace",
            },
        }
        case, created = RagBenchmarkCase.objects.update_or_create(
            kb=trace.session.kb,
            case_id=case_id,
            defaults=defaults,
        )
        return Response({"created": created, "case": RagBenchmarkCaseSerializer(case).data})

    @action(detail=False, methods=["post"], url_path="from-eval-case")
    def from_eval_case(self, request):
        result_id = request.data.get("eval_case") or request.data.get("eval_case_id")
        if not result_id:
            return Response({"detail": "eval_case is required"}, status=status.HTTP_400_BAD_REQUEST)
        result = (
            RagEvalCaseResult.objects.filter(id=result_id, run__kb__owner=request.user)
            .select_related("run", "run__kb")
            .first()
        )
        if not result:
            return Response({"detail": "Eval case result not found."}, status=status.HTTP_404_NOT_FOUND)

        diagnostics = result.diagnostics or {}
        stages = diagnostics.get("stages") or {}
        failed_stages = [key for key, value in stages.items() if not value.get("hit")]
        final_answer = diagnostics.get("final_answer") or {}
        if final_answer and not final_answer.get("correct"):
            failed_stages.append("final_answer")

        expected_terms = diagnostics.get("expected_terms") or diagnostics.get("reference_terms") or []
        target_chunk_ids = diagnostics.get("target_chunk_ids") or []
        if not target_chunk_ids:
            for value in stages.values():
                target_chunk_ids = value.get("target_chunk_ids") or []
                if target_chunk_ids:
                    break

        raw_case_id = result.case_id or f"eval_case_{result.id}"
        case_id = request.data.get("case_id") or f"regression_{raw_case_id}"
        defaults = {
            "question": result.question,
            "reference": result.reference or "TODO: ???????",
            "tags": request.data.get("tags") or ["eval_failure", "regression"],
            "expected_terms": request.data.get("expected_terms") or expected_terms,
            "target_chunk_ids": request.data.get("target_chunk_ids") or target_chunk_ids,
            "suite": request.data.get("suite") or "regression",
            "source": "eval_failure",
            "notes": request.data.get("notes") or f"Created from Eval Run #{result.run_id}, case {result.case_id}. Failed stages: {', '.join(failed_stages) or 'unknown'}.",
            "difficulty": request.data.get("difficulty") or "medium",
            "enabled": request.data.get("enabled", True),
            "metadata": {
                "eval_run_id": result.run_id,
                "eval_case_result_id": result.id,
                "failed_stages": failed_stages,
                "created_from": "eval_failure",
            },
        }
        case, created = RagBenchmarkCase.objects.update_or_create(
            kb=result.run.kb,
            case_id=case_id,
            defaults=defaults,
        )
        return Response({"created": created, "case": RagBenchmarkCaseSerializer(case).data})

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
                "tags": item.get("tags") or ["default"],
                "expected_terms": item.get("expected_terms") or item.get("expected_keywords") or [],
                "target_chunk_ids": item.get("target_chunk_ids") or [],
                "suite": item.get("suite") or "benchmark",
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

        eval_run = RagEvalRun.objects.create(
            kb=kb,
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
