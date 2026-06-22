from __future__ import annotations

from django.db import transaction
from django.utils.text import slugify

from .models import AccessPolicy, Membership, Organization, ROLE_CAPABILITIES, Role

BUILTIN_ROLES = {
    "owner": list(ROLE_CAPABILITIES),
    "admin": list(ROLE_CAPABILITIES),
    "knowledge_manager": [
        "manage_knowledge_bases", "manage_documents", "manage_policies", "query",
        "view_traces", "run_evaluations", "use_agent",
    ],
    "member": ["query"],
    "auditor": ["query", "view_traces", "run_evaluations"],
}


def unique_organization_slug(name: str, user_id: int | None = None) -> str:
    base = slugify(name) or "organization"
    if user_id:
        base = f"{base}-{user_id}"
    value = base[:170]
    suffix = 1
    while Organization.objects.filter(slug=value).exists():
        suffix += 1
        value = f"{base[:165]}-{suffix}"
    return value


def ensure_builtin_roles(organization: Organization) -> dict[str, Role]:
    roles = {}
    for slug, capabilities in BUILTIN_ROLES.items():
        role, _ = Role.objects.update_or_create(
            organization=organization,
            slug=slug,
            defaults={"name": slug.replace("_", " ").title(), "capabilities": capabilities, "is_system": True},
        )
        roles[slug] = role
    return roles


@transaction.atomic
def bootstrap_user_organization(user, *, name: str | None = None) -> Organization:
    existing = Organization.objects.filter(memberships__user=user, memberships__status="active").order_by("id").first()
    if existing:
        return existing
    organization = Organization.objects.create(
        name=name or f"{user.username} 的工作区",
        slug=unique_organization_slug(name or user.username, user.id),
        created_by=user,
    )
    roles = ensure_builtin_roles(organization)
    membership = Membership.objects.create(
        organization=organization, user=user, status="active", clearance="restricted"
    )
    membership.roles.add(roles["owner"])
    policy = AccessPolicy.objects.create(
        organization=organization,
        name="个人私有策略",
        classification="restricted",
        visibility="restricted",
        created_by=user,
    )
    policy.allowed_users.add(user)
    return organization
