from django.contrib.auth.models import User
from rest_framework import serializers

from .document_parsing.validation import DocumentValidationError, validate_document_file
from .models import (
    ChatMessage,
    ChatSession,
    ChatSessionSummary,
    Chunk,
    Document,
    DocumentIndexRun,
    DocumentPage,
    DocumentParseRun,
    DocumentParseBenchmarkCase,
    DocumentParseEvalCaseResult,
    DocumentParseEvalRun,
    KnowledgeBase,
    ModelCallLog,
    RagAgentAction,
    RagBenchmarkCase,
    RagEvalCaseResult,
    RagEvalRun,
    RagExperimentPlan,
    RagExperimentVariant,
    RagConfigDeployment,
    RagConfigVersion,
    RagTrace,
    RagUserFeedback,
    AccessPolicy, Membership, Organization, Role, AuthorizationAuditLog, ROLE_CAPABILITIES,
)


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)

    class Meta:
        model = User
        fields = ["id", "username", "password"]

    def create(self, validated_data):
        from .tenancy import bootstrap_user_organization
        user = User.objects.create_user(**validated_data)
        bootstrap_user_organization(user)
        return user


class KnowledgeBaseSerializer(serializers.ModelSerializer):
    active_config = serializers.SerializerMethodField()

    class Meta:
        model = KnowledgeBase
        fields = ["id", "organization", "name", "description", "visibility", "access_policy", "active_config_version", "active_config", "created_at", "updated_at"]
        read_only_fields = ["active_config_version", "active_config"]

    def validate(self, attrs):
        organization = attrs.get("organization") or getattr(self.instance, "organization", None)
        policy = attrs.get("access_policy") or getattr(self.instance, "access_policy", None)
        if organization and policy and policy.organization_id != organization.id:
            raise serializers.ValidationError({"access_policy": "Policy must belong to the knowledge base organization."})
        return attrs

    def get_active_config(self, obj):
        version = obj.active_config_version
        if not version:
            return None
        return {"id": version.id, "version": version.version, "signature": version.signature, "payload": version.payload}


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
            from .access_control import filter_knowledge_bases_for_user
            capability = self.context.get("kb_capability", "query")
            return filter_knowledge_bases_for_user(request.user, capability=capability)
        return KnowledgeBase.objects.none()


class DocumentParseRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentParseRun
        fields = [
            "id", "status", "parser", "parser_version", "progress_current", "progress_total",
            "quality_score", "quality_metrics", "error_code", "error_message", "started_at",
            "finished_at", "created_at", "updated_at",
        ]


class DocumentIndexRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentIndexRun
        fields = ["id", "document", "parse_run", "status", "celery_task_id", "chunk_method", "chunk_options", "target_signature", "progress_current", "progress_total", "chunk_count", "retry_count", "error_message", "started_at", "heartbeat_at", "finished_at", "created_at", "updated_at"]
        read_only_fields = fields


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
            "access_policy", "inherits_policy", "index_signature", "index_manifest", "indexed_at", "error_message", "created_at", "updated_at",
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
        fields = ["id", "index", "content", "token_count", "metadata", "access_policy", "inherits_policy"]


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

    def to_representation(self, obj):
        data = super().to_representation(obj)
        request = self.context.get("request")
        user = getattr(request, "user", None)
        source_ids = {int(value) for value in (obj.source_chunk_ids or []) if str(value).isdigit()}
        if not user or not user.is_authenticated or not source_ids:
            data["sources"] = obj.sources or []
            return data
        from .access_control import build_access_scope
        scope = build_access_scope(user, kb=obj.session.kb)
        chunks = scope.filter_chunks(Chunk.objects.filter(id__in=source_ids)).select_related("document")
        by_id = {chunk.id: chunk for chunk in chunks}
        if set(by_id) != source_ids:
            data["content"] = "内容因权限变更不可用。"
            data["sources"] = []
            data["authorization"] = {"available": False, "reason": "permission_changed"}
            return data
        sources = []
        compact = obj.sources or []
        for item in compact:
            chunk = by_id.get(int(item.get("chunk_id") or 0))
            if not chunk:
                continue
            sources.append({**item, "document": chunk.document.filename, "content": chunk.content[:220]})
        data["sources"] = sources
        data["authorization"] = {"available": True, "filtered_count": 0}
        return data

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
            "original_context": "",
            "compressed_context": "",
            "final_prompt": "",
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


