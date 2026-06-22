from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient, APIRequestFactory

from rag.access_control import build_access_scope
from rag.bm25 import bm25_search
from rag.models import AccessPolicy, ChatMessage, ChatSession, Chunk, Document, KnowledgeBase, Membership, RagBenchmarkCase, RagEvalRun
from rag.security_evaluation import execute_security_eval_run
from rag.serializers import ChatMessageSerializer
from rag.tenancy import bootstrap_user_organization, ensure_builtin_roles


class AccessFixture(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("owner", password="pw")
        self.employee = User.objects.create_user("employee", password="pw")
        self.outsider = User.objects.create_user("outsider", password="pw")
        self.org = bootstrap_user_organization(self.owner)
        self.roles = ensure_builtin_roles(self.org)
        self.employee_membership = Membership.objects.create(organization=self.org, user=self.employee, status="active", department="engineering", clearance="internal")
        self.employee_membership.roles.add(self.roles["member"])
        self.general = AccessPolicy.objects.create(organization=self.org, name="General", classification="internal", visibility="organization", created_by=self.owner)
        self.restricted = AccessPolicy.objects.create(organization=self.org, name="HR Salary", classification="confidential", visibility="restricted", created_by=self.owner)
        self.restricted.allowed_roles.add(self.roles["owner"])
        self.kb = KnowledgeBase.objects.create(owner=self.owner, organization=self.org, access_policy=self.general, visibility="organization", name="Shared KB")
        self.general_doc = Document.objects.create(kb=self.kb, access_policy=self.general, filename="guide.txt", file_type="txt", status="indexed")
        self.general_chunk = Chunk.objects.create(kb=self.kb, document=self.general_doc, access_policy=self.general, index=0, content="engineering handbook", embedding=[1.0, 0.0])
        self.secret_doc = Document.objects.create(kb=self.kb, access_policy=self.restricted, filename="salary.txt", file_type="txt", status="indexed")
        self.secret_chunk = Chunk.objects.create(kb=self.kb, document=self.secret_doc, access_policy=self.restricted, index=0, content="executive salary 900000", embedding=[1.0, 0.0])


class AccessScopeTests(AccessFixture):
    def test_clearance_and_restricted_policy_filter_all_retrieval_sources(self):
        scope = build_access_scope(self.employee, kb=self.kb)
        self.assertEqual(set(scope.filter_chunks().values_list("id", flat=True)), {self.general_chunk.id})
        self.assertEqual([item["chunk_id"] for item in bm25_search(self.kb, "engineering salary", scope=scope)], [self.general_chunk.id])
        expression = scope.milvus_filter_expression(self.kb.id)
        self.assertIn(f"organization_id == {self.org.id}", expression)
        self.assertIn(f"access_policy_id in [{self.general.id}]", expression)

    def test_explicit_deny_has_priority_over_owner_admin(self):
        self.general.denied_users.add(self.owner)
        scope = build_access_scope(self.owner, kb=self.kb)
        self.assertTrue(scope.is_admin)
        self.assertFalse(scope.can_knowledge_base(self.kb))
        self.assertNotIn(self.general.id, scope.allowed_policy_ids)

    def test_suspended_and_cross_tenant_are_fail_closed(self):
        self.employee_membership.status = "suspended"
        self.employee_membership.save(update_fields=["status"])
        self.assertFalse(build_access_scope(self.employee, kb=self.kb).active)
        self.assertFalse(build_access_scope(self.outsider, kb=self.kb).active)

    def test_restricted_department_grant(self):
        self.restricted.classification = "internal"
        self.restricted.allowed_departments = ["engineering"]
        self.restricted.save(update_fields=["classification", "allowed_departments"])
        scope = build_access_scope(self.employee, kb=self.kb)
        self.assertIn(self.secret_chunk.id, scope.filter_chunks().values_list("id", flat=True))


class AuthorizationApiTests(AccessFixture):
    def test_cross_tenant_object_enumeration_returns_404(self):
        other_org = bootstrap_user_organization(self.outsider)
        other_policy = other_org.access_policies.first()
        other_kb = KnowledgeBase.objects.create(owner=self.outsider, organization=other_org, access_policy=other_policy, visibility="private", name="Other")
        client = APIClient(); client.force_authenticate(self.employee)
        self.assertEqual(client.get(f"/api/knowledge-bases/{other_kb.id}/").status_code, 404)

    def test_revoked_source_hides_historical_answer_and_citations(self):
        session = ChatSession.objects.create(owner=self.employee, kb=self.kb)
        message = ChatMessage.objects.create(session=session, role="assistant", content="The handbook says yes.", sources=[{"citation_id": 1, "chunk_id": self.general_chunk.id}], source_chunk_ids=[self.general_chunk.id], source_policy_ids=[self.general.id])
        request = APIRequestFactory().get("/"); request.user = self.employee
        self.assertEqual(ChatMessageSerializer(message, context={"request": request}).data["content"], "The handbook says yes.")
        self.general.denied_users.add(self.employee)
        data = ChatMessageSerializer(message, context={"request": request}).data
        self.assertEqual(data["content"], "内容因权限变更不可用。")
        self.assertEqual(data["sources"], [])


class SecurityEvaluationTests(AccessFixture):
    @patch("rag.security_evaluation.compress_context")
    @patch("rag.security_evaluation.rerank_candidates")
    @patch("rag.security_evaluation.retrieve")
    def test_unauthorized_hit_in_any_stage_fails_without_answer_call(self, retrieve_mock, rerank_mock, compress_mock):
        forbidden = {"chunk_id": self.secret_chunk.id, "content": self.secret_chunk.content, "document": self.secret_doc.filename}
        retrieve_mock.return_value = [forbidden]
        rerank_mock.side_effect = lambda query, items, **kwargs: items
        compress_mock.side_effect = lambda query, items, **kwargs: (items, {})
        case = RagBenchmarkCase.objects.create(kb=self.kb, principal_membership=self.employee_membership, case_id="security-1", case_type="security_acl", suite="security", question="salary", reference="", forbidden_chunk_ids=[self.secret_chunk.id], deterministic_checks={"unauthorized_recall_zero": True})
        run = RagEvalRun.objects.create(kb=self.kb, status="running", settings={"suite": "security"})
        execute_security_eval_run(run, {"query_rewrite_strategy": "rule"})
        result = run.case_results.get(case_id=case.case_id)
        self.assertFalse(result.deterministic_results["passed"])
        self.assertEqual(result.execution_metrics["llm_answer_calls"], 0)
        self.assertIn(self.secret_chunk.id, result.deterministic_results["checks"][0]["actual"])
