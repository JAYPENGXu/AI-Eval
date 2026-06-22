from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from django.db.models import Q, QuerySet
from rest_framework.exceptions import PermissionDenied as DRFPermissionDenied

from .models import (
    AccessPolicy, AuthorizationAuditLog, CLASSIFICATION_RANK, Chunk, Document,
    KnowledgeBase, Membership, Organization, RagTrace,
)


class AccessDenied(PermissionError, DRFPermissionDenied):
    pass


@dataclass
class AccessScope:
    user: object
    organization: Organization | None
    membership: Membership | None
    role_ids: set[int] = field(default_factory=set)
    role_slugs: set[str] = field(default_factory=set)
    capabilities: set[str] = field(default_factory=set)
    allowed_policy_ids: set[int] = field(default_factory=set)
    clearance: str = "public"
    department: str = ""
    is_admin: bool = False
    denial_reason: str = ""

    @property
    def active(self) -> bool:
        return bool(self.membership and self.membership.status == "active" and self.organization)

    @property
    def fingerprint(self) -> str:
        payload = {
            "organization": self.organization.id if self.organization else None,
            "membership": self.membership.id if self.membership else None,
            "roles": sorted(self.role_ids),
            "capabilities": sorted(self.capabilities),
            "policies": sorted(self.allowed_policy_ids),
            "clearance": self.clearance,
            "department": self.department,
            "admin": self.is_admin,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def can_capability(self, capability: str) -> bool:
        return self.active and capability in self.capabilities

    def can_policy(self, policy_id: int | None) -> bool:
        return self.active and bool(policy_id) and int(policy_id) in self.allowed_policy_ids

    def can_knowledge_base(self, kb: KnowledgeBase, capability: str = "query") -> bool:
        if not self.active or kb.organization_id != self.organization.id or not self.can_capability(capability):
            return False
        if not kb.access_policy_id or not self.can_policy(kb.access_policy_id):
            return False
        if self.is_admin:
            return True
        if kb.visibility == "private":
            return kb.owner_id == self.user.id
        return self.can_policy(kb.access_policy_id)

    def filter_knowledge_bases(self, queryset: QuerySet | None = None, capability: str = "query"):
        queryset = queryset if queryset is not None else KnowledgeBase.objects.all()
        if not self.active or not self.can_capability(capability):
            return queryset.none()
        base = queryset.filter(organization=self.organization)
        if self.is_admin:
            return base.filter(access_policy_id__in=self.allowed_policy_ids)
        return base.filter(
            Q(visibility="private", owner=self.user)
            | Q(visibility__in=["organization", "restricted"], access_policy_id__in=self.allowed_policy_ids)
        )

    def filter_documents(self, queryset: QuerySet | None = None, capability: str = "query"):
        queryset = queryset if queryset is not None else Document.objects.all()
        kb_ids = self.filter_knowledge_bases(capability=capability).values("id")
        return queryset.filter(kb_id__in=kb_ids, access_policy_id__in=self.allowed_policy_ids)

    def filter_chunks(self, queryset: QuerySet | None = None, capability: str = "query"):
        queryset = queryset if queryset is not None else Chunk.objects.all()
        kb_ids = self.filter_knowledge_bases(capability=capability).values("id")
        return queryset.filter(kb_id__in=kb_ids, access_policy_id__in=self.allowed_policy_ids)

    def filter_traces(self, queryset: QuerySet | None = None):
        queryset = queryset if queryset is not None else RagTrace.objects.all()
        if not self.can_capability("view_traces"):
            return queryset.none()
        kb_ids = self.filter_knowledge_bases(capability="view_traces").values("id")
        return queryset.filter(organization=self.organization, session__kb_id__in=kb_ids)

    def milvus_filter_expression(self, kb_id: int) -> str:
        if not self.active:
            return "organization_id == -1"
        policy_ids = sorted(self.allowed_policy_ids)
        if not policy_ids:
            return "organization_id == -1"
        values = ", ".join(str(value) for value in policy_ids)
        return (
            f"organization_id == {int(self.organization.id)} and kb_id == {int(kb_id)} "
            f"and access_policy_id in [{values}]"
        )

    def cache_key(self, namespace: str, *parts) -> str:
        safe = ":".join(str(part) for part in parts)
        return f"{namespace}:org:{self.organization.id if self.organization else 'none'}:scope:{self.fingerprint}:{safe}"


def _policy_allowed(policy, membership, role_ids: set[int], is_admin: bool) -> bool:
    if not policy.is_active:
        return False
    if policy.denied_users.filter(id=membership.user_id).exists():
        return False
    if is_admin:
        return True
    if CLASSIFICATION_RANK.get(membership.clearance, -1) < CLASSIFICATION_RANK.get(policy.classification, 99):
        return False
    if policy.visibility == "organization":
        return True
    if policy.allowed_users.filter(id=membership.user_id).exists():
        return True
    if role_ids and policy.allowed_roles.filter(id__in=role_ids).exists():
        return True
    departments = {str(value).strip() for value in (policy.allowed_departments or []) if str(value).strip()}
    return bool(membership.department and membership.department in departments)


def build_access_scope(user, kb: KnowledgeBase | None = None, organization: Organization | int | None = None) -> AccessScope:
    if not user or not getattr(user, "is_authenticated", False):
        return AccessScope(user=user, organization=None, membership=None, denial_reason="authentication_required")
    org_id = kb.organization_id if kb else (organization.id if isinstance(organization, Organization) else organization)
    if not org_id:
        return AccessScope(user=user, organization=None, membership=None, denial_reason="organization_required")
    membership = (
        Membership.objects.filter(user=user, organization_id=org_id)
        .select_related("organization")
        .prefetch_related("roles")
        .first()
    )
    if not membership or membership.status != "active":
        org = Organization.objects.filter(id=org_id).first()
        return AccessScope(user=user, organization=org, membership=membership, denial_reason="membership_inactive")
    roles = list(membership.roles.filter(organization_id=org_id))
    role_ids = {role.id for role in roles}
    role_slugs = {role.slug for role in roles}
    capabilities = {cap for role in roles for cap in (role.capabilities or [])}
    is_admin = bool(role_slugs & {"owner", "admin"})
    policies = AccessPolicy.objects.filter(organization_id=org_id).prefetch_related(
        "allowed_roles", "allowed_users", "denied_users"
    )
    allowed = {
        policy.id for policy in policies
        if _policy_allowed(policy, membership, role_ids, is_admin)
    }
    return AccessScope(
        user=user, organization=membership.organization, membership=membership,
        role_ids=role_ids, role_slugs=role_slugs, capabilities=capabilities,
        allowed_policy_ids=allowed, clearance=membership.clearance,
        department=membership.department, is_admin=is_admin,
    )


def scopes_for_user(user) -> list[AccessScope]:
    memberships = Membership.objects.filter(user=user, status="active").select_related("organization")
    return [build_access_scope(user, organization=item.organization_id) for item in memberships]


def filter_knowledge_bases_for_user(user, queryset=None, capability="query"):
    queryset = queryset if queryset is not None else KnowledgeBase.objects.all()
    ids = []
    for scope in scopes_for_user(user):
        ids.extend(scope.filter_knowledge_bases(capability=capability).values_list("id", flat=True))
    return queryset.filter(id__in=set(ids))


def filter_documents_for_user(user, queryset=None, capability="query"):
    queryset = queryset if queryset is not None else Document.objects.all()
    ids = []
    for scope in scopes_for_user(user):
        ids.extend(scope.filter_documents(capability=capability).values_list("id", flat=True))
    return queryset.filter(id__in=set(ids))


def filter_traces_for_user(user, queryset=None):
    queryset = queryset if queryset is not None else RagTrace.objects.all()
    ids = []
    for scope in scopes_for_user(user):
        ids.extend(scope.filter_traces().values_list("id", flat=True))
    return queryset.filter(id__in=set(ids))


def require_capability(user, capability: str, *, kb=None, organization=None) -> AccessScope:
    scope = build_access_scope(user, kb=kb, organization=organization)
    if not scope.can_capability(capability):
        audit_access(scope, capability, kb or organization, False, "capability_denied")
        raise AccessDenied(f"Missing capability: {capability}")
    return scope


def audit_access(scope: AccessScope, action: str, resource=None, allowed=False, reason="", metadata=None):
    if not scope.organization:
        return None
    resource_type = resource.__class__.__name__ if resource is not None else ""
    resource_id = str(getattr(resource, "pk", "") or "")
    return AuthorizationAuditLog.objects.create(
        organization=scope.organization, actor=scope.user if getattr(scope.user, "is_authenticated", False) else None,
        membership=scope.membership, action=action, resource_type=resource_type,
        resource_id=resource_id, allowed=allowed, reason=str(reason)[:240],
        scope_fingerprint=scope.fingerprint, metadata=metadata or {},
    )
