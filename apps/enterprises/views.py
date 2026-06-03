from __future__ import annotations

from datetime import date

from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.farms.models import Farm, StaffMembership
from apps.tenancy.permissions import (
    assert_can_create,
    assert_can_modify,
    role_for,
)

from .budget_templates import ensure_plan_budget
from .calendar import planned_tasks_for_farm
from .metrics import metrics_for
from .models import Enterprise, EnterprisePlan, SeasonTask
from .season_tasks import ensure_season_tasks, regenerate_season_tasks
from .serializers import (
    EnterprisePlanSerializer,
    EnterpriseSerializer,
    SeasonTaskSerializer,
)

TABLE = "enterprises_enterprise"
PLAN_TABLE = "enterprises_enterpriseplan"
MANAGER_ROLES = {StaffMembership.ROLE_OWNER, StaffMembership.ROLE_MANAGER}


class EnterpriseViewSet(viewsets.ModelViewSet):
    """Enterprises scoped to the active tenant (= farm) via X-Tenant-Id.

    Falls back to listing across all the user's farms when no tenant is set
    (useful for multi-farm owner overview screens).
    """

    serializer_class = EnterpriseSerializer
    permission_classes = [IsAuthenticated]

    def _user_farm_ids(self):
        return StaffMembership.objects.filter(user=self.request.user).values_list(
            "farm_id", flat=True
        )

    def get_queryset(self):
        tenant_id = getattr(self.request, "tenant_id", None)
        qs = Enterprise.objects.all()
        if tenant_id is not None:
            qs = qs.filter(tenant_id=tenant_id)
        else:
            qs = qs.filter(farm_id__in=self._user_farm_ids())
        return qs.order_by("-start_date", "name")

    def perform_create(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if tenant_id is None:
            raise PermissionDenied("X-Tenant-Id header required.")
        farm_field = serializer.validated_data.get("farm")
        farm = get_object_or_404(Farm, pk=farm_field.id if farm_field else tenant_id)
        if farm.id != tenant_id:
            raise PermissionDenied("Farm and tenant header mismatch.")
        assert_can_create(role_for(self.request.user, tenant_id), TABLE)
        serializer.save(tenant_id=tenant_id, farm=farm)

    def perform_update(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        assert_can_modify(
            role_for(self.request.user, tenant_id),
            instance=self.get_object(), user=self.request.user, table=TABLE,
        )
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        tenant_id = getattr(self.request, "tenant_id", None)
        assert_can_modify(
            role_for(self.request.user, tenant_id),
            instance=instance, user=self.request.user, table=TABLE,
        )
        from django.utils import timezone
        instance.deleted_at = timezone.now()
        instance.save(update_fields=["deleted_at", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["get"], url_path="metrics")
    def metrics(self, request, pk=None):
        """Yields + FCR + margin for the enterprise. Computed on the fly."""
        enterprise = self.get_object()
        return Response(metrics_for(enterprise))

    @action(detail=True, methods=["get", "patch", "put"], url_path="plan")
    def plan(self, request, pk=None):
        """Per-enterprise budget + expected outcome ("Plan a season").

        GET   — current plan (creates an empty one on first read).
        PATCH — partial update (budget_lines, expected_yield_kg, …).
        """
        enterprise = self.get_object()
        plan, _ = EnterprisePlan.objects.get_or_create(
            enterprise=enterprise,
            defaults={"tenant_id": enterprise.tenant_id},
        )
        if request.method == "GET":
            # Auto-generate a cost breakdown + expected outcome on first read,
            # the budget sibling of materializing the GAP calendar.
            ensure_plan_budget(plan, enterprise)
            return Response(EnterprisePlanSerializer(plan).data)

        # Locked plans are immutable until the user explicitly unlocks them
        # (PATCH with locked_at=null clears the lock and lets edits through).
        will_unlock = (
            "locked_at" in request.data and request.data.get("locked_at") in (None, "")
        )
        if plan.locked_at is not None and not will_unlock:
            raise PermissionDenied("Plan is locked. Unlock it to edit.")

        assert_can_modify(
            role_for(self.request.user, enterprise.tenant_id),
            instance=plan, user=self.request.user, table=PLAN_TABLE,
        )
        serializer = EnterprisePlanSerializer(plan, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class PlannedTasksView(APIView):
    """Upcoming tasks across all live enterprises for the active farm.

    Synthesizes the calendar on the fly from crop / vaccination templates and
    matches each entry against recorded Activity rows to determine status.

    Query params:
      from=<YYYY-MM-DD>  — window start (default: today - 14 days)
      to=<YYYY-MM-DD>    — window end (default: today + 90 days)
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        tenant_id = getattr(request, "tenant_id", None)
        if tenant_id is None:
            raise PermissionDenied("X-Tenant-Id header required.")
        farm = get_object_or_404(Farm, pk=tenant_id)
        window_from = parse_date(request.query_params.get("from", "")) if request.query_params.get("from") else None
        window_to = parse_date(request.query_params.get("to", "")) if request.query_params.get("to") else None
        enterprise_id = request.query_params.get("enterprise") or None
        rows = planned_tasks_for_farm(
            farm,
            window_from=window_from,
            window_to=window_to,
            enterprise_id=enterprise_id,
        )
        return Response({"tasks": rows})


class SeasonTaskViewSet(viewsets.ReadOnlyModelViewSet):
    """Persistent, assignable GAP tasks for the active farm's enterprises.

    Listing lazily materializes tasks from the GAP template so the schedule
    exists the first time it's viewed. Filters:
      ?enterprise=<id>   one enterprise
      ?assigned_to_me=true   only my assigned tasks (a farm hand's worklist)
      ?status=pending|done|skipped

    Mutations are explicit actions (assign / complete / skip / generate), each
    enforcing the role matrix.
    """

    serializer_class = SeasonTaskSerializer
    permission_classes = [IsAuthenticated]

    def _farm(self) -> Farm:
        tenant_id = getattr(self.request, "tenant_id", None)
        if tenant_id is None:
            raise PermissionDenied("X-Tenant-Id header required.")
        return get_object_or_404(Farm, pk=tenant_id)

    def _is_manager(self, farm) -> bool:
        return StaffMembership.objects.filter(
            user=self.request.user, farm=farm, role__in=MANAGER_ROLES,
        ).exists()

    def _assert_member(self, farm):
        if not StaffMembership.objects.filter(user=self.request.user, farm=farm).exists():
            raise PermissionDenied("You don't have access to this farm.")

    def get_queryset(self):
        tenant_id = getattr(self.request, "tenant_id", None)
        if tenant_id is None:
            return SeasonTask.objects.none()
        # Lazily materialize so the schedule exists on first view.
        for ent in Enterprise.objects.filter(
            tenant_id=tenant_id, deleted_at__isnull=True,
        ).exclude(lifecycle_state__in=["completed", "abandoned"]):
            ensure_season_tasks(ent)

        qs = SeasonTask.objects.filter(tenant_id=tenant_id).select_related(
            "enterprise", "assigned_to",
        )
        params = self.request.query_params
        if (eid := params.get("enterprise")):
            qs = qs.filter(enterprise_id=eid)
        if params.get("assigned_to_me") == "true":
            qs = qs.filter(assigned_to=self.request.user)
        if (st := params.get("status")):
            qs = qs.filter(status=st)
        return qs

    def _get_task(self, pk) -> SeasonTask:
        tenant_id = getattr(self.request, "tenant_id", None)
        return get_object_or_404(SeasonTask, pk=pk, tenant_id=tenant_id)

    @action(detail=True, methods=["post"], url_path="assign")
    def assign(self, request, pk=None):
        """Manager assigns a task to a farm hand (or clears it with assignee=null)."""
        farm = self._farm()
        if not self._is_manager(farm):
            raise PermissionDenied("Only owners and managers can assign tasks.")
        task = self._get_task(pk)
        assignee_id = request.data.get("assignee")
        if assignee_id:
            membership = StaffMembership.objects.filter(
                user_id=assignee_id, farm=farm,
            ).first()
            if membership is None:
                raise PermissionDenied("That user is not a member of this farm.")
            task.assigned_to_id = assignee_id
        else:
            task.assigned_to = None
        task.save(update_fields=["assigned_to", "updated_at"])
        return Response(SeasonTaskSerializer(task).data)

    @action(detail=True, methods=["post"], url_path="complete")
    def complete(self, request, pk=None):
        """Mark a task done without a full activity record (the quick path).

        Allowed for any farm member who is the assignee, or any manager.
        Logging a matching activity also completes the task automatically.
        """
        farm = self._farm()
        self._assert_member(farm)
        task = self._get_task(pk)
        if not self._is_manager(farm) and task.assigned_to_id not in (None, request.user.id):
            raise PermissionDenied("This task is assigned to someone else.")
        from django.utils import timezone
        task.status = SeasonTask.STATUS_DONE
        task.completed_at = timezone.now()
        task.save(update_fields=["status", "completed_at", "updated_at"])
        return Response(SeasonTaskSerializer(task).data)

    @action(detail=True, methods=["post"], url_path="skip")
    def skip(self, request, pk=None):
        farm = self._farm()
        if not self._is_manager(farm):
            raise PermissionDenied("Only owners and managers can skip tasks.")
        task = self._get_task(pk)
        task.status = SeasonTask.STATUS_SKIPPED
        task.save(update_fields=["status", "updated_at"])
        return Response(SeasonTaskSerializer(task).data)

    @action(detail=False, methods=["post"], url_path="generate")
    def generate(self, request):
        """Regenerate the schedule for one enterprise after a planting-date change.
        Body: {enterprise}. Preserves done/skipped/assigned tasks."""
        farm = self._farm()
        if not self._is_manager(farm):
            raise PermissionDenied("Only owners and managers can regenerate the schedule.")
        eid = request.data.get("enterprise")
        ent = get_object_or_404(Enterprise, pk=eid, tenant_id=farm.id)
        tasks = regenerate_season_tasks(ent)
        return Response(SeasonTaskSerializer(tasks, many=True).data)

    @action(detail=False, methods=["post"], url_path="add")
    def add(self, request):
        """Add a custom task to an enterprise's schedule (manager).
        Body: {enterprise, label, activity_type, target_date, notes?}."""
        import uuid as _uuid
        from rest_framework.exceptions import ValidationError
        farm = self._farm()
        if not self._is_manager(farm):
            raise PermissionDenied("Only owners and managers can add tasks.")
        ent = get_object_or_404(Enterprise, pk=request.data.get("enterprise"), tenant_id=farm.id)
        label = (request.data.get("label") or "").strip()
        activity_type = (request.data.get("activity_type") or "").strip()
        target_raw = request.data.get("target_date")
        if not (label and activity_type and target_raw):
            raise ValidationError("label, activity_type and target_date are required.")
        target = parse_date(str(target_raw))
        if target is None:
            raise ValidationError("target_date must be YYYY-MM-DD.")
        # Custom tasks carry a uuid suffix in slot_key so they never collide with
        # a generated slot or another custom task on the same day.
        task = SeasonTask.objects.create(
            tenant_id=ent.tenant_id, enterprise=ent,
            activity_type=activity_type, label=label,
            notes=request.data.get("notes", ""),
            target_date=target, source="custom",
            slot_key=f"custom:{activity_type}:{target.isoformat()}:{_uuid.uuid4().hex[:8]}",
        )
        return Response(SeasonTaskSerializer(task).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["patch"], url_path="edit")
    def edit(self, request, pk=None):
        """Edit a task's label / activity_type / target_date / notes (manager)."""
        from rest_framework.exceptions import ValidationError
        farm = self._farm()
        if not self._is_manager(farm):
            raise PermissionDenied("Only owners and managers can edit tasks.")
        task = self._get_task(pk)
        updated = []
        if "label" in request.data:
            task.label = (request.data.get("label") or "").strip() or task.label
            updated.append("label")
        if "activity_type" in request.data:
            task.activity_type = (request.data.get("activity_type") or task.activity_type).strip()
            updated.append("activity_type")
        if "notes" in request.data:
            task.notes = request.data.get("notes") or ""
            updated.append("notes")
        if "target_date" in request.data:
            target = parse_date(str(request.data.get("target_date")))
            if target is None:
                raise ValidationError("target_date must be YYYY-MM-DD.")
            task.target_date = target
            updated.append("target_date")
        if updated:
            updated.append("updated_at")
            task.save(update_fields=updated)
        return Response(SeasonTaskSerializer(task).data)

    @action(detail=True, methods=["delete"], url_path="remove")
    def remove(self, request, pk=None):
        """Delete a task from the schedule (manager)."""
        farm = self._farm()
        if not self._is_manager(farm):
            raise PermissionDenied("Only owners and managers can delete tasks.")
        task = self._get_task(pk)
        task.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
