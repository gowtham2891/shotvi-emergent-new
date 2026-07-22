"""
ClipForge AI — Telugu → Tanglish (casual romanization) engine
==============================================================
Deterministic, pure, offline. Powers the editor's Telugu ⇄ Tanglish caption
toggle: Telugu script in, WhatsApp-style romanized Telugu out.

    telugu_to_tanglish("దీన్ని")      -> "deenni"
    telugu_to_tanglish("mind-ని")     -> "mind-ni"
    telugu_to_tanglish("control")     -> "control"

DIRECTION NOTE: this is Telugu→Latin ONLY. The reverse (Latin→Telugu phonetic
suggestions) is the separate IndicXlit stub behind POST /transliterate —
ML-based, different task, do not merge the two.

Pipeline per word:
  1. CHARACTER-RUN split — only Telugu-block runs (U+0C00–0C7F, plus ZWJ/ZWNJ
     riding inside them) are transliterated; Latin/digits/punctuation pass
     through verbatim, so hybrid tokens like "mind-ని" come out "mind-ni".
  2. indic-transliteration (sanscript) Telugu → ISO-15919 for each Telugu run.
  3. Casual rules on the ISO output so it reads like WhatsApp-Telugu, not an
     academic journal:
       - long vowels double:  ā→aa  ī→ee  ū→oo   (ē→e, ō→o — casual Telugu
         writes "prema"/"lo", not "preema"/"loo")
       - anusvara ṁ is context-sensitive: n before stops ("andaru", "intlo",
         "sangham"), m before labials AND everywhere else — liquids/sibilants
         ("kalpavrukshamlaa", "samvatsaram") and run-final ("pustakam") —
         matching how casual Telugu is actually typed
       - చ family gets its h back: c→ch ("cheppu"), ఛ ch→chh
       - vocalic r: r̥→ru ("vruddhi", "krushna")
       - retroflex/sibilant diacritics dropped: ṭ→t ḍ→d ṇ→n ḷ→l, ś/ṣ→sh
       - final safety net strips ANY residual combining mark / non-ASCII so
         the output never contains dots or macrons.

No network, no model, no state — same input always gives the same output.
Guarded by tests/test_tanglish.py.
"""

import re
import unicodedata

from indic_transliteration import sanscript

# Telugu block + ZWJ/ZWNJ (shaping controls that can sit inside a Telugu run).
_TELUGU_RUN = re.compile(r"[ఀ-౿‌‍]+")

# ISO-15919 code points produced by sanscript for Telugu, in casual order.
_ANUSVARA = "ṁ"  # ṁ
# Consonants before which the anusvara reads as 'n' (velar/palatal/retroflex/
# dental stops + nasals). Before labials, liquids, sibilants, and at run end
# it reads 'm' — the way casual Telugu is actually typed: "andaru"/"intlo"/
# "sangham" but "pampu"/"kalpavrukshamlaa"/"samvatsaram"/"pustakam".
_N_BEFORE = frozenset("kgcjtdnṭḍṇ")

# Straight one-way character/digraph swaps applied AFTER the context-sensitive
# rules (vocalic r, anusvara, the c→ch shuffle) have run.
_CASUAL_MAP = (
    ("ā", "aa"),  # ā
    ("ī", "ee"),  # ī
    ("ū", "oo"),  # ū
    ("ē", "e"),   # ē — casual Telugu writes "prema", "emi"
    ("ō", "o"),   # ō — "lo", "arogyam"
    ("ṭ", "t"),   # ṭ
    ("ḍ", "d"),   # ḍ
    ("ṇ", "n"),   # ṇ
    ("ḷ", "l"),   # ḷ
    ("ḻ", "l"),   # ḻ
    ("ṟ", "r"),   # ṟ
    ("ś", "sh"),  # ś
    ("ṣ", "sh"),  # ṣ
    ("ñ", "n"),   # ñ
    ("ṅ", "n"),   # ṅ
    ("ḥ", "h"),   # ḥ (visarga)
)


def _casualize(iso: str) -> str:
    """ISO-15919 → casual Tanglish. Pure string rules, order-sensitive."""
    s = iso

    # Vocalic r (ISO: r + combining ring below U+0325, optionally + macron for
    # the long form) — must run before anything else touches 'r'.
    s = s.replace("r̥̄", "ruu").replace("r̥", "ru")

    # Anusvara: n before stops, m everywhere else (labials, liquids,
    # sibilants, run end) — see _N_BEFORE.
    out = []
    for i, ch in enumerate(s):
        if ch == _ANUSVARA:
            nxt = s[i + 1] if i + 1 < len(s) else ""
            out.append("n" if (nxt.isalpha() and nxt.lower() in _N_BEFORE) else "m")
        else:
            out.append(ch)
    s = "".join(out)

    # చ family: ISO 'c' reads academic; casual Telugu writes "ch". The
    # aspirated ఛ is ISO 'ch' and must not double-convert, so park it first.
    s = s.replace("ch", "\x01").replace("c", "ch").replace("\x01", "chh")

    for src, dst in _CASUAL_MAP:
        s = s.replace(src, dst)

    # Safety net: no dots/macrons anywhere in the output, ever. Decompose,
    # drop combining marks, drop any straggler non-ASCII.
    s = unicodedata.normalize("NFD", s)
    return "".join(ch for ch in s if ord(ch) < 128 and not unicodedata.combining(ch))


def telugu_to_tanglish(text: str) -> str:
    """Casual-romanize the Telugu-script runs of *text*; pass everything else
    (Latin, digits, punctuation) through untouched. Pure and deterministic."""
    if not text:
        return text

    def _convert(match: re.Match) -> str:
        run = match.group(0).replace("‌", "").replace("‍", "")
        if not run:
            return ""
        iso = sanscript.transliterate(run, sanscript.TELUGU, sanscript.ISO)
        return _casualize(iso)

    return _TELUGU_RUN.sub(_convert, text)


def ensure_word_tanglish(transcript: dict) -> int:
    """Backfill `word_tanglish` beside `word` wherever it's missing, in both
    transcript shapes (Sarvam flat word_timestamps, whisper nested
    segments[].words). Mutates *transcript* in place; returns how many words
    were filled (0 = already complete, nothing to persist)."""
    filled = 0
    for w in transcript.get("word_timestamps") or []:
        if isinstance(w, dict) and "word" in w and w.get("word_tanglish") is None:
            w["word_tanglish"] = telugu_to_tanglish(w["word"])
            filled += 1
    for seg in transcript.get("segments") or []:
        for w in (seg.get("words") or []) if isinstance(seg, dict) else []:
            if isinstance(w, dict) and "word" in w and w.get("word_tanglish") is None:
                w["word_tanglish"] = telugu_to_tanglish(w["word"])
                filled += 1
    return filled
