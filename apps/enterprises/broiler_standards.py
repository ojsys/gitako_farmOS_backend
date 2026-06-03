"""
Broiler breed performance standards.

Reference target curves for common broiler strains used in West Africa. Targets
are *defaults*: a batch may override any of them via `enterprise.attrs`
(target_fcr, target_mortality_pct, target_market_weight_g, cycle_length_days) —
see `resolve_targets()` for the hybrid lookup.

Weight points are (day, grams) of expected average live weight as raised on a
standard commercial program. Values interpolated linearly between points and
held flat past the last point.
"""
from __future__ import annotations

# Weekly target average live weight (day -> grams), as-hatched mixed sex.
_COBB_500 = {
    "label": "Cobb 500",
    "cycle_length_days": 56,
    "target_fcr": 1.65,
    "target_mortality_pct": 4.0,
    "target_market_weight_g": 2700,
    "weight_curve": {
        0: 42, 7: 185, 14: 465, 21: 950, 28: 1500,
        35: 2100, 42: 2700, 49: 3250, 56: 3750,
    },
}

_ROSS_308 = {
    "label": "Ross 308",
    "cycle_length_days": 56,
    "target_fcr": 1.62,
    "target_mortality_pct": 4.0,
    "target_market_weight_g": 2750,
    "weight_curve": {
        0: 43, 7: 190, 14: 480, 21: 970, 28: 1530,
        35: 2150, 42: 2750, 49: 3300, 56: 3800,
    },
}

# Conservative generic curve for unknown/local strains.
_GENERIC = {
    "label": "Broiler",
    "cycle_length_days": 56,
    "target_fcr": 1.80,
    "target_mortality_pct": 5.0,
    "target_market_weight_g": 2400,
    "weight_curve": {
        0: 40, 7: 170, 14: 430, 21: 880, 28: 1380,
        35: 1900, 42: 2400, 49: 2850, 56: 3250,
    },
}

_STANDARDS = {
    "cobb_500": _COBB_500,
    "cobb500": _COBB_500,
    "cobb 500": _COBB_500,
    "ross_308": _ROSS_308,
    "ross308": _ROSS_308,
    "ross 308": _ROSS_308,
}


def _normalize(breed) -> str:
    return str(breed or "").strip().lower().replace("-", "_")


def standard_for(breed) -> dict:
    """Return the breed standard dict, falling back to a generic curve."""
    return _STANDARDS.get(_normalize(breed), _GENERIC)


def target_weight_g(breed, day) -> int | None:
    """Expected average live weight (g) at `day` for a breed, interpolated."""
    if day is None or day < 0:
        return None
    curve = standard_for(breed)["weight_curve"]
    points = sorted(curve.items())
    if day <= points[0][0]:
        return int(points[0][1])
    if day >= points[-1][0]:
        return int(points[-1][1])
    for (d0, g0), (d1, g1) in zip(points, points[1:]):
        if d0 <= day <= d1:
            span = d1 - d0
            frac = (day - d0) / span if span else 0
            return int(round(g0 + (g1 - g0) * frac))
    return int(points[-1][1])


def resolve_targets(attrs: dict) -> dict:
    """
    Hybrid targets for a batch: breed-standard defaults overridden by anything
    explicitly set on the enterprise's attrs.
    """
    attrs = attrs or {}
    std = standard_for(attrs.get("breed"))

    def pick(key, std_key, cast):
        v = attrs.get(key)
        if v in (None, ""):
            return std[std_key]
        try:
            return cast(v)
        except (TypeError, ValueError):
            return std[std_key]

    return {
        "breed_label": std["label"],
        "cycle_length_days": pick("cycle_length_days", "cycle_length_days", int),
        "target_fcr": pick("target_fcr", "target_fcr", float),
        "target_mortality_pct": pick("target_mortality_pct", "target_mortality_pct", float),
        "target_market_weight_g": pick("target_market_weight_g", "target_market_weight_g", int),
    }
