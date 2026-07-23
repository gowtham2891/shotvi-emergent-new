# -*- coding: utf-8 -*-
"""Features #17-21 — tier entitlements + the render-minute metering store.

The API gate wiring (rerender endpoint 402s) is covered by the endpoint's own
behavior; here we pin the config table and the metering counters that back it.
"""

import pytest

from api import tiers


# ── #19 tier config ─────────────────────────────────────────────────────────

def test_free_is_the_safe_floor_for_unknown_plans():
    for bad in (None, "", "enterprise", "garbage"):
        assert tiers.entitlements(bad) is tiers.TIERS[tiers.FREE]


def test_entitlements_ladder():
    assert tiers.has_watermark("free") is True
    assert tiers.has_watermark("creator") is False
    assert tiers.has_watermark("studio") is False
    assert tiers.render_minutes_budget("free") < tiers.render_minutes_budget("creator")
    assert tiers.render_minutes_budget("creator") < tiers.render_minutes_budget("studio")
    assert tiers.expiry_hours("free") == 24
    assert tiers.expiry_hours("studio") is None  # no expiry


def test_premium_preset_gate():
    assert tiers.is_premium_preset("purple-punch") is True
    assert tiers.is_premium_preset("bold-yellow") is False   # original preset
    assert tiers.can_use_premium_presets("free") is False
    assert tiers.can_use_premium_presets("creator") is True


def test_public_tiers_lists_three():
    keys = [t["key"] for t in tiers.public_tiers()]
    assert keys == ["free", "creator", "studio"]


# ── #18 render-minute metering store ────────────────────────────────────────

@pytest.fixture
def redis_stub(monkeypatch):
    class R:
        def __init__(self): self.h = {}
        def hget(self, k, f): return self.h.get(k, {}).get(f)
        def hincrbyfloat(self, k, f, a):
            d = self.h.setdefault(k, {})
            d[f] = str(float(d.get(f, 0) or 0) + float(a)); return float(d[f])
    from api import database
    r = R()
    monkeypatch.setattr(database, "get_redis", lambda: r)
    return database


def test_minutes_accumulate_within_the_month(redis_stub):
    db = redis_stub
    assert db.get_render_minutes_used("u1") == 0.0
    db.add_render_minutes("u1", 2.5)
    db.add_render_minutes("u1", 1.0)
    assert db.get_render_minutes_used("u1") == pytest.approx(3.5)


def test_month_key_isolates_usage(redis_stub, monkeypatch):
    db = redis_stub
    db.add_render_minutes("u1", 5.0)
    # Force a different month → a fresh (zero) counter.
    monkeypatch.setattr(db, "_minutes_used_field", lambda: "minutes_used_209901")
    assert db.get_render_minutes_used("u1") == 0.0


def test_credit_pack_is_separate_and_persists(redis_stub):
    db = redis_stub
    db.add_render_minutes_pack("u1", 60)
    assert db.get_render_minutes_pack("u1") == pytest.approx(60)
    # pack is independent of monthly used minutes
    db.add_render_minutes("u1", 3)
    assert db.get_render_minutes_pack("u1") == pytest.approx(60)


def test_non_positive_and_missing_user_are_safe(redis_stub):
    db = redis_stub
    db.add_render_minutes("", 5)          # no user → no-op
    db.add_render_minutes("u1", 0)        # zero → no-op
    db.add_render_minutes("u1", -3)       # negative → no-op
    assert db.get_render_minutes_used("u1") == 0.0
    assert db.get_render_minutes_used("") == 0.0
