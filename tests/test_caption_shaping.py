"""
Telugu caption shaping self-test + engine guard for services/caption_renderer.py.

Background — the engine lesson this file exists to lock in: on the production
libass build, the `ass` filter shapes Telugu below-base (vattu/ottu) conjuncts
CORRECTLY (e.g. ప్ర), while the `subtitles` filter DECOMPOSES them (renders a
wider, spelled-out form). Production must always use `ass`. These tests catch a
regression to `subtitles`, a missing/mis-resolved bundled font, or a broken
fontsdir wiring — any of which reintroduces broken Telugu.

The shaping check renders the isolated conjunct ప్ర through the REAL burn path
(generate_ass_karaoke + burn_captions → `ass` + fontsdir + bundled font),
measures the rendered ink's bounding-box aspect ratio, and compares it to a
HarfBuzz/FreeType reference aspect (measured on the bundled files). Correct
shaping keeps the ra tucked under the base → compact aspect ≈ the reference;
the broken `subtitles` form spreads it out → ~2x wider aspect → fails. Aspect
ratio (not IoU or absolute size) is used because it is robust to the preset's
outline, to caption size, and to per-engine antialiasing. Needs only ffmpeg
(no libraqm at test time), so it runs as the Docker/CI gate against whatever
ffmpeg the environment provides (PATH, via burn_captions).
"""

import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from PIL import Image

from services.caption_renderer import (
    generate_ass_karaoke, burn_captions, caption_font_size, CAPTION_FONT_CAP_K,
)
from services.fonts import CAPTION_FONTS, DEFAULT_CAPTION_FONT, get_caption_font


def _ffmpeg_available():
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=10)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _libass_has_libraqm():
    """The Telugu below-base shaping check (ప్ర) requires libass to be built
    against libraqm, which enables proper Indic complex-script shaping. Debian
    stock ffmpeg / libass are NOT built with libraqm (--enable-libraqm is
    missing from its ./configure), so the ప్ర test would fail with an aspect
    ~1.9 (decomposed) even though the render path is correct. The production
    Docker image ships a libraqm-enabled libass; anywhere else we skip these
    tests as environment-specific rather than mark them as real failures. The
    engine-guard test (test_burn_captions_uses_ass_filter_not_subtitles) does
    not need libraqm and remains active in every environment."""
    try:
        deps = subprocess.run(
            ["sh", "-c",
             "for so in /usr/lib/*/libass.so* /usr/lib/libass.so* /usr/local/lib/libass.so*; "
             "do [ -e \"$so\" ] && ldd \"$so\"; done"],
            capture_output=True, text=True, timeout=5,
        ).stdout.lower()
        return "libraqm" in deps
    except Exception:
        return False


requires_ffmpeg = pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg not on PATH")
requires_libraqm = pytest.mark.skipif(
    not _libass_has_libraqm(),
    reason="libass not built with libraqm — Telugu below-base shaping check "
           "cannot run (Debian stock; production Docker image ships libraqm)",
)

VATTU_WORD = "ప్ర"   # ప్ర — pa + virama + ra (below-base vattu)

# HarfBuzz/FreeType reference: ink-bbox aspect (w/h) of ప్ר per bundled font,
# measured via PIL + libraqm on the shipped font files. Correct libass `ass`
# output lands within REL_TOL of these; the broken `subtitles` form is ~2x
# wider (aspect ~1.5 → rel_err ~1.1). To regenerate: render ప్ర with
# ImageFont.truetype(path, size, layout_engine=Layout.RAQM) and take
# (bbox_w / bbox_h) of the ink.
HB_REF_ASPECT = {
    "Noto Sans Telugu": 0.69,
    "Ramabhadra":       0.75,
    "Mandali":          0.73,
}
REL_TOL = 0.60   # correct observed ≤0.24; broken ~1.1 — 0.60 separates with ~2x margin

