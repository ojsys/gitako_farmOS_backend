"""API-key authentication + rate limiting for the partner API.

Partners send `Authorization: Api-Key <key>`. We hash the presented key and
match it against ApiKey.key_hash. On success, `request.partner` is set and the
key's last_used_at is bumped. DRF auth classes return (user, auth); we use
AnonymousUser as the "user" since a partner is not a Gitako user — downstream
permission lives in the consent check, not the user object.
"""
from __future__ import annotations

import hashlib
import secrets

from django.contrib.auth.models import AnonymousUser
from django.utils import timezone
from rest_framework import authentication, exceptions, throttling

from .models import ApiKey

KEY_PREFIX = "gk_"


def generate_api_key() -> tuple[str, str, str]:
    """Return (raw_key, prefix, sha256_hash). Raw key is shown once, never stored."""
    body = secrets.token_urlsafe(32)
    raw = f"{KEY_PREFIX}{body}"
    prefix = raw[: len(KEY_PREFIX) + 6]
    return raw, prefix, hashlib.sha256(raw.encode()).hexdigest()


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class PartnerApiKeyAuthentication(authentication.BaseAuthentication):
    keyword = "Api-Key"

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).decode("latin-1")
        if not header or not header.startswith(self.keyword):
            return None  # let other auth classes try
        raw = header[len(self.keyword):].strip()
        if not raw:
            raise exceptions.AuthenticationFailed("Invalid API key header.")

        prefix = raw[: len(KEY_PREFIX) + 6]
        candidates = ApiKey.objects.filter(
            prefix=prefix, is_active=True, partner__is_active=True,
        ).select_related("partner")
        presented = _hash(raw)
        for key in candidates:
            if secrets.compare_digest(key.key_hash, presented):
                key.last_used_at = timezone.now()
                key.save(update_fields=["last_used_at"])
                request.partner = key.partner
                return (AnonymousUser(), key)
        raise exceptions.AuthenticationFailed("Invalid API key.")

    def authenticate_header(self, request):
        # Makes DRF return 401 (not 403) when auth fails on a key-bearing request.
        return self.keyword


class PartnerRateThrottle(throttling.SimpleRateThrottle):
    """Per-partner RPM throttle using the partner's configured tier."""

    scope = "partner"

    def get_cache_key(self, request, view):
        partner = getattr(request, "partner", None)
        if partner is None:
            return None
        return f"throttle_partner_{partner.id}"

    def allow_request(self, request, view):
        partner = getattr(request, "partner", None)
        if partner is None:
            return True
        self.rate = f"{partner.rate_limit_per_min}/min"
        self.num_requests, self.duration = self.parse_rate(self.rate)
        return super().allow_request(request, view)
