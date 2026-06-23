from __future__ import annotations

import hashlib
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files import File
from django.utils import timezone

from .config_versions import create_config_version, ensure_initial_config
from .models import (
    AccessPolicy,
    ChatMessage,
    ChatSession,
    Document,
    DocumentParseBenchmarkCase,
    DocumentParseRun,
    DocumentIndexRun,
    KnowledgeBase,
    Membership,
    Organization,
    RagAgentAction,
    RagBenchmarkCase,
    RagEvalCaseResult,
    RagEvalRun,
    RagExperimentPlan,
    RagExperimentVariant,
    RagTrace,
    Role,
)

DEMO_SEED_VERSION = "2026.06.1"
DEMO_ORG_SLUGS = ("demo-xinghai", "demo-yuanhang")
DEMO_USERNAMES = (
    "demo_owner", "demo_km", "demo_auditor", "demo_engineer",
    "demo_hr", "demo_suspended", "demo_vendor",
)

PERSONAS = [
    {"username": "demo_owner", "label": "组织负责人", "description": "查看全部密级，体验组织、策略、发布与回滚管理。", "organization": "demo-xinghai"},
    {"username": "demo_km", "label": "知识库管理员", "description": "维护文档、解析、切片、索引和评测集。", "organization": "demo-xinghai"},
    {"username": "demo_auditor", "label": "审计员", "description": "只读查看 Trace、评测报告与授权审计。", "organization": "demo-xinghai"},
    {"username": "demo_engineer", "label": "研发员工", "description": "可查研发制度和本人薪资，不可查 HR 薪酬政策。", "organization": "demo-xinghai"},
    {"username": "demo_hr", "label": "HR 专员", "description": "可查受限薪酬资料，不能管理组织配置。", "organization": "demo-xinghai"},
    {"username": "demo_suspended", "label": "停用员工", "description": "用于验证停用成员零召回。", "organization": "demo-xinghai", "disabled": True},
    {"username": "demo_vendor", "label": "外部供应商", "description": "仅属于远航供应商租户，用于验证跨租户隔离。", "organization": "demo-yuanhang"},
]

SYSTEM_ROLES = {
    "owner": ["manage_organization", "manage_members", "manage_roles", "manage_knowledge_bases", "manage_documents", "manage_policies", "query", "view_traces", "run_evaluations", "use_agent"],
    "admin": ["manage_members", "manage_roles", "manage_knowledge_bases", "manage_documents", "manage_policies", "query", "view_traces", "run_evaluations", "use_agent"],
    "knowledge_manager": ["manage_knowledge_bases", "manage_documents", "query", "view_traces", "run_evaluations", "use_agent"],
    "member": ["query"],
    "auditor": ["view_traces", "run_evaluations"],
    "hr_specialist": ["query", "view_traces"],
}

ASSET_DIR = Path(__file__).resolve().parent / "demo_assets"


def demo_personas():
    users = {u.username: u for u in get_user_model().objects.filter(username__in=DEMO_USERNAMES)}
    result = []
    for persona in PERSONAS:
        if persona["username"] not in users or persona.get("disabled"):
            continue
        result.append({key: value for key, value in persona.items() if key != "disabled"})
    return result


def _user(username, password):
    user, _ = get_user_model().objects.get_or_create(username=username)
    user.is_active = True
    user.is_staff = False
    user.is_superuser = False
    user.set_password(password)
    user.save()
    return user


def _roles(org):
    rows = {}
    for slug, capabilities in SYSTEM_ROLES.items():
        rows[slug], _ = Role.objects.update_or_create(
            organization=org,
            slug=slug,
            defaults={"name": slug.replace("_", " ").title(), "capabilities": capabilities, "is_system": slug != "hr_specialist"},
        )
    return rows


def _membership(org, user, roles, role_slugs, department, clearance, status="active"):
    item, _ = Membership.objects.update_or_create(
        organization=org, user=user,
        defaults={"department": department, "clearance": clearance, "status": status},
    )
    item.roles.set([roles[slug] for slug in role_slugs])
    return item


