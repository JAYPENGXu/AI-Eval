from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .permission_views import AccessPolicyViewSet, AuthorizationAuditLogViewSet, ChunkAccessViewSet, OrganizationViewSet
from .views import (
    ChatSessionViewSet,
    DocumentViewSet,
    DocumentParseBenchmarkCaseViewSet,
    DocumentParseEvalRunViewSet,
    KnowledgeBaseViewSet,
    RagAgentActionViewSet,
    RagBenchmarkCaseViewSet,
    RagEvalRunViewSet,
    RagExperimentPlanViewSet,
    RagConfigVersionViewSet,
    RagConfigDeploymentViewSet,
    RagTraceViewSet,
    RagUserFeedbackViewSet,
    RegisterView,
    chunk_methods,
    health_live,
    health_ready,
    system_health,
    me,
    ragops_agent_run,
    ragops_agent_state,
    ragops_agent_resume,
    model_usage_summary,
    reset_workspace,
)

router = DefaultRouter()
router.register("organizations", OrganizationViewSet, basename="organization")
router.register("access-policies", AccessPolicyViewSet, basename="access-policy")
router.register("authorization-audit-logs", AuthorizationAuditLogViewSet, basename="authorization-audit-log")
router.register("chunks", ChunkAccessViewSet, basename="chunk-access")
router.register("knowledge-bases", KnowledgeBaseViewSet, basename="knowledge-base")
router.register("documents", DocumentViewSet, basename="document")
router.register("chat-sessions", ChatSessionViewSet, basename="chat-session")
router.register("rag-traces", RagTraceViewSet, basename="rag-trace")
router.register("rag-benchmark-cases", RagBenchmarkCaseViewSet, basename="rag-benchmark-case")
router.register("rag-agent-actions", RagAgentActionViewSet, basename="rag-agent-action")
router.register("rag-user-feedback", RagUserFeedbackViewSet, basename="rag-user-feedback")
router.register("rag-eval-runs", RagEvalRunViewSet, basename="rag-eval-run")
router.register("rag-experiment-plans", RagExperimentPlanViewSet, basename="rag-experiment-plan")
router.register("document-parse-cases", DocumentParseBenchmarkCaseViewSet, basename="document-parse-case")
router.register("document-parse-eval-runs", DocumentParseEvalRunViewSet, basename="document-parse-eval-run")
router.register("rag-config-versions", RagConfigVersionViewSet, basename="rag-config-version")
router.register("rag-config-deployments", RagConfigDeploymentViewSet, basename="rag-config-deployment")

urlpatterns = [
    path("health/live/", health_live),
    path("health/ready/", health_ready),
    path("system-health/", system_health),
    path("auth/register/", RegisterView.as_view()),
    path("auth/me/", me),
    path("chunk-methods/", chunk_methods),
    path("model-usage/summary/", model_usage_summary),
    path("ragops-agent/run/", ragops_agent_run),
    path("ragops-agent/state/", ragops_agent_state),
    path("ragops-agent/resume/", ragops_agent_resume),
    path("reset-workspace/", reset_workspace),
    path("", include(router.urls)),
]
