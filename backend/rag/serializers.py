from django.contrib.auth.models import User
from rest_framework import serializers

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


class DocumentSerializer(serializers.ModelSerializer):
    chunk_count = serializers.IntegerField(source="chunks.count", read_only=True)

    class Meta:
        model = Document
        fields = [
            "id",
            "kb",
            "filename",
            "file",
            "file_type",
            "status",
            "chunk_method",
            "chunk_options",
            "chunk_count",
            "error_message",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["filename", "file_type", "status", "error_message"]


class ChunkSerializer(serializers.ModelSerializer):
    class Meta:
        model = Chunk
        fields = ["id", "index", "content", "token_count", "metadata"]


class ChatSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatSession
        fields = ["id", "kb", "title", "created_at", "updated_at"]


class ChatMessageSerializer(serializers.ModelSerializer):
    trace = serializers.SerializerMethodField()

    class Meta:
        model = ChatMessage
        fields = ["id", "role", "content", "sources", "trace", "created_at"]

    def get_trace(self, obj):
        trace = getattr(obj, "trace", None)
        if not trace:
            return None
        return {
            "id": trace.id,
            "question": trace.question,
            "rewritten_query": trace.rewritten_query,
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


class RagBenchmarkCaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = RagBenchmarkCase
        fields = [
            "id",
            "kb",
            "case_id",
            "question",
            "reference",
            "tags",
            "expected_terms",
            "target_chunk_ids",
            "suite",
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
            "error_message",
            "created_at",
        ]


class RagEvalRunListSerializer(serializers.ModelSerializer):
    kb_name = serializers.CharField(source="kb.name", read_only=True)

    class Meta:
        model = RagEvalRun
        fields = [
            "id",
            "kb",
            "kb_name",
            "status",
            "metrics",
            "settings",
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
    case_results = RagEvalCaseResultSerializer(many=True, read_only=True)

    class Meta:
        model = RagEvalRun
        fields = [
            "id",
            "kb",
            "kb_name",
            "status",
            "metrics",
            "settings",
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
