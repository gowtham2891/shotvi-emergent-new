import os
import json
from typing import Optional, List
from datetime import datetime
import redis

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

_redis_client = None

def get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    return _redis_client


# ── Job operations ────────────────────────────────────────────

def create_job(job_id: str, url: str, language: str = "te", owner: str = "",
               ttl_seconds: Optional[int] = 86400):
    """owner: verified user id resolved by the API from the Supabase JWT
    (never client-supplied). Stamped once at creation; Celery tasks only ever
    carry job_id and read the owner from here — workers never see user ids
    from the client.

    ttl_seconds (feature #20): the published-clip expiry. Default 86400 (24h,
    the free-tier limit). Paid tiers pass a longer value, or None for NO
    expiry (the key persists). The API computes this from the owner's tier."""
    r = get_redis()
    job = {
        "job_id":        job_id,
        "url":           url,
        "language":      language,
        "owner":         owner,
        "status":        "pending",
        "progress":      0,
        "current_stage": "queued",
        "video_id":      "",
        "error":         "",
        "clips":         "[]",
        "created_at":    datetime.utcnow().isoformat(),
    }
    r.hset(f"job:{job_id}", mapping=job)
    if ttl_seconds:
        r.expire(f"job:{job_id}", ttl_seconds)
    # ttl_seconds None → no expiry (paid/no-expiry tier); the key persists.
    return job


def get_job(job_id: str) -> Optional[dict]:
    r = get_redis()
    job = r.hgetall(f"job:{job_id}")
    if not job:
        return None
    job["clips"] = json.loads(job.get("clips", "[]"))
    # Rerender jobs store these at top level
    job.setdefault("captioned_path", "")
    job.setdefault("vertical_path", "")
    return job


def update_job(job_id: str, **kwargs):
    r = get_redis()
    if "clips" in kwargs and isinstance(kwargs["clips"], list):
        kwargs["clips"] = json.dumps(kwargs["clips"])
    r.hset(f"job:{job_id}", mapping=kwargs)


def set_job_clips(job_id: str, clips: list):
    r = get_redis()
    r.hset(f"job:{job_id}", "clips", json.dumps(clips))


def delete_job(job_id: str) -> int:
    """Remove a job record from Redis. Used to drop a stale 'done' job whose
    output files were deleted from storage, so a fresh regeneration job takes
    its place and future video-id scans don't re-find the dead record.
    Returns the number of keys deleted (0 if it was already gone)."""
    return get_redis().delete(f"job:{job_id}")


def _owner_matches(job: dict, owner: str, include_ownerless: bool) -> bool:
    """Ownership predicate for scans. Mirrors api.auth.user_owns_job: an
    owner id matches only its own jobs; ownerless (pre-auth dev artifact)
    jobs match only when include_ownerless (DEV_MODE identity) is set."""
    job_owner = job.get("owner") or ""
    if job_owner:
        return job_owner == owner
    return include_ownerless


def get_job_by_video_id(video_id: str, owner: str = "",
                        include_ownerless: bool = False) -> Optional[dict]:
    """
    Scan Redis for an existing *done* job with this video_id BELONGING TO
    `owner`. Returns the job dict if found, None otherwise.
    Used to skip re-processing the same video — scoped per owner so one
    user's cached job is never handed to another user.
    """
    r = get_redis()
    # Scan all job keys — fine for dev/small scale
    for key in r.scan_iter("job:*"):
        job = r.hgetall(key)
        if (job.get("video_id") == video_id
                and job.get("status") == "done"
                and not job.get("url", "").startswith("rerender:")
                and _owner_matches(job, owner, include_ownerless)):
            job["clips"] = json.loads(job.get("clips", "[]"))
            return job
    return None


def list_jobs_by_owner(owner: str, include_ownerless: bool = False) -> List[dict]:
    """All pipeline jobs (rerender jobs excluded) owned by `owner`, newest
    first. Backend-enforced job list: the frontend only displays this."""
    r = get_redis()
    jobs = []
    for key in r.scan_iter("job:*"):
        job = r.hgetall(key)
        if not job or job.get("url", "").startswith("rerender:"):
            continue
        if not _owner_matches(job, owner, include_ownerless):
            continue
        job["clips"] = json.loads(job.get("clips", "[]"))
        job.setdefault("captioned_path", "")
        job.setdefault("vertical_path", "")
        jobs.append(job)
    jobs.sort(key=lambda j: j.get("created_at", ""), reverse=True)
    return jobs


