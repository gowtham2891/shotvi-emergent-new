"""
SPRINT 3 gate — user image overlays: upload endpoint + id resolution.

What must hold:
  1. POST /jobs/{id}/overlay-images requires auth; strangers get the same
     404 as every job route (existence never leaks).
  2. Upload validation: bytes are sniffed with PIL (declared content type is
     never trusted) — real PNG/JPEG in; text/GIF/empty → 422; oversized →
     413. The stored file is {video_id}_useroverlay_{8 hex}.{png|jpg} in
     outputs, so the existing static mount serves it and the _useroverlay
     cleanup marker protects it.
  3. valid_overlay_image_id pins ids to the rendering job's own video_id:
     no traversal, no cross-video (= cross-user) references, no paths.
  4. resolve_image_overlays: IDENTITY (same object) when no image elements —
     the pre-existing payload path stays byte-identical; invalid/missing ids
     are dropped, valid ones get props._resolved_path injected.
  5. The rerender endpoint 422s a payload whose image element references an
     image that was not minted for that job's video.
"""

import io
import json
import os
import sys
import time

import pytest
import jwt as pyjwt
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import api.auth as auth
import api.database as database
import api.main as main
from services.overlay_renderer import valid_overlay_image_id, resolve_image_overlays

SECRET = "test-jwt-secret-0123456789abcdef0123456789abcdef"
ALICE = "11111111-aaaa-4aaa-8aaa-111111111111"
BOB = "22222222-bbbb-4bbb-8bbb-222222222222"
VIDEO_ID = "vid12345"


def make_token(sub=ALICE, secret=SECRET, aud="authenticated"):
    now = int(time.time())
    return pyjwt.encode(
        {"sub": sub, "aud": aud, "email": f"{sub[:4]}@example.com", "iat": now, "exp": now + 3600},
        secret, algorithm="HS256",
    )


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


class _FakeRedis:
    def __init__(self):
        self.h = {}
        self.kv = {}

    def hgetall(self, key):
        return dict(self.h.get(key, {}))

    def hget(self, key, field):
        return self.h.get(key, {}).get(field)

    def hset(self, key, field=None, value=None, mapping=None, **kw):
        d = self.h.setdefault(key, {})
        if field is not None:
            d[field] = str(value)
        if mapping:
            d.update({k: str(v) for k, v in mapping.items()})
        if kw:
            d.update({k: str(v) for k, v in kw.items()})

    def hdel(self, key, field):
        return 1 if self.h.get(key, {}).pop(field, None) is not None else 0

    def expire(self, key, ttl):
        pass

    def set(self, key, val, ex=None, nx=False):
        if nx and key in self.kv:
            return None
        self.kv[key] = str(val)
        return True

    def get(self, key):
        return self.kv.get(key)

    def delete(self, key):
        return 1 if self.kv.pop(key, None) is not None else 0


def png_bytes(size=(64, 40), color=(255, 0, 0, 255)):
    buf = io.BytesIO()
    Image.new("RGBA", size, color).save(buf, format="PNG")
    return buf.getvalue()


def jpeg_bytes(size=(64, 40)):
    buf = io.BytesIO()
    Image.new("RGB", size, (0, 128, 255)).save(buf, format="JPEG")
    return buf.getvalue()


def gif_bytes():
    buf = io.BytesIO()
    Image.new("P", (8, 8)).save(buf, format="GIF")
    return buf.getvalue()


