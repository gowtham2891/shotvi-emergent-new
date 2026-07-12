"""
BUG-002 regression gate — /clips/download must be confined to OUTPUT_DIR.

Historically the endpoint took a user-controlled `path` query param and passed
it straight to FileResponse, letting an unauthenticated caller read any file
on the container. Post-fix, the endpoint must:

  1. Serve a legitimate file inside OUTPUT_DIR (200)
  2. Reject a `..` traversal attempt (403)
  3. Reject an absolute path escape (e.g. /app/.env) (403)
  4. Reject a symlink whose target is outside OUTPUT_DIR (403)
  5. Return 404 (not 403) for a non-existent path INSIDE OUTPUT_DIR
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Spin the FastAPI app up with OUTPUT_DIR pointing at a tmp dir so we can
    plant a legit file (in) and an off-limits file (out) around it, all
    without touching the real storage/outputs tree."""
    from fastapi.testclient import TestClient

    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "legit.mp4").write_bytes(b"fake mp4 bytes")

    off_limits = tmp_path / "secret.env"
    off_limits.write_text("SECRET=verboten\n", encoding="utf-8")

    # symlink escape: symlink INSIDE outputs pointing OUT of outputs
    escape_link = outputs / "escape.mp4"
    try:
        escape_link.symlink_to(off_limits)
        symlink_available = True
    except (OSError, NotImplementedError):
        symlink_available = False

    from api import main as api_main
    monkeypatch.setattr(api_main, "OUTPUT_DIR", outputs)

    yield TestClient(api_main.app), outputs, off_limits, escape_link, symlink_available


def test_legit_clip_inside_outputs_downloads_200(client):
    tc, outputs, _, _, _ = client
    r = tc.get("/clips/download", params={"path": str(outputs / "legit.mp4")})
    assert r.status_code == 200
    assert r.content == b"fake mp4 bytes"
    assert r.headers["content-type"].startswith("video/mp4")


def test_dotdot_traversal_is_403(client, tmp_path):
    tc, outputs, off_limits, _, _ = client
    # relative traversal from inside outputs pointing back up
    escaped = outputs / ".." / "secret.env"
    r = tc.get("/clips/download", params={"path": str(escaped)})
    assert r.status_code == 403
    assert "outside" in r.json()["detail"].lower()


def test_absolute_path_escape_is_403(client):
    tc, _, off_limits, _, _ = client
    # tmp secret is outside OUTPUT_DIR — should be rejected even by absolute path
    r = tc.get("/clips/download", params={"path": str(off_limits)})
    assert r.status_code == 403


def test_wellknown_secret_target_is_403(client):
    """Sanity: hitting a plausible high-value target like /app/.env or /etc/passwd
    must be rejected even though the file may exist on the host."""
    tc, *_ = client
    for target in ("/app/.env", "/etc/passwd", "/etc/hosts"):
        r = tc.get("/clips/download", params={"path": target})
        assert r.status_code == 403, f"{target}: expected 403, got {r.status_code}"


def test_symlink_escape_from_inside_outputs_is_403(client):
    tc, outputs, off_limits, escape_link, symlink_available = client
    if not symlink_available:
        pytest.skip("symlinks not supported on this filesystem")
    # The symlink itself lives INSIDE outputs, so a naive containment check
    # (string-prefix on the input path) would pass. The fix uses resolve(),
    # which follows the symlink — the resolved target is off_limits, outside
    # outputs, so this must be rejected.
    r = tc.get("/clips/download", params={"path": str(escape_link)})
    assert r.status_code == 403


def test_missing_file_inside_outputs_is_404_not_403(client):
    tc, outputs, *_ = client
    r = tc.get("/clips/download", params={"path": str(outputs / "does_not_exist.mp4")})
    assert r.status_code == 404


def test_invalid_path_string_is_400(client):
    """A null-byte or otherwise pathologically-invalid path resolves to an
    error we surface as 400 rather than a 500 stack trace."""
    tc, *_ = client
    r = tc.get("/clips/download", params={"path": "\x00"})
    assert r.status_code in (400, 403)  # OS may raise before or during resolve
