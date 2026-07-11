from pydantic import BaseModel
from typing import Optional, List, Any
from enum import Enum


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


class TranscriptEdits(BaseModel):
    wordEdits:    List[Any] = []   # [{ref:{type,index|segIndex+wordIndex}, word, start, end}]
    mergedGroups: List[int] = []   # lineIdx values where adjacent lines are merged
    lineSplits:   List[int] = []   # rawIndex values where forced line breaks occur


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
    elements:         Optional[List[dict]]      = None  # EditDocument overlay elements (progress/logo/headline/sticker) — None/[] renders exactly as today
    caption_font:     Optional[str]             = None  # bundled caption font (Noto Sans Telugu default, Ramabhadra/Mandali selectable) — None → default
    caption_x:        Optional[float]           = None  # caption center X (0–1); None = unpositioned → default centered path (Stage 6)
    caption_y:        Optional[float]           = None  # caption center Y (0–1); None = unpositioned → default 84% path (Stage 6)


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