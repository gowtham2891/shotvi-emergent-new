# -*- coding: utf-8 -*-
"""Feature #30 — caption emoji as TIMED COLOR PNG OVERLAYS (Twemoji).

Why overlays and not inline caption text: libass 0.17.4 (this FFmpeg build)
cannot composite color glyphs — an emoji typed into caption text burns as a
flat, karaoke-tinted monochrome outline on Windows and BLANK/tofu on Linux
(see DIAGNOSIS_EMOJI.md). The only path to true color emoji is to composite a
color PNG over the video, time-bounded to the caption line it belongs to
(services/overlay_renderer.py :: the `emoji` layer preparer + enable='between'
window). This module owns the emoji↔asset contract both ends share.

CURATED PALETTE: Gemini may only suggest emoji from EMOJI_PALETTE, so every
suggestion is guaranteed a bundled asset — no runtime download, no missing-PNG
render gap. The palette is the SINGLE SOURCE OF TRUTH: the fine-cut prompt lists
it (build_fine_cut_prompt), the resolver validates against it, and the asset
fetch script (scripts/fetch_emoji_assets.py) bundles exactly these files.
"""

import os
import re

EMOJI_ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets", "emoji")

# (emoji, keyword) — keyword is what Gemini sees/returns-alongside in the prompt
# so it can reason in words; the emoji char is the anchor we resolve on. Chosen
# for short-form content (the reactions a CapCut/Reels editor actually drops):
# reactions, emphasis, money/growth, agreement, alerts. All map to a single
# Twemoji codepoint (variation selector U+FE0F stripped — Twemoji's own naming).
EMOJI_PALETTE = [
    ("🔥", "fire / hot / trending"),
    ("😂", "hilarious / laughing"),
    ("💯", "100 / totally true"),
    ("🎉", "celebration / win"),
    ("😱", "shock / no way"),
    ("💡", "idea / tip / insight"),
    ("❤️", "love / heart"),
    ("👀", "look / watch this"),
    ("🚀", "growth / takeoff / fast"),
    ("💪", "strength / effort"),
    ("🤯", "mind blown"),
    ("😍", "love it / amazing"),
    ("🙏", "please / grateful / respect"),
    ("👏", "applause / well done"),
    ("✅", "correct / do this"),
    ("❌", "wrong / don't do this"),
    ("⚡", "energy / speed / power"),
    ("💰", "money / profit"),
    ("🤔", "hmm / think about it"),
    ("😎", "cool / confident"),
    ("🥳", "party / hype"),
    ("😭", "crying / emotional"),
    ("💥", "boom / impact"),
    ("⭐", "star / quality"),
    ("🎯", "on target / exactly"),
    ("📈", "growth / up / results"),
    ("🧠", "smart / knowledge"),
    ("👍", "good / yes"),
    ("👎", "bad / no"),
    ("⚠️", "warning / careful"),
    ("✨", "magic / special"),
    ("👑", "king / best / top"),
    ("🏆", "winner / achievement"),
    ("⏰", "time / hurry"),
    ("🛑", "stop / danger"),
    ("👉", "pointing / look here"),
    ("🙌", "praise / celebration"),
    ("👌", "perfect / ok"),
    ("😊", "happy / friendly"),
    ("😢", "sad"),
    ("😳", "awkward / embarrassed"),
    ("💀", "dead / so funny / brutal"),
    ("💎", "valuable / premium"),
    ("🔑", "key point / secret"),
    ("🔔", "reminder / notification"),
    ("📣", "announce / shout out"),
    ("❓", "question"),
    ("❗", "important / attention"),
    ("🤝", "deal / agreement"),
    ("🤫", "secret / shh"),
    ("😅", "nervous / phew"),
    ("🙄", "eye roll / really"),
    ("🤓", "nerd / technical"),
    ("🤑", "cash / greedy"),
]

# Fast membership + prompt rendering derived once.
PALETTE_CHARS = {ch for ch, _ in EMOJI_PALETTE}


def emoji_codepoint(ch: str) -> str:
    """Twemoji filename stem for an emoji char: each Unicode scalar as
    lowercase hex, joined by '-', with the U+FE0F variation selector dropped
    (Twemoji's own convention — e.g. '❤️' U+2764 U+FE0F -> '2764')."""
    parts = [f"{ord(c):x}" for c in ch if ord(c) != 0xFE0F]
    return "-".join(parts)


