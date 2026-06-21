from django.contrib.auth.models import User
from rest_framework import serializers

from .document_parsing.validation import DocumentValidationError, validate_document_file
from .models import (
    ChatMessage,
    ChatSession,
    ChatSessionSummary,
    Chunk,
    Document,
    DocumentPage,
    DocumentParseRun,
    KnowledgeBase,
    ModelCallLog,
    RagAgentAction,
    RagBenchmarkCase,
    RagEvalCaseResult,
    RagEvalRun,
    RagExperimentPlan,
    RagExperimentVariant,
    RagTrace,
    RagUserFeedback,
)


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)

    class Meta:
        model = User
        fields = ["id", "username", "password"]

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)


class KnowledgeBaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = KnowledgeBase
        fields = ["id", "name", "description", "created_at", "updated_at"]


class OwnedKnowledgeBaseRelatedField(serializers.PrimaryKeyRelatedField):
    """Limit kb choices to knowledge bases owned by the current request user."""

    default_error_messages = {
        "does_not_exist": "Knowledge base not found.",
        "invalid": "Knowledge base not found.",
    }

    def __init__(self, **kwargs):
        kwargs.setdefault("queryset", KnowledgeBase.objects.none())
        super().__init__(**kwargs)

    def get_queryset(self):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return KnowledgeBase.objects.filter(owner=request.user)
        return KnowledgeBase.objects.none()


class DocumentParseRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentParseRun
        fields = [
            "id", "status", "parser", "parser_version", "progress_current", "progress_total",
            "quality_score", "quality_metrics", "error_code", "error_message", "started_at",
            "finished_at", "created_at", "updated_at",
        ]


class DocumentPageSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentPage
        fields = [
            "page_number", "extraction_method", "text", "markdown", "blocks",
            "char_count", "is_blank", "metrics",
        ]


class DocumentSerializer(serializers.ModelSerializer):
    kb = OwnedKnowledgeBaseRelatedField()
    chunk_count = serializers.IntegerField(source="chunks.count", read_only=True)
    latest_parse = serializers.SerializerMethodField()

    class Meta:
        model = Document
        fields = [
            "id", "kb", "filename", "file", "file_type", "mime_type", "size_bytes", "sha256",
            "status", "chunk_method", "chunk_options", "chunk_count", "latest_parse",
            "error_message", "created_at", "updated_at",
        ]
        read_only_fields = [
            "filename", "file_type", "mime_type", "size_bytes", "sha256", "status", "error_message"
        ]

    def validate_file(self, value):
        try:
            self._validated_file_metadata = validate_document_file(value)
        except DocumentValidationError as exc:
            raise serializers.ValidationError(str(exc)) from exc
        return value

    def get_latest_parse(self, obj):
        run = obj.parse_runs.order_by("-created_at", "-id").first()
        return DocumentParseRunSerializer(run).data if run else None


class ChunkSerializer(serializers.ModelSerializer):
    class Meta:
        model = Chunk
        fields = ["id", "index", "content", "token_count", "metadata"]


class ChatSessionSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatSessionSummary
        fields = [
            "summary",
            "summary_message_count",
            "covered_until_message",
            "token_estimate",
            "status",
            "error_message",
            "last_started_at",
            "updated_at",
        ]


class ChatSessionSerializer(serializers.ModelSerializer):
    kb = OwnedKnowledgeBaseRelatedField()
    message_count = serializers.IntegerField(source="messages.count", read_only=True)
    display_title = serializers.SerializerMethodField()
    summary_state = ChatSessionSummarySerializer(read_only=True)

    class Meta:
        model = ChatSession
        fields = ["id", "kb", "title", "display_title", "message_count", "summary_state", "created_at", "updated_at"]

    def get_display_title(self, obj):
        first_question = obj.messages.filter(role="user").order_by("created_at", "id").values_list("content", flat=True).first()
        text = (first_question or obj.title or "").strip()
        for char in "，。！？；：,.!?;:\n\r\t":
            text = text.replace(char, " ")
        text = " ".join(text.split())
        if not text:
            return "RAG 问答"
        return text[:10]


class ChatMessageSerializer(serializers.ModelSerializer):
    trace = serializers.SerializerMethodField()
    feedback = serializers.SerializerMethodField()

    class Meta:
        model = ChatMessage
        fields = ["id", "role", "content", "sources", "trace", "feedback", "created_at"]

    def get_feedback(self, obj):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return None
        feedback = obj.feedback.filter(owner=user).order_by("-created_at", "-id").first()
        if not feedback:
            return None
        return {
            "id": feedback.id,
            "rating": feedback.rating,
            "reason": feedback.reason,
            "comment": feedback.comment,
            "failure_signals": feedback.failure_signals,
            "created_action": feedback.created_action_id,
            "created_at": feedback.created_at.isoformat(),
        }

    def get_trace(self, obj):
        trace = getattr(obj, "trace", None)
        if not trace:
            return None
        return {
            "id": trace.id,
            "question": trace.question,
            "rewritten_query": trace.rewritten_query,
            "query_intent": trace.query_intent,
            "route_decision": trace.route_decision,
            "route_reason": trace.route_reason,
            "retrieval_mode": trace.retrieval_mode,
            "vector_results": trace.vector_results,
            "bm25_results": trace.bm25_results,
            "hybrid_results": trace.hybrid_results,
            "rerank_results": trace.rerank_results,
            "compression_results": trace.compression_results,
            "compression_stats": trace.compression_stats,
            "original_context": trace.original_context,
            "compressed_context": trace.compressed_context,
            "final_prompt": trace.final_prompt,
            "settings": trace.settings,
            "created_at": trace.created_at.isoformat(),
        }


