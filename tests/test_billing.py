"""
PHASE 2 BUILD 2 gate — Razorpay billing (Studio Plan subscriptions).

What must hold:
  1. Every user-facing billing route requires auth (same guard as job routes).
  2. Plan status defaults to free and reflects stored state; reports whether
     Razorpay is configured.
  3. Subscription creation returns the Checkout.js payload and records the
     subscription against the user (+ reverse index) so a webhook can match it.
  4. Webhook: unsigned/invalid signature → 400 (forged calls can never move
     plan status); verified events flip plan status per the documented map;
     the user is matched by reverse index or notes.user_id fallback.
  5. Cancel requests Razorpay cancellation; the webhook is authoritative.

Auth uses the SAME real HS256 path as test_auth_ownership (no dependency
override). Redis is an in-memory fake. Razorpay's network calls
(create/cancel) are monkeypatched — signature verification runs the REAL
hmac code path.
"""

import os
import sys
import json
import time
import hmac
import hashlib

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
BOB = "22222222-bbbb-4bbb-8bbb-222222222222"


def make_token(sub=ALICE, secret=SECRET, aud="authenticated", email="alice@example.com"):
    now = int(time.time())
    return pyjwt.encode(
        {"sub": sub, "aud": aud, "email": email, "iat": now, "exp": now + 3600},
        secret, algorithm="HS256",
    )


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


class _FakeRedis:
    """Minimal Redis surface the billing storage uses: hashes + string keys,
    including SET NX (event ledger / create lock) and DELETE."""
    def __init__(self):
        self.h = {}   # key -> dict
        self.kv = {}  # key -> str

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
            return None          # redis-py: NX miss → None
        self.kv[key] = str(val)
        return True

    def get(self, key):
        return self.kv.get(key)

    def delete(self, key):
        return 1 if self.kv.pop(key, None) is not None else 0


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient

    # Real HS256 auth path.
    monkeypatch.setattr(auth, "SUPABASE_JWT_SECRET", SECRET)
    monkeypatch.setattr(auth, "SUPABASE_URL", "")
    monkeypatch.setattr(auth, "DEV_MODE", False)

    # In-memory Redis shared by the billing storage helpers.
    fake = _FakeRedis()
    monkeypatch.setattr(database, "get_redis", lambda: fake)

    # Razorpay configured (env present) by default; individual tests may undo.
    monkeypatch.setattr(billing, "RAZORPAY_KEY_ID", "rzp_test_key")
    monkeypatch.setattr(billing, "RAZORPAY_KEY_SECRET", "rzp_test_secret")
    monkeypatch.setattr(billing, "RAZORPAY_PLAN_ID", "plan_test_studio")
    monkeypatch.setattr(billing, "RAZORPAY_WEBHOOK_SECRET", WEBHOOK_SECRET)

    return TestClient(main.app), fake


# ── Signature helper ────────────────────────────────────────────────────────

def signed_webhook(payload: dict, secret=WEBHOOK_SECRET):
    body = json.dumps(payload).encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return body, sig


def _sub_event(event, sub_id="sub_test123", notes=None):
    entity = {"id": sub_id, "status": "active"}
    if notes is not None:
        entity["notes"] = notes
    return {"event": event, "payload": {"subscription": {"entity": entity}}}


# ── 1. Auth required ────────────────────────────────────────────────────────

def test_status_requires_auth(client):
    tc, _ = client
    assert tc.get("/billing/status").status_code == 401


def test_subscription_requires_auth(client):
    tc, _ = client
    assert tc.post("/billing/subscription").status_code == 401


def test_cancel_requires_auth(client):
    tc, _ = client
    assert tc.post("/billing/cancel").status_code == 401


# ── 2. Plan status ──────────────────────────────────────────────────────────

def test_status_defaults_to_free(client):
    tc, _ = client
    r = tc.get("/billing/status", headers=bearer(make_token()))
    assert r.status_code == 200
    body = r.json()
    assert body["plan"] == "free"
    assert body["subscription_status"] == ""
    assert body["configured"] is True
    assert body["plan_info"]["name"] == "Studio Plan"
    assert body["plan_info"]["price_display"] == billing.STUDIO_PLAN["price_display"]


def test_status_reports_unconfigured(client, monkeypatch):
    tc, _ = client
    monkeypatch.setattr(billing, "RAZORPAY_KEY_ID", "")
    r = tc.get("/billing/status", headers=bearer(make_token()))
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is False
    assert body["plan_info"] is None
    assert body["plan"] == "free"


