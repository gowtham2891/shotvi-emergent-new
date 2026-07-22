"""
Shared worker-pipeline test harness (FIX SPRINT 1).

wire_pipeline() points the worker at a temp storage tree with surviving
checkpoints and stubs every pipeline stage to count invocations. The stage
modules are injected as monkeypatch-scoped stub modules in sys.modules, so
these tests run even where the heavy service deps (yt_dlp, cv2, …) aren't
installed — the worker imports the stage functions lazily by name, and the
stubs are all it ever sees. monkeypatch reverts sys.modules afterwards, so
other tests (e.g. test_stale_cache's importorskip guards) are unaffected.
"""

import sys
import json
import types


def _stub_module(monkeypatch, name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    monkeypatch.setitem(sys.modules, name, mod)
    return mod


def wire_pipeline(tmp_path, monkeypatch, vid, *, video=True, transcript=True,
                  clips_json=True, clips=None):
    """Temp storage tree + fully stubbed pipeline stages. Returns
    (worker, called, locks, updates): stage-call counters (crop records its
    kwargs), lock acquire/release recorder, update_job call recorder."""
    import api.worker as worker

    up = tmp_path / "uploads"
    out = tmp_path / "outputs"
    up.mkdir(exist_ok=True)
    out.mkdir(exist_ok=True)
    monkeypatch.setattr(worker, "UPLOAD_DIR", up)
    monkeypatch.setattr(worker, "OUTPUT_DIR", out)

    if video:
        (up / f"{vid}.mp4").write_text("x", encoding="utf-8")
        (up / f"{vid}_audio.wav").write_text("x", encoding="utf-8")
    if transcript:
        (up / f"{vid}_audio_transcript.json").write_text('{"sentences": []}', encoding="utf-8")
    if clips_json:
        payload = {"clips": clips if clips is not None else [{"clip_id": "c1"}]}
        (up / f"{vid}_audio_clips.json").write_text(json.dumps(payload), encoding="utf-8")

    called = {"download": 0, "upload": 0, "transcribe": 0, "select": 0,
              "cut": 0, "crop": 0, "caption": 0, "crop_kwargs": None}

    def _dl(url):
        called["download"] += 1
        return {"video_id": vid, "video_path": str(up / f"{vid}.mp4"),
                "audio_path": str(up / f"{vid}_audio.wav")}

    def _up(path, filename="upload"):
        called["upload"] += 1
        return {"video_id": filename, "video_path": path,
                "audio_path": str(up / f"{filename}_audio.wav")}

    def _crop(input_dir, output_dir=None, video_id=None):
        called["crop"] += 1
        called["crop_kwargs"] = {"video_id": video_id}
        return []

    _stub_module(monkeypatch, "services.video_downloader",
                 download_youtube=_dl, handle_upload=_up,
                 extract_audio=lambda v, a: None)
    _stub_module(monkeypatch, "services.transcriber",
                 transcribe_audio=lambda a, language="te": called.__setitem__(
                     "transcribe", called["transcribe"] + 1) or {},
                 save_transcript=lambda t, p: None)
    _stub_module(monkeypatch, "services.clip_selector",
                 select_clips=lambda p: called.__setitem__("select", called["select"] + 1))
    _stub_module(monkeypatch, "services.video_cutter",
                 cut_all_clips=lambda *a, **k: called.__setitem__("cut", called["cut"] + 1))
    _stub_module(monkeypatch, "services.vertical_cropper", crop_all_clips=_crop)
    _stub_module(monkeypatch, "services.caption_renderer",
                 render_all_captions=lambda **k: called.__setitem__(
                     "caption", called["caption"] + 1))

    monkeypatch.setattr(worker, "set_job_clips", lambda *a, **k: None)
    monkeypatch.setattr(worker, "get_job", lambda jid: {})

    updates = []
    monkeypatch.setattr(worker, "update_job",
                        lambda jid, **kw: updates.append((jid, kw)))

    locks = {"acquired": [], "released": [], "grant": True}
    monkeypatch.setattr(worker, "acquire_video_lock",
                        lambda v, tok, ttl=None: locks["acquired"].append((v, tok)) or locks["grant"])
    monkeypatch.setattr(worker, "release_video_lock",
                        lambda v, tok: locks["released"].append((v, tok)))

    return worker, called, locks, updates