# ── User billing operations (PHASE 2 BUILD 2) ─────────────────
# Per-user billing state (plan + Razorpay subscription linkage), keyed by the
# SAME Supabase user id (JWT `sub`) that stamps job ownership — billing hangs
# off identity exactly as Build 1 intended. Unlike jobs (24h TTL) these keys
# carry NO expiry: a paying user must stay paid across job expiry. This is the
# minimal extension of the existing Redis store the build asked for; a proper
# subscriptions table belongs to the later Supabase-Postgres phase.

_DEFAULT_BILLING = {
    "plan": "free",              # 'free' | 'studio'
    "subscription_status": "",   # '' | 'created' | 'active' | 'cancelled' | 'halted' | ...
    "subscription_id": "",
    "razorpay_customer_id": "",
}


def get_user_billing(user_id: str) -> dict:
    """Current billing state for a user, defaults merged in so callers always
    get the full shape (a user who never touched billing reads as free)."""
    if not user_id:
        return dict(_DEFAULT_BILLING)
    stored = get_redis().hgetall(f"user:{user_id}")
    return {**_DEFAULT_BILLING, **stored}


def set_user_billing(user_id: str, **fields):
    """Merge billing fields onto user:{id}. Stamps updated_at. No TTL."""
    if not user_id or not fields:
        return
    fields["updated_at"] = datetime.utcnow().isoformat()
    get_redis().hset(f"user:{user_id}", mapping=fields)


# ── Feature #18: render-minute metering ──────────────────────────────────────
# Used minutes live on the same no-TTL user:{id} hash, keyed BY MONTH
# (minutes_used_YYYYMM) so the budget resets naturally each calendar month
# without a cron — a new month is simply a new, absent (→ 0) field. A ₹99
# credit pack adds to `minutes_pack` (no monthly reset).

def _minutes_used_field() -> str:
    return f"minutes_used_{datetime.utcnow():%Y%m}"


def get_render_minutes_used(user_id: str) -> float:
    """Render minutes consumed this calendar month (0.0 if none / no user)."""
    if not user_id:
        return 0.0
    raw = get_redis().hget(f"user:{user_id}", _minutes_used_field())
    try:
        return float(raw) if raw else 0.0
    except (ValueError, TypeError):
        return 0.0


def add_render_minutes(user_id: str, minutes: float):
    """Add to this month's used minutes (atomic incr). Ignores non-positive."""
    if not user_id or not minutes or minutes <= 0:
        return
    get_redis().hincrbyfloat(f"user:{user_id}", _minutes_used_field(), float(minutes))


def get_render_minutes_pack(user_id: str) -> float:
    """Extra minutes bought via ₹99 top-up packs (no monthly reset)."""
    if not user_id:
        return 0.0
    raw = get_redis().hget(f"user:{user_id}", "minutes_pack")
    try:
        return float(raw) if raw else 0.0
    except (ValueError, TypeError):
        return 0.0


def add_render_minutes_pack(user_id: str, minutes: float):
    """Credit a top-up pack's minutes onto the user (no reset)."""
    if not user_id or not minutes or minutes <= 0:
        return
    get_redis().hincrbyfloat(f"user:{user_id}", "minutes_pack", float(minutes))


def get_user_caption_template(user_id: str) -> Optional[dict]:
    """The user's saved caption template ("My Style"), or None. Rides the same
    no-TTL user:{id} hash as billing (billing reads its fields explicitly, so
    the extra field never leaks into plan status)."""
    if not user_id:
        return None
    raw = get_redis().hget(f"user:{user_id}", "caption_template")
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except (ValueError, TypeError):
        return None


def set_user_caption_template(user_id: str, template: Optional[dict]):
    """Store (or with None: delete) the user's saved caption template."""
    if not user_id:
        return
    r = get_redis()
    if template is None:
        r.hdel(f"user:{user_id}", "caption_template")
    else:
        r.hset(f"user:{user_id}", "caption_template", json.dumps(template))


def set_subscription_owner(subscription_id: str, user_id: str):
    """Reverse index subscription_id → user_id so a webhook (which identifies
    the subscription, not the user) can find whose plan to update. No TTL."""
    if subscription_id and user_id:
        get_redis().set(f"billing:sub:{subscription_id}", user_id)