@pytest.fixture
def client(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    monkeypatch.setattr(auth, "SUPABASE_JWT_SECRET", SECRET)
    monkeypatch.setattr(auth, "SUPABASE_URL", "")
    monkeypatch.setattr(auth, "DEV_MODE", False)

    fake = _FakeRedis()
    monkeypatch.setattr(database, "get_redis", lambda: fake)

    # Overlay images land in a temp outputs dir, not the repo's storage/.
    monkeypatch.setattr(main, "OUTPUT_DIR", tmp_path)

    c = TestClient(main.app)
    c._tmp_outputs = tmp_path
    return c


def make_job(owner=ALICE, video_id=VIDEO_ID, job_id="job-img-1"):
    database.create_job(job_id, url="https://youtu.be/x", language="te", owner=owner)
    database.update_job(job_id, video_id=video_id,
                        clips=[{"clip_id": f"{video_id}_c1", "start": 0, "end": 10}])
    return job_id


# ── 1-2. Upload endpoint ──────────────────────────────────────

def test_upload_requires_auth(client):
    make_job()
    r = client.post("/jobs/job-img-1/overlay-images",
                    files={"file": ("a.png", png_bytes(), "image/png")})
    assert r.status_code == 401


def test_stranger_gets_404_not_403(client):
    make_job(owner=ALICE)
    r = client.post("/jobs/job-img-1/overlay-images",
                    files={"file": ("a.png", png_bytes(), "image/png")},
                    headers=bearer(make_token(sub=BOB)))
    assert r.status_code == 404


def test_valid_png_uploads_and_is_stored_under_video_id(client):
    make_job()
    r = client.post("/jobs/job-img-1/overlay-images",
                    files={"file": ("logo.png", png_bytes(), "image/png")},
                    headers=bearer(make_token()))
    assert r.status_code == 200
    image_id = r.json()["image_id"]
    assert valid_overlay_image_id(image_id, VIDEO_ID)
    assert image_id.endswith(".png")
    stored = client._tmp_outputs / image_id
    assert stored.exists()
    Image.open(stored).verify()  # round-trips as a real image


def test_valid_jpeg_uploads_with_jpg_extension(client):
    make_job()
    r = client.post("/jobs/job-img-1/overlay-images",
                    files={"file": ("photo.jpg", jpeg_bytes(), "image/jpeg")},
                    headers=bearer(make_token()))
    assert r.status_code == 200
    assert r.json()["image_id"].endswith(".jpg")


def test_content_type_is_not_trusted_bytes_are(client):
    make_job()
    # Text bytes wearing an image/png content type → 422.
    r = client.post("/jobs/job-img-1/overlay-images",
                    files={"file": ("fake.png", b"#!/bin/sh\necho pwned", "image/png")},
                    headers=bearer(make_token()))
    assert r.status_code == 422


def test_non_png_jpeg_formats_rejected(client):
    make_job()
    r = client.post("/jobs/job-img-1/overlay-images",
                    files={"file": ("anim.gif", gif_bytes(), "image/gif")},
                    headers=bearer(make_token()))
    assert r.status_code == 422


def test_empty_file_rejected(client):
    make_job()
    r = client.post("/jobs/job-img-1/overlay-images",
                    files={"file": ("empty.png", b"", "image/png")},
                    headers=bearer(make_token()))
    assert r.status_code == 422


def test_oversized_image_rejected(client, monkeypatch):
    make_job()
    monkeypatch.setattr(main, "_OVERLAY_IMAGE_MAX_BYTES", 100)
    r = client.post("/jobs/job-img-1/overlay-images",
                    files={"file": ("big.png", png_bytes(size=(500, 500)), "image/png")},
                    headers=bearer(make_token()))
    assert r.status_code == 413


def test_job_without_video_id_rejected(client):
    database.create_job("job-novid", url="https://youtu.be/x", language="te", owner=ALICE)
    r = client.post("/jobs/job-novid/overlay-images",
                    files={"file": ("a.png", png_bytes(), "image/png")},
                    headers=bearer(make_token()))
    assert r.status_code == 400


# ── 3. Image id validation ────────────────────────────────────

def test_valid_overlay_image_id_accepts_only_this_videos_ids():
    good = f"{VIDEO_ID}_useroverlay_deadbeef.png"
    assert valid_overlay_image_id(good, VIDEO_ID)
    assert valid_overlay_image_id(f"{VIDEO_ID}_useroverlay_01234567.jpg", VIDEO_ID)

    # Cross-video (= potentially cross-user) reference.
    assert not valid_overlay_image_id("othervid_useroverlay_deadbeef.png", VIDEO_ID)
    # Traversal / path smuggling.
    assert not valid_overlay_image_id(f"../{VIDEO_ID}_useroverlay_deadbeef.png", VIDEO_ID)
    assert not valid_overlay_image_id(f"{VIDEO_ID}_useroverlay_deadbeef.png/../../x", VIDEO_ID)
    assert not valid_overlay_image_id("..\\secret.png", VIDEO_ID)
    # Malformed shapes.
    assert not valid_overlay_image_id(f"{VIDEO_ID}_useroverlay_zzzzzzzz.png", VIDEO_ID)
    assert not valid_overlay_image_id(f"{VIDEO_ID}_useroverlay_dead.png", VIDEO_ID)
    assert not valid_overlay_image_id(f"{VIDEO_ID}_useroverlay_deadbeef.gif", VIDEO_ID)
    assert not valid_overlay_image_id(None, VIDEO_ID)
    assert not valid_overlay_image_id(123, VIDEO_ID)
    assert not valid_overlay_image_id(good, "")


# ── 4. resolve_image_overlays ─────────────────────────────────

def test_resolver_is_identity_when_no_image_elements():
    for elements in (None, [], [{"type": "logo", "props": {}}]):
        assert resolve_image_overlays(elements, VIDEO_ID, "/nowhere") is elements


def test_resolver_injects_path_for_valid_existing_image(tmp_path):
    image_id = f"{VIDEO_ID}_useroverlay_deadbeef.png"
    (tmp_path / image_id).write_bytes(png_bytes())
    elements = [
        {"type": "logo", "props": {"text": "@x"}},
        {"id": "el_image_1", "type": "image", "props": {"image_id": image_id, "height": 0.2}},
    ]
    out = resolve_image_overlays(elements, VIDEO_ID, str(tmp_path))
    assert len(out) == 2
    assert out[0] is elements[0]  # non-image untouched
    assert out[1]["props"]["_resolved_path"] == os.path.join(str(tmp_path), image_id)
    # Input list is not mutated (worker safety).
    assert "_resolved_path" not in elements[1]["props"]


def test_resolver_drops_foreign_traversal_and_missing_ids(tmp_path):
    elements = [
        {"id": "a", "type": "image", "props": {"image_id": "othervid_useroverlay_deadbeef.png"}},
        {"id": "b", "type": "image", "props": {"image_id": f"../{VIDEO_ID}_useroverlay_deadbeef.png"}},
        {"id": "c", "type": "image", "props": {"image_id": f"{VIDEO_ID}_useroverlay_deadbeef.png"}},  # valid but missing on disk
        {"id": "d", "type": "image", "props": {}},
    ]
    out = resolve_image_overlays(elements, VIDEO_ID, str(tmp_path))
    assert out == []


# ── 5. Rerender boundary ──────────────────────────────────────

def _rerender(client, elements, job_id="job-img-1"):
    return client.post(
        f"/jobs/{job_id}/clips/0/rerender",
        json={"style": "bold-yellow", "format": "9:16", "elements": elements},
        headers=bearer(make_token()),
    )


def test_rerender_rejects_foreign_image_reference(client, monkeypatch):
    make_job()
    monkeypatch.setattr(main.rerender_clip, "delay", lambda **kw: None)
    r = _rerender(client, [
        {"type": "image", "props": {"image_id": "othervid_useroverlay_deadbeef.png"}},
    ])
    assert r.status_code == 422


def test_rerender_accepts_own_image_reference(client, monkeypatch):
    make_job()
    calls = {}
    monkeypatch.setattr(main.rerender_clip, "delay", lambda **kw: calls.update(kw))
    r = _rerender(client, [
        {"type": "image", "props": {"image_id": f"{VIDEO_ID}_useroverlay_deadbeef.png"}},
    ])
    assert r.status_code == 200
    assert calls["elements"][0]["props"]["image_id"] == f"{VIDEO_ID}_useroverlay_deadbeef.png"


def test_rerender_without_elements_is_unaffected(client, monkeypatch):
    make_job()
    called = {}
    monkeypatch.setattr(main.rerender_clip, "delay", lambda **kw: called.update(kw))
    r = client.post("/jobs/job-img-1/clips/0/rerender",
                    json={"style": "bold-yellow", "format": "9:16"},
                    headers=bearer(make_token()))
    assert r.status_code == 200
    assert called["elements"] is None
