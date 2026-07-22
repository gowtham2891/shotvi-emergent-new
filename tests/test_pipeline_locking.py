"""
FIX SPRINT 1, FIX 1 — same-video concurrent pipelines destroy each other's outputs.

What must hold:
  1. The worker takes a per-video_id lock for the whole pipeline run; a second
     submission for the same video while one is in flight is REJECTED (clean
     failed job with a clear error), never run concurrently.
  2. The lock is keyed by the video id, tokened by the job id, and always
     released — on success AND on stage failure.
  3. Pre-cut cleanup is scoped to THIS video's own pipeline artifacts:
     rerender/export outputs (_canvas/_overlays/_prepared-marked) survive, and
     so do other videos whose id merely shares a string prefix.
  4. The crop stage only processes this job's clips (video_id filter passed).
  5. The crop/trim intermediate carries the rerender job_suffix like every
     other rerender artifact, so concurrent re-exports can't collide on it.
  6. POST /jobs pre-checks the lock and 409s a resubmit while a run is live.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.pipeline_stubs import wire_pipeline

VID = "vidLOCK01"
YT = f"https://youtu.be/{VID}"


# ── 1+2. Worker lock semantics ──────────────────────────────────────────────

def test_second_submission_same_video_is_rejected_not_run(tmp_path, monkeypatch):
    worker, called, locks, updates = wire_pipeline(tmp_path, monkeypatch, VID)
    locks["grant"] = False  # someone else holds the lock

    worker.process_video("job-second", YT, "te")

    # Clean rejection: failed status with a clear message, no stage ever ran.
    statuses = [kw for _, kw in updates if kw.get("status") == "failed"]
    assert statuses and "already being processed" in statuses[0]["error"]
    assert called["cut"] == 0 and called["crop"] == 0 and called["caption"] == 0
    assert called["download"] == 0 and called["transcribe"] == 0
    # Never releases a lock it didn't acquire.
    assert locks["released"] == []


def test_lock_keyed_by_video_id_tokened_by_job_id_and_released(tmp_path, monkeypatch):
    worker, called, locks, updates = wire_pipeline(tmp_path, monkeypatch, VID)

    worker.process_video("job-one", YT, "te")

    assert locks["acquired"] == [(VID, "job-one")]
    assert locks["released"] == [(VID, "job-one")]
    assert called["cut"] == 1  # pipeline actually ran


def test_lock_released_even_when_a_stage_fails(tmp_path, monkeypatch):
    worker, called, locks, updates = wire_pipeline(tmp_path, monkeypatch, VID)

    def boom(*a, **k):
        raise RuntimeError("ffmpeg died")

    # Mutate the monkeypatch-scoped stub module directly — the worker resolves
    # the stage from sys.modules, and this stub dies with the test.
    sys.modules["services.video_cutter"].cut_all_clips = boom

    with pytest.raises(RuntimeError):
        worker.process_video("job-boom", YT, "te")

    assert locks["released"] == [(VID, "job-boom")]
    assert any(kw.get("status") == "failed" for _, kw in updates)


def test_upload_job_locks_on_upload_video_id(tmp_path, monkeypatch):
    worker, called, locks, updates = wire_pipeline(tmp_path, monkeypatch, "up1a2b3c",
                                                   video=False)
    src = tmp_path / "uploads" / "up1a2b3c.mp4"
    src.write_text("x", encoding="utf-8")

    worker.process_video("up1a2b3c-full-job-id", str(src), "te", is_upload=True)

    assert locks["acquired"][0][0] == "up1a2b3c"
    assert called["upload"] == 1


# ── 3. Scoped cleanup ───────────────────────────────────────────────────────

def test_cleanup_preserves_rerenders_and_prefix_sharing_videos(tmp_path, monkeypatch):
    worker, called, locks, updates = wire_pipeline(tmp_path, monkeypatch, VID)
    out = tmp_path / "outputs"

    doomed = [
        f"{VID}_clip1_old.mp4",                                   # stale raw cut
        f"{VID}_clip1_old_vertical.mp4",                          # stale vertical
        f"{VID}_clip1_old_vertical_bold-yellow_captioned.mp4",    # stale pipeline caption
        f"{VID}_clip1_old_thumb.jpg",                             # stale thumbnail
    ]
    survivors = [
        # Rerender/export artifacts — a user's previous exports must survive.
        f"{VID}_clip1_old_vertical_9_16_blur_ab12cd34_canvas.mp4",
        f"{VID}_clip1_old_vertical_9_16_blur_ab12cd34_overlays.mp4",
        f"{VID}_clip1_old_vertical_9_16_blur_ab12cd34_overlays_bold-yellow_captioned.mp4",
        f"{VID}_clip1_old_ab12cd34_prepared.mp4",
        # Another video whose id shares this one's prefix — old bare
        # startswith(video_id) glob would have deleted it.
        f"{VID}XX_clip1_other_video.mp4",
    ]
    for name in doomed + survivors:
        (out / name).write_text("x", encoding="utf-8")

    worker.process_video("job-clean", YT, "te")

    remaining = {f.name for f in out.iterdir()}
    for name in doomed:
        assert name not in remaining, f"stale pipeline artifact not cleaned: {name}"
    for name in survivors:
        assert name in remaining, f"must survive cleanup: {name}"


def test_pipeline_output_collection_never_adopts_a_rerender_export(tmp_path, monkeypatch):
    worker, called, locks, updates = wire_pipeline(tmp_path, monkeypatch, VID)
    out = tmp_path / "outputs"
    # Only a surviving rerender export matches the *captioned.mp4 glob shape.
    rerender = f"{VID}_clip1_old_vertical_9_16_blur_ab12cd34_overlays_bold-yellow_captioned.mp4"
    (out / rerender).write_text("x", encoding="utf-8")

    captured = {}
    monkeypatch.setattr(worker, "set_job_clips",
                        lambda jid, clips: captured.setdefault("clips", clips))

    worker.process_video("job-collect", YT, "te")

    clips = captured["clips"]
    assert len(clips) == 1
    assert clips[0]["captioned_path"] == ""   # NOT the old export
    assert rerender not in clips[0]["captioned_path"]


# ── 4. Crop stage scoped to this job's video ────────────────────────────────

def test_crop_receives_video_id_filter(tmp_path, monkeypatch):
    worker, called, locks, updates = wire_pipeline(tmp_path, monkeypatch, VID)

    worker.process_video("job-crop", YT, "te")

    assert called["crop"] == 1
    assert called["crop_kwargs"] == {"video_id": VID}


# ── 5. _prepared intermediate carries the job suffix ────────────────────────

def test_prepared_intermediate_is_job_unique(tmp_path, monkeypatch):
    import api.worker as worker

    out = tmp_path / "outputs"
    up = tmp_path / "uploads"
    out.mkdir()
    up.mkdir()
    monkeypatch.setattr(worker, "UPLOAD_DIR", up)
    monkeypatch.setattr(worker, "OUTPUT_DIR", out)

    src = out / f"{VID}_clip1_x.mp4"
    src.write_text("x", encoding="utf-8")

    monkeypatch.setattr(worker, "get_job", lambda jid: {
        "clips": [{"raw_path": str(src), "vertical_path": ""}],
    })
    monkeypatch.setattr(worker, "update_job", lambda *a, **k: None)
    monkeypatch.setattr(worker, "_get_duration", lambda p: 30.0)

    prepared_paths = []
    monkeypatch.setattr(worker, "_prepare_source",
                        lambda i, o, **kw: prepared_paths.append(o))
    monkeypatch.setattr(worker, "_apply_canvas", lambda *a, **k: None)
    monkeypatch.setattr("services.overlay_renderer.render_elements",
                        lambda cin, cout, els, w, h: cin)
    monkeypatch.setattr("services.caption_renderer.render_captions_for_clip",
                        lambda **kw: str(out / "final.mp4"))

    rjob = "abcdef12-3456-7890-abcd-ef1234567890"
    worker.rerender_clip(rjob, "srcjob", 0, "bold-yellow", "9:16", "blur", "#000000",
                         False, 2.0, -1.0, VID)

    assert len(prepared_paths) == 1
    name = os.path.basename(prepared_paths[0])
    # job_suffix (first 8 chars of the rerender job id) before _prepared.mp4 —
    # same convention as every other rerender artifact.
    assert name.endswith(f"_{rjob[:8]}_prepared.mp4")


# ── 6. API pre-check: 409 while a run is in flight ──────────────────────────

def test_post_jobs_409_when_video_lock_held(monkeypatch):
    import api.main as main
    from api.auth import AuthUser
    from api.models import JobCreate
    from fastapi import HTTPException

    monkeypatch.setattr(main, "get_job_by_video_id", lambda vid, **kw: None)
    monkeypatch.setattr(main, "_recover_from_storage", lambda vid, owner="": None)
    monkeypatch.setattr(main, "video_lock_held", lambda vid: True)
    monkeypatch.setattr(main, "create_job",
                        lambda *a, **k: pytest.fail("no job may be created while locked"))

    with pytest.raises(HTTPException) as exc:
        main.create_job_endpoint(JobCreate(url=YT), user=AuthUser(id="u1"))
    assert exc.value.status_code == 409
