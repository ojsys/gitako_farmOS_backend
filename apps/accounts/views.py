"""OTP authentication — works via SMS (phone) or email.

Flow (channel is implicit: client sends `phone` or `email`):
  1. POST /api/auth/otp/request  with phone OR email → server issues a 6-digit
     OTP and dispatches via the matching channel.
  2. POST /api/auth/otp/verify   with the same identifier + code → JWT pair.
  3. POST /api/auth/token/refresh — standard SimpleJWT.

User accounts are deduplicated by the channel that signed them up:
  - phone   → unique on `User.phone`
  - email   → unique on `User.email`
A future "link accounts" flow can merge them; for v1 they're separate users.
"""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .email import send_email_otp, send_welcome_email
from .models import OtpCode, User
from .serializers import (
    MeSerializer,
    OtpRequestSerializer,
    OtpVerifySerializer,
    TokenPairSerializer,
)
from .sms import get_provider

MAX_ATTEMPTS = 5


def _recipient(phone: str, email: str) -> tuple[str, str]:
    """Return (channel, recipient) — both normalized."""
    if phone:
        return OtpCode.CHANNEL_SMS, phone
    return OtpCode.CHANNEL_EMAIL, email


class OtpRequestView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(request=OtpRequestSerializer, responses={202: None})
    def post(self, request):
        ser = OtpRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        channel, recipient = _recipient(ser.validated_data["phone"], ser.validated_data["email"])

        window_start = timezone.now() - timedelta(hours=1)
        recent = OtpCode.objects.filter(
            recipient=recipient, channel=channel, created_at__gte=window_start,
        ).count()
        if recent >= settings.GITAKO["OTP_RATE_LIMIT_PER_HOUR"]:
            return Response(
                {"detail": "Too many OTP requests. Try again later."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        otp = OtpCode.issue(recipient=recipient, channel=channel)
        if channel == OtpCode.CHANNEL_SMS:
            get_provider().send_otp(phone=recipient, code=otp.code)
        else:
            send_email_otp(email=recipient, code=otp.code)
        return Response(status=status.HTTP_202_ACCEPTED)


class OtpVerifyView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(request=OtpVerifySerializer, responses={200: TokenPairSerializer})
    def post(self, request):
        ser = OtpVerifySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        channel, recipient = _recipient(ser.validated_data["phone"], ser.validated_data["email"])
        code = ser.validated_data["code"]

        otp = (
            OtpCode.objects.filter(
                recipient=recipient, channel=channel, purpose=OtpCode.PURPOSE_LOGIN,
            )
            .order_by("-created_at")
            .first()
        )
        if otp is None or otp.is_consumed or otp.is_expired:
            return Response({"detail": "Invalid or expired code."},
                            status=status.HTTP_400_BAD_REQUEST)
        if otp.attempts >= MAX_ATTEMPTS:
            return Response({"detail": "Too many attempts. Request a new code."},
                            status=status.HTTP_429_TOO_MANY_REQUESTS)
        if otp.code != code:
            otp.attempts += 1
            otp.save(update_fields=["attempts"])
            return Response({"detail": "Invalid or expired code."},
                            status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            otp.mark_consumed()
            if channel == OtpCode.CHANNEL_SMS:
                user, created = User.objects.get_or_create(phone=recipient)
            else:
                # Email path: dedupe on email. Phone stays empty for these
                # users until they later add one in their profile.
                user = User.objects.filter(email__iexact=recipient).first()
                if user is None:
                    user = User.objects.create_user(phone="", email=recipient)
                    created = True
                else:
                    created = False
            if not user.is_active:
                return Response({"detail": "Account disabled."},
                                status=status.HTTP_403_FORBIDDEN)
            user.last_login = timezone.now()
            user.save(update_fields=["last_login"])

        # First-ever sign-in for an email account → welcome them. Best-effort:
        # never let a mail failure break the sign-up response.
        if created and user.email:
            send_welcome_email(email=user.email, name=user.full_name or "")

        refresh = RefreshToken.for_user(user)
        return Response(TokenPairSerializer({
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "user_id": str(user.id),
            "is_new_user": created,
        }).data)


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: MeSerializer})
    def get(self, request):
        return Response(MeSerializer(request.user).data)

    @extend_schema(request=MeSerializer, responses={200: MeSerializer})
    def patch(self, request):
        ser = MeSerializer(data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        user = request.user
        for field in ("full_name", "email", "preferred_language"):
            if field in ser.validated_data:
                setattr(user, field, ser.validated_data[field])
        user.save()
        return Response(MeSerializer(user).data)