class AuthorizedTraceRepresentationMixin:
    sensitive_fields = ("vector_results", "bm25_results", "hybrid_results", "rerank_results", "compression_results", "original_context", "compressed_context", "final_prompt")

    def to_representation(self, obj):
        data = super().to_representation(obj)
        request = self.context.get("request")
        user = getattr(request, "user", None)
        from .access_control import build_access_scope
        from .redaction import sanitize_trace_results
        scope = build_access_scope(user, kb=obj.session.kb) if user and user.is_authenticated else None
        policy_ids = {int(value) for value in (obj.access_policy_ids or []) if str(value).isdigit()}
        available = bool(scope and scope.can_knowledge_base(obj.session.kb, "view_traces") and policy_ids.issubset(scope.allowed_policy_ids))
        if not available:
            data["message_content"] = "内容因权限变更不可用。"
            for field in self.sensitive_fields:
                if field in data: data[field] = [] if field.endswith("results") else ""
            data["authorization"] = {"available": False, "reason": "permission_changed"}
            return data
        for field in ("vector_results", "bm25_results", "hybrid_results", "rerank_results", "compression_results"):
            if field in data: data[field] = sanitize_trace_results(data[field])
        for field in ("original_context", "compressed_context", "final_prompt"):
            if field in data: data[field] = ""
        settings_data = dict(data.get("settings") or {})
        for key in ("conversation_context", "session_summary", "blocked_answer"):
            settings_data.pop(key, None)
        data["settings"] = settings_data
        data["authorization"] = {"available": True, "scope_fingerprint": scope.fingerprint}
        return data


class RagTraceListSerializer(AuthorizedTraceRepresentationMixin, serializers.ModelSerializer):
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


class RagTraceDetailSerializer(AuthorizedTraceRepresentationMixin, serializers.ModelSerializer):
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
            "principal_membership",
            "forbidden_document_ids",
            "forbidden_chunk_ids",
            "expected_authorized_document_ids",
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

    def validate(self, attrs):
        attrs = super().validate(attrs)
        kb = attrs.get("kb") or getattr(self.instance, "kb", None)
        principal = attrs.get("principal_membership") or getattr(self.instance, "principal_membership", None)
        suite = attrs.get("suite") or getattr(self.instance, "suite", "")
        if principal and kb and principal.organization_id != kb.organization_id:
            raise serializers.ValidationError({"principal_membership": "Principal must belong to the knowledge base organization."})
        if suite == "security" and not principal:
            raise serializers.ValidationError({"principal_membership": "Security cases require a principal membership."})
        if kb:
            valid_documents = set(Document.objects.filter(kb=kb).values_list("id", flat=True))
            valid_chunks = set(Chunk.objects.filter(kb=kb).values_list("id", flat=True))
            supplied_documents = {int(value) for field in ("forbidden_document_ids", "expected_authorized_document_ids") for value in (attrs.get(field, getattr(self.instance, field, []) if self.instance else []) or [])}
            supplied_chunks = {int(value) for value in (attrs.get("forbidden_chunk_ids", getattr(self.instance, "forbidden_chunk_ids", []) if self.instance else []) or [])}
            if not supplied_documents.issubset(valid_documents):
                raise serializers.ValidationError("Security document IDs must belong to the selected knowledge base.")
            if not supplied_chunks.issubset(valid_chunks):
                raise serializers.ValidationError("Security chunk IDs must belong to the selected knowledge base.")
        return attrs


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
            "execution_metrics",
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
            "celery_task_id", "retry_count", "heartbeat_at", "execution_metrics",
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
            "celery_task_id", "retry_count", "heartbeat_at", "execution_metrics",
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


class RagConfigVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = RagConfigVersion
        fields = ["id", "kb", "version", "payload", "signature", "source", "validation_status", "parent", "experiment_plan", "winner_variant", "release_eval_run", "created_by", "created_at"]
        read_only_fields = fields


class RagConfigDeploymentSerializer(serializers.ModelSerializer):
    target_version_number = serializers.IntegerField(source="target_version.version", read_only=True)
    previous_version_number = serializers.IntegerField(source="previous_version.version", read_only=True)

    class Meta:
        model = RagConfigDeployment
        fields = ["id", "kb", "previous_version", "previous_version_number", "target_version", "target_version_number", "action", "operation", "reason", "deployed_by", "created_at"]
        read_only_fields = fields


class DocumentParseBenchmarkCaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentParseBenchmarkCase
        fields = ["id", "case_id", "title", "file", "suite", "tags", "expected_page_count", "expected_ocr_pages", "expected_headings", "expected_terms_by_page", "expected_block_types", "expected_table_terms", "thresholds", "enabled", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]
        extra_kwargs = {"enabled": {"default": True}}

    def validate_case_id(self, value):
        value = value.strip()
        if not value: raise serializers.ValidationError("case_id is required.")
        return value

    def validate_file(self, value):
        try:
            validate_document_file(value)
        except DocumentValidationError as exc:
            raise serializers.ValidationError(str(exc)) from exc
        return value


class DocumentParseEvalCaseResultSerializer(serializers.ModelSerializer):
    case_id = serializers.CharField(source="case.case_id", read_only=True)
    title = serializers.CharField(source="case.title", read_only=True)
    class Meta:
        model = DocumentParseEvalCaseResult
        fields = ["id", "case", "case_id", "title", "passed", "metrics", "checks", "error_message", "duration_ms", "created_at"]


class DocumentParseEvalRunSerializer(serializers.ModelSerializer):
    case_results = DocumentParseEvalCaseResultSerializer(many=True, read_only=True)
    class Meta:
        model = DocumentParseEvalRun
        fields = ["id", "suite", "status", "celery_task_id", "case_count", "passed_count", "summary", "error_message", "started_at", "finished_at", "created_at", "case_results"]
        read_only_fields = fields