def get_subscription_owner(subscription_id: str) -> Optional[str]:
    if not subscription_id:
        return None
    return get_redis().get(f"billing:sub:{subscription_id}")


# ── Per-video pipeline lock (FIX SPRINT 1) ────────────────────
# Storage artifacts are shared per video_id, so two pipeline runs over the
# same video corrupt each other's outputs (cleanup unlinks mid-encode files).
# The worker takes this lock for the whole run; the API uses video_lock_held
# as a fast pre-check to 409 a resubmit while a run is in flight. The lock
# carries a TTL so a crashed worker can't wedge a video forever, and a holder
# token (the job_id) so release can't drop a lock a later job now holds.

_VIDEO_LOCK_TTL = 2 * 3600  # generous upper bound on one pipeline run


def acquire_video_lock(video_id: str, token: str, ttl: int = _VIDEO_LOCK_TTL) -> bool:
    """SET NX — True iff this call took the lock."""
    if not video_id:
        return True  # nothing to key on; caller proceeds unlocked
    return bool(get_redis().set(f"lock:video:{video_id}", token, nx=True, ex=ttl))


def release_video_lock(video_id: str, token: str):
    """Release only if we still hold it (compare-and-delete). The GET/DEL pair
    is not atomic, but the only way to lose the race is the TTL expiring in
    the microseconds between them — acceptable at this scale."""
    if not video_id:
        return
    r = get_redis()
    key = f"lock:video:{video_id}"
    if r.get(key) == token:
        r.delete(key)


def video_lock_held(video_id: str) -> bool:
    if not video_id:
        return False
    return get_redis().get(f"lock:video:{video_id}") is not None


# ── Billing webhook ledger + ordering (FIX SPRINT 1) ──────────
# Razorpay retries webhook delivery for up to 24h and delivery is unordered.
# Two guards: an event ledger (each event id applied at most once) and a
# per-subscription created_at high-water mark (an out-of-order .activated
# can't overwrite a later .cancelled).

_BILLING_EVENT_TTL = 7 * 86400  # comfortably past Razorpay's 24h retry window


def claim_billing_event(event_key: str, ttl: int = _BILLING_EVENT_TTL) -> bool:
    """SETNX billing:event:{key} — True iff this event has NOT been processed
    before. Callers pass the x-razorpay-event-id (or a body hash fallback)."""
    if not event_key:
        return True  # nothing to dedup on; process normally
    return bool(get_redis().set(f"billing:event:{event_key}", "1", nx=True, ex=ttl))


def release_billing_event(event_key: str):
    """Undo a claim when processing failed after claiming, so Razorpay's retry
    of the same event isn't swallowed as a duplicate."""
    if event_key:
        get_redis().delete(f"billing:event:{event_key}")


def get_subscription_event_ts(subscription_id: str) -> Optional[int]:
    """created_at of the newest webhook event applied for this subscription."""
    if not subscription_id:
        return None
    v = get_redis().get(f"billing:subts:{subscription_id}")
    try:
        return int(v) if v is not None else None
    except (ValueError, TypeError):
        return None


def set_subscription_event_ts(subscription_id: str, ts: int):
    if subscription_id:
        get_redis().set(f"billing:subts:{subscription_id}", int(ts))


def acquire_billing_create_lock(user_id: str, ttl: int = 30) -> bool:
    """Short-lived per-user lock around subscription create, so two concurrent
    upgrade clicks can't both pass the 'already active' guard and create two
    live Razorpay subscriptions. TTL bounds a crashed request."""
    if not user_id:
        return True
    return bool(get_redis().set(f"billing:createlock:{user_id}", "1", nx=True, ex=ttl))


def release_billing_create_lock(user_id: str):
    if user_id:
        get_redis().delete(f"billing:createlock:{user_id}")


def video_owned_by(video_id: str, owner: str,
                   include_ownerless: bool = False) -> bool:
    """True if `owner` has ANY job (pipeline or rerender, any status) for
    this video_id. Guards video-id-keyed resources (transcript, downloads):
    storage artifacts are shared per video, so ownership of any job over the
    video grants access to them."""
    if not video_id:
        return False
    r = get_redis()
    for key in r.scan_iter("job:*"):
        job = r.hgetall(key)
        if (job.get("video_id") == video_id
                and _owner_matches(job, owner, include_ownerless)):
            return True
    return False