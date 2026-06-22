import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from rag.config_versions import create_config_version, deploy_config, ensure_initial_config, resolve_runtime_config
from rag.index_lifecycle import index_health
from rag.models import (
    Chunk,
    Document,
    DocumentParseBenchmarkCase,
    DocumentParseEvalRun,
    DocumentParseRun,
    KnowledgeBase,
    RagConfigDeployment,
    RagEvalCaseResult,
    RagEvalRun,
    RagExperimentPlan,
    RagExperimentVariant,
)
from rag.parse_evaluation import execute_parse_eval_run
from rag.experiments import choose_winner, create_release_candidate, summarize_variant


class ConfigVersionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="ops", password="secret")
        self.kb = KnowledgeBase.objects.create(owner=self.user, name="KB")

    def test_initial_config_and_override_precedence(self):
        active = ensure_initial_config(self.kb, self.user)
        resolved, metadata = resolve_runtime_config(
            self.kb, {"top_k": 9, "embedding_model": "forbidden"}, override_enabled=True
        )
        self.assertEqual(active.validation_status, "release_passed")
        self.assertEqual(resolved["top_k"], 9)
        self.assertNotIn("embedding_model", resolved)
        self.assertEqual(metadata["config_source"], "temporary_override")

    def test_publish_and_rollback_are_audited(self):
        initial = ensure_initial_config(self.kb, self.user)
        candidate = create_config_version(
            kb=self.kb, payload={"top_k": 8}, user=self.user, source="manual", parent=initial
        )
        candidate.validation_status = "release_passed"
        candidate.save(update_fields=["validation_status"])
        publish = deploy_config(kb=self.kb, target=candidate, user=self.user)
        rollback = deploy_config(
            kb=self.kb, target=initial, user=self.user, operation="rollback", reason="regression"
        )
        self.kb.refresh_from_db()
        self.assertEqual(self.kb.active_config_version_id, initial.id)
        self.assertEqual(publish.previous_version_id, initial.id)
        self.assertEqual(rollback.previous_version_id, candidate.id)
        self.assertEqual(RagConfigDeployment.objects.count(), 2)


class IndexHealthTests(TestCase):
    def setUp(self):
        user = User.objects.create_user(username="indexer")
        self.kb = KnowledgeBase.objects.create(owner=user, name="KB")
        self.document = Document.objects.create(
            kb=self.kb, filename="doc.txt", file=SimpleUploadedFile("doc.txt", b"hello"),
            file_type="txt", sha256="abc", status="indexed",
        )
        self.parse_run = DocumentParseRun.objects.create(
            document=self.document, status="completed", parser="text", parser_version="1.0"
        )
        Chunk.objects.create(document=self.document, kb=self.kb, parse_run=self.parse_run, index=0, content="hello")

    def test_legacy_index_is_warned_but_usable(self):
        state = index_health(self.document)
        self.assertTrue(state["stale"])
        self.assertFalse(state["critical"])
        self.assertTrue(state["usable"])
        self.assertEqual(state["reasons"][0]["code"], "missing_manifest")

    @override_settings(EMBEDDING_DIMENSIONS=1024)
    def test_dimension_change_is_critical(self):
        self.document.index_signature = "sig"
        self.document.index_manifest = {
            "parse_run_id": self.parse_run.id,
            "embedding_model": "model",
            "embedding_dimensions": 768,
            "vector_collection": "aiassistant_chunks",
            "index_schema_version": "2",
        }
        self.document.save(update_fields=["index_signature", "index_manifest"])
        self.assertTrue(index_health(self.document)["critical"])


class ParseEvaluationTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.tmp.name)
        self.override.enable()
        self.user = User.objects.create_user(username="parser")

    def tearDown(self):
        self.override.disable()
        self.tmp.cleanup()

    def test_markdown_case_runs_and_saves_page_checks(self):
        case = DocumentParseBenchmarkCase.objects.create(
            owner=self.user, case_id="md-1", title="Markdown",
            file=SimpleUploadedFile("sample.md", b"# Architecture\n\nRedis and Celery."),
            suite="smoke", expected_page_count=1, expected_headings=["Architecture"],
            expected_terms_by_page={"1": ["Redis", "Celery"]}, expected_block_types=["heading", "paragraph"],
        )
        run = DocumentParseEvalRun.objects.create(owner=self.user, suite="smoke")
        execute_parse_eval_run(run.id)
        run.refresh_from_db()
        result = run.case_results.get(case=case)
        self.assertEqual(run.status, "completed")
        self.assertTrue(result.passed)
        self.assertEqual(result.metrics["heading_recall"], 1.0)
        self.assertTrue(result.checks["page_terms"])


class HealthApiTests(TestCase):
    def test_live_is_public_and_ready_uses_503_when_dependency_fails(self):
        client = APIClient()
        self.assertEqual(client.get("/api/health/live/").status_code, 200)
        with patch("rag.views.health_report", return_value={"ready": False, "status": "unavailable", "checks": {}}):
            self.assertEqual(client.get("/api/health/ready/").status_code, 503)


class AgentExperimentGateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="agent")
        self.kb = KnowledgeBase.objects.create(owner=self.user, name="KB")
        self.baseline = RagEvalRun.objects.create(kb=self.kb, status="completed", mean_scores={"faithfulness": 0.7}, case_count=1, execution_metrics={"avg_latency_ms": 100})
        RagEvalCaseResult.objects.create(run=self.baseline, case_id="base", question="q", diagnostics={"final_answer": {"correct": True}})
        self.plan = RagExperimentPlan.objects.create(owner=self.user, kb=self.kb, baseline_run=self.baseline, goal="improve", status="running")

    def test_winner_requires_material_gain_and_release_case_is_mandatory(self):
        run = RagEvalRun.objects.create(kb=self.kb, baseline_run=self.baseline, status="completed", mean_scores={"faithfulness": 0.75}, case_count=1, execution_metrics={"avg_latency_ms": 110})
        RagEvalCaseResult.objects.create(run=run, case_id="candidate", question="q", diagnostics={"final_answer": {"correct": True}}, deterministic_results={"passed": True}, judge_results={"passed": True})
        variant = RagExperimentVariant.objects.create(plan=self.plan, eval_run=run, name="candidate", rag_options={"top_k": 8})
        variant.result_summary = summarize_variant(self.baseline, run); variant.save(update_fields=["result_summary"])
        self.assertEqual(choose_winner([variant]), variant)
        candidate = create_release_candidate(self.plan, variant)
        candidate.refresh_from_db()
        self.assertEqual(candidate.validation_status, "release_failed")
        self.assertEqual(self.plan.config_versions.count(), 1)

    def test_latency_regression_rejects_winner(self):
        run = RagEvalRun.objects.create(kb=self.kb, baseline_run=self.baseline, status="completed", mean_scores={"faithfulness": 0.9}, case_count=1, execution_metrics={"avg_latency_ms": 150})
        RagEvalCaseResult.objects.create(run=run, case_id="slow", question="q", diagnostics={"final_answer": {"correct": True}}, deterministic_results={"passed": True}, judge_results={"passed": True})
        variant = RagExperimentVariant.objects.create(plan=self.plan, eval_run=run, name="slow")
        variant.result_summary = summarize_variant(self.baseline, run)
        self.assertIsNone(choose_winner([variant]))