class RagUserFeedbackSerializer(serializers.ModelSerializer):
    action = serializers.SerializerMethodField()

    class Meta:
        model = RagUserFeedback
        fields = [
            "id",
            "kb",
            "session",
            "message",
            "trace",
            "rating",
            "reason",
            "comment",
            "failure_signals",
            "created_action",
            "action",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "kb", "session", "trace", "failure_signals", "created_action", "action", "created_at", "updated_at"]

    def get_action(self, obj):
        if not obj.created_action_id:
            return None
        return RagAgentActionSerializer(obj.created_action).data


class RagTraceListSerializer(serializers.ModelSerializer):
    session_title = serializers.CharField(source="session.title", read_only=True)
    kb = serializers.IntegerField(source="session.kb_id", read_only=True)
    kb_name = serializers.CharField(source="session.kb.name", read_only=True)
    message_content = serializers.CharField(source="message.content", read_only=True, allow_null=True)

    class Meta:
        model = RagTrace
        fields = [
            "id",
            "session",
            "session_title",
            "kb",
            "kb_name",
            "message",
            "message_content",
            "question",
            "query_intent",
            "route_decision",
            "route_reason",
            "retrieval_mode",
            "compression_stats",
            "settings",
            "created_at",
        ]


class RagTraceDetailSerializer(serializers.ModelSerializer):
    session_title = serializers.CharField(source="session.title", read_only=True)
    kb = serializers.IntegerField(source="session.kb_id", read_only=True)
    kb_name = serializers.CharField(source="session.kb.name", read_only=True)
    message_content = serializers.CharField(source="message.content", read_only=True, allow_null=True)

    class Meta:
        model = RagTrace
        fields = [
            "id",
            "session",
            "session_title",
            "kb",
            "kb_name",
            "message",
            "message_content",
            "question",
            "rewritten_query",
            "query_intent",
            "route_decision",
            "route_reason",
            "retrieval_mode",
            "vector_results",
            "bm25_results",
            "hybrid_results",
            "rerank_results",
            "compression_results",
            "compression_stats",
            "original_context",
            "compressed_context",
            "final_prompt",
            "settings",
            "created_at",
        ]


class RagAgentActionSerializer(serializers.ModelSerializer):
    kb_name = serializers.CharField(source="kb.name", read_only=True)
    trace_question = serializers.CharField(source="trace.question", read_only=True)
    created_case_id = serializers.CharField(source="created_case.case_id", read_only=True)

    class Meta:
        model = RagAgentAction
        fields = [
            "id",
            "kb",
            "kb_name",
            "trace",
            "trace_question",
            "eval_run",
            "eval_case_result",
            "created_case",
            "created_case_id",
            "action_uid",
            "action_type",
            "source",
            "title",
            "description",
            "confirm_label",
            "payload",
            "status",
            "result",
            "error_message",
            "rejected_reason",
            "created_at",
            "confirmed_at",
            "completed_at",
            "updated_at",
        ]
        read_only_fields = fields


