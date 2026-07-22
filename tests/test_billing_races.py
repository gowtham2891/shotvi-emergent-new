"""
FIX SPRINT 1, FIX 4 — billing webhook replay/ordering races (real money).

What must hold:
  1. Event ledger: a webhook replay (same x-razorpay-event-id, or identical
     body when the header is absent) is acknowledged but applies NOTHING —
     Razorpay retries delivery for up to 24h.
  2. Ordering: an event whose created_at is older than the newest event
     already applied for that subscription is a no-op — a delayed
     .activated/.charged can never flip a cancelled user back to paid.
  3. Newer events still apply normally (the guards don't break the happy path).
  4. Subscription create is serialized per user: two concurrent upgrade clicks
     produce exactly ONE Razorpay subscription (second click 409s), and the
     lock is released afterwards so later legitimate attempts work.

Same house style as test_billing.py: real HS256 auth, real HMAC verification,
in-memory Redis, Razorpay network calls monkeypatched.
"""

import os
import sys
import json
import time
import hmac
import hashlib
import threading

import pytest
import jwt as pyjwt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import api.auth as auth
import api.billing as billing
import api.database as database
import api.main as main

SECRET = "test-jwt-secret-0123456789abcdef0123456789abcdef"
WEBHOOK_SECRET = "whsec_test_0123456789"
ALICE = "11111111-aaaa-4aaa-8aaa-111111111111"


def make_token(sub=ALICE, email="alice@example.com"):
    now = int(time.time())
    return pyjwt.encode(
        {"sub": sub, "aud": "authenticated", "email": email, "iat": now, "exp": now + 3600},
        SECRET, algorithm="HS256",
    )


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


class _FakeRedis:
    def __init__(self):
        self.h = {}
        self.kv = {}

    def hgetall(self, key):
        return dict(self.h.get(key, {}))

    def hset(self, key, mapping=None, **kw):
        d = self.h.setdefault(key, {})
        if mapping:
            d.update({k: str(v) for k, v in mapping.items()})
        if kw:
            d.update({k: str(v) for k, v in kw.items()})

    def set(self, key, val, ex=None, nx=False):
        if nx and key in self.kv:
            return None
        self.kv[key] = str(val)
        return True

    def get(self, key):
        return self.kv.get(key)

    def delete(self, key):
        return 1 if self.kv.pop(key, None) is not None else 0


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setattr(auth, "SUPABASE_JWT_SECRET", SECRET)
    monkeypatch.setattr(auth, "SUPABASE_URL", "")
    monkeypatch.setattr(auth, "DEV_MODE", False)

    fake = _FakeRedis()
    monkeypatch.setattr(database, "get_redis", lambda: fake)

    monkeypatch.setattr(billing, "RAZORPAY_KEY_ID", "rzp_test_key")
    monkeypatch.setattr(billing, "RAZORPAY_KEY_SECRET", "rzp_test_secret")
    monkeypatch.setattr(billing, "RAZORPAY_PLAN_ID", "plan_test_studio")
    monkeypatch.setattr(billing, "RAZORPAY_WEBHOOK_SECRET", WEBHOOK_SECRET)

    return TestClient(main.app), fake


