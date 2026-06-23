from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken

from .demo_seed import DEMO_USERNAMES, demo_personas


class DemoLoginThrottle(AnonRateThrottle):
    scope = "demo_login"


@api_view(["GET"])
@permission_classes([AllowAny])
def personas(request):
    if not settings.DEMO_MODE:
        return Response({"detail": "Demo mode is disabled."}, status=status.HTTP_404_NOT_FOUND)
    return Response({"personas": demo_personas(), "seed_version": settings.DEMO_SEED_VERSION})


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([DemoLoginThrottle])
def persona_login(request):
    if not settings.DEMO_MODE:
        return Response({"detail": "Demo mode is disabled."}, status=status.HTTP_404_NOT_FOUND)
    username = str(request.data.get("username") or "").strip()
    if username not in DEMO_USERNAMES:
        return Response({"detail": "Unknown demo persona."}, status=status.HTTP_400_BAD_REQUEST)
    user = get_user_model().objects.filter(username=username, is_active=True).first()
    active_membership = user and user.organization_memberships.filter(
        organization__is_demo=True, status="active"
    ).exists()
    if not active_membership:
        return Response({"detail": "This demo persona is not available."}, status=status.HTTP_403_FORBIDDEN)
    refresh = RefreshToken.for_user(user)
    return Response({"refresh": str(refresh), "access": str(refresh.access_token)})
