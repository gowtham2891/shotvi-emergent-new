from pydantic import BaseModel, field_validator
from typing import Optional, List, Any
from enum import Enum
import re


# BUG-007 fix: strict 6-hex-digit color validator. The value flows into FFmpeg's
# `pad=...:color=<bg_color>` filter string, so anything other than a canonical
# hex triple risks (a) FFmpeg parse failure — the endpoint used to strip the `#`
# leaving a bare `rrggbb` that FFmpeg treats as an unknown named color and fails
# on — and (b) filter-token injection via commas / colons / spaces sneaked into
# the value ("black:c=x,anullsrc" and friends). Reject anything else at the API
# boundary with a 422 instead of letting the malformed value reach FFmpeg.
_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")


class JobStatus(str, Enum):
    pending     = "pending"
    downloading = "downloading"
    transcribing = "transcribing"
    selecting   = "selecting"
    cutting     = "cutting"
    cropping    = "cropping"
    captioning  = "captioning"
    done        = "done"
    failed      = "failed"


class JobCreate(BaseModel):
    url: str
    language: str = "te"
    email: Optional[str] = None


class MetadataRequest(BaseModel):
    transcript_text: str


# Phonetic-typing support for the editable transcript (frontend
# api/transliterate.js adapter). Latin token in, Telugu candidates out.
class TransliterateRequest(BaseModel):
    text: str
    lang: str = "te"


class TransliterateResponse(BaseModel):
    suggestions: List[str] = []


# Telugu→Tanglish word derivation for the caption toggle's edit seam: when a
# word-fix commits new Telugu text, the frontend re-derives its Tanglish here
# (deterministic services/tanglish.py — NOT the IndicXlit stub above, which is
# the reverse direction). Order-preserving: tanglish[i] romanizes words[i].
class TanglishRequest(BaseModel):
    words: List[str] = []


class TanglishResponse(BaseModel):
    tanglish: List[str] = []


class TranscriptEdits(BaseModel):
    wordEdits:    List[Any] = []   # [{ref:{type,index|segIndex+wordIndex}, word, start, end}]
    mergedGroups: List[int] = []   # lineIdx values where adjacent lines are merged
    lineSplits:   List[int] = []   # rawIndex values where forced line breaks occur
    # Line-level re-alignments (Descript-style line edit with changed word
    # count). Each entry replaces ONE caption line's words with freshly
    # aligned ones INSIDE the line's fixed span: {startIdx, endIdx (raw index
    # range of the ORIGINAL words the line covered — same index space as
    # lineSplits), words: [{word, start, end, word_tanglish}], approximate}.
    # Applied AFTER line grouping (apply_line_realignments), so an entry is
    # inert unless the grouping still yields a line spanning exactly that
    # range — grouping-changed lines safely render their original words.
    lineRealignments: List[Any] = []


# POST /realign-line (line-level caption editing): the line's fixed span +
# the user's new word list in; per-word timestamps within that span out.
class RealignLineRequest(BaseModel):
    line_start: float          # clip-relative seconds — FIXED line span start
    line_end:   float          # clip-relative seconds — FIXED line span end
    words:      List[str]      # new Telugu word list (text authority)


class RealignedWord(BaseModel):
    word:          str
    start:         float       # clip-relative, within [line_start, line_end]
    end:           float
    word_tanglish: Optional[str] = None  # deterministic services/tanglish.py derivation


class RealignLineResponse(BaseModel):
    words:       List[RealignedWord]
    approximate: bool = False  # True → even-distribution fallback timing was used


