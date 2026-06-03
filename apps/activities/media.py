"""Pre-signed S3 PUT URL endpoint for direct uploads.

The mobile client requests a key + URL, PUTs the file (photo/receipt) to S3
directly, then references the key in an Activity's `photo_keys[]` or a
Transaction's `receipt_key`. This keeps payloads out of the sync stream and
lets large media survive flaky uplinks via resumable client logic.

Dev mode (no S3 credentials): we return a stub URL pointing at the backend
itself with a `/api/media/dev-upload/{key}` endpoint that accepts and discards
the bytes. The mobile app sees a normal pre-signed flow either way.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import boto3
from botocore.client import Config as BotoConfig
from django.conf import settings
from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

EXT_TO_CONTENT_TYPE = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "heic": "image/heic",
    "pdf": "application/pdf",
}


class MediaUploadRequestSerializer(serializers.Serializer):
    ext = serializers.ChoiceField(choices=sorted(EXT_TO_CONTENT_TYPE.keys()))
    # Optional hint about what the file is for; goes into the key prefix.
    purpose = serializers.ChoiceField(
        choices=["activity_photo", "receipt", "farm_boundary", "other"],
        default="activity_photo",
        required=False,
    )


class MediaUploadResponseSerializer(serializers.Serializer):
    key = serializers.CharField()
    upload_url = serializers.URLField()
    method = serializers.CharField()
    headers = serializers.DictField()
    expires_in = serializers.IntegerField()


def _build_key(purpose: str, ext: str) -> str:
    return f"{purpose}/{uuid.uuid4()}.{ext}"


def _s3_client():
    cfg = settings.GITAKO
    if not (cfg["S3_ENDPOINT_URL"] and cfg["S3_ACCESS_KEY"] and cfg["S3_SECRET_KEY"]):
        return None
    return boto3.client(
        "s3",
        endpoint_url=cfg["S3_ENDPOINT_URL"],
        aws_access_key_id=cfg["S3_ACCESS_KEY"],
        aws_secret_access_key=cfg["S3_SECRET_KEY"],
        region_name=cfg["S3_REGION"],
        config=BotoConfig(signature_version="s3v4"),
    )


class MediaUploadView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=MediaUploadRequestSerializer,
        responses={201: MediaUploadResponseSerializer},
    )
    def post(self, request):
        ser = MediaUploadRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        ext = ser.validated_data["ext"]
        purpose = ser.validated_data.get("purpose", "activity_photo")
        key = _build_key(purpose, ext)
        content_type = EXT_TO_CONTENT_TYPE[ext]

        client = _s3_client()
        if client is None:
            # Dev fallback — backend itself accepts the bytes at /dev-upload/<key>.
            request_url = request.build_absolute_uri(f"/api/media/dev-upload/{key}")
            return Response(
                {
                    "key": key,
                    "upload_url": request_url,
                    "method": "PUT",
                    "headers": {"Content-Type": content_type},
                    "expires_in": 300,
                },
                status=status.HTTP_201_CREATED,
            )

        bucket = settings.GITAKO["S3_BUCKET"]
        url = client.generate_presigned_url(
            ClientMethod="put_object",
            Params={"Bucket": bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=300,
            HttpMethod="PUT",
        )
        return Response(
            {
                "key": key,
                "upload_url": url,
                "method": "PUT",
                "headers": {"Content-Type": content_type},
                "expires_in": 300,
            },
            status=status.HTTP_201_CREATED,
        )


@method_decorator(csrf_exempt, name="dispatch")
class DevUploadSinkView(APIView):
    """Accepts PUT bodies for the dev pre-signed URL and writes them to /media/.

    Mirrors what S3 does but on the local filesystem so the mobile client can
    upload photos against a Django-only stack with no S3 dependency.
    """

    permission_classes = [AllowAny]  # the URL itself is the credential

    @extend_schema(
        parameters=[OpenApiParameter("key", str, OpenApiParameter.PATH)],
        request=None,
        responses={200: None},
    )
    def put(self, request, key: str):
        media_root: Path = Path(settings.BASE_DIR) / "media"
        target = media_root / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(request.body)
        return HttpResponse(status=200)