def test_status_reflects_paid_state(client):
    tc, fake = client
    database.set_user_billing(ALICE, plan="studio", subscription_status="active",
                              subscription_id="sub_abc")
    r = tc.get("/billing/status", headers=bearer(make_token(sub=ALICE)))
    body = r.json()
    assert body["plan"] == "studio"
    assert body["subscription_status"] == "active"
    assert body["subscription_id"] == "sub_abc"


def test_status_scoped_per_user(client):
    tc, _ = client
    database.set_user_billing(ALICE, plan="studio", subscription_status="active")
    # Bob is unaffected by Alice's plan.
    r = tc.get("/billing/status", headers=bearer(make_token(sub=BOB)))
    assert r.json()["plan"] == "free"


# ── 3. Subscription creation ────────────────────────────────────────────────

def test_create_subscription_returns_payload_and_records(client, monkeypatch):
    tc, fake = client

    def fake_create(user_id, email=""):
        assert user_id == ALICE
        return {"subscription_id": "sub_new1", "key_id": "rzp_test_key",
                "plan": billing.public_plan_info()}

    monkeypatch.setattr(billing, "create_studio_subscription", fake_create)
    r = tc.post("/billing/subscription", headers=bearer(make_token(sub=ALICE)))
    assert r.status_code == 200
    body = r.json()
    assert body["subscription_id"] == "sub_new1"
    assert body["key_id"] == "rzp_test_key"
    assert body["plan"]["key"] == "studio"

    # Recorded against the user + reverse index for webhook matching.
    stored = database.get_user_billing(ALICE)
    assert stored["subscription_id"] == "sub_new1"
    assert stored["subscription_status"] == "created"
    assert database.get_subscription_owner("sub_new1") == ALICE


def test_create_subscription_503_when_unconfigured(client, monkeypatch):
    tc, _ = client
    monkeypatch.setattr(billing, "RAZORPAY_PLAN_ID", "")
    r = tc.post("/billing/subscription", headers=bearer(make_token()))
    assert r.status_code == 503


def test_create_subscription_409_when_already_active(client, monkeypatch):
    tc, _ = client
    database.set_user_billing(ALICE, plan="studio", subscription_status="active",
                              subscription_id="sub_live")
    called = {"n": 0}
    monkeypatch.setattr(billing, "create_studio_subscription",
                        lambda *a, **k: called.__setitem__("n", called["n"] + 1))
    r = tc.post("/billing/subscription", headers=bearer(make_token(sub=ALICE)))
    assert r.status_code == 409
    assert called["n"] == 0  # no duplicate subscription created


def test_create_subscription_502_on_razorpay_error(client, monkeypatch):
    tc, _ = client

    def boom(*a, **k):
        raise RuntimeError("razorpay down")

    monkeypatch.setattr(billing, "create_studio_subscription", boom)
    r = tc.post("/billing/subscription", headers=bearer(make_token()))
    assert r.status_code == 502


# ── 4. Webhook ──────────────────────────────────────────────────────────────

def test_webhook_rejects_missing_signature(client):
    tc, _ = client
    body, _ = signed_webhook(_sub_event("subscription.activated"))
    r = tc.post("/billing/webhook", content=body)
    assert r.status_code == 400


def test_webhook_rejects_invalid_signature(client):
    tc, _ = client
    body, _ = signed_webhook(_sub_event("subscription.activated"))
    r = tc.post("/billing/webhook", content=body,
                headers={"X-Razorpay-Signature": "deadbeef"})
    assert r.status_code == 400


def test_webhook_activated_marks_user_paid(client):
    tc, _ = client
    database.set_subscription_owner("sub_test123", ALICE)
    body, sig = signed_webhook(_sub_event("subscription.activated"))
    r = tc.post("/billing/webhook", content=body,
                headers={"X-Razorpay-Signature": sig})
    assert r.status_code == 200
    stored = database.get_user_billing(ALICE)
    assert stored["plan"] == "studio"
    assert stored["subscription_status"] == "active"


def test_webhook_charged_marks_user_paid(client):
    tc, _ = client
    database.set_subscription_owner("sub_test123", ALICE)
    body, sig = signed_webhook(_sub_event("subscription.charged"))
    tc.post("/billing/webhook", content=body, headers={"X-Razorpay-Signature": sig})
    assert database.get_user_billing(ALICE)["plan"] == "studio"


