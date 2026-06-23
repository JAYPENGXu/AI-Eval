from __future__ import annotations


from .demo_protection import DEMO_DOCUMENTS, DEMO_POLICIES
from .demo_seed import DEMO_USERNAMES, seed_demo_workspace
from .models import (
    AuthorizationAuditLog,
    ChatSession,
    Document,
    DocumentParseBenchmarkCase,
    DocumentParseEvalRun,
    KnowledgeBase,
    Membership,
    Organization,
    RagAgentAction,
    RagBenchmarkCase,
    RagConfigDeployment,
    RagConfigVersion,
    RagEvalRun,
    RagExperimentPlan,
    Role,
)

CORE_KBS = {"星海科技企业知识库", "远航供应商知识库"}
CORE_ROLES = {"owner", "admin", "knowledge_manager", "member", "auditor", "hr_specialist"}
CORE_PARSE_CASES = {"parse-guide", "parse-text-pdf", "parse-mixed-ocr"}
CORE_RAG_CASES = {
    "smoke-release-window", "benchmark-probation", "regression-orion-dr", "release-change-approval",
    "security-engineer-no-hr", "security-hr-scope", "security-suspended-zero", "security-cross-tenant-zero", "security-owner-read",
}


def _delete_document(document):
    try:
        from .vector_store import get_vector_store
        get_vector_store().delete_document(document.id)
    except Exception:
        pass
    if document.file:
        document.file.delete(save=False)
    document.delete()


def reset_demo_runtime():
    """Remove visitor-created state while preserving parsed/indexed fixture documents."""
    organizations = list(Organization.objects.filter(is_demo=True))
    for organization in organizations:
        for kb in organization.knowledge_bases.exclude(name__in=CORE_KBS):
            for document in list(kb.documents.all()):
                _delete_document(document)
            kb.delete()
        for document in list(Document.objects.filter(kb__organization=organization).exclude(filename__in=DEMO_DOCUMENTS)):
            _delete_document(document)

        core_kbs = KnowledgeBase.objects.filter(organization=organization, name__in=CORE_KBS)
        ChatSession.objects.filter(kb__in=core_kbs).delete()
        AuthorizationAuditLog.objects.filter(organization=organization).delete()
        DocumentParseEvalRun.objects.filter(owner__username__in=DEMO_USERNAMES).delete()
        RagBenchmarkCase.objects.filter(kb__in=core_kbs).exclude(case_id__in=CORE_RAG_CASES).delete()

        stable_runs = RagEvalRun.objects.filter(kb__in=core_kbs, settings__demo_seed__isnull=False)
        stable_run_ids = set(stable_runs.values_list("id", flat=True))
        RagExperimentPlan.objects.filter(kb__in=core_kbs).exclude(baseline_run_id__in=stable_run_ids).delete()
        RagEvalRun.objects.filter(kb__in=core_kbs).exclude(id__in=stable_run_ids).delete()

        RagConfigDeployment.objects.filter(kb__in=core_kbs).delete()
        for kb in core_kbs:
            initial = kb.config_versions.filter(source="initial").order_by("version").first()
            if initial:
                kb.active_config_version = initial
                kb.save(update_fields=["active_config_version", "updated_at"])
            stable_versions = kb.config_versions.filter(experiment_plan__baseline_run_id__in=stable_run_ids)
            keep_ids = set(stable_versions.values_list("id", flat=True))
            if initial:
                keep_ids.add(initial.id)
            RagConfigVersion.objects.filter(kb=kb).exclude(id__in=keep_ids).delete()

        RagAgentAction.objects.filter(kb__in=core_kbs).exclude(source="demo_seed").delete()
        RagAgentAction.objects.filter(kb__in=core_kbs, source="demo_seed").update(
            status="pending", result={}, error_message="", rejected_reason="",
            confirmed_at=None, completed_at=None,
        )
        organization.memberships.exclude(user__username__in=DEMO_USERNAMES).delete()
        Role.objects.filter(organization=organization).exclude(slug__in=CORE_ROLES).delete()
        organization.access_policies.exclude(name__in=DEMO_POLICIES).delete()

    for case in DocumentParseBenchmarkCase.objects.filter(owner__username__in=DEMO_USERNAMES).exclude(case_id__in=CORE_PARSE_CASES):
        if case.file:
            case.file.delete(save=False)
        case.delete()

    # Reapply immutable fixture attributes and recreate any missing baseline row.
    seed_demo_workspace(process=False)
    return {"organizations": len(organizations)}
