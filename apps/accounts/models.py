"""User and OTP models.

Gitako uses **phone-first** identity: phone number is the unique identifier and
the OTP channel for login. Email is optional. Per PRD §6 (Auth) and the
onboarding screens in /screens_download/onboarding_splash_done/.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, phone: str, password: str | None, **extra_fields):
        # phone OR email is required (we no longer reject blank phone, since
        # email-channel users have none — but at least one must be set).
        email = extra_fields.get("email") or ""
        if not phone and not email:
            raise ValueError("phone or email is required")
        user = self.model(phone=phone or "", **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_user(self, phone: str = "", password: str | None = None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(phone, password, **extra_fields)

    def create_superuser(self, phone: str, password: str, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self._create_user(phone, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """Phone-first user. Email optional, password optional (OTP is the default channel)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Either phone or email is required, both are allowed. Uniqueness is
    # enforced via partial indexes below so blank values don't collide.
    phone = models.CharField(max_length=20, blank=True, default="", db_index=True)
    email = models.EmailField(blank=True, null=True, db_index=True)
    full_name = models.CharField(max_length=150, blank=True)
    preferred_language = models.CharField(max_length=8, default="en")
    totp_secret = models.CharField(max_length=64, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)
    last_login = models.DateTimeField(blank=True, null=True)

    objects = UserManager()

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        ordering = ["-date_joined"]
        constraints = [
            models.UniqueConstraint(
                fields=["phone"], condition=models.Q(phone__gt=""),
                name="uniq_user_phone_when_set",
            ),
            models.UniqueConstraint(
                fields=["email"], condition=models.Q(email__isnull=False),
                name="uniq_user_email_when_set",
            ),
        ]

    def __str__(self) -> str:
        return self.phone


def _generate_otp_code() -> str:
    length = settings.GITAKO["OTP_LENGTH"]
    upper = 10**length
    return str(secrets.randbelow(upper)).zfill(length)


class OtpCode(models.Model):
    """One-time passcode for login.

    Supports two channels: SMS-to-phone and email. The lookup column we use to
    find/match a code is `recipient` — for backwards compatibility we keep the
    legacy `phone` column populated when the channel is SMS.
    Codes are short-lived (settings.GITAKO['OTP_TTL_SECONDS']) and single-use.
    """

    PURPOSE_LOGIN = "login"
    PURPOSE_VERIFY = "verify"
    PURPOSE_CHOICES = [(PURPOSE_LOGIN, "Login"), (PURPOSE_VERIFY, "Verify")]

    CHANNEL_SMS = "sms"
    CHANNEL_EMAIL = "email"
    CHANNEL_CHOICES = [(CHANNEL_SMS, "SMS"), (CHANNEL_EMAIL, "Email")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # `phone` retained for back-compat — the canonical lookup is `recipient`.
    phone = models.CharField(max_length=20, db_index=True, blank=True)
    recipient = models.CharField(
        max_length=255, db_index=True, default="",
        help_text="Phone (E.164) for SMS, email address for email.",
    )
    channel = models.CharField(
        max_length=8, choices=CHANNEL_CHOICES, default=CHANNEL_SMS,
    )
    code = models.CharField(max_length=8)
    purpose = models.CharField(max_length=16, choices=PURPOSE_CHOICES, default=PURPOSE_LOGIN)
    consumed_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    expires_at = models.DateTimeField()

    class Meta:
        indexes = [
            models.Index(fields=["recipient", "channel", "purpose", "-created_at"]),
            models.Index(fields=["phone", "purpose", "-created_at"]),
        ]

    @classmethod
    def issue(cls, *, recipient: str, channel: str = CHANNEL_SMS,
              purpose: str = PURPOSE_LOGIN) -> "OtpCode":
        ttl = settings.GITAKO["OTP_TTL_SECONDS"]
        return cls.objects.create(
            recipient=recipient,
            phone=recipient if channel == cls.CHANNEL_SMS else "",
            channel=channel,
            code=_generate_otp_code(),
            purpose=purpose,
            expires_at=timezone.now() + timedelta(seconds=ttl),
        )

    @property
    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at

    @property
    def is_consumed(self) -> bool:
        return self.consumed_at is not None

    def mark_consumed(self) -> None:
        self.consumed_at = timezone.now()
        self.save(update_fields=["consumed_at"])