# ── Why aspect ratio and not ink-overlap IoU ─────────────────────────────────
# IoU (of the burned ink mask vs the HarfBuzz reference mask) was implemented
# and calibrated FIRST, per the original spec (correct ≳0.8 / broken ≲0.5). It
# empirically FAILED to separate correct from broken — the styled burn (bold-
# yellow outline + karaoke highlight) does not overlay cleanly on the plain HB
# glyph, so outline width + cross-engine antialiasing dominate the overlap.
# Measured IoU(ass-burn, HB) for CORRECT renders vs IoU(subtitles-burn, HB) for
# BROKEN, for ప్ర / ప్రపంచంలో / దేశాలన్నిటిలో:
#     Noto        correct 0.75 / 0.55 / 0.40   broken ~0.13–0.18
#     Ramabhadra  correct 0.23 / 0.25 / 0.21   broken 0.14 / 0.19 / 0.21
#     Mandali     correct 0.37 / 0.22 / 0.14   broken 0.09 / 0.13 / 0.13
# For Ramabhadra/Mandali the correct IoU never approached 0.8 and barely beat
# the broken IoU (one pair effectively tied: 0.213 vs 0.212). So the spec's IoU
# thresholds were unachievable. Ink-bbox aspect ratio separated cleanly
# (correct ≤0.24, broken ~1.1, since decomposition roughly doubles the width),
# so it is used instead.
#
# Known blind spots of the aspect metric (accepted; the ass-only guard below is
# the real safety net):
#   - Single-conjunct coverage: only ప్ర is asserted. A break specific to a
#     different conjunct/matra (ప్రపంచంలో / దేశాలన్నిటిలో are NOT asserted) is not caught.
#   - Bbox-preserving breakage: aspect is a coarse 1-D signature; any breakage
#     that preserves the overall width/height ratio slips through (decomposition
#     happens to widen the bbox, so it is caught — but not every breakage does).
#   - Outline-config coupling: the correct-case baseline is measured with
#     bold-yellow's outline (Mandali already sits at ~24% vs the 60% cap), so a
#     large outline change could erode the margin.
#   - Similar-proportion fallback: a wrong-but-similar-aspect fallback font
#     would pass on aspect alone (the fonts-bundled test + fontsdir make
#     fallback unlikely, but aspect does not detect it).
#
# PRIMARY regression protection is test_burn_captions_uses_ass_filter_not_subtitles
# (below): it intercepts the real -vf argument and fails on any switch to the
# subtitles filter — the actual failure mode — with certainty and no ffmpeg.
# The aspect test is a SECONDARY render-level sanity check.


# ── Engine guard — the whole point of this file ──────────────────────────────

def test_burn_captions_uses_ass_filter_not_subtitles(monkeypatch):
    """burn_captions must build an `ass=` filter, never `subtitles=`. The
    subtitles filter mis-shapes Telugu below-base conjuncts on the production
    libass build (see module docstring). Inspects the ACTUAL -vf argument by
    intercepting the ffmpeg invocation (no ffmpeg run, no docstring false-match)."""
    captured = {}

    class _Result:
        returncode = 0
        stderr = ""

    def _fake_run(cmd, *a, **k):
        captured["cmd"] = cmd
        return _Result()

    monkeypatch.setattr(subprocess, "run", _fake_run)
    burn_captions("in.mp4", "cap.ass", "out.mp4")

    cmd = captured["cmd"]
    vf = cmd[cmd.index("-vf") + 1]
    assert vf.startswith("ass='"), f"caption burn must use the ass filter, got: {vf!r}"
    assert "subtitles=" not in vf, (
        "burn_captions must NOT use the subtitles filter — it breaks Telugu "
        "below-base shaping on the production libass build"
    )
    assert "fontsdir=" in vf, "caption burn must pass fontsdir for deterministic fonts"


def test_caption_fonts_bundled_and_resolvable():
    """Every selectable caption font resolves to a bundled file that exists,
    and the default is Noto Sans Telugu."""
    assert DEFAULT_CAPTION_FONT == "Noto Sans Telugu"
    for name, path in CAPTION_FONTS.items():
        assert os.path.exists(path), f"bundled caption font missing: {name} -> {path}"
    # unknown / None both fall back to the default (never host fontconfig, never raise)
    assert get_caption_font("does-not-exist")[0] == DEFAULT_CAPTION_FONT
    assert get_caption_font(None)[0] == DEFAULT_CAPTION_FONT


def test_caption_font_sizes_are_calibrated():
    """Noto anchors each preset's size (keeps the preset's own font_size);
    the heavier-metric fonts scale down to match Noto's cap-height."""
    base = 62
    assert caption_font_size(base, "Noto Sans Telugu") == base
    for fam in ("Ramabhadra", "Mandali"):
        sz = caption_font_size(base, fam)
        assert 6 <= sz < base, f"{fam} size {sz} not scaled below Noto anchor {base}"
    # every registered font has a calibration coefficient
    for fam in CAPTION_FONTS:
        assert fam in CAPTION_FONT_CAP_K


