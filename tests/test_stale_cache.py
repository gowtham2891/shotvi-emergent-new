"""
Redis stale-cache validation (POST /jobs cache-hit path).

Bug reproduced: POST /jobs with a YouTube URL whose job is already 'done' in
Redis returned the cached record immediately — but if the output files it
references were deleted from storage/outputs, the frontend 404s forever and
nothing ever re-renders.

Fix under test (api/main.py):
  - On a Redis hit, validate the artifacts the record references actually exist
    on disk (transcript + each clip's captioned output).
  - All present  → return the cached record, no pipeline invocation.
  - Missing      → regenerate, re-running ONLY the stages needed and reusing
                   surviving checkpoints (never re-transcribe if the transcript
                   is still on disk — that costs external API credits).

`_regeneration_stages` mirrors process_video's checkpoint guards, so asserting
it proves "missing transcript vs missing clips re-run different stage sets".
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import api.main as main
from api.auth import AuthUser
from api.models import JobCreate


VIDEO_ID = "vid12345678"
YT_URL = f"https://youtu.be/{VIDEO_ID}"

# Identity for direct endpoint calls (auth itself is covered in
# test_auth_ownership); the cached job below is stamped with the same owner
# so the owner-scoped cache path behaves exactly as before auth existed.
USER = AuthUser(id="owner-1")


# ── Fixtures / helpers ──────────────────────────────────────────────────────

@pytest.fixture
def storage(tmp_path, monkeypatch):
    """Point main's UPLOAD_DIR/OUTPUT_DIR at a temp tree and yield helpers to
    create/delete the checkpoint + output files the validators inspect."""
    up = tmp_path / "uploads"
    out = tmp_path / "outputs"
    up.mkdir()
    out.mkdir()
    monkeypatch.setattr(main, "UPLOAD_DIR", up)
    monkeypatch.setattr(main, "OUTPUT_DIR", out)

    class S:
        uploads = up
        outputs = out

        def write(self, path, content="x"):
            path.write_text(content, encoding="utf-8")
            return str(path)

        def transcript(self, exists=True):
            p = up / f"{VIDEO_ID}_audio_transcript.json"
            if exists:
                self.write(p, "{}")
            return p

        def clips_json(self, exists=True):
            p = up / f"{VIDEO_ID}_audio_clips.json"
            if exists:
                self.write(p, "{}")
            return p

        def video(self, exists=True):
            p = up / f"{VIDEO_ID}.mp4"
            if exists:
                self.write(p, "x")
            return p

        def captioned(self, exists=True):
            p = out / f"{VIDEO_ID}_clip1_bold-yellow_captioned.mp4"
            if exists:
                self.write(p, "x")
            return str(p)

    return S()


def _existing_job(captioned_path):
    return {
        "job_id": "old-job-123",
        "owner": USER.id,
        "status": "done",
        "progress": 100,
        "current_stage": "Complete",
        "video_id": VIDEO_ID,
        "error": "",
        "clips": [{
            "clip_id": f"{VIDEO_ID}_c1", "rank": 1, "why": "", "hook_text": "",
            "virality_score": 0, "engagement_type": "", "start": 0, "end": 5,
            "duration": 5, "segments": [], "raw_path": "", "vertical_path": "",
            "captioned_path": captioned_path, "thumbnail_path": None,
        }],
        "captioned_path": "", "vertical_path": "",
    }


class _FakeTask:
    def __init__(self):
        self.calls = []

    def delay(self, *args, **kwargs):
        self.calls.append((args, kwargs))


# ── _missing_artifacts ──────────────────────────────────────────────────────

def test_missing_artifacts_empty_when_all_present(storage):
    storage.transcript(exists=True)
    cap = storage.captioned(exists=True)
    assert main._missing_artifacts(VIDEO_ID, _existing_job(cap)) == []


def test_missing_artifacts_flags_deleted_clip_outputs(storage):
    storage.transcript(exists=True)
    cap = storage.captioned(exists=False)  # path recorded, file gone
    assert main._missing_artifacts(VIDEO_ID, _existing_job(cap)) == ["clip_outputs"]


def test_missing_artifacts_flags_deleted_transcript(storage):
    storage.transcript(exists=False)
    cap = storage.captioned(exists=True)
    assert main._missing_artifacts(VIDEO_ID, _existing_job(cap)) == ["transcript"]


def test_missing_artifacts_flags_empty_clip_list(storage):
    storage.transcript(exists=True)
    job = _existing_job("")
    job["clips"] = []
    assert "clips" in main._missing_artifacts(VIDEO_ID, job)


# ── _regeneration_stages — differentiated stage sets ────────────────────────

def test_all_checkpoints_present_reruns_only_local_output_stages(storage):
    storage.video(); storage.transcript(); storage.clips_json()
    assert main._regeneration_stages(VIDEO_ID) == ["cut", "crop", "caption"]


def test_missing_transcript_reruns_transcription_and_selection(storage):
    # Video + clips present, transcript gone.
    storage.video(); storage.clips_json(); storage.transcript(exists=False)
    stages = main._regeneration_stages(VIDEO_ID)
    assert "transcribe" in stages
    assert "select_clips" in stages   # fresh transcript can renumber ids
    assert "download" not in stages    # source .mp4 survives


def test_missing_clips_only_reselects_but_does_not_retranscribe(storage):
    # Video + transcript present, clip selection gone.
    storage.video(); storage.transcript(); storage.clips_json(exists=False)
    stages = main._regeneration_stages(VIDEO_ID)
    assert "select_clips" in stages
    assert "transcribe" not in stages  # transcript survives → no API credits
    assert "download" not in stages


def test_missing_transcript_vs_missing_clips_are_different_stage_sets(storage):
    storage.video()
    storage.clips_json()
    storage.transcript(exists=False)
    transcript_gone = main._regeneration_stages(VIDEO_ID)

    # Now the mirror case: transcript back, clips gone.
    storage.transcript(exists=True)
    (storage.uploads / f"{VIDEO_ID}_audio_clips.json").unlink()
    clips_gone = main._regeneration_stages(VIDEO_ID)

    assert transcript_gone != clips_gone
    assert "transcribe" in transcript_gone and "transcribe" not in clips_gone


def test_missing_source_video_reruns_download(storage):
    storage.transcript(); storage.clips_json(); storage.video(exists=False)
    stages = main._regeneration_stages(VIDEO_ID)
    assert "download" in stages


# ── Endpoint behaviour ──────────────────────────────────────────────────────

def test_cache_hit_all_present_returns_immediately_no_pipeline(storage, monkeypatch):
    storage.transcript(exists=True)
    cap = storage.captioned(exists=True)
    existing = _existing_job(cap)

    fake_pv = _FakeTask()
    deleted = []
    monkeypatch.setattr(main, "get_job_by_video_id", lambda vid, **kw: existing)
    monkeypatch.setattr(main, "process_video", fake_pv)
    monkeypatch.setattr(main, "delete_job", lambda jid: deleted.append(jid))
    # These must NOT be reached on the all-present path — make them explode if they are.
    monkeypatch.setattr(main, "_recover_from_storage",
                        lambda vid, **kw: pytest.fail("recovery must not run"))

    out = main.create_job_endpoint(JobCreate(url=YT_URL), user=USER)

    assert out.job_id == "old-job-123"       # the cached record, unchanged
    assert out.status.value == "done"
    assert fake_pv.calls == []               # no pipeline invocation
    assert deleted == []                     # stale record not touched


def test_cache_hit_missing_outputs_triggers_regeneration(storage, monkeypatch):
    # Transcript + source survive, but the captioned output file was deleted.
    storage.transcript(exists=True)
    storage.video(exists=True)
    storage.clips_json(exists=True)
    cap = storage.captioned(exists=False)
    existing = _existing_job(cap)

    fake_pv = _FakeTask()
    deleted = []
    store = {}

    def fake_create_job(job_id, url, language="te", owner="", **kwargs):
        store[job_id] = {
            "job_id": job_id, "owner": owner, "status": "pending", "progress": 0,
            "current_stage": "queued", "video_id": "", "error": "",
            "clips": [], "captioned_path": "", "vertical_path": "",
        }
        return store[job_id]

    monkeypatch.setattr(main, "get_job_by_video_id", lambda vid, **kw: existing)
    monkeypatch.setattr(main, "process_video", fake_pv)
    monkeypatch.setattr(main, "delete_job", lambda jid: deleted.append(jid))
    monkeypatch.setattr(main, "video_lock_held", lambda vid: False)
    monkeypatch.setattr(main, "create_job", fake_create_job)
    monkeypatch.setattr(main, "get_job", lambda jid: store.get(jid))
    monkeypatch.setattr(main, "update_job", lambda *a, **k: None)

    out = main.create_job_endpoint(JobCreate(url=YT_URL), user=USER)

    # A fresh regeneration job was created (not the stale one returned as-is).
    assert out.job_id != "old-job-123"
    assert out.job_id in store
    # The stale record was dropped so future scans don't re-find it.
    assert deleted == ["old-job-123"]
    # The pipeline was dispatched, reusing the source via known_video_id so
    # transcription (external credits) is skipped on the worker side.
    assert len(fake_pv.calls) == 1
    _, kwargs = fake_pv.calls[0]
    assert kwargs.get("known_video_id") == VIDEO_ID


def test_cache_hit_missing_transcript_still_regenerates(storage, monkeypatch):
    # Even the expensive checkpoint gone: must still regenerate, not 404 forever.
    storage.transcript(exists=False)
    cap = storage.captioned(exists=True)
    existing = _existing_job(cap)

    fake_pv = _FakeTask()
    store = {}
    monkeypatch.setattr(main, "get_job_by_video_id", lambda vid, **kw: existing)
    monkeypatch.setattr(main, "process_video", fake_pv)
    monkeypatch.setattr(main, "delete_job", lambda jid: None)
    monkeypatch.setattr(main, "video_lock_held", lambda vid: False)
    monkeypatch.setattr(main, "create_job",
                        lambda job_id, url, language="te", owner="", **kwargs: store.setdefault(
                            job_id, {"job_id": job_id, "owner": owner, "status": "pending",
                                     "progress": 0,
                                     "current_stage": "queued", "video_id": "", "error": "",
                                     "clips": [], "captioned_path": "", "vertical_path": ""}))
    monkeypatch.setattr(main, "get_job", lambda jid: store.get(jid))
    monkeypatch.setattr(main, "update_job", lambda *a, **k: None)

    out = main.create_job_endpoint(JobCreate(url=YT_URL), user=USER)
    assert out.job_id != "old-job-123"
    assert len(fake_pv.calls) == 1


# ── Worker checkpoint reuse (the credit-saving guarantee) ───────────────────

def _wire_pipeline(tmp_path, monkeypatch, vid, *, video, transcript, clips_json):
    """Set worker dirs to a temp tree, create the requested surviving
    checkpoints, and stub every pipeline stage to just count invocations."""
    # process_video imports services.video_downloader (→ yt_dlp) at runtime;
    # skip cleanly where that heavy dep isn't installed (same spirit as the
    # ffmpeg skips), so the checkpoint logic still runs in CI/prod where it is.
    pytest.importorskip("yt_dlp")
    import api.worker as worker
    up = tmp_path / "uploads"
    out = tmp_path / "outputs"
    up.mkdir()
    out.mkdir()
    monkeypatch.setattr(worker, "UPLOAD_DIR", up)
    monkeypatch.setattr(worker, "OUTPUT_DIR", out)

    if video:
        (up / f"{vid}.mp4").write_text("x", encoding="utf-8")
        (up / f"{vid}_audio.wav").write_text("x", encoding="utf-8")
    if transcript:
        (up / f"{vid}_audio_transcript.json").write_text('{"sentences": []}', encoding="utf-8")
    if clips_json:
        (up / f"{vid}_audio_clips.json").write_text('{"clips": [{"clip_id": "c1"}]}', encoding="utf-8")

    called = {"download": 0, "transcribe": 0, "select": 0, "cut": 0, "crop": 0, "caption": 0}

    def _dl(url):
        called["download"] += 1
        return {"video_id": vid, "video_path": str(up / f"{vid}.mp4"),
                "audio_path": str(up / f"{vid}_audio.wav")}

    monkeypatch.setattr("services.video_downloader.download_youtube", _dl)
    monkeypatch.setattr("services.transcriber.transcribe_audio",
                        lambda a, language="te": called.__setitem__("transcribe", called["transcribe"] + 1) or {})
    monkeypatch.setattr("services.transcriber.save_transcript", lambda t, p: None)
    monkeypatch.setattr("services.clip_selector.select_clips",
                        lambda p: called.__setitem__("select", called["select"] + 1))
    monkeypatch.setattr("services.video_cutter.cut_all_clips",
                        lambda *a, **k: called.__setitem__("cut", called["cut"] + 1))
    monkeypatch.setattr("services.vertical_cropper.crop_all_clips",
                        lambda *a, **k: called.__setitem__("crop", called["crop"] + 1))
    monkeypatch.setattr("services.caption_renderer.render_all_captions",
                        lambda **k: called.__setitem__("caption", called["caption"] + 1))

    monkeypatch.setattr(worker, "update_job", lambda *a, **k: None)
    monkeypatch.setattr(worker, "set_job_clips", lambda *a, **k: None)
    monkeypatch.setattr(worker, "get_job", lambda jid: {})
    # Per-video pipeline lock (FIX SPRINT 1): no Redis here — stub it held-free.
    monkeypatch.setattr(worker, "acquire_video_lock", lambda vid, tok, ttl=None: True)
    monkeypatch.setattr(worker, "release_video_lock", lambda vid, tok: None)
    return worker, called


def test_worker_reuses_all_checkpoints_when_only_outputs_missing(tmp_path, monkeypatch):
    vid = "vidABC"
    worker, called = _wire_pipeline(tmp_path, monkeypatch, vid,
                                    video=True, transcript=True, clips_json=True)

    worker.process_video("job1", f"https://youtu.be/{vid}", "te", known_video_id=vid)

    # The whole point: no external-cost stage re-runs when its output survives.
    assert called["download"] == 0    # source .mp4 reused
    assert called["transcribe"] == 0  # transcript reused — no API credits
    assert called["select"] == 0      # clip selection reused — no Gemini call
    # Only the local ffmpeg output stages regenerate the missing clips.
    assert called["cut"] == 1 and called["crop"] == 1 and called["caption"] == 1


def test_worker_retranscribes_and_reselects_when_transcript_gone(tmp_path, monkeypatch):
    vid = "vidDEF"
    worker, called = _wire_pipeline(tmp_path, monkeypatch, vid,
                                    video=True, transcript=False, clips_json=True)

    worker.process_video("job2", f"https://youtu.be/{vid}", "te", known_video_id=vid)

    assert called["download"] == 0     # source still reused
    assert called["transcribe"] == 1   # transcript gone → must re-transcribe
    assert called["select"] == 1       # …which invalidates the old clip selection
    assert called["cut"] == 1 and called["crop"] == 1 and called["caption"] == 1
