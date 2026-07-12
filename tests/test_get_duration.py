"""
BUG-004 regression gate — _get_duration must fail loud and return None.

Historically:
  - bare `except: return 0.0` swallowed every failure
  - caller `needs_trim = trim_start > 0 or (trim_end > 0 and trim_end < _get_duration(...))`
    used 0.0 in the clamp, so any ffprobe failure made trim_end always > 0.0,
    which then propagated as a zero-length trim in _trim_clip.

Post-fix:
  1. On ffprobe unavailable / non-parseable output, returns None (no more 0.0).
  2. On a working ffprobe stdout, returns the parsed float unchanged.
  3. Uses subprocess.run with a bounded timeout (no hang).
"""

import os
import sys
import subprocess as sp
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture()
def worker_mod():
    from api import worker
    return worker


def _fake_run(stdout="", stderr="", returncode=0, raise_exc=None):
    """Build a monkey-patch replacement for subprocess.run."""
    def _run(cmd, capture_output=True, text=True, timeout=None, **kw):
        if raise_exc is not None:
            raise raise_exc
        class R:
            pass
        R.stdout = stdout
        R.stderr = stderr
        R.returncode = returncode
        return R()
    return _run


def test_returns_float_for_valid_ffprobe_output(worker_mod, monkeypatch):
    monkeypatch.setattr(sp, "run", _fake_run(stdout="12.345\n"))
    assert worker_mod._get_duration("some.mp4") == pytest.approx(12.345)


def test_returns_none_when_ffprobe_binary_missing(worker_mod, monkeypatch):
    """Historically this returned 0.0 which collapsed every trim. Now: None."""
    monkeypatch.setattr(sp, "run", _fake_run(raise_exc=FileNotFoundError("no ffprobe")))
    assert worker_mod._get_duration("some.mp4") is None


def test_returns_none_when_ffprobe_times_out(worker_mod, monkeypatch):
    monkeypatch.setattr(sp, "run", _fake_run(raise_exc=sp.TimeoutExpired(cmd="ffprobe", timeout=15)))
    assert worker_mod._get_duration("some.mp4") is None


def test_returns_none_on_unparseable_stdout(worker_mod, monkeypatch):
    """Malformed / empty ffprobe output must not become 0.0."""
    for junk in ["", "\n", "N/A", "unknown", "abc"]:
        monkeypatch.setattr(sp, "run", _fake_run(stdout=junk))
        assert worker_mod._get_duration("some.mp4") is None, f"junk={junk!r}"


def test_no_bare_except_left_in_source(worker_mod):
    """Post-fix source must not reintroduce a bare `except:` in _get_duration
    (or anywhere else in worker.py — belt-and-braces regression gate)."""
    import inspect
    import re
    src = inspect.getsource(worker_mod)
    # `except:` (bare) with no exception type — allow `except ` followed by a name.
    bare = re.findall(r"^\s*except\s*:\s*", src, flags=re.MULTILINE)
    assert bare == [], f"bare `except:` reintroduced in api/worker.py: {bare!r}"


def test_ffprobe_call_has_bounded_timeout(worker_mod, monkeypatch):
    """The call must pass a timeout so a hung ffprobe process cannot wedge the
    Celery worker forever."""
    seen = {}
    def _run(cmd, capture_output=True, text=True, timeout=None, **kw):
        seen["timeout"] = timeout
        class R:
            stdout = "1.0\n"; stderr = ""; returncode = 0
        return R()
    monkeypatch.setattr(sp, "run", _run)
    worker_mod._get_duration("some.mp4")
    assert isinstance(seen["timeout"], (int, float)) and seen["timeout"] > 0, (
        "no bounded timeout on ffprobe subprocess.run — hung ffprobe would wedge worker"
    )
