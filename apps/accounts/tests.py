"""OTP login roundtrip tests."""
from __future__ import annotations

import pytest
from django.urls import reverse

from .models import OtpCode, User

pytestmark = pytest.mark.django_db


def test_otp_request_creates_code(api_client):
    resp = api_client.post(reverse("otp-request"), {"phone": "+2348012345678"}, format="json")
    assert resp.status_code == 202
    assert OtpCode.objects.filter(phone="+2348012345678").exists()


def test_otp_verify_creates_user_and_returns_tokens(api_client):
    api_client.post(reverse("otp-request"), {"phone": "+2348012345678"}, format="json")
    otp = OtpCode.objects.get(phone="+2348012345678")

    resp = api_client.post(
        reverse("otp-verify"),
        {"phone": "+2348012345678", "code": otp.code},
        format="json",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["access"]
    assert body["refresh"]
    assert body["is_new_user"] is True
    assert User.objects.filter(phone="+2348012345678").exists()


def test_otp_verify_wrong_code_rejected(api_client):
    api_client.post(reverse("otp-request"), {"phone": "+2348012345678"}, format="json")
    resp = api_client.post(
        reverse("otp-verify"),
        {"phone": "+2348012345678", "code": "000000"},
        format="json",
    )
    assert resp.status_code == 400


def test_otp_verify_consumes_code(api_client):
    api_client.post(reverse("otp-request"), {"phone": "+2348012345678"}, format="json")
    otp = OtpCode.objects.get(phone="+2348012345678")
    payload = {"phone": "+2348012345678", "code": otp.code}

    assert api_client.post(reverse("otp-verify"), payload, format="json").status_code == 200
    # Reusing the same code must fail.
    assert api_client.post(reverse("otp-verify"), payload, format="json").status_code == 400


def test_otp_invalid_phone_format_rejected(api_client):
    resp = api_client.post(reverse("otp-request"), {"phone": "not-a-phone"}, format="json")
    assert resp.status_code == 400


def test_rate_limited_after_threshold(api_client, settings):
    settings.GITAKO = {**settings.GITAKO, "OTP_RATE_LIMIT_PER_HOUR": 2}
    for _ in range(2):
        assert (
            api_client.post(reverse("otp-request"), {"phone": "+2348012345678"}, format="json").status_code
            == 202
        )
    resp = api_client.post(reverse("otp-request"), {"phone": "+2348012345678"}, format="json")
    assert resp.status_code == 429


def test_email_otp_request_creates_code(api_client):
    resp = api_client.post(reverse("otp-request"), {"email": "musa@example.com"}, format="json")
    assert resp.status_code == 202
    code = OtpCode.objects.filter(recipient="musa@example.com", channel="email").first()
    assert code is not None
    assert code.phone == ""  # SMS column stays blank for email channel


def test_email_otp_verify_creates_user(api_client, mailoutbox):
    api_client.post(reverse("otp-request"), {"email": "musa@example.com"}, format="json")
    otp = OtpCode.objects.get(recipient="musa@example.com")
    resp = api_client.post(
        reverse("otp-verify"),
        {"email": "musa@example.com", "code": otp.code},
        format="json",
    )
    assert resp.status_code == 200, resp.content
    assert resp.json()["is_new_user"] is True
    assert User.objects.filter(email__iexact="musa@example.com").exists()
    # A real email was dispatched via Django's mail backend.
    assert len(mailoutbox) == 1
    assert otp.code in mailoutbox[0].body


def test_otp_request_requires_exactly_one_identifier(api_client):
    # Neither provided.
    resp = api_client.post(reverse("otp-request"), {}, format="json")
    assert resp.status_code == 400
    # Both provided.
    resp = api_client.post(
        reverse("otp-request"),
        {"phone": "+2348012345678", "email": "a@b.com"},
        format="json",
    )
    assert resp.status_code == 400


def test_email_otp_dedupes_users(api_client):
    """Re-verifying with the same email gives back the existing user."""
    api_client.post(reverse("otp-request"), {"email": "musa@example.com"}, format="json")
    otp = OtpCode.objects.get(recipient="musa@example.com")
    first = api_client.post(
        reverse("otp-verify"),
        {"email": "musa@example.com", "code": otp.code},
        format="json",
    ).json()

    api_client.post(reverse("otp-request"), {"email": "musa@example.com"}, format="json")
    otp2 = OtpCode.objects.filter(recipient="musa@example.com").latest("created_at")
    second = api_client.post(
        reverse("otp-verify"),
        {"email": "musa@example.com", "code": otp2.code},
        format="json",
    ).json()

    assert first["user_id"] == second["user_id"]
    assert second["is_new_user"] is False