def _policy(org, owner, name, classification, visibility="organization", roles=(), users=(), departments=(), denied=()):
    policy, _ = AccessPolicy.objects.update_or_create(
        organization=org, name=name,
        defaults={
            "classification": classification, "visibility": visibility,
            "allowed_departments": list(departments), "is_active": True,
            "created_by": owner,
        },
    )
    policy.allowed_roles.set(list(roles))
    policy.allowed_users.set(list(users))
    policy.denied_users.set(list(denied))
    return policy


def _copy_document(kb, policy, filename, *, process):
    source = ASSET_DIR / filename
    if not source.is_file():
        raise FileNotFoundError(f"Demo PDF is missing: {source}")
    document = Document.objects.filter(kb=kb, filename=filename).first()
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if not document:
        document = Document(
            kb=kb, access_policy=policy, inherits_policy=False, filename=filename,
            file_type="pdf", mime_type="application/pdf", size_bytes=source.stat().st_size,
            sha256=digest, status="uploaded", chunk_method="sentence",
            chunk_options={"chunk_size": 500, "chunk_overlap": 80},
        )
        with source.open("rb") as handle:
            document.file.save(f"demo/{kb.organization.slug}/{filename}", File(handle), save=False)
        document.save()
    else:
        document.access_policy = policy
        document.inherits_policy = False
        document.save(update_fields=["access_policy", "inherits_policy", "updated_at"])
    if process:
        from .document_parsing.service import execute_parse_run
        from .index_lifecycle import build_index_manifest, sign_manifest
        from .indexing import index_document

        run = document.parse_runs.filter(status__in=["completed", "needs_review"]).order_by("-id").first()
        if not run:
            run = DocumentParseRun.objects.create(document=document, status="queued")
            execute_parse_run(run.id, task_id="demo-seed")
            run.refresh_from_db()
        if run.status == "needs_review":
            metrics = {**(run.quality_metrics or {}), "demo_accepted": True}
            run.status = "completed"
            run.quality_metrics = metrics
            run.save(update_fields=["status", "quality_metrics", "updated_at"])
            Document.objects.filter(id=document.id).update(status="parsed", error_message="")
        if run.status != "completed":
            raise RuntimeError(f"Demo document parse failed: {filename}: {run.error_message or run.status}")
        if not document.chunks.exists():
            manifest = build_index_manifest(document, run, document.chunk_method, document.chunk_options)
            signature = sign_manifest(manifest)
            index_run = DocumentIndexRun.objects.create(
                document=document, parse_run=run, status="running", chunk_method=document.chunk_method,
                chunk_options=document.chunk_options, target_manifest=manifest, target_signature=signature,
                celery_task_id="demo-seed", started_at=timezone.now(),
            )
            try:
                count = index_document(document, document.chunk_method, document.chunk_options, run.id)
            except Exception as exc:
                index_run.status = "failed"
                index_run.error_message = str(exc)
                index_run.finished_at = timezone.now()
                index_run.save(update_fields=["status", "error_message", "finished_at", "updated_at"])
                raise
            index_run.status = "completed"
            index_run.chunk_count = count
            index_run.progress_current = count
            index_run.progress_total = count
            index_run.finished_at = timezone.now()
            index_run.save(update_fields=["status", "chunk_count", "progress_current", "progress_total", "finished_at", "updated_at"])
            document.refresh_from_db()
            document.index_signature = signature
            document.index_manifest = manifest
            document.indexed_at = timezone.now()
            document.save(update_fields=["index_signature", "index_manifest", "indexed_at", "updated_at"])
    return document


def _case(kb, case_id, suite, question, reference, expected_terms, **extra):
    defaults = {
        "case_type": extra.pop("case_type", "expert"), "question": question,
        "reference": reference, "expected_terms": expected_terms, "suite": suite,
        "deterministic_checks": extra.pop("deterministic_checks", {"answer_contains": expected_terms}),
        "rubric": {"correctness": "事实与标准答案一致", "citation": "引用能支持关键结论"},
        "thresholds": {"correctness_score": 0.8, "citation_score": 0.8, "hallucination_risk": 0.2},
        "source": "expert", "difficulty": extra.pop("difficulty", "medium"), "enabled": True,
        **extra,
    }
    return RagBenchmarkCase.objects.update_or_create(kb=kb, case_id=case_id, defaults=defaults)[0]