def emoji_asset_path(ch: str) -> str:
    """Absolute path to the bundled Twemoji PNG for a palette emoji, or None if
    the char is not in the palette / the asset is missing. Mirrors
    services/fonts.py :: get_font_path — a static asset lookup, no per-video
    ownership check (bundled assets, not user uploads)."""
    if ch not in PALETTE_CHARS:
        return None
    path = os.path.join(EMOJI_ASSETS_DIR, f"{emoji_codepoint(ch)}.png")
    return path if os.path.isfile(path) else None


def is_palette_emoji(ch: str) -> bool:
    return ch in PALETTE_CHARS


def palette_prompt_block() -> str:
    """The emoji menu injected into the fine-cut prompt — one `emoji keyword`
    per line so Gemini picks a char that is guaranteed to have an asset."""
    return "\n".join(f"{ch}  {kw}" for ch, kw in EMOJI_PALETTE)


# ── typed-caption emoji → overlay (burn-time) ───────────────────────────────
# A user can TYPE an emoji into caption text. libass can't composite color
# glyphs (DIAGNOSIS_EMOJI.md — mono outline on Win, blank/tofu on Linux), so at
# burn time we STRIP every emoji from the caption text and re-emit the palette
# ones as timed color PNG overlays — the exact same path feature #30 uses.

# Codepoint match ignores the U+FE0F variation selector, so a typed "❤" (bare)
# and "❤️" (with selector) both resolve to the bundled palette asset.
PALETTE_BY_CODEPOINT = {emoji_codepoint(ch): ch for ch, _ in EMOJI_PALETTE}

# Emoji codepoint ranges — broad enough to catch a typed emoji from any standard
# keyboard, narrow enough to leave ordinary text (Latin, Telugu U+0C00–0C7F,
# ASCII punctuation) untouched: every range here is far above those blocks.
_EMOJI_RANGES = (
    (0x1F000, 0x1FAFF),  # all pictographic emoji blocks
    (0x2600, 0x26FF),    # misc symbols (⚡ ⚠ ☀ …)
    (0x2700, 0x27BF),    # dingbats (✅ ❌ ✨ ❤ ✌ ✋ …)
    (0x2B00, 0x2BFF),    # ⭐ and misc symbols/arrows-B
    (0x2300, 0x23FF),    # ⏰ ⏳ ⌛ … (misc technical)
    (0x1F1E6, 0x1F1FF),  # regional indicators (flags)
)
_EMOJI_MODIFIERS = {0xFE0F, 0x200D, 0x20E3}  # variation selector, ZWJ, keycap


def _is_emoji_base(cp: int) -> bool:
    return any(lo <= cp <= hi for lo, hi in _EMOJI_RANGES)


def _is_skin_tone(cp: int) -> bool:
    return 0x1F3FB <= cp <= 0x1F3FF


def split_caption_emoji(text: str):
    """Split caption text into (clean_text, [emoji_tokens]).

    Every emoji is removed from clean_text; the emoji tokens are returned in
    order. Adjacent emoji become separate tokens; a ZWJ sequence and its
    variation-selector/skin-tone modifiers stay attached to their base. Ordinary
    text/punctuation is never touched (the ranges sit far above Latin/Telugu).
    """
    if not text:
        return text, []
    clean, tokens, cur = [], [], []
    prev_zwj = False
    for ch in text:
        cp = ord(ch)
        if _is_emoji_base(cp) or cp in _EMOJI_MODIFIERS or _is_skin_tone(cp):
            # A new base (not glued by a preceding ZWJ) starts a fresh token.
            if cur and _is_emoji_base(cp) and not prev_zwj:
                tokens.append("".join(cur))
                cur = []
            cur.append(ch)
            prev_zwj = cp == 0x200D
        else:
            if cur:
                tokens.append("".join(cur))
                cur = []
            prev_zwj = False
            clean.append(ch)
    if cur:
        tokens.append("".join(cur))
    # Collapse the whitespace a mid-word strip can leave behind.
    clean_text = re.sub(r"\s{2,}", " ", "".join(clean)).strip()
    # Drop stray lone modifiers (a token with no actual emoji base).
    tokens = [t for t in tokens if any(_is_emoji_base(ord(c)) for c in t)]
    return clean_text, tokens


def resolve_palette_emoji(token: str) -> str:
    """A typed emoji token → the canonical palette char (matched by codepoint,
    so FE0F/skin-tone-free base forms resolve), or None if it is not in the
    curated palette (caller strips it with a warning)."""
    return PALETTE_BY_CODEPOINT.get(emoji_codepoint(token))