class RerenderRequest(BaseModel):
    style:        str   = "bold-yellow"
    format:       str   = "9:16"
    background:   str   = "blur"        # blur | black | white | color
    bg_color:     str   = "#000000"     # hex color when background=color
    use_autocrop: bool  = True          # True=face-cropped vertical, False=original
    trim_start:   float = 0.0
    trim_end:     float = -1.0
    # New fields — all optional so old payloads continue to work unchanged
    crop_mode:        str                       = "auto"  # 'auto' | 'manual'
    transcript_edits: Optional[TranscriptEdits] = None
    crop_box:         Optional[dict]            = None    # {x,y,w,h} as 0–1 fractions of source
    selected_subject: Optional[str]             = None
    crop_keyframes:   List[dict]                = []
    version:          Optional[int]             = None
    elements:         Optional[List[dict]]      = None  # EditDocument overlay elements (progress/logo/headline) — None/[] renders exactly as today; unknown/retired types (old sticker) are skipped
    caption_font:     Optional[str]             = None  # bundled caption font (Noto Sans Telugu default, Ramabhadra/Mandali selectable) — None → default
    caption_x:        Optional[float]           = None  # caption center X (0–1); None = unpositioned → default centered path (Stage 6)
    caption_y:        Optional[float]           = None  # caption center Y (0–1); None = unpositioned → default 84% path (Stage 6)

    # BUG-001 partial fix — carry the editor's per-caption Size + Background
    # Pill through to the burn so the export reflects the Inspector state.
    # Both are optional; None → the preset's built-in defaults render exactly
    # as before this existed (byte-identical to today).
    caption_font_size: Optional[float]           = None  # 0–1 fraction of video height (same units the preview scales by)
    caption_pill:      Optional[dict]            = None  # {enabled, color: '#rrggbb', opacity: 0–1, padding, radius} — None disables the pill

    # Telugu ⇄ Tanglish caption toggle: which script the burn renders.
    # 'telugu' (default, omitted by the frontend → byte-identical old payloads)
    # or 'tanglish' (captions render word_tanglish through the same ASS path —
    # same fonts, same k-values, same \an5\pos; timestamps untouched).
    caption_script:    str                       = "telugu"

    @field_validator("bg_color")
    @classmethod
    def _bg_color_must_be_hex_triplet(cls, v: str) -> str:
        """Reject anything that is not #RRGGBB. See _HEX_COLOR above for why."""
        if not isinstance(v, str) or not _HEX_COLOR.match(v):
            raise ValueError(
                "bg_color must match ^#[0-9A-Fa-f]{6}$ (e.g. '#7c3aed'); "
                "got: %r" % (v,)
            )
        return v


# ── Billing (PHASE 2 BUILD 2) ───────────────────────────────────────────────

class PlanInfo(BaseModel):
    key:           str        # 'studio'
    name:          str        # 'Studio Plan'
    price_display: str        # '₹499/mo' (display placeholder; real price = Razorpay Plan)
    interval:      str        # 'monthly'


class BillingStatusOut(BaseModel):
    """What the frontend reads to render plan state and decide (in a future
    build) whether a paid feature is unlocked — `plan == 'studio'`."""
    plan:                str            # 'free' | 'studio'
    subscription_status: str = ""       # '' | 'created' | 'active' | 'cancelled' | 'halted' | ...
    subscription_id:     str = ""
    configured:          bool = False   # False → Razorpay env absent; UI shows a "not configured" state
    plan_info:           Optional[PlanInfo] = None  # the paid plan on offer (price/name), when configured


class SubscriptionCreateOut(BaseModel):
    """Everything Razorpay Checkout.js needs to open the payment modal."""
    subscription_id: str
    key_id:          str        # public Razorpay key id
    plan:            PlanInfo


class ClipOut(BaseModel):
    clip_id:          str
    rank:             int
    why:              str
    hook_text:        str
    virality_score:   float
    engagement_type:  str
    start:            float
    end:              float
    duration:         float
    segments:         List[dict] = []   # [{start_sent_id, end_sent_id}] — >1 entry = dead zone cut out; needed for clip-local transcript remap
    raw_path:         Optional[str] = None
    video_path:       Optional[str] = None
    vertical_path:    Optional[str] = None
    captioned_path:   Optional[str] = None
    thumbnail_path:   Optional[str] = None
    # Sprint 4: the AI face-crop as a fractional window {x,y,w,h} (0–1) over
    # the 16:9 master (raw_path). The editor initializes its crop window from
    # this; None for pre-Sprint-4 jobs (frontend falls back to a centered
    # default). The 9:16 vertical_path stays byte-identical to this window.
    default_crop_box: Optional[dict] = None


class JobOut(BaseModel):
    job_id:        str
    status:        JobStatus
    progress:      int
    current_stage: str
    video_id:      Optional[str] = None
    error:         Optional[str] = None
    clips:         Optional[List[ClipOut]] = None
    # Rerender jobs store these at the top level instead of clips[]
    captioned_path: Optional[str] = None
    vertical_path:  Optional[str] = None
    warnings:       Optional[List[str]] = None