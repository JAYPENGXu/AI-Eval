from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    ChatSessionViewSet,
    DocumentViewSet,
    KnowledgeBaseViewSet,
    RagBenchmarkCaseViewSet,
    RagEvalRunViewSet,
    RagTraceViewSet,
    RegisterView,
    chunk_methods,
    me,
    model_usage_summary,
    reset_workspace,
)

router = DefaultRouter()
router.register("knowledge-bases", KnowledgeBaseViewSet, basename="knowledge-base")
router.register("documents", DocumentViewSet, basename="document")
router.register("chat-sessions", ChatSessionViewSet, basename="chat-session")
router.register("rag-traces", RagTraceViewSet, basename="rag-trace")
router.register("rag-benchmark-cases", RagBenchmarkCaseViewSet, basename="rag-benchmark-case")
router.register("rag-eval-runs", RagEvalRunViewSet, basename="rag-eval-run")

urlpatterns = [
    path("auth/register/", RegisterView.as_view()),
    path("auth/me/", me),
    path("chunk-methods/", chunk_methods),
    path("model-usage/summary/", model_usage_summary),
    path("reset-workspace/", reset_workspace),
    path("", include(router.urls)),
]
