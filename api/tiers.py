"""
Feature #19 — the tier ladder as a single config table.

ONE place that describes what each plan is entitled to; the feature gates
(#17 watermark, #18 render-minute metering, #20 export expiry, #21 premium
presets) all read from here rather than hard-coding plan checks. Payment
wiring stays in api/billing.py / Razorpay — this module is entitlements only.

Plan keys mirror the billing store's `plan` field (api/database.py). Today
Razorpay drives 'free' ⇄ 'studio'; 'creator' is defined here for when its
Razorpay plan is added (a dashboard + webhook task, not a code change). An
unknown/missing plan resolves to FREE — the safe floor.

PRICES here are display placeholders only. The authoritative charge is the
Razorpay Plan (see api/billing.py). Keep the strings in sync when real
Creator/Studio/pack plans land in the dashboard.
"""

from typing import Optional

FREE = "free"
CREATOR = "creator"
STUDIO = "studio"

# Render-minute budgets are per calendar month (feature #18). expiry_hours is
# the published-clip TTL (feature #20); None = never expires.
TIERS = {
    FREE: {
        "key": FREE,
        "name": "Starter",
        "price_display": "₹0",
        "watermark": True,             # #17 — free exports are watermarked
        "render_minutes": 30,          # #18 — monthly render-minute budget
        "expiry_hours": 24,            # #20 — the existing 24h TTL, now official
        "premium_presets": False,      # #21 — premium styles are export-gated
    },
    CREATOR: {
        "key": CREATOR,
        "name": "Creator",
        "price_display": "₹499/mo",
        "watermark": False,
        "render_minutes": 300,
        "expiry_hours": 24 * 30,       # 30 days
        "premium_presets": True,
    },
    STUDIO: {
        "key": STUDIO,
        "name": "Studio",
        "price_display": "₹999/mo",
        "watermark": False,
        "render_minutes": 1200,
        "expiry_hours": None,          # no expiry
        "premium_presets": True,
    },
}

# Optional one-time top-up (feature #19): ₹99 buys extra render minutes without
# a subscription. Applied on top of the tier budget (api metering reads it).
CREDIT_PACK = {
    "key": "pack_99",
    "price_display": "₹99",
    "render_minutes": 60,
}

# Feature #21 — the caption presets that require a paid tier to EXPORT. Free
# users still SEE them in the gallery (marketing); the export gate rejects a
# free-tier export that selected one. These are the 6 added in feature #16.
PREMIUM_PRESETS = frozenset({
    "purple-punch", "ocean-blue", "sunshine", "mono-bold", "pink-pop", "lime-shock",
})


def entitlements(plan_key: Optional[str]) -> dict:
    """Entitlement dict for a plan key; unknown/None → FREE (the safe floor)."""
    return TIERS.get((plan_key or FREE), TIERS[FREE])


def has_watermark(plan_key: Optional[str]) -> bool:
    return entitlements(plan_key)["watermark"]


def render_minutes_budget(plan_key: Optional[str]) -> int:
    return entitlements(plan_key)["render_minutes"]


def expiry_hours(plan_key: Optional[str]) -> Optional[int]:
    return entitlements(plan_key)["expiry_hours"]


def can_use_premium_presets(plan_key: Optional[str]) -> bool:
    return entitlements(plan_key)["premium_presets"]


def is_premium_preset(style_id: str) -> bool:
    return style_id in PREMIUM_PRESETS


def public_tiers() -> list:
    """Tier ladder for the UI (pricing page / upgrade prompts)."""
    return [TIERS[FREE], TIERS[CREATOR], TIERS[STUDIO]]