def _seed_cases(kb, docs, members):
    _case(kb, "smoke-release-window", "smoke", "普通变更的发布窗口是什么？", "每周二、周四 14:00-16:00。", ["周二", "周四", "14:00-16:00"])
    _case(kb, "benchmark-probation", "benchmark", "新员工试用期通常多久？", "试用期通常为三个月。", ["三个月"])
    _case(kb, "regression-orion-dr", "regression", "ORION 灾备演练的验证码是什么？", "验证码为 ORION-7421。", ["ORION-7421"], difficulty="hard")
    _case(kb, "release-change-approval", "release", "高风险变更发布前必须满足什么条件？", "必须完成双人复核、回滚演练，并通过 release 评测。", ["双人复核", "回滚", "release"])
    all_documents = [document.id for document in docs.values()]
    engineering_documents = [docs["engineering"].id, docs["mixed"].id]
    cases = [
        ("security-engineer-no-hr", members["engineer"], "高管年度奖金系数是多少？", [docs["compensation"].id], []),
        ("security-hr-scope", members["hr"], "高管年度奖金系数是多少？", engineering_documents, [document_id for document_id in all_documents if document_id not in engineering_documents]),
        ("security-suspended-zero", members["suspended"], "公司年假有几天？", all_documents, []),
        ("security-cross-tenant-zero", members["vendor"], "星海科技发布窗口是什么？", all_documents, []),
        ("security-owner-read", members["owner"], "高管年度奖金系数是多少？", [], all_documents),
    ]
    for case_id, principal, question, forbidden_documents, expected_documents in cases:
        _case(
            kb, case_id, "security", question, "验证授权 Scope 内零越权召回。", [],
            case_type="security_acl", principal_membership=principal,
            forbidden_document_ids=forbidden_documents,
            expected_authorized_document_ids=expected_documents,
            deterministic_checks={"unauthorized_recall_zero": True},
        )


def _seed_parse_cases(owner):
    specs = [
        ("parse-guide", "RAGPilot 演示手册", "ragpilot_demo_guide.pdf", 11, []),
        ("parse-text-pdf", "研发发布规范", "xinghai_engineering_release.pdf", 5, []),
        ("parse-mixed-ocr", "混合 OCR 灾备手册", "xinghai_mixed_ocr_dr.pdf", 4, [3]),
    ]
    for case_id, title, filename, pages, ocr_pages in specs:
        case = DocumentParseBenchmarkCase.objects.filter(owner=owner, case_id=case_id).first()
        defaults = {
            "title": title, "suite": "benchmark", "tags": ["demo", "pdf"],
            "expected_page_count": pages, "expected_ocr_pages": ocr_pages,
            "expected_headings": [],
            "expected_terms_by_page": {"3": ["ORION-7421"]} if ocr_pages else {},
            "expected_block_types": ["paragraph"],
            "thresholds": {"text_coverage": 0.9, "abnormal_char_ratio": 0.02}, "enabled": True,
        }
        if not case:
            source = ASSET_DIR / filename
            case = DocumentParseBenchmarkCase(owner=owner, case_id=case_id, **defaults)
            with source.open("rb") as handle:
                case.file.save(f"demo/{filename}", File(handle), save=False)
            case.save()
        else:
            for key, value in defaults.items():
                setattr(case, key, value)
            case.save()


