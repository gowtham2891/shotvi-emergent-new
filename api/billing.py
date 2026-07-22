"""
Razorpay billing — Studio Plan subscriptions (PHASE 2 BUILD 2).

Scope of this module: turn an authenticated user into a paying subscriber and
keep their plan status in sync with Razorpay. It is payment + plan-status
plumbing ONLY — it gates no features (there are no paid features yet). A future
real feature gates on `plan == "studio"` with a one-line check against the
status endpoint; nothing here decides what paid users can do.

Identity: billing hangs off the SAME Supabase user id (JWT `sub`) that stamps
job ownership in Build 1 — see api/auth.py. Plan state lives in Redis next to
jobs (api/database.py user_billing helpers), NOT in a new database; a dedicated
subscriptions table is a natural fit for the later Supabase-Postgres phase.

Configuration (all via env; absent → billing_configured() is False and the API
reports an unconfigured state instead of crashing — see SETUP_BILLING.md):
  RAZORPAY_KEY_ID        — public key id (safe to hand the browser for Checkout)
  RAZORPAY_KEY_SECRET    — secret key (server-only; signs API calls)
  RAZORPAY_WEBHOOK_SECRET— shared secret Razorpay signs webhooks with
  RAZORPAY_PLAN_ID       — the Studio Plan created in the Razorpay dashboard;
                           THE authoritative price lives there, not in code.

PRICE: the real amount is the Razorpay Plan (RAZORPAY_PLAN_ID). The ₹499/mo
below is a DISPLAY placeholder only (one constant, one place) — changing the
real price is a dashboard edit, never a code hunt.
"""

import os
import hmac
import hashlib

# ── Plan definition — the single place the plan is described in code ─────────
# The price shown in the UI. The charge itself is whatever the Razorpay Plan
# says; keep this string in sync with the dashboard when the real price lands.
STUDIO_PLAN = {
    "key": "studio",
    "name": "Studio Plan",
    "price_display": "₹499/mo",   # PLACEHOLDER — authoritative amount is the Razorpay Plan
    "interval": "monthly",
    # Billing cycles Razorpay will attempt before the subscription completes.
    # Razorpay requires a finite total_count; 120 months (~10 years) stands in
    # for "ongoing" so a subscription doesn't silently end while in use.
    "billing_cycles": 120,
}

FREE_PLAN_KEY = "free"
STUDIO_PLAN_KEY = STUDIO_PLAN["key"]


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


# Read at import; tests monkeypatch these module globals directly (house style,
# matching api/auth.py).
RAZORPAY_KEY_ID         = _env("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET     = _env("RAZORPAY_KEY_SECRET")
RAZORPAY_WEBHOOK_SECRET = _env("RAZORPAY_WEBHOOK_SECRET")
RAZORPAY_PLAN_ID        = _env("RAZORPAY_PLAN_ID")


def billing_configured() -> bool:
    """True only when the subscription-creation path can actually run: needs
    the API key pair AND a plan id. The webhook secret is checked separately
    (webhook verification fails closed without it)."""
    return bool(RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET and RAZORPAY_PLAN_ID)


def webhook_configured() -> bool:
    return bool(RAZORPAY_WEBHOOK_SECRET)


class BillingNotConfigured(RuntimeError):
    """Raised by paths that need Razorpay when env vars are absent — the route
    layer maps it to a clear 503, never a 500 stack trace."""


_client = None


def _get_client():
    """Lazy Razorpay client. Imported lazily so the whole API doesn't hard-
    depend on the razorpay SDK just to boot in dev/unconfigured mode."""
    global _client
    if not billing_configured():
        raise BillingNotConfigured(
            "Razorpay is not configured (set RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET "
            "/ RAZORPAY_PLAN_ID). See SETUP_BILLING.md."
        )
    if _client is None:
        import razorpay  # local import: optional dependency
        _client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
    return _client


# ── Webhook signature verification ──────────────────────────────────────────

def verify_webhook_signature(body: bytes, signature: str) -> bool:
    """Razorpay signs each webhook with HMAC-SHA256 of the RAW request body
    keyed by RAZORPAY_WEBHOOK_SECRET, delivered in the X-Razorpay-Signature
    header. Recompute and constant-time compare. Fails closed: no secret
    configured, no signature, or any mismatch → False (the route rejects with
    400, so an unsigned/forged call can never move plan status).

    Implemented with stdlib hmac/hashlib (not the SDK) so verification is
    dependency-free and deterministically testable."""
    if not RAZORPAY_WEBHOOK_SECRET or not signature:
        return False
    expected = hmac.new(
        RAZORPAY_WEBHOOK_SECRET.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


# ── Event → plan-status mapping ─────────────────────────────────────────────
# The webhook route calls this to decide the new plan state for an event. One
# place so the "which events make you paid" rule is auditable at a glance.
#
# Returns (plan, subscription_status) or None for events we don't act on.
_ACTIVATE_EVENTS = {"subscription.activated", "subscription.charged"}
_DEACTIVATE_EVENTS = {
    "subscription.cancelled": "cancelled",
    "subscription.halted": "halted",
    # 'completed' (all cycles billed) and 'expired' also end access.
    "subscription.completed": "completed",
    "subscription.expired": "expired",
}


def plan_state_for_event(event: str):
    if event in _ACTIVATE_EVENTS:
        return (STUDIO_PLAN_KEY, "active")
    if event in _DEACTIVATE_EVENTS:
        return (FREE_PLAN_KEY, _DEACTIVATE_EVENTS[event])
    return None


# ── Subscription lifecycle (Razorpay API calls) ─────────────────────────────

def create_studio_subscription(user_id: str, email: str = "") -> dict:
    """Create a Razorpay subscription for the Studio Plan and return what the
    browser's Checkout.js needs: {subscription_id, key_id, plan}. Raises
    BillingNotConfigured when env is absent.

    Customer details are collected by Razorpay Checkout at authorization time,
    so no customer is pre-created here. The user id is stamped into the
    subscription `notes` so a webhook can recover ownership even if the reverse
    index is ever lost."""
    client = _get_client()
    sub = client.subscription.create({
        "plan_id": RAZORPAY_PLAN_ID,
        "total_count": STUDIO_PLAN["billing_cycles"],
        "customer_notify": 1,
        "notes": {"user_id": user_id, "email": email or ""},
    })
    return {
        "subscription_id": sub["id"],
        "key_id": RAZORPAY_KEY_ID,
        "plan": public_plan_info(),
    }


def cancel_subscription(subscription_id: str, cancel_at_cycle_end: bool = False) -> dict:
    """Cancel a subscription in Razorpay. The authoritative status flip to
    'free' happens when the resulting subscription.cancelled webhook arrives —
    this call just requests it. Raises BillingNotConfigured when env is absent."""
    client = _get_client()
    return client.subscription.cancel(
        subscription_id, {"cancel_at_cycle_end": 1 if cancel_at_cycle_end else 0}
    )


# ── Public shapes ───────────────────────────────────────────────────────────

def public_plan_info() -> dict:
    """Plan descriptor safe to expose to the frontend (no secrets)."""
    return {
        "key": STUDIO_PLAN["key"],
        "name": STUDIO_PLAN["name"],
        "price_display": STUDIO_PLAN["price_display"],
        "interval": STUDIO_PLAN["interval"],
    }
