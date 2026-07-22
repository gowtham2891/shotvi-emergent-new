"""
Caption font RESOLUTION guard — the test class that was missing when the
fontsdir bug shipped (root-caused in DIAGNOSIS_FONTS.md).

test_caption_font.py asserts the Fontname STRING written into the ASS; it
never proves libass can actually LOAD the font behind that string. That gap
let every export silently fall back to a system font (Nirmala UI on Windows)
for months while the string-level tests stayed green: CAPTION_FONTS_DIR
pointed at services/assets/fonts, the .ttfs lived in per-font SUBDIRECTORIES,
and libass's fontsdir scan is NON-RECURSIVE — it fopen()s each directory
entry as a font file, so subdirectories are skipped and zero bundled fonts
were loaded.

Two layers close the gap:

1. Static layout guards (no ffmpeg): every bundled caption .ttf must be an
   IMMEDIATE child of CAPTION_FONTS_DIR, a real file (never a symlink), and
   its internal TTF family name must equal the CAPTION_FONTS key used as the
   ASS Fontname — the exact string libass matches against.

2. A real resolution probe (ffmpeg required, else skipped): burn through the
   REAL burn_captions command (captured verbatim, replayed at -v verbose) and
   assert libass's own fontselect log maps each requested family to the
   bundled font — e.g. `fontselect: (Ramabhadra, 700, 0) -> Ramabhadra` —
   with NO fallback (Arial/Nirmala/DejaVu) and NO "Glyph not found" font
   substitution for Telugu text.
"""

import os
import re
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from services.caption_renderer import generate_ass_karaoke, burn_captions
from services.fonts import CAPTION_FONTS, CAPTION_FONTS_DIR


def _ffmpeg_available():
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=10)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


requires_ffmpeg = pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg not on PATH")

# Telugu word in every probe so resolution is proven for the glyphs that
# matter — a wrong (Latin-only) font match would trigger libass's per-glyph
# "Glyph 0xNNN not found" fallback, which the probe asserts against.
TELUGU_WORD = "పరీక్ష"

# PostScript names of the bundled static instances, as libass logs them in
# `fontselect: (<family>, <bold>, <italic>) -> <ps-name>, <index>, <ps-name>`.
# Read from the TTF name tables (nameID 6); they change only if the bundled
# files themselves are ever replaced (they are calibrated spec — see
# CAPTION_FONT_CAP_K — so effectively never).
EXPECTED_POSTSCRIPT = {
    "Noto Sans Telugu": "NotoSansTelugu-Regular",
    "Ramabhadra":       "Ramabhadra",
    "Mandali":          "Mandali",
}

# System fonts libass falls back to when fontsdir yields nothing: Nirmala UI
# is Windows' only Telugu font (the exact wrong font users saw), Arial the
# Latin first-hop, DejaVu/Liberation the common Linux-fontconfig equivalents.
FALLBACK_FONT_MARKERS = ("Nirmala", "Arial", "DejaVu", "Liberation")


# ── 1. Static layout guards ──────────────────────────────────────────────────

def test_every_caption_ttf_is_immediate_child_of_fontsdir():
    """libass's fontsdir scan is non-recursive: a font in a subdirectory is
    NEVER loaded (silent system-font fallback — the DIAGNOSIS_FONTS.md bug).
    Every registered caption font must therefore sit directly in
    CAPTION_FONTS_DIR, as a real file, never a symlink."""
    fontsdir = os.path.abspath(CAPTION_FONTS_DIR)
    assert os.path.isdir(fontsdir), f"CAPTION_FONTS_DIR missing: {fontsdir}"
    for family, path in CAPTION_FONTS.items():
        apath = os.path.abspath(path)
        assert os.path.isfile(apath), f"{family}: bundled font missing: {apath}"
        assert not os.path.islink(apath), (
            f"{family}: {apath} is a symlink — caption fonts must be real files"
        )
        assert os.path.dirname(apath) == fontsdir, (
            f"{family}: {apath} is not an IMMEDIATE child of fontsdir {fontsdir} — "
            f"libass's fontsdir scan does not recurse, so libass would never load "
            f"it and every export would silently fall back to a system font"
        )


def test_fontsdir_files_are_all_ttf():
    """Non-font files as immediate children of fontsdir make libass log
    'Error opening memory font' on every burn (licenses live in
    captions/licenses/, which the scan skips). Directories are allowed."""
    for entry in os.scandir(CAPTION_FONTS_DIR):
        if entry.is_file():
            assert entry.name.lower().endswith(".ttf"), (
                f"non-.ttf file in fontsdir: {entry.name} — move it out "
                f"(licenses belong in captions/licenses/)"
            )


def _ttf_family_names(path):
    """Internal family names from the TTF `name` table (nameIDs 1 and 16) —
    the strings libass matches the ASS Fontname against. Raw parser: no
    fontTools dependency."""
    with open(path, "rb") as f:
        data = f.read()
    num_tables = struct.unpack(">H", data[4:6])[0]
    name_off = None
    for i in range(num_tables):
        rec = 12 + i * 16
        tag, _, toff, _ = struct.unpack(">4sIII", data[rec:rec + 16])
        if tag == b"name":
            name_off = toff
            break
    assert name_off is not None, f"no name table in {path}"
    _, count, str_off = struct.unpack(">HHH", data[name_off:name_off + 6])
    families = {}
    for i in range(count):
        rec = name_off + 6 + i * 12
        pid, eid, lid, nid, length, offset = struct.unpack(">HHHHHH", data[rec:rec + 12])
        if nid not in (1, 16):
            continue
        raw = data[name_off + str_off + offset: name_off + str_off + offset + length]
        s = raw.decode("utf-16-be") if pid in (0, 3) else raw.decode("latin-1", "replace")
        # prefer the Windows en-US record libass/FreeType favor
        if nid not in families or (pid == 3 and lid == 0x409):
            families[nid] = s
    return families


