from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.response import Response

from .access_control import audit_access, build_access_scope, require_capability
from .demo_protection import DEMO_POLICIES, demo_protected, deny_demo_core_mutation
from .models import AccessPolicy, AuthorizationAuditLog, Chunk, Membership, Organization, Role
from .permission_serializers import AccessPolicySerializer, AuthorizationAuditLogSerializer, MembershipSerializer, OrganizationSerializer, RoleSerializer


class OrganizationViewSet(viewsets.ModelViewSet):
    serializer_class = OrganizationSerializer

    def get_queryset(self):
        return Organization.objects.filter(memberships__user=self.request.user, memberships__status="active").distinct()

    def _scope(self, capability):
        organization = self.get_object()
        scope = build_access_scope(self.request.user, organization=organization)
        if not scope.can_capability(capability):
            audit_access(scope, capability, organization, False, "capability_denied")
            raise PermissionDenied("Permission denied.")
        return organization, scope

    def perform_update(self, serializer):
        organization, scope = self._scope("manage_organization")
        deny_demo_core_mutation(organization)
        serializer.save()
        audit_access(scope, "manage_organization", organization, True, "updated")

    def perform_destroy(self, instance):
        _, scope = self._scope("manage_organization")
        if instance.memberships.filter(status="active").count() > 1 or instance.knowledge_bases.exists():
            raise PermissionDenied("Organization with active members or knowledge bases cannot be deleted.")
        audit_access(scope, "manage_organization", instance, True, "deleted")
        instance.delete()

    @action(detail=True, methods=["get"], url_path="principals")
    def principals(self, request, pk=None):
        organization = self.get_object()
        scope = build_access_scope(request.user, organization=organization)
        if not scope.can_capability("run_evaluations"):
            raise PermissionDenied("Permission denied.")
        rows = organization.memberships.select_related("user").prefetch_related("roles").order_by("user__username")
        return Response([{
            "id": item.id, "user": item.user_id, "user_name": item.user.username,
            "status": item.status, "department": item.department, "clearance": item.clearance,
            "roles": [role.slug for role in item.roles.all()],
        } for item in rows])

    @action(detail=True, methods=["get", "post"], url_path="memberships")
    def memberships(self, request, pk=None):
        organization, scope = self._scope("manage_members")
        if request.method == "GET":
            return Response(MembershipSerializer(organization.memberships.select_related("user").prefetch_related("roles"), many=True, context={"organization": organization, "request": request}).data)
        serializer = MembershipSerializer(data=request.data, context={"organization": organization, "request": request})
        serializer.is_valid(raise_exception=True)
        item = serializer.save()
        audit_access(scope, "manage_members", item, True, "created")
        return Response(MembershipSerializer(item, context={"organization": organization, "request": request}).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["patch", "delete"], url_path=r"memberships/(?P<membership_id>[^/.]+)")
    def membership_detail(self, request, pk=None, membership_id=None):
        organization, scope = self._scope("manage_members")
        item = organization.memberships.filter(pk=membership_id).first()
        if not item:
            raise NotFound()
        if demo_protected(organization) and item.user.username.startswith("demo_"):
            raise PermissionDenied("预置演示成员不可修改或删除。")
        if request.method == "DELETE":
            if item.roles.filter(slug="owner").exists() and organization.memberships.filter(status="active", roles__slug="owner").count() <= 1:
                raise PermissionDenied("The last active owner cannot be removed.")
            item.delete(); audit_access(scope, "manage_members", item, True, "deleted")
            return Response(status=status.HTTP_204_NO_CONTENT)
        serializer = MembershipSerializer(item, data=request.data, partial=True, context={"organization": organization, "request": request})
        serializer.is_valid(raise_exception=True)
        is_last_owner = item.roles.filter(slug="owner").exists() and organization.memberships.filter(status="active", roles__slug="owner").distinct().count() <= 1
        next_roles = serializer.validated_data.get("roles")
        removes_owner = next_roles is not None and not any(role.slug == "owner" for role in next_roles)
        suspends_owner = serializer.validated_data.get("status", item.status) != "active"
        if is_last_owner and (removes_owner or suspends_owner):
            raise PermissionDenied("The last active owner cannot be suspended or lose the owner role.")
        serializer.save()
        audit_access(scope, "manage_members", item, True, "updated")
        return Response(serializer.data)

    @action(detail=True, methods=["get", "post"], url_path="roles")
    def roles(self, request, pk=None):
        organization, scope = self._scope("manage_roles")
        if request.method == "GET":
            return Response(RoleSerializer(organization.roles.all(), many=True).data)
        serializer = RoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        role = serializer.save(organization=organization)
        audit_access(scope, "manage_roles", role, True, "created")
        return Response(RoleSerializer(role).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["patch", "delete"], url_path=r"roles/(?P<role_id>[^/.]+)")
    def role_detail(self, request, pk=None, role_id=None):
        organization, scope = self._scope("manage_roles")
        role = organization.roles.filter(pk=role_id).first()
        if not role: raise NotFound()
        if demo_protected(organization) and (role.is_system or role.slug == "hr_specialist"):
            raise PermissionDenied("预置演示角色不可修改或删除。")
        if request.method == "DELETE":
            if role.is_system: raise PermissionDenied("System roles cannot be deleted.")
            role.delete(); audit_access(scope, "manage_roles", role, True, "deleted")
            return Response(status=status.HTTP_204_NO_CONTENT)
        serializer = RoleSerializer(role, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True); serializer.save()
        audit_access(scope, "manage_roles", role, True, "updated")
        return Response(serializer.data)


