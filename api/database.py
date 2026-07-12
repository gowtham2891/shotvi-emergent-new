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

def create_job(job_id: str, url: str, language: str = "te"):
    r = get_redis()
    job = {
        "job_id":        job_id,
        "url":           url,
        "language":      language,
        "status":        "pending",
        "progress":      0,
        "current_stage": "queued",
        "video_id":      "",
        "error":         "",
        "clips":         "[]",
        "created_at":    datetime.utcnow().isoformat(),
    }
    r.hset(f"job:{job_id}", mapping=job)
    r.expire(f"job:{job_id}", 86400)  # 24hr TTL
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


def get_job_by_video_id(video_id: str) -> Optional[dict]:
    """
    Scan Redis for an existing *done* job with this video_id.
    Returns the job dict if found, None otherwise.
    Used to skip re-processing the same video.
    """
    r = get_redis()
    # Scan all job keys — fine for dev/small scale
    for key in r.scan_iter("job:*"):
        job = r.hgetall(key)
        if (job.get("video_id") == video_id
                and job.get("status") == "done"
                and not job.get("url", "").startswith("rerender:")):
            job["clips"] = json.loads(job.get("clips", "[]"))
            return job
    return None