@pytest.mark.parametrize("family", list(CAPTION_FONTS))
def test_internal_family_name_matches_ass_fontname(family):
    """The CAPTION_FONTS key is written verbatim into the ASS Style Fontname
    (via get_caption_font); libass matches it against the .ttf's INTERNAL
    family name. They must be exactly equal — filename similarity proves
    nothing."""
    names = _ttf_family_names(CAPTION_FONTS[family])
    internal = names.get(16, names.get(1))
    assert internal == family, (
        f"ASS Fontname {family!r} != internal TTF family {internal!r} "
        f"({CAPTION_FONTS[family]}) — libass will not match it and will "
        f"silently substitute a system font"
    )


# ── 2. Real libass resolution probe ─────────────────────────────────────────

def _burn_and_capture_fontselect_log(caption_font, tmp, monkeypatch):
    """Burn a 1.2s Telugu caption through the REAL production path and return
    ffmpeg's verbose stderr. The exact command burn_captions builds (filter
    string, fontsdir escaping and all) is captured via an intercepted
    subprocess.run, then replayed with -v verbose prepended — so the probe
    can't drift from production wiring."""
    real_run = subprocess.run

    clip = os.path.join(tmp, "clip.mp4")
    real_run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=540x960:d=1.2",
         "-f", "lavfi", "-i", "anullsrc", "-shortest",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", clip],
        capture_output=True, timeout=60, check=True,
    )
    lines = [{"words": [{"word": TELUGU_WORD, "start": 0.0, "end": 1.0}],
              "line_start": 0.0, "line_end": 1.2}]
    ass = generate_ass_karaoke(lines, "bold-yellow",
                               video_width=540, video_height=960,
                               caption_font=caption_font)
    ass_path = os.path.join(tmp, "cap.ass")
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(ass)

    captured = {}

    class _FakeResult:
        returncode = 0
        stderr = ""

    def _capture(cmd, *a, **k):
        captured["cmd"] = cmd
        return _FakeResult()

    monkeypatch.setattr(subprocess, "run", _capture)
    burn_captions(clip, ass_path, os.path.join(tmp, "out.mp4"))
    monkeypatch.setattr(subprocess, "run", real_run)

    cmd = captured["cmd"]
    assert cmd[0] == "ffmpeg", f"unexpected burn command: {cmd[:3]}"
    verbose_cmd = cmd[:1] + ["-v", "verbose"] + cmd[1:]
    r = real_run(verbose_cmd, capture_output=True, text=True,
                 encoding="utf-8", errors="replace", timeout=120)
    assert r.returncode == 0, f"burn failed: {r.stderr[-600:]}"
    return r.stderr


@requires_ffmpeg
@pytest.mark.parametrize("family", list(CAPTION_FONTS))
def test_libass_resolves_bundled_font_not_a_fallback(family, monkeypatch):
    """THE regression test for the DIAGNOSIS_FONTS.md bug. With the broken
    (subdirectory) fontsdir, libass loaded zero fonts and its own log read
        fontselect: (Ramabhadra, 700, 0) -> Arial-BoldMT ... -> NirmalaUI-Bold
    while the worker log claimed the chosen font. Assert from libass's own
    fontselect lines that each family resolves to the BUNDLED font."""
    with tempfile.TemporaryDirectory(prefix="fontres_") as tmp:
        log = _burn_and_capture_fontselect_log(family, tmp, monkeypatch)

    # The bundled file was actually discovered and loaded from fontsdir.
    ttf_base = os.path.basename(CAPTION_FONTS[family])
    assert re.search(r"Loading font file '[^']*" + re.escape(ttf_base) + "'", log), (
        f"{ttf_base} was never loaded from fontsdir — fontsdir flatness broken?\n"
        f"{log[-800:]}"
    )
    assert not re.search(re.escape(ttf_base) + r".*fopen failed", log), (
        f"libass failed to open {ttf_base}:\n{log[-800:]}"
    )

    # libass matched the requested family to the bundled font, not a fallback.
    sel = re.findall(r"fontselect: \(" + re.escape(family) + r", \d+, \d+\) -> ([^,]+),", log)
    assert sel, f"no fontselect line for ({family}, ...) in ffmpeg log:\n{log[-800:]}"
    expected_ps = EXPECTED_POSTSCRIPT[family]
    assert all(s.strip() == expected_ps for s in sel), (
        f"libass resolved {family!r} to {sorted(set(sel))} instead of the bundled "
        f"{expected_ps!r} — system-font fallback is back (DIAGNOSIS_FONTS.md)"
    )
    for marker in FALLBACK_FONT_MARKERS:
        assert marker not in log, (
            f"fallback font {marker!r} appears in the burn log for {family!r}:\n{log[-800:]}"
        )

    # Telugu glyphs came from the bundled font itself — no per-glyph rescue.
    assert "not found, selecting one more font" not in log, (
        f"libass had to substitute another font for missing glyphs — the "
        f"resolved {family!r} face does not actually cover Telugu:\n{log[-800:]}"
    )