def _seed_agent_story(kb, owner, policy):
    initial = ensure_initial_config(kb, owner)
    baseline = RagEvalRun.objects.create(
        kb=kb, status="completed", metrics=["answer_relevancy", "faithfulness"],
        settings={"suite": "regression", "demo_seed": DEMO_SEED_VERSION, "requested_options": initial.payload},
        mean_scores={"answer_relevancy": 0.73, "faithfulness": 0.78},
        retrieval_metrics={"pass_rate": 0.75, "failed_cases": 1}, case_count=4,
        execution_metrics={"avg_latency_ms": 1280, "total_tokens": 4200}, finished_at=timezone.now(),
    )
    failure = RagEvalCaseResult.objects.create(
        run=baseline, case_id="regression-orion-dr", case_type="regression", suite="regression",
        question="ORION 灾备演练的验证码是什么？", reference="ORION-7421", answer="未找到相关信息。",
        scores={"answer_relevancy": 0.2, "faithfulness": 1.0},
        diagnostics={"failure_categories": ["compression_lost"], "summary": "压缩阶段丢失扫描页关键术语"},
        deterministic_results={"passed": False, "checks": [{"type": "answer_contains", "passed": False, "expected": "ORION-7421"}]},
        judge_results={"correctness_score": 0.1, "citation_score": 0.0, "hallucination_risk": 0.1, "reason": "答案遗漏关键事实。"},
        execution_metrics={"latency_ms": 1320, "total_tokens": 980},
    )
    candidate_chunks = list(kb.chunks.filter(document__filename="xinghai_mixed_ocr_dr.pdf").order_by("index")[:2])
    candidate_ids = [chunk.id for chunk in candidate_chunks]
    trace_policy_ids = sorted({chunk.access_policy_id for chunk in candidate_chunks if chunk.access_policy_id}) or [policy.id]
    stage_rows = [{
        "chunk_id": chunk.id, "document_id": chunk.document_id, "score": round(0.93 - offset * 0.05, 2),
        "location": {
            "page_start": chunk.metadata.get("page_start"), "page_end": chunk.metadata.get("page_end"),
            "heading_path": chunk.metadata.get("heading_path") or [],
        },
        "char_count": len(chunk.content),
        "content_hash": hashlib.sha256(chunk.content.encode("utf-8")).hexdigest()[:16],
        "summary": "灾备手册扫描页候选（正文已脱敏）",
    } for offset, chunk in enumerate(candidate_chunks)]
    session = ChatSession.objects.create(owner=owner, kb=kb, title="Demo · OCR 关键术语回归失败")
    message = ChatMessage.objects.create(
        session=session, role="assistant", content="当前上下文未保留足够证据，无法确认验证码。",
        source_chunk_ids=candidate_ids, source_policy_ids=trace_policy_ids,
        authorization_snapshot={"organization_id": kb.organization_id, "policy_ids": trace_policy_ids},
    )
    RagTrace.objects.create(
        session=session, message=message, organization=kb.organization,
        access_scope_fingerprint=hashlib.sha256(f"demo:{kb.organization_id}:{', '.join(map(str, trace_policy_ids))}".encode()).hexdigest(),
        access_policy_ids=trace_policy_ids, authorization_decision={"allowed": True, "filtered_count": 0},
        redaction_metadata={"mode": "summary_hash_only", "sensitive_fields_removed": True},
        question="ORION 灾备演练的验证码是什么？", rewritten_query="ORION 灾备 验证码",
        query_intent="internal_knowledge", route_decision="rag", route_reason="企业知识库事实查询",
        retrieval_mode="hybrid", vector_results=stage_rows, bm25_results=stage_rows,
        hybrid_results=stage_rows, rerank_results=stage_rows, compression_results=[],
        compression_stats={"input_chunks": len(stage_rows), "output_chunks": 0, "lost_required_terms": ["ORION-7421"]},
        settings={"demo_seed": DEMO_SEED_VERSION, "failure_stage": "compression", "config_version": initial.version},
    )
    plan = RagExperimentPlan.objects.create(
        owner=owner, kb=kb, baseline_run=baseline, goal="恢复 OCR 关键术语并保持延迟预算",
        status="completed", failure_cases=[failure.id],
        failure_summary={"primary_stage": "compression", "failed_cases": 1},
        recommendation={"winner_reason": "结构化压缩保留关键术语，通过 deterministic checks，延迟增幅 8.6%。"},
        started_at=timezone.now(), completed_at=timezone.now(),
    )
    winner_run = RagEvalRun.objects.create(
        kb=kb, baseline_run=baseline, status="completed", metrics=baseline.metrics,
        settings={"suite": "regression", "demo_seed": DEMO_SEED_VERSION, "experiment_plan": plan.id, "requested_options": {**initial.payload, "compression_strategy": "structure_aware", "rerank_top_n": 6}},
        mean_scores={"answer_relevancy": 0.87, "faithfulness": 0.91},
        retrieval_metrics={"pass_rate": 1.0, "failed_cases": 0}, case_count=4,
        execution_metrics={"avg_latency_ms": 1390, "total_tokens": 4380}, finished_at=timezone.now(),
    )
    winner = RagExperimentVariant.objects.create(
        plan=plan, eval_run=winner_run, name="保留结构关键术语", hypothesis="增加 rerank 保留量并使用结构化压缩",
        rag_options={"rerank_top_n": 6, "compression_strategy": "structure_aware"},
        result_summary={"score": 0.89, "score_delta": 0.135, "failed_cases": 0, "latency_ratio": 1.086}, is_winner=True,
    )
    RagExperimentVariant.objects.create(
        plan=plan, name="扩大初始召回", hypothesis="提高 top_k", rag_options={"top_k": 8},
        result_summary={"score": 0.79, "score_delta": 0.035, "failed_cases": 1, "latency_ratio": 1.24},
    )
    plan.winner_variant = winner
    plan.save(update_fields=["winner_variant", "updated_at"])
    release = RagEvalRun.objects.create(
        kb=kb, baseline_run=baseline, status="completed", metrics=baseline.metrics,
        settings={"suite": "release", "demo_seed": DEMO_SEED_VERSION, "experiment_plan": plan.id, "requested_options": winner.rag_options},
        mean_scores={"answer_relevancy": 0.9, "faithfulness": 0.93},
        retrieval_metrics={"pass_rate": 1.0, "failed_cases": 0}, case_count=1,
        execution_metrics={"avg_latency_ms": 1410, "total_tokens": 1120}, finished_at=timezone.now(),
    )
    candidate = create_config_version(
        kb=kb, payload={**initial.payload, **winner.rag_options}, user=owner, source="experiment",
        parent=initial, experiment_plan=plan, winner_variant=winner, release_eval_run=release,
    )
    candidate.validation_status = "release_passed"
    candidate.save(update_fields=["validation_status"])
    RagAgentAction.objects.create(
        owner=owner, kb=kb, eval_run=release, action_uid=f"demo-publish-config-{candidate.id}",
        action_type="publish_rag_config", source="demo_seed", title="发布通过 Release Gate 的 RAG 配置",
        description="候选配置提升回归得分且没有新增失败 Case。确认后原子切换活跃版本。",
        confirm_label="确认发布", payload={"config_version": candidate.id, "reason": "Demo release gate passed"}, status="pending",
    )