class RagBenchmarkCaseSerializer(serializers.ModelSerializer):
    kb = OwnedKnowledgeBaseRelatedField()

    class Meta:
        model = RagBenchmarkCase
        fields = [
            "id",
            "kb",
            "case_id",
            "case_type",
            "question",
            "reference",
            "tags",
            "expected_terms",
            "target_chunk_ids",
            "suite",
            "deterministic_checks",
            "rubric",
            "thresholds",
            "source",
            "notes",
            "difficulty",
            "enabled",
            "metadata",
            "created_at",
            "updated_at",
        ]

    def validate_tags(self, value):
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value or []


    def validate_expected_terms(self, value):
        if isinstance(value, str):
            return [item.strip() for item in value.replace("\n", ",").split(",") if item.strip()]
        return value or []

    def validate_target_chunk_ids(self, value):
        if isinstance(value, str):
            raw_items = [item.strip() for item in value.replace("\n", ",").split(",") if item.strip()]
        else:
            raw_items = value or []
        chunk_ids = []
        for item in raw_items:
            try:
                chunk_ids.append(int(item))
            except (TypeError, ValueError):
                raise serializers.ValidationError("target_chunk_ids must be integers.")
        return chunk_ids

    def validate_case_type(self, value):
        value = (value or "expert").strip()
        allowed = {choice[0] for choice in RagBenchmarkCase.CASE_TYPE_CHOICES}
        if value not in allowed:
            raise serializers.ValidationError(f"case_type must be one of: {', '.join(sorted(allowed))}.")
        return value

    def validate_deterministic_checks(self, value):
        return value or {}

    def validate_rubric(self, value):
        return value or {}

    def validate_thresholds(self, value):
        return value or {}

    def validate_suite(self, value):
        value = (value or "benchmark").strip()
        allowed = {choice[0] for choice in RagBenchmarkCase.SUITE_CHOICES}
        if value not in allowed:
            raise serializers.ValidationError(f"suite must be one of: {', '.join(sorted(allowed))}.")
        return value

    def validate_source(self, value):
        value = (value or "expert").strip()
        allowed = {choice[0] for choice in RagBenchmarkCase.SOURCE_CHOICES}
        if value not in allowed:
            raise serializers.ValidationError(f"source must be one of: {', '.join(sorted(allowed))}.")
        return value

    def validate_case_id(self, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("case_id is required.")
        return value

    def validate_question(self, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("question is required.")
        return value

    def validate_reference(self, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("reference is required.")
        return value


class RagEvalCaseResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = RagEvalCaseResult
        fields = [
            "id",
            "case_id",
            "case_type",
            "suite",
            "question",
            "reference",
            "answer",
            "rewritten_query",
            "rewrite_strategy",
            "contexts",
            "scores",
            "compression_stats",
            "top_chunks",
            "diagnostics",
            "deterministic_results",
            "judge_results",
            "error_message",
            "created_at",
        ]


class RagEvalRunListSerializer(serializers.ModelSerializer):
    kb_name = serializers.CharField(source="kb.name", read_only=True)
    baseline_param_signature = serializers.CharField(source="baseline_run.param_signature", read_only=True)

    class Meta:
        model = RagEvalRun
        fields = [
            "id",
            "kb",
            "kb_name",
            "baseline_run",
            "baseline_param_signature",
            "status",
            "metrics",
            "settings",
            "param_signature",
            "mean_scores",
            "retrieval_metrics",
            "case_count",
            "cases_path",
            "error_message",
            "started_at",
            "finished_at",
            "created_at",
        ]


class RagEvalRunDetailSerializer(serializers.ModelSerializer):
    kb_name = serializers.CharField(source="kb.name", read_only=True)
    baseline_param_signature = serializers.CharField(source="baseline_run.param_signature", read_only=True)
    case_results = RagEvalCaseResultSerializer(many=True, read_only=True)

    class Meta:
        model = RagEvalRun
        fields = [
            "id",
            "kb",
            "kb_name",
            "baseline_run",
            "baseline_param_signature",
            "status",
            "metrics",
            "settings",
            "param_signature",
            "mean_scores",
            "retrieval_metrics",
            "case_count",
            "cases_path",
            "error_message",
            "started_at",
            "finished_at",
            "created_at",
            "case_results",
        ]



class RagExperimentVariantSerializer(serializers.ModelSerializer):
    eval_run_status = serializers.CharField(source="eval_run.status", read_only=True)
    eval_run_signature = serializers.CharField(source="eval_run.param_signature", read_only=True)

    class Meta:
        model = RagExperimentVariant
        fields = [
            "id",
            "name",
            "hypothesis",
            "rag_options",
            "eval_run",
            "eval_run_status",
            "eval_run_signature",
            "result_summary",
            "is_winner",
            "created_at",
            "updated_at",
        ]


class RagExperimentPlanSerializer(serializers.ModelSerializer):
    kb_name = serializers.CharField(source="kb.name", read_only=True)
    baseline_param_signature = serializers.CharField(source="baseline_run.param_signature", read_only=True)
    variants = RagExperimentVariantSerializer(many=True, read_only=True)

    class Meta:
        model = RagExperimentPlan
        fields = [
            "id",
            "kb",
            "kb_name",
            "baseline_run",
            "baseline_param_signature",
            "winner_variant",
            "goal",
            "status",
            "failure_cases",
            "failure_summary",
            "recommendation",
            "error_message",
            "variants",
            "created_at",
            "updated_at",
            "started_at",
            "completed_at",
        ]
        read_only_fields = fields


class ModelCallLogSerializer(serializers.ModelSerializer):
    trace_question = serializers.CharField(source="trace.question", read_only=True)
    kb_name = serializers.CharField(source="kb.name", read_only=True)

    class Meta:
        model = ModelCallLog
        fields = [
            "id",
            "kb",
            "kb_name",
            "session",
            "message",
            "trace",
            "trace_question",
            "eval_run",
            "provider",
            "model",
            "call_type",
            "status",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "estimated_cost",
            "latency_ms",
            "error_message",
            "metadata",
            "created_at",
        ]
