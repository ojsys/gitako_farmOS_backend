"""Developer App Store endpoints (PRD M20).

- Browse published modules (cross-tenant — any authed user).
- Install a module to the active farm (owner/manager); paid installs run the
  revenue split and charge through the payments seam.
- List the farm's installs; uninstall.
"""
from __future__ import annotations

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.farms.models import Farm, StaffMembership
from apps.payments.providers import get_payment_provider, new_reference

from .models import DeveloperModule, ModuleInstall
from .serializers import DeveloperModuleSerializer, ModuleInstallSerializer

MANAGER_ROLES = {StaffMembership.ROLE_OWNER, StaffMembership.ROLE_MANAGER}


class ModuleBrowseView(viewsets.ReadOnlyModelViewSet):
    """Published modules, cross-tenant browse. Filter ?category=."""

    serializer_class = DeveloperModuleSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = DeveloperModule.objects.filter(status=DeveloperModule.STATUS_PUBLISHED).select_related("developer")
        if (cat := self.request.query_params.get("category")):
            qs = qs.filter(category=cat)
        return qs


class FarmInstallViewSet(viewsets.ReadOnlyModelViewSet):
    """The active farm's installs + install/uninstall actions."""

    serializer_class = ModuleInstallSerializer
    permission_classes = [IsAuthenticated]

    def _farm_as_manager(self) -> Farm:
        tenant_id = getattr(self.request, "tenant_id", None)
        if tenant_id is None:
            raise PermissionDenied("X-Tenant-Id header required.")
        farm = get_object_or_404(Farm, pk=tenant_id)
        membership = StaffMembership.objects.filter(
            user=self.request.user, farm=farm,
        ).only("role").first()
        if not membership or membership.role not in MANAGER_ROLES:
            raise PermissionDenied("Only owners and managers can manage modules.")
        return farm

    def get_queryset(self):
        tenant_id = getattr(self.request, "tenant_id", None)
        if tenant_id is None:
            return ModuleInstall.objects.none()
        return ModuleInstall.objects.filter(farm_id=tenant_id).select_related("module")

    @action(detail=False, methods=["post"], url_path="install")
    def install(self, request):
        farm = self._farm_as_manager()
        module_id = request.data.get("module_id")
        module = get_object_or_404(DeveloperModule, pk=module_id,
                                   status=DeveloperModule.STATUS_PUBLISHED)
        if ModuleInstall.objects.filter(module=module, farm=farm, is_active=True).exists():
            raise ValidationError("Module already installed.")

        gitako_cut = module.gitako_cut_kobo()
        dev_take = module.developer_take_kobo()
        payment_ref = ""
        if module.price_kobo > 0:
            ref = new_reference("module_chg")
            result = get_payment_provider().charge(
                amount_kobo=module.price_kobo, reference=ref,
                description=f"Install {module.slug} for farm {farm.id}",
            )
            if not result.ok:
                raise ValidationError("Payment failed — module not installed.")
            payment_ref = result.reference

        install, created = ModuleInstall.objects.update_or_create(
            module=module, farm=farm,
            defaults={
                "is_active": True, "uninstalled_at": None,
                "price_kobo": module.price_kobo,
                "gitako_cut_kobo": gitako_cut,
                "developer_take_kobo": dev_take,
                "payment_reference": payment_ref,
            },
        )
        return Response(ModuleInstallSerializer(install).data,
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="uninstall")
    def uninstall(self, request, pk=None):
        self._farm_as_manager()
        install = get_object_or_404(self.get_queryset(), pk=pk)
        install.is_active = False
        install.uninstalled_at = timezone.now()
        install.save(update_fields=["is_active", "uninstalled_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)