# ── Real-path shaping check (the CI/Docker gate) ─────────────────────────────

def _burn_vattu_aspect(caption_font, tmp):
    """Render ప్ర through the real burn path; return rendered ink-bbox aspect w/h."""
    clip = os.path.join(tmp, "clip.mp4")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=540x960:d=1.2",
         "-f", "lavfi", "-i", "anullsrc", "-shortest",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", clip],
        capture_output=True, timeout=60,
    )
    lines = [{"words": [{"word": VATTU_WORD, "start": 0.0, "end": 1.0}],
              "line_start": 0.0, "line_end": 1.2}]
    ass = generate_ass_karaoke(lines, "bold-yellow", caption_position=50.0,
                               video_width=540, video_height=960,
                               caption_font=caption_font)
    ass_path = os.path.join(tmp, "cap.ass")
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(ass)
    out = os.path.join(tmp, "out.mp4")
    ok = burn_captions(clip, ass_path, out)
    assert ok and os.path.exists(out), "burn_captions failed"
    frame = os.path.join(tmp, "frame.png")
    subprocess.run(["ffmpeg", "-y", "-ss", "0.6", "-i", out,
                    "-frames:v", "1", "-update", "1", frame],
                   capture_output=True, timeout=30)
    img = Image.open(frame).convert("L")
    px = img.load()
    w, h = img.size
    xs, ys = [], []
    for y in range(h):
        for x in range(w):
            if px[x, y] > 80:
                xs.append(x); ys.append(y)
    assert xs, "no caption ink rendered (font failed to load / caption not burned?)"
    return (max(xs) - min(xs) + 1) / (max(ys) - min(ys) + 1)


@requires_ffmpeg
@requires_libraqm
@pytest.mark.parametrize("caption_font", list(CAPTION_FONTS))
def test_telugu_vattu_shapes_correctly_via_real_burn_path(caption_font):
    """The real burn path (`ass` + fontsdir + bundled font) shapes the ప్ర
    below-base conjunct compactly, matching the HarfBuzz reference aspect —
    NOT the ~2x-wider decomposed form the forbidden subtitles filter produces."""
    ref = HB_REF_ASPECT[caption_font]
    with tempfile.TemporaryDirectory(prefix="capshape_") as tmp:
        aspect = _burn_vattu_aspect(caption_font, tmp)
    rel_err = abs(aspect - ref) / ref
    assert rel_err < REL_TOL, (
        f"{caption_font}: ప్ర rendered aspect {aspect:.3f} vs HB ref {ref:.3f} "
        f"(rel_err {rel_err:.0%} ≥ {REL_TOL:.0%}) — Telugu vattu likely broken "
        f"(subtitles-style decomposition?) or wrong font resolved"
    )


# ── Static-verification smoke test: caption burn end-to-end via ass=+fontsdir ──

@requires_ffmpeg
def test_caption_burn_pipeline_end_to_end_ass_fontsdir_smoke():
    """Rebuild the whole caption burn stack — a small lavfi-generated sample
    clip, ASS from generate_ass_karaoke, and burn_captions rendering via
    `ass=` + `fontsdir=services/assets/fonts/captions` — and prove:

      (a) ffmpeg exits 0 (the caption filtergraph is valid on THIS ffmpeg build,
          not just an assumed one — caught a regression to `subtitles=` or a
          malformed fontsdir escape locally without needing the CI shaping gate),
      (b) an .mp4 was produced and is non-empty, and
      (c) a decodable frame exists at the caption's display time (proves the
          filter chain actually ran through to completion; a filtergraph that
          silently drops frames would fail this).

    Deliberately does NOT assert glyph shape or ink pixel counts — that belongs
    to the libraqm-gated Telugu shaping test above. This is the environment-
    agnostic smoke check the owner asked for: "prove the caption path still works"
    on any machine with ffmpeg, without depending on complex-script shaping."""
    with tempfile.TemporaryDirectory(prefix="capsmoke_") as tmp:
        clip = os.path.join(tmp, "clip.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=540x960:d=1.5",
             "-f", "lavfi", "-i", "anullsrc", "-shortest",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", clip],
            capture_output=True, timeout=60, check=True,
        )
        # Latin words only — no libraqm dependency for THIS smoke test.
        words = [{"word": "hello", "start": 0.0, "end": 0.4},
                 {"word": "world", "start": 0.4, "end": 0.9}]
        ass = generate_ass_karaoke(
            [{"words": words, "line_start": 0.0, "line_end": 1.2}],
            "bold-yellow",
            video_width=540, video_height=960,
            caption_font=DEFAULT_CAPTION_FONT,
        )
        # Positioning contract (Commit 4): every event carries \an5\pos.
        assert "\\an5" in ass and "\\pos(" in ass, (
            "generate_ass_karaoke must emit an explicit \\an5\\pos on every "
            "event — the unified positioning code path introduced in Commit 4"
        )
        ass_path = os.path.join(tmp, "cap.ass")
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(ass)

        out = os.path.join(tmp, "out.mp4")
        assert burn_captions(clip, ass_path, out), (
            "burn_captions returned False — ffmpeg failed on the caption "
            "filtergraph (regression to subtitles=, bad fontsdir escape, or "
            "unresolved caption font?)"
        )
        assert os.path.exists(out) and os.path.getsize(out) > 0, (
            f"burned clip missing/empty: {out}"
        )

        # (c) decode a frame at 0.6s — proves the filter chain ran end-to-end.
        frame = os.path.join(tmp, "frame.png")
        r = subprocess.run(
            ["ffmpeg", "-y", "-ss", "0.6", "-i", out,
             "-frames:v", "1", "-update", "1", frame],
            capture_output=True, text=True, timeout=30,
        )
        assert r.returncode == 0 and os.path.exists(frame) and os.path.getsize(frame) > 0, (
            f"could not decode a frame from the captioned clip: {r.stderr[-300:]}"
        )


