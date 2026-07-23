"""
FIX SPRINT 1, FIX 2 — POST /jobs accepted local filesystem paths (ownership bypass).

What must hold:
  1. POST /jobs accepts ONLY genuine YouTube URLs (_extract_video_id parses
     them). A local path — including another user's storage/uploads file — or
     any other garbage is rejected 400 before anything is enqueued.
  2. The worker no longer trusts disk existence: a task url is treated as a
     local file ONLY when the API's own upload route flagged it (is_upload),
     and even then it must resolve inside storage/uploads.
  3. Ownership stays intact end to end: an attacker submitting another user's
     upload path gets a 4xx, never a job over that file.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import api.main as main
from api.auth import AuthUser
from api.models import JobCreate
from fastapi import HTTPException

from tests.pipeline_stubs import wire_pipeline

USER = AuthUser(id="attacker-1")


def _expect_400(url):
    with pytest.raises(HTTPException) as exc:
        main.create_job_endpoint(JobCreate(url=url), user=USER)
    assert exc.value.status_code == 400
    return exc.value


# ── 1. API: only YouTube URLs pass ──────────────────────────────────────────

def test_post_jobs_rejects_other_users_upload_path(monkeypatch):
    # The exact attack from the review: a path to someone else's private
    # upload. Must 400 with no job created, no task enqueued.
    monkeypatch.setattr(main, "create_job",
                        lambda *a, **k: pytest.fail("no job may be created"))
    monkeypatch.setattr(main.process_video, "delay",
                        lambda *a, **k: pytest.fail("no task may be enqueued"),
                        raising=False)
    _expect_400("storage/uploads/1a2b3c4d.mp4")


def test_post_jobs_rejects_absolute_path_and_garbage(monkeypatch):
    monkeypatch.setattr(main, "create_job",
                        lambda *a, **k: pytest.fail("no job may be created"))
    _expect_400("C:/Windows/system32/config/sam")
    _expect_400("/etc/passwd")
    _expect_400("not a url at all")
    _expect_400("https://example.com/watch?v=abc")  # right shape, wrong host


def test_post_jobs_still_accepts_youtube_urls(monkeypatch):
    store = {}

    def fake_create(job_id, url, language="te", owner="", **kwargs):
        store[job_id] = {"job_id": job_id, "status": "pending", "progress": 0,
                         "current_stage": "queued", "video_id": "", "error": "",
                         "clips": [], "captioned_path": "", "vertical_path": ""}
        return store[job_id]

    delays = []
    monkeypatch.setattr(main, "get_job_by_video_id", lambda vid, **kw: None)
    monkeypatch.setattr(main, "_recover_from_storage", lambda vid, owner="": None)
    monkeypatch.setattr(main, "video_lock_held", lambda vid: False)
    monkeypatch.setattr(main, "create_job", fake_create)
    monkeypatch.setattr(main, "get_job", lambda jid: store.get(jid))
    monkeypatch.setattr(main, "update_job", lambda *a, **k: None)

    class _T:
        def delay(self, *a, **k):
            delays.append((a, k))

    monkeypatch.setattr(main, "process_video", _T())

    out = main.create_job_endpoint(
        JobCreate(url="https://www.youtube.com/watch?v=CC8V0PwlQ4o"), user=USER)

    assert out.status.value == "pending"
    assert len(delays) == 1
    # The YouTube path must never be flagged as an upload.
    assert delays[0][1].get("is_upload") is not True


# ── 2. Worker: no more Path(url).exists() trust ─────────────────────────────

def test_worker_ignores_existing_path_without_upload_flag(tmp_path, monkeypatch):
    """A path that EXISTS on disk but wasn't flagged by the upload route must
    not be processed as an upload — this was the bypass."""
    worker, called, locks, updates = wire_pipeline(tmp_path, monkeypatch, "victim01",
                                                   video=False)
    victim = tmp_path / "uploads" / "victim01.mp4"
    victim.write_text("private", encoding="utf-8")

    def dl_fails(url):
        called["download"] += 1
        raise RuntimeError("YouTube download failed: not a valid URL")

    # Mutate the monkeypatch-scoped stub module directly — the worker resolves
    # the stage from sys.modules, and this stub dies with the test.
    sys.modules["services.video_downloader"].download_youtube = dl_fails

    with pytest.raises(RuntimeError):
        worker.process_video("job-x", str(victim), "te")  # is_upload defaults False

    assert called["upload"] == 0          # the victim's file was never adopted
    assert called["download"] == 1        # treated as a (failing) URL instead
    assert any(kw.get("status") == "failed" for _, kw in updates)


def test_worker_rejects_upload_path_outside_uploads_dir(tmp_path, monkeypatch):
    worker, called, locks, updates = wire_pipeline(tmp_path, monkeypatch, "esc01")
    outside = tmp_path / "somewhere_else.mp4"
    outside.write_text("x", encoding="utf-8")

    with pytest.raises(ValueError):
        worker.process_video("job-esc", str(outside), "te", is_upload=True)

    assert called["upload"] == 0
    failed = [kw for _, kw in updates if kw.get("status") == "failed"]
    assert failed and "outside storage/uploads" in failed[0]["error"]


def test_worker_accepts_genuine_upload_inside_uploads_dir(tmp_path, monkeypatch):
    worker, called, locks, updates = wire_pipeline(tmp_path, monkeypatch, "good1234",
                                                   video=False)
    src = tmp_path / "uploads" / "good1234.mp4"
    src.write_text("x", encoding="utf-8")

    worker.process_video("job-good", str(src), "te", is_upload=True)

    assert called["upload"] == 1
    assert called["download"] == 0
