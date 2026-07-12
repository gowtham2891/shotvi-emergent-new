"""
BUG-007 regression gate — bg_color validation at the API boundary.

Historically the worker stripped `#` from the hex value and passed a bare
`rrggbb` into FFmpeg's `pad=...:color=...` filter string, which FFmpeg
interpreted as an unknown named color and rejected — so custom-color exports
failed silently. It also concatenated the user's string directly, allowing
filter-token injection ("black:c=x,anullsrc" etc). Post-fix:

  1. #RRGGBB (upper- and lower-case) validates and is passed to FFmpeg with
     the `0x` prefix so it parses as a color.
  2. Missing `#`, wrong length, and injection strings are rejected at the API
     boundary with a 422 (pydantic ValidationError).
  3. The endpoint never emits a bare `rrggbb` into the filtergraph.
"""

import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api.models import RerenderRequest
from pydantic import ValidationError


# ── API-boundary validation ────────────────────────────────────────────────

@pytest.mark.parametrize("valid", [
    "#000000", "#FFFFFF", "#7c3aed", "#7C3AED", "#Ff00Aa", "#123456",
])
def test_valid_hex_triples_accepted(valid):
    r = RerenderRequest(bg_color=valid)
    assert r.bg_color == valid  # untouched — validator returns as-is


@pytest.mark.parametrize("bad", [
    "000000",                  # missing #
    "#00000",                  # 5 chars
    "#0000000",                # 7 chars
    "#GGGGGG",                 # non-hex
    "#7c3ae",                  # 5 hex
    "black",                   # named color — reject at boundary
    "",                        # empty
    "#7c3aed ",                # trailing whitespace
    " #7c3aed",                # leading whitespace
    "black:c=x,anullsrc",      # filter-token injection
    "#7c3aed:c=x,foo",         # injection tacked onto a real hex
    "#7c3aed,black",           # comma injection
    "0x7c3aed",                # 0x prefix at input — must be normalized in
                               # the worker, not accepted from the client
])
def test_invalid_bg_color_raises_validation_error(bad):
    with pytest.raises(ValidationError):
        RerenderRequest(bg_color=bad)


def test_default_bg_color_is_valid():
    """Default `#000000` must still pass its own validator."""
    r = RerenderRequest()
    assert r.bg_color == "#000000"


# ── Worker filter-string uses 0x prefix ────────────────────────────────────

def test_worker_applies_0x_prefix_to_color_background(monkeypatch, tmp_path):
    """When background='color', the FFmpeg command must contain
    `color=0x<hex>` (parseable by FFmpeg) — NOT the pre-fix bare `<hex>`."""
    from api import worker
    import subprocess

    calls = {}
    def fake_run(cmd, capture_output=True, text=True, check=False, **kw):
        calls["cmd"] = list(cmd)
        class R:
            returncode = 0
            stderr = ""
        return R()
    monkeypatch.setattr(subprocess, "run", fake_run)

    src = tmp_path / "in.mp4"; src.write_bytes(b"x")
    out = tmp_path / "out.mp4"
    worker._apply_canvas(
        input_path=str(src), output_path=str(out),
        target_w=1080, target_h=1920,
        background="color", bg_color="#7C3AED",
    )
    vf = _extract_vf(calls["cmd"])
    assert "color=0x7C3AED" in vf, f"expected `color=0x7C3AED` in filter, got: {vf!r}"
    # And absolutely no bare `7C3AED` unprefixed (would have been the pre-fix bug):
    assert ":color=7C3AED" not in vf


def test_worker_black_and_white_backgrounds_unchanged(monkeypatch, tmp_path):
    from api import worker
    import subprocess

    calls = {}
    def fake_run(cmd, capture_output=True, text=True, check=False, **kw):
        calls["cmd"] = list(cmd)
        class R:
            returncode = 0
            stderr = ""
        return R()
    monkeypatch.setattr(subprocess, "run", fake_run)

    src = tmp_path / "in.mp4"; src.write_bytes(b"x")
    for bg, expected in (("black", "color=black"), ("white", "color=white")):
        out = tmp_path / f"out_{bg}.mp4"
        worker._apply_canvas(
            input_path=str(src), output_path=str(out),
            target_w=1080, target_h=1920,
            background=bg, bg_color="#000000",
        )
        vf = _extract_vf(calls["cmd"])
        assert expected in vf, f"{bg}: expected {expected!r} in {vf!r}"


def _extract_vf(cmd):
    """Grab whichever filter argument the worker built."""
    for i, tok in enumerate(cmd):
        if tok in ("-vf", "-filter_complex"):
            return cmd[i + 1]
    raise AssertionError(f"no -vf/-filter_complex in cmd: {cmd!r}")
