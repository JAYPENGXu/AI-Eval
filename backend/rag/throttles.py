from django.conf import settings
from rest_framework.throttling import UserRateThrottle


class DemoUserThrottle(UserRateThrottle):
    scope = "demo_user"

    def allow_request(self, request, view):
        if not settings.DEMO_MODE:
            return True
        organization_is_demo = request.user.is_authenticated and request.user.organization_memberships.filter(
            organization__is_demo=True, status="active"
        ).exists()
        return super().allow_request(request, view) if organization_is_demo else True


class DemoExpensiveThrottle(DemoUserThrottle):
    scope = "demo_expensive"
