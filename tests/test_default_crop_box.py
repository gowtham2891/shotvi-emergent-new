"""
Sprint 4 — 16:9-master source of truth + per-aspect crop window.

Backend halves under test:

1. The vertical cropper now RETURNS the crop it computes as a fractional
   window over the source frame and persists it as a *_vertical.cropbox.json
   sidecar, which the worker adopts onto the clip record as default_crop_box
   (surfaced on ClipOut).

2. select_rerender_source — THE byte-identical gate's backend half. An
   untouched-crop 9:16 export payload (crop_mode='auto', no crop_box —
   exactly the pre-sprint wire shape) must keep reading the pre-baked
   vertical_path; a manual crop window reads the 16:9 master (raw_path).
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.pipeline_stubs import wire_pipeline


# ── select_rerender_source — byte-identical source pin ──────────────────────

CLIP = {
    "raw_path": "storage/outputs/vid_clip1_t.mp4",
    "vertical_path": "storage/outputs/vid_clip1_t_vertical.mp4",
}


def test_untouched_default_payload_selects_the_prebaked_vertical():
    """THE BYTE-IDENTICAL GATE (backend half): the untouched-crop 9:16 export
    payload carries crop_mode='auto' and no crop_box — exactly what the
    frontend sent before this sprint — and must resolve to the SAME
    pre-baked vertical_path the pre-sprint code returned, so the burn chain
    and its output bytes are unchanged."""
    from api.worker import select_rerender_source
    assert select_rerender_source(CLIP, True, "auto", None) == CLIP["vertical_path"]


def test_manual_crop_window_selects_the_16_9_master():
    from api.worker import select_rerender_source
    box = {"x": 0.1, "y": 0.0, "w": 0.5625, "h": 1.0}
    assert select_rerender_source(CLIP, True, "manual", box) == CLIP["raw_path"]
    # use_autocrop cannot override a manual window back onto the vertical.
    assert select_rerender_source(CLIP, False, "manual", box) == CLIP["raw_path"]


def test_manual_without_a_box_behaves_like_before():
    """crop_mode='manual' with no crop_box was already possible on the old
    wire format; it never cropped, and source selection must not change."""
    from api.worker import select_rerender_source
    assert select_rerender_source(CLIP, True, "manual", None) == CLIP["vertical_path"]
    assert select_rerender_source(CLIP, False, "manual", None) == CLIP["raw_path"]


def test_legacy_record_without_raw_falls_back_to_vertical():
    from api.worker import select_rerender_source
    legacy = {"raw_path": "", "vertical_path": CLIP["vertical_path"]}
    box = {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
    assert select_rerender_source(legacy, True, "manual", box) == CLIP["vertical_path"]


def test_use_autocrop_false_still_selects_raw():
    from api.worker import select_rerender_source
    assert select_rerender_source(CLIP, False, "auto", None) == CLIP["raw_path"]


# ── read_default_crop_box — sidecar adoption ────────────────────────────────

def test_read_default_crop_box_reads_the_sidecar(tmp_path):
    from api.worker import read_default_crop_box
    box = {"x": 0.25, "y": 0.0, "w": 0.5625, "h": 1.0}
    (tmp_path / "vid_clip2_slug_vertical.cropbox.json").write_text(
        json.dumps(box), encoding="utf-8")
    assert read_default_crop_box(tmp_path, "vid", 2) == box


def test_read_default_crop_box_missing_or_malformed_is_none(tmp_path):
    from api.worker import read_default_crop_box
    assert read_default_crop_box(tmp_path, "vid", 1) is None          # no sidecar
    (tmp_path / "vid_clip1_s_vertical.cropbox.json").write_text(
        "not json", encoding="utf-8")
    assert read_default_crop_box(tmp_path, "vid", 1) is None          # junk content
    (tmp_path / "vid_clip3_s_vertical.cropbox.json").write_text(
        json.dumps({"x": 0.1}), encoding="utf-8")
    assert read_default_crop_box(tmp_path, "vid", 3) is None          # missing keys


def test_read_default_crop_box_does_not_leak_across_clip_numbers(tmp_path):
    from api.worker import read_default_crop_box
    (tmp_path / "vid_clip1_s_vertical.cropbox.json").write_text(
        json.dumps({"x": 0.1, "y": 0.0, "w": 0.5, "h": 1.0}), encoding="utf-8")
    # clip1's sidecar must not satisfy clip1X's glob or vice versa
    assert read_default_crop_box(tmp_path, "vid", 2) is None


# ── vertical_cropper returns + persists the crop window ─────────────────────

def _import_cropper():
    pytest.importorskip("cv2")
    pytest.importorskip("numpy")
    from services import vertical_cropper
    return vertical_cropper


def test_crop_to_vertical_returns_the_fractional_window(monkeypatch, tmp_path):
    vc = _import_cropper()
    monkeypatch.setattr(vc, "get_video_dimensions", lambda p: (1920, 1080))
    monkeypatch.setattr(vc, "sample_frames", lambda p, num_frames=8: [])
    monkeypatch.setattr(vc, "detect_faces", lambda frames: [])

    class _OK:
        returncode = 0
        stderr = ""
    monkeypatch.setattr(vc.subprocess, "run", lambda *a, **k: _OK())

    box = vc.crop_to_vertical("in.mp4", str(tmp_path / "out.mp4"))
    # Centre crop on a 1920x1080 source: crop_width = int(1080·0.5625) = 607,
    # crop_x = (1920-607)//2 = 656 — the exact framing baked into the
    # vertical, expressed as fractions of the master.
    assert box == {"x": 656 / 1920, "y": 0.0, "w": 607 / 1920, "h": 1.0}


def test_crop_to_vertical_face_crop_window_matches_the_baked_crop(monkeypatch, tmp_path):
    vc = _import_cropper()
    monkeypatch.setattr(vc, "get_video_dimensions", lambda p: (1920, 1080))
    monkeypatch.setattr(vc, "sample_frames", lambda p, num_frames=8: ["f"])
    monkeypatch.setattr(vc, "detect_faces", lambda frames: [1500])  # face right of centre

    captured = {}

    class _OK:
        returncode = 0
        stderr = ""

    def _run(cmd, **k):
        captured["cmd"] = cmd
        return _OK()
    monkeypatch.setattr(vc.subprocess, "run", _run)

    box = vc.crop_to_vertical("in.mp4", str(tmp_path / "out.mp4"))
    # calculate_crop_x: crop_x = 1500 - 607//2 = 1197, clamped to 1920-607=1313 → 1197
    assert box == {"x": 1197 / 1920, "y": 0.0, "w": 607 / 1920, "h": 1.0}
    # The window IS the baked crop: the ffmpeg filter carries the same pixels.
    vf = captured["cmd"][captured["cmd"].index("-vf") + 1]
    assert "crop=607:1080:1197:0" in vf


def test_crop_to_vertical_already_vertical_returns_full_frame(monkeypatch, tmp_path):
    vc = _import_cropper()
    src = tmp_path / "in.mp4"
    src.write_text("x", encoding="utf-8")
    monkeypatch.setattr(vc, "get_video_dimensions", lambda p: (720, 1280))
    box = vc.crop_to_vertical(str(src), str(tmp_path / "out.mp4"))
    assert box == {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}


def test_crop_to_vertical_failure_returns_none(monkeypatch, tmp_path):
    vc = _import_cropper()
    monkeypatch.setattr(vc, "get_video_dimensions", lambda p: (1920, 1080))
    monkeypatch.setattr(vc, "sample_frames", lambda p, num_frames=8: [])
    monkeypatch.setattr(vc, "detect_faces", lambda frames: [])

    class _Fail:
        returncode = 1
        stderr = "boom"
    monkeypatch.setattr(vc.subprocess, "run", lambda *a, **k: _Fail())
    assert vc.crop_to_vertical("in.mp4", str(tmp_path / "out.mp4")) is None


def test_crop_all_clips_writes_the_sidecar(monkeypatch, tmp_path):
    vc = _import_cropper()
    (tmp_path / "vid_clip1_slug.mp4").write_text("x", encoding="utf-8")
    box = {"x": 0.2, "y": 0.0, "w": 0.5, "h": 1.0}

    def _fake_crop(input_path, output_path, use_blur_bg=False):
        Path(output_path).write_text("v", encoding="utf-8")
        return dict(box)
    monkeypatch.setattr(vc, "crop_to_vertical", _fake_crop)

    results = vc.crop_all_clips(str(tmp_path), video_id="vid")
    assert len(results) == 1
    sidecar = tmp_path / "vid_clip1_slug_vertical.cropbox.json"
    assert json.loads(sidecar.read_text(encoding="utf-8")) == box


def test_crop_all_clips_skips_sidecars_and_derived_outputs_as_inputs(monkeypatch, tmp_path):
    vc = _import_cropper()
    (tmp_path / "vid_clip1_s.mp4").write_text("x", encoding="utf-8")
    (tmp_path / "vid_clip1_s_vertical.mp4").write_text("x", encoding="utf-8")
    (tmp_path / "vid_clip1_s_vertical.cropbox.json").write_text("{}", encoding="utf-8")
    seen = []

    def _fake_crop(input_path, output_path, use_blur_bg=False):
        seen.append(Path(input_path).name)
        Path(output_path).write_text("v", encoding="utf-8")
        return {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
    monkeypatch.setattr(vc, "crop_to_vertical", _fake_crop)

    vc.crop_all_clips(str(tmp_path), video_id="vid")
    assert seen == ["vid_clip1_s.mp4"]


# ── process_video adopts the sidecar onto the clip record ───────────────────

VID = "dQw4w9WgXcQ"
YT = f"https://www.youtube.com/watch?v={VID}"


def test_process_video_adopts_default_crop_box(tmp_path, monkeypatch):
    worker, called, locks, updates = wire_pipeline(tmp_path, monkeypatch, VID)
    out = tmp_path / "outputs"
    box = {"x": 0.25, "y": 0.0, "w": 0.5625, "h": 1.0}

    # The stage stubs produce this run's artifacts (creating them up front
    # wouldn't survive the cutting stage's scoped cleanup).
    def _cut(clips_path, video_path, output_dir):
        (out / f"{VID}_clip1_t.mp4").write_text("x", encoding="utf-8")
    sys.modules["services.video_cutter"].cut_all_clips = _cut

    def _crop(input_dir, output_dir=None, video_id=None):
        (out / f"{VID}_clip1_t_vertical.mp4").write_text("x", encoding="utf-8")
        (out / f"{VID}_clip1_t_vertical.cropbox.json").write_text(
            json.dumps(box), encoding="utf-8")
        return [str(out / f"{VID}_clip1_t_vertical.mp4")]
    sys.modules["services.vertical_cropper"].crop_all_clips = _crop

    def _cap(**k):
        (out / f"{VID}_clip1_t_bold-yellow_captioned.mp4").write_text("x", encoding="utf-8")
    sys.modules["services.caption_renderer"].render_all_captions = _cap

    captured = {}
    monkeypatch.setattr(worker, "set_job_clips",
                        lambda jid, clips: captured.setdefault("clips", clips))

    worker.process_video("job-cropbox", YT, "te")

    clips = captured["clips"]
    assert len(clips) == 1
    assert clips[0]["default_crop_box"] == box
    # And the existing paths still resolve alongside it.
    assert clips[0]["vertical_path"].endswith("_vertical.mp4")
    assert clips[0]["raw_path"].endswith("_clip1_t.mp4")


def test_process_video_without_sidecar_records_none(tmp_path, monkeypatch):
    worker, called, locks, updates = wire_pipeline(tmp_path, monkeypatch, VID)
    out = tmp_path / "outputs"

    def _cut(clips_path, video_path, output_dir):
        (out / f"{VID}_clip1_t.mp4").write_text("x", encoding="utf-8")
    sys.modules["services.video_cutter"].cut_all_clips = _cut

    captured = {}
    monkeypatch.setattr(worker, "set_job_clips",
                        lambda jid, clips: captured.setdefault("clips", clips))

    worker.process_video("job-nosidecar", YT, "te")
    assert captured["clips"][0]["default_crop_box"] is None
