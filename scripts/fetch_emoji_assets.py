# -*- coding: utf-8 -*-
"""Feature #30 — bundle the curated Twemoji PNG palette into
services/assets/emoji/. Idempotent: skips files already present. Run once (and
whenever EMOJI_PALETTE changes). Twemoji is CC-BY 4.0 (jdecked/twemoji fork).

    python scripts/fetch_emoji_assets.py

Downloads the 72x72 color PNG for every emoji in services.emoji.EMOJI_PALETTE
and verifies each is a valid PNG. Prints a summary; exits non-zero if any
palette emoji failed to resolve (so a bad palette entry can't ship silently).
"""

import io
import os
import sys
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.emoji import EMOJI_PALETTE, EMOJI_ASSETS_DIR, emoji_codepoint

# jdecked/twemoji is the maintained fork after Twitter archived the original.
CDN = "https://cdn.jsdelivr.net/gh/jdecked/twemoji@latest/assets/72x72/{cp}.png"


def _looks_like_png(data: bytes) -> bool:
    return data[:8] == b"\x89PNG\r\n\x1a\n"


def main() -> int:
    os.makedirs(EMOJI_ASSETS_DIR, exist_ok=True)
    ok, skipped, failed = 0, 0, []
    for ch, kw in EMOJI_PALETTE:
        cp = emoji_codepoint(ch)
        dest = os.path.join(EMOJI_ASSETS_DIR, f"{cp}.png")
        if os.path.isfile(dest) and os.path.getsize(dest) > 0:
            skipped += 1
            continue
        url = CDN.format(cp=cp)
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                data = r.read()
            if not _looks_like_png(data):
                failed.append((ch, cp, "not a PNG"))
                continue
            with open(dest, "wb") as f:
                f.write(data)
            ok += 1
            print(f"  + {ch}  {cp}.png  ({kw})")
        except Exception as e:  # noqa: BLE001 — report, don't crash the batch
            failed.append((ch, cp, str(e)))

    print(f"\nDownloaded {ok}, already had {skipped}, failed {len(failed)} "
          f"of {len(EMOJI_PALETTE)} palette emoji.")
    if failed:
        print("FAILED (fix the palette or codepoint):")
        for ch, cp, why in failed:
            print(f"  ✗ {ch}  {cp}  — {why}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
