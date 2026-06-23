from django.contrib.auth.models import User
from django.db import transaction
from rest_framework import serializers

from .models import AccessPolicy, AuthorizationAuditLog, Membership, Organization, ROLE_CAPABILITIES, Role
from .tenancy import ensure_builtin_roles


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ["id", "organization", "name", "slug", "capabilities", "is_system", "created_at", "updated_at"]
        read_only_fields = ["organization", "is_system"]

    def validate_capabilities(self, value):
        invalid = sorted(set(value or []) - set(ROLE_CAPABILITIES))
        if invalid:
            raise serializers.ValidationError(f"Unsupported capabilities: {', '.join(invalid)}")
        return sorted(set(value or []))

    def validate_slug(self, value):
        if self.instance and self.instance.is_system and value != self.instance.slug:
            raise serializers.ValidationError("System role slug is immutable.")
        return value


class MembershipSerializer(serializers.ModelSerializer):
    username = serializers.CharField(write_only=True, required=False)
    user = serializers.IntegerField(source="user_id", read_only=True)
    user_name = serializers.CharField(source="user.username", read_only=True)
    roles = serializers.PrimaryKeyRelatedField(queryset=Role.objects.all(), many=True, required=False)

    class Meta:
        model = Membership
        fields = ["id", "organization", "user", "username", "user_name", "status", "department", "clearance", "roles", "created_at", "updated_at"]
        read_only_fields = ["organization"]

    def validate(self, attrs):
        organization = self.context["organization"]
        if self.instance:
            attrs.pop("username", None)
        roles = attrs.get("roles", [])
        if any(role.organization_id != organization.id for role in roles):
            raise serializers.ValidationError({"roles": "Roles must belong to the current organization."})
        if not self.instance:
            username = attrs.pop("username", "").strip()
            try:
                attrs["user"] = User.objects.get(username=username)
            except User.DoesNotExist as exc:
                raise serializers.ValidationError({"username": "User not found."}) from exc
        return attrs

    def create(self, validated_data):
        roles = validated_data.pop("roles", [])
        membership = Membership.objects.create(organization=self.context["organization"], **validated_data)
        membership.roles.set(roles)
        return membership

    def update(self, instance, validated_data):
        roles = validated_data.pop("roles", None)
        instance = super().update(instance, validated_data)
        if roles is not None:
            instance.roles.set(roles)
        return instance


class OrganizationSerializer(serializers.ModelSerializer):
    membership = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = ["id", "name", "slug", "is_demo", "demo_seed_version", "membership", "created_at", "updated_at"]
        read_only_fields = ["slug", "is_demo", "demo_seed_version"]

    def get_membership(self, obj):
        request = self.context.get("request")
        membership = obj.memberships.filter(user=request.user).prefetch_related("roles").first() if request else None
        if not membership:
            return None
        return {
            "id": membership.id, "status": membership.status, "department": membership.department,
            "clearance": membership.clearance, "roles": [r.slug for r in membership.roles.all()],
            "capabilities": sorted({cap for r in membership.roles.all() for cap in (r.capabilities or [])}),
        }

    @transaction.atomic
    def create(self, validated_data):
        request = self.context["request"]
        from .tenancy import unique_organization_slug
        org = Organization.objects.create(created_by=request.user, slug=unique_organization_slug(validated_data["name"]), **validated_data)
        roles = ensure_builtin_roles(org)
        membership = Membership.objects.create(organization=org, user=request.user, status="active", clearance="restricted")
        membership.roles.add(roles["owner"])
        policy = AccessPolicy.objects.create(organization=org, name="组织默认策略", classification="internal", visibility="organization", created_by=request.user)
        policy.allowed_roles.add(roles["member"])
        return org


class AccessPolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = AccessPolicy
        fields = ["id", "organization", "name", "classification", "visibility", "allowed_roles", "allowed_users", "allowed_departments", "denied_users", "is_active", "version", "created_by", "created_at", "updated_at"]
        read_only_fields = ["created_by", "version"]

    def validate(self, attrs):
        organization = attrs.get("organization") or getattr(self.instance, "organization", None)
        if not organization:
            raise serializers.ValidationError({"organization": "This field is required."})
        request = self.context["request"]
        if not organization.memberships.filter(user=request.user, status="active").exists():
            raise serializers.ValidationError({"organization": "Organization not found."})
        roles = attrs.get("allowed_roles", [])
        if any(role.organization_id != organization.id for role in roles):
            raise serializers.ValidationError({"allowed_roles": "Roles must belong to this organization."})
        member_ids = set(organization.memberships.filter(status="active").values_list("user_id", flat=True))
        for field in ("allowed_users", "denied_users"):
            users = attrs.get(field, [])
            if any(user.id not in member_ids for user in users):
                raise serializers.ValidationError({field: "Users must be active members of this organization."})
        return attrs

    def update(self, instance, validated_data):
        validated_data["version"] = instance.version + 1
        return super().update(instance, validated_data)


class AuthorizationAuditLogSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.username", read_only=True)
    class Meta:
        model = AuthorizationAuditLog
        fields = ["id", "organization", "actor", "actor_name", "action", "resource_type", "resource_id", "allowed", "reason", "scope_fingerprint", "metadata", "created_at"]
        read_only_fields = fields