def seed_demo_workspace(*, process=False, reset=False):
    if reset:
        reset_demo_workspace(delete_users=True)
    password = getattr(settings, "DEMO_DEFAULT_PASSWORD", "RagPilot-Demo-2026")
    users = {username: _user(username, password) for username in DEMO_USERNAMES}
    xinghai, _ = Organization.objects.update_or_create(
        slug="demo-xinghai", defaults={"name": "星海科技（演示租户）", "created_by": users["demo_owner"], "is_demo": True, "demo_seed_version": DEMO_SEED_VERSION},
    )
    yuanhang, _ = Organization.objects.update_or_create(
        slug="demo-yuanhang", defaults={"name": "远航供应链（隔离租户）", "created_by": users["demo_vendor"], "is_demo": True, "demo_seed_version": DEMO_SEED_VERSION},
    )
    xr, yr = _roles(xinghai), _roles(yuanhang)
    members = {
        "owner": _membership(xinghai, users["demo_owner"], xr, ["owner"], "Executive", "restricted"),
        "km": _membership(xinghai, users["demo_km"], xr, ["knowledge_manager"], "Knowledge Platform", "restricted"),
        "auditor": _membership(xinghai, users["demo_auditor"], xr, ["auditor"], "Audit", "confidential"),
        "engineer": _membership(xinghai, users["demo_engineer"], xr, ["member"], "Engineering", "restricted"),
        "hr": _membership(xinghai, users["demo_hr"], xr, ["member", "hr_specialist"], "HR", "restricted"),
        "suspended": _membership(xinghai, users["demo_suspended"], xr, ["member"], "Engineering", "confidential", "suspended"),
        "vendor": _membership(yuanhang, users["demo_vendor"], yr, ["member"], "Delivery", "internal"),
    }
    general = _policy(xinghai, users["demo_owner"], "全员内部资料", "internal")
    engineering = _policy(xinghai, users["demo_owner"], "研发机密资料", "confidential", "restricted", departments=["Engineering"])
    compensation = _policy(xinghai, users["demo_owner"], "HR 薪酬受限资料", "restricted", "restricted", roles=[xr["hr_specialist"]])
    personal = _policy(xinghai, users["demo_owner"], "林晓个人薪资", "restricted", "restricted", roles=[xr["hr_specialist"]], users=[users["demo_engineer"]])
    vendor_policy = _policy(yuanhang, users["demo_vendor"], "供应商内部资料", "internal")
    kb, _ = KnowledgeBase.objects.update_or_create(
        organization=xinghai, name="星海科技企业知识库", defaults={"owner": users["demo_owner"], "description": "覆盖制度、研发发布、OCR 灾备与受限薪酬的全链路演示知识库。", "visibility": "organization", "access_policy": general},
    )
    vendor_kb, _ = KnowledgeBase.objects.update_or_create(
        organization=yuanhang, name="远航供应商知识库", defaults={"owner": users["demo_vendor"], "description": "用于验证跨租户零召回。", "visibility": "organization", "access_policy": vendor_policy},
    )
    document_specs = {
        "guide": ("ragpilot_demo_guide.pdf", general),
        "employee": ("xinghai_employee_handbook.pdf", general),
        "engineering": ("xinghai_engineering_release.pdf", engineering),
        "compensation": ("xinghai_compensation_policy.pdf", compensation),
        "salary": ("xinghai_personal_salary_linxiao.pdf", personal),
        "mixed": ("xinghai_mixed_ocr_dr.pdf", engineering),
    }
    docs = {key: _copy_document(kb, policy, filename, process=process) for key, (filename, policy) in document_specs.items()}
    _copy_document(vendor_kb, vendor_policy, "yuanhang_vendor_delivery.pdf", process=process)
    _seed_cases(kb, docs, members)
    _seed_parse_cases(users["demo_km"])
    if not kb.eval_runs.filter(settings__demo_seed=DEMO_SEED_VERSION).exists():
        _seed_agent_story(kb, users["demo_owner"], general)
    ensure_initial_config(vendor_kb, users["demo_vendor"])
    return {"organization": xinghai, "knowledge_base": kb, "documents": docs, "members": members}


def reset_demo_workspace(*, delete_users=False):
    organizations = list(Organization.objects.filter(is_demo=True, slug__in=DEMO_ORG_SLUGS))
    for organization in organizations:
        for document in Document.objects.filter(kb__organization=organization):
            try:
                from .vector_store import get_vector_store
                get_vector_store().delete_document(document.id)
            except Exception:
                pass
            if document.file:
                document.file.delete(save=False)
        DocumentIndexRun.objects.filter(document__kb__organization=organization).delete()
        KnowledgeBase.objects.filter(organization=organization).delete()
        AccessPolicy.objects.filter(organization=organization).delete()
        organization.delete()
    for case in DocumentParseBenchmarkCase.objects.filter(owner__username__in=DEMO_USERNAMES):
        if case.file:
            case.file.delete(save=False)
    DocumentParseBenchmarkCase.objects.filter(owner__username__in=DEMO_USERNAMES).delete()
    if delete_users:
        get_user_model().objects.filter(username__in=DEMO_USERNAMES).delete()
    return len(organizations)
