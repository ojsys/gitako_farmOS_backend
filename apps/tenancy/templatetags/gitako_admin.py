"""Helpers powering the custom Gitako admin shell.

Two things the templates need:
  - the registered admin app list (so the sidebar can render itself)
  - small utilities for nav highlighting and icon mapping
"""
from __future__ import annotations

from django import template
from django.contrib import admin
from django.utils.safestring import mark_safe

register = template.Library()


# Map admin model paths to small SVG icons. Keep glyphs lightweight — they
# render at 16-18px in the sidebar.
ICONS = {
    "accounts.user": "person",
    "accounts.otpcode": "key",
    "farms.farm": "layers",
    "farms.staffmembership": "group",
    "farms.party": "handshake",
    "enterprises.enterprise": "eco",
    "activities.activity": "task",
    "sync.changelog": "history",
    "sync.synccursor": "cursor",
    "sync.syncnote": "note",
    "sync.synctag": "tag",
    "tenancy.auditentry": "shield",
    "auth.group": "group",
    "auth.permission": "lock",
}

APP_ICONS = {
    "accounts": "person",
    "farms": "layers",
    "enterprises": "eco",
    "activities": "task",
    "inventory": "warehouse",
    "finance": "money",
    "sync": "sync",
    "notifications": "bell",
    "tenancy": "shield",
    "auth": "lock",
    "django_celery_beat": "schedule",
}

# Pre-render glyphs as inline SVGs (no external icon font dependency).
_SVG = {
    "person":  '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M12 12a4 4 0 1 0-4-4 4 4 0 0 0 4 4Zm0 2c-3 0-9 1.5-9 4.5V21h18v-2.5c0-3-6-4.5-9-4.5Z"/></svg>',
    "key":     '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M14 3a5 5 0 1 0 4.83 6.3l1.62 1.62-1.41 1.41 1.41 1.41-2.83 2.83-1.41-1.41-1.41 1.41-1.41-1.41-1.41 1.41a5 5 0 1 0 2.02-12Zm-2 5a1 1 0 1 1-2 0 1 1 0 0 1 2 0Z"/></svg>',
    "layers":  '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="m12 2 10 5-10 5L2 7l10-5Zm0 9 10 5-10 5L2 16l10-5Z"/></svg>',
    "group":   '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M16 11a3 3 0 1 0-3-3 3 3 0 0 0 3 3Zm-8 0a3 3 0 1 0-3-3 3 3 0 0 0 3 3Zm0 2c-2.6 0-8 1.3-8 4v3h10v-3c0-1 .35-2 1-2.7-1-.2-2-.3-3-.3Zm8 0c-.5 0-1 0-1.4.1A4.7 4.7 0 0 1 16 17v3h8v-3c0-2.6-5.3-4-8-4Z"/></svg>',
    "handshake": '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M12 2 4 6v6c0 5 3.5 9.7 8 10 4.5-.3 8-5 8-10V6l-8-4Z"/></svg>',
    "eco":     '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M6 3c8 0 14 6 14 14a8 8 0 0 1-8 4 8 8 0 0 1-8-8c0-3 1.5-6 4-8 1-1 3-1 5-1l-3 5h4l-3 5h4l-3 5"/></svg>',
    "task":    '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M9 16.2 4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4Z"/></svg>',
    "history": '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M13 3a9 9 0 1 0 9 9h-2a7 7 0 1 1-7-7v3l4-4-4-4Zm-1 5v6l5 3 1-1.5-4-2.5V8Z"/></svg>',
    "cursor":  '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="m3 3 7 17 2-7 7-2Z"/></svg>',
    "note":    '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M5 3h12l4 4v14H5Zm2 2v14h12V8h-4V5Z"/></svg>',
    "tag":     '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M21 11.6V4h-7.6L2 15.4 8.6 22Zm-4-4a1.5 1.5 0 1 1-1.5-1.5A1.5 1.5 0 0 1 17 7.6Z"/></svg>',
    "shield":  '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M12 2 4 5v6c0 5 3.4 9.7 8 11 4.6-1.3 8-6 8-11V5Z"/></svg>',
    "lock":    '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M12 2a5 5 0 0 0-5 5v3H6a2 2 0 0 0-2 2v9h16v-9a2 2 0 0 0-2-2h-1V7a5 5 0 0 0-5-5Zm-3 8V7a3 3 0 0 1 6 0v3Z"/></svg>',
    "warehouse":'<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M3 9 12 4l9 5v11h-6v-6h-6v6H3Z"/></svg>',
    "money":   '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M3 6h18v12H3Zm9 2a4 4 0 1 0 4 4 4 4 0 0 0-4-4Z"/></svg>',
    "sync":    '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M12 4V1L8 5l4 4V6a6 6 0 0 1 6 6h2a8 8 0 0 0-8-8Zm-6 8H4a8 8 0 0 0 8 8v3l4-4-4-4v3a6 6 0 0 1-6-6Z"/></svg>',
    "bell":    '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M12 22a2 2 0 0 0 2-2h-4a2 2 0 0 0 2 2Zm6-6V11a6 6 0 0 0-5-5.9V4a1 1 0 0 0-2 0v1.1A6 6 0 0 0 6 11v5l-2 2v1h16v-1Z"/></svg>',
    "schedule":'<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2Zm1 11h-4V7h2v4h2Z"/></svg>',
    "default": '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><circle cx="12" cy="12" r="3"/></svg>',
}


@register.simple_tag(takes_context=True)
def gitako_app_list(context):
    """Return the same app-list shape the default admin uses, but skip the
    apps we don't want in the sidebar (e.g. celery_beat noise).
    """
    request = context.get("request")
    if not request:
        return []
    raw = admin.site.get_app_list(request)
    return [app for app in raw if app.get("app_label") not in {"django_celery_beat"}]


@register.simple_tag
def gitako_icon(name: str):
    return mark_safe(_SVG.get(name or "default", _SVG["default"]))


@register.simple_tag
def gitako_model_icon(model_dict):
    """Pick the icon for a model entry in the admin app list."""
    obj_name = (model_dict.get("object_name") or "").lower()
    app_label = (model_dict.get("app_label") or "").lower()
    key = f"{app_label}.{obj_name}"
    return mark_safe(_SVG.get(ICONS.get(key, APP_ICONS.get(app_label, "default")), _SVG["default"]))


@register.simple_tag
def gitako_app_icon(app_label: str):
    return mark_safe(_SVG.get(APP_ICONS.get(app_label, "default"), _SVG["default"]))


@register.simple_tag(takes_context=True)
def gitako_is_active(context, model_dict) -> bool:
    """Whether a sidebar nav item should render as the active one."""
    request = context.get("request")
    if not request:
        return False
    target = model_dict.get("admin_url") or ""
    return target and request.path.startswith(target)


@register.simple_tag(takes_context=True)
def gitako_is_app_active(context, app) -> bool:
    request = context.get("request")
    if not request:
        return False
    app_label = app.get("app_label", "")
    return f"/admin/{app_label}/" in request.path