def _post_event(tc, event, sub_id="sub_race1", created_at=None, event_id=None):
    payload = {"event": event,
               "payload": {"subscription": {"entity": {"id": sub_id, "status": "x"}}}}
    if created_at is not None:
        payload["created_at"] = created_at
    body = json.dumps(payload).encode("utf-8")
    sig = hmac.new(WEBHOOK_SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()
    headers = {"X-Razorpay-Signature": sig}
    if event_id:
        headers["x-razorpay-event-id"] = event_id
    return tc.post("/billing/webhook", content=body, headers=headers)


# ── 1. Replay (same event id) is a no-op ────────────────────────────────────

def test_webhook_replay_is_noop(client):
    tc, _ = client
    database.set_subscription_owner("sub_race1", ALICE)

    r = _post_event(tc, "subscription.activated", created_at=100, event_id="evt_A")
    assert r.status_code == 200 and r.json().get("plan") == "studio"
    assert database.get_user_billing(ALICE)["plan"] == "studio"

    # The user later cancels; then Razorpay redelivers the OLD activated event.
    database.set_user_billing(ALICE, plan="free", subscription_status="cancelled")
    r2 = _post_event(tc, "subscription.activated", created_at=100, event_id="evt_A")
    assert r2.status_code == 200
    assert r2.json().get("duplicate")
    stored = database.get_user_billing(ALICE)
    assert stored["plan"] == "free"                     # replay changed nothing
    assert stored["subscription_status"] == "cancelled"


def test_webhook_replay_dedups_on_body_hash_without_header(client):
    tc, _ = client
    database.set_subscription_owner("sub_race1", ALICE)

    r = _post_event(tc, "subscription.charged", created_at=50)
    assert r.json().get("plan") == "studio"

    database.set_user_billing(ALICE, plan="free", subscription_status="halted")
    r2 = _post_event(tc, "subscription.charged", created_at=50)   # identical body
    assert r2.json().get("duplicate")
    assert database.get_user_billing(ALICE)["plan"] == "free"


# ── 2. Out-of-order delivery cannot resurrect a cancelled sub ───────────────

def test_delayed_activated_cannot_overwrite_later_cancelled(client):
    tc, _ = client
    database.set_subscription_owner("sub_race1", ALICE)

    # Cancellation (newer) lands first — delivery is unordered.
    r = _post_event(tc, "subscription.cancelled", created_at=200, event_id="evt_C")
    assert r.json().get("plan") == "free"

    # The delayed activation (older) arrives up to 24h later.
    r2 = _post_event(tc, "subscription.activated", created_at=100, event_id="evt_B")
    assert r2.status_code == 200
    assert r2.json().get("stale") == "subscription.activated"
    stored = database.get_user_billing(ALICE)
    assert stored["plan"] == "free"
    assert stored["subscription_status"] == "cancelled"


def test_delayed_charged_cannot_overwrite_later_halted(client):
    tc, _ = client
    database.set_subscription_owner("sub_race1", ALICE)
    _post_event(tc, "subscription.halted", created_at=500, event_id="evt_H")
    _post_event(tc, "subscription.charged", created_at=499, event_id="evt_G")
    assert database.get_user_billing(ALICE)["plan"] == "free"


# ── 3. The guards don't break correctly-ordered events ──────────────────────

def test_newer_events_apply_in_sequence(client):
    tc, _ = client
    database.set_subscription_owner("sub_race1", ALICE)

    _post_event(tc, "subscription.activated", created_at=100, event_id="e1")
    assert database.get_user_billing(ALICE)["plan"] == "studio"

    _post_event(tc, "subscription.charged", created_at=200, event_id="e2")
    assert database.get_user_billing(ALICE)["plan"] == "studio"

    _post_event(tc, "subscription.cancelled", created_at=300, event_id="e3")
    stored = database.get_user_billing(ALICE)
    assert stored["plan"] == "free"
    assert stored["subscription_status"] == "cancelled"


def test_events_without_created_at_still_apply(client):
    # Legacy/edge payloads with no created_at skip the ordering guard but
    # still dedup by event id.
    tc, _ = client
    database.set_subscription_owner("sub_race1", ALICE)
    r = _post_event(tc, "subscription.activated", event_id="evt_nots")
    assert r.json().get("plan") == "studio"


# ── 4. Concurrent upgrade clicks → exactly one subscription ─────────────────

def test_concurrent_upgrade_clicks_create_exactly_one_subscription(client, monkeypatch):
    tc, _ = client
    created = []
    first_inside = threading.Event()   # first request has entered create
    release_first = threading.Event()  # let the first request finish

    def slow_create(user_id, email=""):
        created.append(user_id)
        first_inside.set()
        assert release_first.wait(timeout=10), "test deadlock"
        return {"subscription_id": f"sub_{len(created)}", "key_id": "rzp_test_key",
                "plan": billing.public_plan_info()}

    monkeypatch.setattr(billing, "create_studio_subscription", slow_create)

    results = {}

    def first_click():
        results["first"] = tc.post("/billing/subscription",
                                   headers=bearer(make_token())).status_code

    t = threading.Thread(target=first_click)
    t.start()
    assert first_inside.wait(timeout=10), "first request never reached create"

    # Second click lands while the first is still mid-create: must 409, and
    # must NOT reach Razorpay.
    second = tc.post("/billing/subscription", headers=bearer(make_token()))
    assert second.status_code == 409

    release_first.set()
    t.join(timeout=10)
    assert results["first"] == 200
    assert created == [ALICE]                 # exactly one Razorpay create call
    stored = database.get_user_billing(ALICE)
    assert stored["subscription_id"] == "sub_1"
    assert stored["subscription_status"] == "created"


def test_create_lock_released_after_completion(client, monkeypatch):
    tc, _ = client
    calls = {"n": 0}

    def fake_create(user_id, email=""):
        calls["n"] += 1
        return {"subscription_id": f"sub_{calls['n']}", "key_id": "rzp_test_key",
                "plan": billing.public_plan_info()}

    monkeypatch.setattr(billing, "create_studio_subscription", fake_create)

    assert tc.post("/billing/subscription", headers=bearer(make_token())).status_code == 200
    # Lock must not linger: a later attempt (e.g. abandoned checkout, retry)
    # goes through instead of 409ing on a stale lock.
    assert tc.post("/billing/subscription", headers=bearer(make_token())).status_code == 200
    assert calls["n"] == 2


def test_create_lock_blocks_only_while_held(client, monkeypatch):
    tc, _ = client
    monkeypatch.setattr(billing, "create_studio_subscription",
                        lambda *a, **k: pytest.fail("must not reach Razorpay while locked"))
    assert database.acquire_billing_create_lock(ALICE) is True
    r = tc.post("/billing/subscription", headers=bearer(make_token()))
    assert r.status_code == 409
    database.release_billing_create_lock(ALICE)
