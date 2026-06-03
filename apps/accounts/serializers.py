from __future__ import annotations

import re

from rest_framework import serializers

PHONE_RE = re.compile(r"^\+?[1-9]\d{7,14}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class OtpRequestSerializer(serializers.Serializer):
    """Accepts either `phone` (E.164) OR `email`. Exactly one must be set."""

    phone = serializers.CharField(required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)

    def validate(self, data):
        phone = (data.get("phone") or "").strip()
        email = (data.get("email") or "").strip().lower()
        if bool(phone) == bool(email):
            raise serializers.ValidationError(
                {"detail": "Provide exactly one of phone or email."}
            )
        if phone and not PHONE_RE.match(phone):
            raise serializers.ValidationError(
                {"phone": "Enter a valid E.164-style phone number."}
            )
        if email and not EMAIL_RE.match(email):
            raise serializers.ValidationError({"email": "Enter a valid email."})
        return {"phone": phone, "email": email}


class OtpVerifySerializer(serializers.Serializer):
    phone = serializers.CharField(required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    code = serializers.CharField()

    def validate(self, data):
        phone = (data.get("phone") or "").strip()
        email = (data.get("email") or "").strip().lower()
        if bool(phone) == bool(email):
            raise serializers.ValidationError(
                {"detail": "Provide exactly one of phone or email."}
            )
        return {"phone": phone, "email": email, "code": data["code"]}


class TokenPairSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()
    user_id = serializers.UUIDField()
    is_new_user = serializers.BooleanField()


class MeSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    phone = serializers.CharField(read_only=True)
    full_name = serializers.CharField(required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True, allow_null=True)
    preferred_language = serializers.CharField(required=False)
