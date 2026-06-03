from __future__ import annotations

from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.models import User

from .models import Farm, Party, StaffMembership
from .serializers import (
    FarmSerializer,
    PartySerializer,
    StaffInviteSerializer,
    StaffMembershipSerializer,
)


class FarmViewSet(viewsets.ModelViewSet):
    """Farms the current user is a member of.

    Membership is the boundary. Owners + managers can mutate; field_staff and
    viewers get read-only (enforced via role filter in get_queryset for mutations).
    """

    serializer_class = FarmSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            Farm.objects.filter(memberships__user=self.request.user, deleted_at__isnull=True)
            .order_by("-created_at")
            .distinct()
        )

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "request": self.request}

    def perform_destroy(self, instance: Farm):
        instance.deleted_at = timezone.now()
        instance.save(update_fields=["deleted_at"])

    @extend_schema(responses={200: StaffMembershipSerializer(many=True)})
    @action(detail=True, methods=["get"], url_path="staff")
    def staff(self, request, pk=None):
        farm = self.get_object()
        memberships = farm.memberships.select_related("user").order_by("invited_at")
        return Response(StaffMembershipSerializer(memberships, many=True).data)

    @extend_schema(
        request=StaffInviteSerializer,
        responses={201: StaffMembershipSerializer},
    )
    @action(detail=True, methods=["post"], url_path="invite")
    def invite(self, request, pk=None):
        farm = self.get_object()
        # Only owners + managers can invite.
        caller = farm.memberships.filter(user=request.user).only("role").first()
        if not caller or caller.role not in {
            StaffMembership.ROLE_OWNER, StaffMembership.ROLE_MANAGER,
        }:
            return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)

        ser = StaffInviteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        phone = ser.validated_data["phone"]
        role = ser.validated_data["role"]
        full_name = ser.validated_data.get("full_name", "")

        user, _created = User.objects.get_or_create(
            phone=phone, defaults={"full_name": full_name},
        )
        if full_name and not user.full_name:
            user.full_name = full_name
            user.save(update_fields=["full_name"])

        membership, created = StaffMembership.objects.get_or_create(
            user=user, farm=farm, defaults={"role": role},
        )
        if not created and membership.role != role:
            membership.role = role
            membership.save(update_fields=["role"])

        return Response(
            StaffMembershipSerializer(membership).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @extend_schema(responses={200: StaffMembershipSerializer})
    @action(
        detail=True,
        methods=["patch", "delete"],
        url_path=r"staff/(?P<membership_id>[^/.]+)",
    )
    def manage_staff(self, request, pk=None, membership_id=None):
        """Change a teammate's role (PATCH) or remove them (DELETE).

        Owner/manager only. The farm owner's membership is protected — it can't
        be re-roled or removed here.
        """
        farm = self.get_object()
        caller = farm.memberships.filter(user=request.user).only("role").first()
        if not caller or caller.role not in {
            StaffMembership.ROLE_OWNER, StaffMembership.ROLE_MANAGER,
        }:
            return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)

        membership = get_object_or_404(farm.memberships, pk=membership_id)
        if membership.role == StaffMembership.ROLE_OWNER:
            return Response(
                {"detail": "The farm owner can't be changed or removed."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if request.method == "DELETE":
            membership.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

        # PATCH — update role.
        new_role = request.data.get("role")
        valid = {c[0] for c in StaffMembership.ROLE_CHOICES} - {StaffMembership.ROLE_OWNER}
        if new_role not in valid:
            return Response(
                {"detail": f"role must be one of {sorted(valid)}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        membership.role = new_role
        membership.save(update_fields=["role"])
        return Response(StaffMembershipSerializer(membership).data)


class PartyViewSet(viewsets.ModelViewSet):
    serializer_class = PartySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        tenant_id = getattr(self.request, "tenant_id", None)
        if tenant_id is None:
            return Party.objects.none()
        return Party.objects.filter(tenant_id=tenant_id).order_by("-created_at")

    def perform_create(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if tenant_id is None:
            from rest_framework.exceptions import ValidationError
            raise ValidationError("X-Tenant-Id header required.")
        serializer.save(tenant_id=tenant_id)


# Membership listing for the current user — used by mobile to populate the
# tenant switcher.
class MyMembershipsViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = StaffMembershipSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            StaffMembership.objects.filter(user=self.request.user)
            .select_related("farm", "user")
            .order_by("farm__created_at")
        )
