from django.contrib import admin

from .models import ChatMessage, ChatSession, ChatSessionSummary, Chunk, Document, DocumentPage, DocumentParseRun, KnowledgeBase, ModelCallLog


@admin.register(KnowledgeBase)
class KnowledgeBaseAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "owner", "created_at")
    search_fields = ("name", "description", "owner__username")


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("id", "filename", "kb", "status", "chunk_method", "created_at")
    list_filter = ("status", "chunk_method")
    search_fields = ("filename",)


@admin.register(Chunk)
class ChunkAdmin(admin.ModelAdmin):
    list_display = ("id", "document", "kb", "index", "token_count")
    search_fields = ("content",)


admin.site.register(ChatSession)
admin.site.register(ChatMessage)


@admin.register(ChatSessionSummary)
class ChatSessionSummaryAdmin(admin.ModelAdmin):
    list_display = ("id", "session", "summary_message_count", "status", "token_estimate", "updated_at")
    list_filter = ("status",)
    search_fields = ("session__title", "summary", "error_message")
    readonly_fields = ("created_at", "updated_at", "last_started_at")


@admin.register(ModelCallLog)
class ModelCallLogAdmin(admin.ModelAdmin):
    list_display = ("id", "owner", "model", "call_type", "status", "total_tokens", "estimated_cost", "latency_ms", "created_at")
    list_filter = ("status", "call_type", "model")
    search_fields = ("model", "error_message", "trace__question")
    readonly_fields = ("created_at",)


@admin.register(DocumentParseRun)
class DocumentParseRunAdmin(admin.ModelAdmin):
    list_display = ("id", "document", "status", "parser", "quality_score", "progress_current", "progress_total", "created_at")
    list_filter = ("status", "parser")
    search_fields = ("document__filename", "provider_job_id", "error_message")


@admin.register(DocumentPage)
class DocumentPageAdmin(admin.ModelAdmin):
    list_display = ("id", "parse_run", "page_number", "extraction_method", "char_count", "is_blank")
    list_filter = ("extraction_method", "is_blank")
