"""Resolve the effective alert rule for a farm + rule_type.

A farm may override defaults via a NotificationRule row; otherwise we use
NotificationRule.DEFAULTS. Channels default to in-app, plus SMS for rules
marked critical (mortality spike).
"""
from __future__ import annotations

from dataclasses import dataclass

from .dispatch import CHANNEL_IN_APP, CHANNEL_SMS
from .models import NotificationRule


@dataclass
class EffectiveRule:
    enabled: bool
    params: dict
    channels: tuple[str, ...]


def effective_rule(farm, rule_type: str) -> EffectiveRule:
    default = NotificationRule.DEFAULTS[rule_type]
    row = NotificationRule.objects.filter(farm=farm, rule_type=rule_type).first()

    if row is None:
        critical = default["critical"]
        channels = (CHANNEL_IN_APP,) + ((CHANNEL_SMS,) if critical else ())
        return EffectiveRule(enabled=default["enabled"], params=dict(default["params"]), channels=channels)

    params = {**default["params"], **(row.params or {})}
    channels = tuple(row.channels) if row.channels else (
        (CHANNEL_IN_APP,) + ((CHANNEL_SMS,) if default["critical"] else ())
    )
    return EffectiveRule(enabled=row.enabled, params=params, channels=channels)