def test_webhook_cancelled_marks_user_free(client):
    tc, _ = client
    database.set_subscription_owner("sub_test123", ALICE)
    database.set_user_billing(ALICE, plan="studio", subscription_status="active")
    body, sig = signed_webhook(_sub_event("subscription.cancelled"))
    tc.post("/billing/webhook", content=body, headers={"X-Razorpay-Signature": sig})
    stored = database.get_user_billing(ALICE)
    assert stored["plan"] == "free"
    assert stored["subscription_status"] == "cancelled"


def test_webhook_halted_marks_user_free(client):
    tc, _ = client
    database.set_subscription_owner("sub_test123", ALICE)
    database.set_user_billing(ALICE, plan="studio", subscription_status="active")
    body, sig = signed_webhook(_sub_event("subscription.halted"))
    tc.post("/billing/webhook", content=body, headers={"X-Razorpay-Signature": sig})
    stored = database.get_user_billing(ALICE)
    assert stored["plan"] == "free"
    assert stored["subscription_status"] == "halted"


def test_webhook_matches_via_notes_fallback(client):
    # No reverse index set — user id recovered from subscription notes.
    tc, _ = client
    body, sig = signed_webhook(
        _sub_event("subscription.activated", sub_id="sub_notes", notes={"user_id": BOB}))
    tc.post("/billing/webhook", content=body, headers={"X-Razorpay-Signature": sig})
    assert database.get_user_billing(BOB)["plan"] == "studio"
    # Reverse index is backfilled for next time.
    assert database.get_subscription_owner("sub_notes") == BOB


def test_webhook_ignores_unhandled_event(client):
    tc, _ = client
    database.set_subscription_owner("sub_test123", ALICE)
    body, sig = signed_webhook(_sub_event("subscription.pending"))
    r = tc.post("/billing/webhook", content=body, headers={"X-Razorpay-Signature": sig})
    assert r.status_code == 200
    assert r.json().get("ignored") == "subscription.pending"
    # Unhandled event changes nothing.
    assert database.get_user_billing(ALICE)["plan"] == "free"


def test_webhook_unmatched_subscription_acknowledged(client):
    tc, _ = client
    body, sig = signed_webhook(_sub_event("subscription.activated", sub_id="sub_orphan"))
    r = tc.post("/billing/webhook", content=body, headers={"X-Razorpay-Signature": sig})
    assert r.status_code == 200
    assert r.json().get("unmatched") == "sub_orphan"


# ── 5. Cancel ───────────────────────────────────────────────────────────────

def test_cancel_requests_razorpay_and_marks_cancelling(client, monkeypatch):
    tc, _ = client
    database.set_user_billing(ALICE, plan="studio", subscription_status="active",
                              subscription_id="sub_cancel_me")
    cancelled = {}
    monkeypatch.setattr(billing, "cancel_subscription",
                        lambda sid, **k: cancelled.setdefault("id", sid))
    r = tc.post("/billing/cancel", headers=bearer(make_token(sub=ALICE)))
    assert r.status_code == 200
    assert cancelled["id"] == "sub_cancel_me"
    assert database.get_user_billing(ALICE)["subscription_status"] == "cancelling"


def test_cancel_404_when_no_subscription(client):
    tc, _ = client
    r = tc.post("/billing/cancel", headers=bearer(make_token(sub=ALICE)))
    assert r.status_code == 404


# ── Unit: signature + event mapping ─────────────────────────────────────────

def test_verify_webhook_signature_unit(monkeypatch):
    monkeypatch.setattr(billing, "RAZORPAY_WEBHOOK_SECRET", WEBHOOK_SECRET)
    body = b'{"event":"subscription.charged"}'
    good = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    assert billing.verify_webhook_signature(body, good) is True
    assert billing.verify_webhook_signature(body, "nope") is False
    assert billing.verify_webhook_signature(body, "") is False


def test_verify_webhook_signature_no_secret_fails_closed(monkeypatch):
    monkeypatch.setattr(billing, "RAZORPAY_WEBHOOK_SECRET", "")
    body = b"{}"
    any_sig = hmac.new(b"whatever", body, hashlib.sha256).hexdigest()
    assert billing.verify_webhook_signature(body, any_sig) is False


def test_plan_state_for_event_unit():
    assert billing.plan_state_for_event("subscription.activated") == ("studio", "active")
    assert billing.plan_state_for_event("subscription.charged") == ("studio", "active")
    assert billing.plan_state_for_event("subscription.cancelled") == ("free", "cancelled")
    assert billing.plan_state_for_event("subscription.halted") == ("free", "halted")
    assert billing.plan_state_for_event("subscription.pending") is None
    assert billing.plan_state_for_event("") is None