class AccessPolicyViewSet(viewsets.ModelViewSet):
    serializer_class = AccessPolicySerializer
    def get_queryset(self):
        queryset = AccessPolicy.objects.none()
        organization = self.request.query_params.get("organization")
        memberships = Membership.objects.filter(user=self.request.user, status="active")
        if organization:
            memberships = memberships.filter(organization_id=organization)
        ids = []
        for membership in memberships:
            scope = build_access_scope(self.request.user, organization=membership.organization_id)
            policy_ids = membership.organization.access_policies.values_list("id", flat=True) if scope.can_capability("manage_policies") else scope.allowed_policy_ids
            ids.extend(policy_ids)
        return AccessPolicy.objects.filter(id__in=set(ids))
    def _scope(self, organization):
        scope = require_capability(self.request.user, "manage_policies", organization=organization)
        return scope
    def perform_create(self, serializer):
        organization = serializer.validated_data["organization"]
        scope = self._scope(organization)
        policy = serializer.save(created_by=self.request.user)
        audit_access(scope, "manage_policies", policy, True, "created")
    def perform_update(self, serializer):
        if demo_protected(serializer.instance.organization) and serializer.instance.name in DEMO_POLICIES:
            raise PermissionDenied("预置演示策略不可修改；可以创建自己的临时策略。")
        scope = self._scope(serializer.instance.organization)
        policy = serializer.save()
        audit_access(scope, "manage_policies", policy, True, "updated")
    def perform_destroy(self, instance):
        if demo_protected(instance.organization) and instance.name in DEMO_POLICIES:
            raise PermissionDenied("预置演示策略不可删除。")
        scope = self._scope(instance.organization)
        if instance.knowledge_bases.exists() or instance.documents.exists() or instance.chunks.exists():
            raise PermissionDenied("Policy is in use and cannot be deleted.")
        audit_access(scope, "manage_policies", instance, True, "deleted")
        instance.delete()


class AuthorizationAuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AuthorizationAuditLogSerializer
    def get_queryset(self):
        ids = []
        for membership in Membership.objects.filter(user=self.request.user, status="active").prefetch_related("roles"):
            capabilities = {cap for role in membership.roles.all() for cap in (role.capabilities or [])}
            if "manage_organization" in capabilities or "view_traces" in capabilities:
                ids.append(membership.organization_id)
        queryset = AuthorizationAuditLog.objects.filter(organization_id__in=ids).select_related("actor", "membership")
        organization = self.request.query_params.get("organization")
        if organization: queryset = queryset.filter(organization_id=organization)
        return queryset


class ChunkAccessViewSet(viewsets.GenericViewSet):
    queryset = Chunk.objects.none()

    @action(detail=False, methods=["post"], url_path="bulk-set-access-policy")
    def bulk_set_access_policy(self, request):
        ids = request.data.get("chunk_ids") or []
        policy_id = request.data.get("access_policy")
        if not ids or not policy_id:
            return Response({"detail": "chunk_ids and access_policy are required."}, status=status.HTTP_400_BAD_REQUEST)
        chunks = Chunk.objects.filter(id__in=ids).select_related("kb")
        if chunks.count() != len(set(int(value) for value in ids)):
            raise NotFound()
        organizations = {item.kb.organization_id for item in chunks}
        if len(organizations) != 1:
            raise PermissionDenied("Chunks must belong to one organization.")
        organization_id = organizations.pop()
        scope = require_capability(request.user, "manage_documents", organization=organization_id)
        policy = AccessPolicy.objects.filter(pk=policy_id, organization_id=organization_id, is_active=True).first()
        if not policy:
            raise NotFound()
        authorized_ids = set(scope.filter_chunks(chunks, capability="manage_documents").values_list("id", flat=True))
        if authorized_ids != {item.id for item in chunks}:
            raise NotFound()
        chunks.update(access_policy=policy, inherits_policy=False)
        vector_metadata_synced = True
        try:
            from .vector_store import get_vector_store
            get_vector_store().index_chunks(list(Chunk.objects.filter(id__in=ids).select_related("kb")))
        except Exception:
            vector_metadata_synced = False
        audit_access(scope, "manage_documents", policy, True, "chunk_policy_override", {"chunk_count": len(ids)})
        return Response({"updated": len(ids), "access_policy": policy.id, "vector_metadata_synced": vector_metadata_synced})
