from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    ChatSessionViewSet,
    DocumentViewSet,
    KnowledgeBaseViewSet,
    RagAgentActionViewSet,
    RagBenchmarkCaseViewSet,
    RagEvalRunViewSet,
    RagExperimentPlanViewSet,
    RagTraceViewSet,
    RagUserFeedbackViewSet,
    RegisterView,
    chunk_methods,
    me,
    ragops_agent_run,
    model_usage_summary,
    reset_workspace,
)

router = DefaultRouter()
router.register("knowledge-bases", KnowledgeBaseViewSet, basename="knowledge-base")
router.register("documents", DocumentViewSet, basename="document")
router.register("chat-sessions", ChatSessionViewSet, basename="chat-session")
router.register("rag-traces", RagTraceViewSet, basename="rag-trace")
router.register("rag-benchmark-cases", RagBenchmarkCaseViewSet, basename="rag-benchmark-case")
router.register("rag-agent-actions", RagAgentActionViewSet, basename="rag-agent-action")
router.register("rag-user-feedback", RagUserFeedbackViewSet, basename="rag-user-feedback")
router.register("rag-eval-runs", RagEvalRunViewSet, basename="rag-eval-run")
router.register("rag-experiment-plans", RagExperimentPlanViewSet, basename="rag-experiment-plan")

urlpatterns = [
    path("auth/register/", RegisterView.as_view()),
    path("auth/me/", me),
    path("chunk-methods/", chunk_methods),
    path("model-usage/summary/", model_usage_summary),
    path("ragops-agent/run/", ragops_agent_run),
    path("reset-workspace/", reset_workspace),
    path("", include(router.urls)),
]