@requires_ffmpeg
def test_typewriter_spoken_words_render_opaque():
    """Regression for the typewriter invisible-text bug: its color_unspoken is
    transparent (&HFFFFFFFF) and became the Style PrimaryColour alpha, so
    spoken/highlight words — coloured with `\\c` (RGB only) — inherited that
    transparency and rendered invisible. _color_tag now emits `\\1a` per word,
    so spoken/highlight words are opaque. At the sampled time both visible words
    are white text on the dark box → many bright pixels; the pre-fix bug left
    ~0."""
    with tempfile.TemporaryDirectory(prefix="capty_") as tmp:
        clip = os.path.join(tmp, "clip.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=720x480:d=1.2",
             "-f", "lavfi", "-i", "anullsrc", "-shortest",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", clip],
            capture_output=True, timeout=60,
        )
        words = [{"word": "typed", "start": 0.0, "end": 0.5},
                 {"word": "now", "start": 0.5, "end": 1.0}]
        ass = generate_ass_karaoke([{"words": words, "line_start": 0.0, "line_end": 1.2}],
                                   "typewriter", caption_position=50.0,
                                   video_width=720, video_height=480,
                                   caption_font="Noto Sans Telugu")
        ass_path = os.path.join(tmp, "t.ass")
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(ass)
        out = os.path.join(tmp, "o.mp4")
        assert burn_captions(clip, ass_path, out)
        frame = os.path.join(tmp, "f.png")
        subprocess.run(["ffmpeg", "-y", "-ss", "0.7", "-i", out,
                        "-frames:v", "1", "-update", "1", frame],
                       capture_output=True, timeout=30)
        img = Image.open(frame).convert("L")
        px = img.load()
        w, h = img.size
        bright = sum(1 for y in range(h) for x in range(w) if px[x, y] > 200)
    assert bright > 150, (
        f"typewriter spoken/highlight text not visible (only {bright} bright px) "
        f"— transparency regression: `\\c` set RGB but not alpha, so words "
        f"inherited the transparent Style PrimaryColour alpha"
    )


# ── Standalone runner: `python tests/test_caption_shaping.py` (Docker CI gate) ─
if __name__ == "__main__":
    if not _ffmpeg_available():
        print("FAIL: ffmpeg not available"); sys.exit(2)
    failures = 0
    for fam in CAPTION_FONTS:
        try:
            with tempfile.TemporaryDirectory(prefix="capshape_") as tmp:
                a = _burn_vattu_aspect(fam, tmp)
            ref = HB_REF_ASPECT[fam]; err = abs(a - ref) / ref
            ok = err < REL_TOL
            print(f"[{'PASS' if ok else 'FAIL'}] {fam:18} aspect={a:.3f} ref={ref:.3f} err={err:.0%}")
            failures += (0 if ok else 1)
        except Exception as e:
            print(f"[FAIL] {fam}: {e}"); failures += 1
    sys.exit(1 if failures else 0)
