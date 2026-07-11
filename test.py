"""
ClipForge AI — TEST: Saaras v3 native word timestamps for LONG audio
=====================================================================
Tests the replacement for transcribe_long_audio_sarvam():
  Batch API + CTC alignment  -->  chunked REST + native word timestamps

Uses the SAME conventions as transcriber.py:
  - requests-based REST call (identical to your working transcribe_with_sarvam)
  - .env / SARVAM_API_KEY via dotenv
  - _build_sentences_from_punctuation / _split-style sentence building
  - same output dict shape (text, sentences, word_timestamps, ...)

Setup:  pip install requests pydub python-dotenv   (ffmpeg on PATH)
Usage:  python test_long_rest.py video.mp4
        python test_long_rest.py video.mp4 --mode verbatim --outdir myout
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests
from dotenv import load_dotenv
from pydub import AudioSegment
from pydub.silence import detect_silence

load_dotenv()

# ============================================================
# CONFIG (same names as transcriber.py)
# ============================================================

SARVAM_API_URL = "https://api.sarvam.ai/speech-to-text"
SARVAM_API_KEY = os.environ.get("SARVAM_API_KEY", "")

MAX_CHUNK_SECONDS   = 28.0   # REST endpoint designed for <30s
MIN_CHUNK_SECONDS   = 5.0    # don't create uselessly tiny chunks
MIN_SILENCE_MS      = 250
SILENCE_THRESH_DBFS = -32    # was -38; raised because your video had music/continuous speech


# ============================================================
# AUDIO PREP
# ============================================================

def extract_audio(input_path: str, out_wav: str) -> None:
    """Extract 16kHz mono wav. Surfaces ffmpeg stderr on failure."""
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
        out_wav,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr[-2000:], file=sys.stderr)
        sys.exit(f"ffmpeg failed with code {result.returncode}")


def find_cut_points(audio: AudioSegment) -> list:
    """Split into chunks <= MAX_CHUNK_SECONDS at detected silences."""
    total_sec = len(audio) / 1000.0
    silences = detect_silence(
        audio, min_silence_len=MIN_SILENCE_MS, silence_thresh=SILENCE_THRESH_DBFS
    )
    candidates = [(s + e) / 2 / 1000.0 for s, e in silences]

    chunks = []
    start = 0.0
    hard_cuts = 0
    while start < total_sec:
        hard_limit = start + MAX_CHUNK_SECONDS
        if hard_limit >= total_sec:
            chunks.append((start, total_sec))
            break
        viable = [c for c in candidates if start + MIN_CHUNK_SECONDS < c <= hard_limit]
        if viable:
            cut = viable[-1]
        else:
            cut = hard_limit
            hard_cuts += 1
        chunks.append((start, cut))
        start = cut

    if hard_cuts:
        print(f"  [Chunk] WARNING: {hard_cuts}/{len(chunks)} chunks hard-cut "
              f"(no silence found). Try SILENCE_THRESH_DBFS = -28 or -25 if this stays high.")
    return chunks


# ============================================================
# SARVAM REST (identical pattern to your transcribe_with_sarvam)
# ============================================================

def transcribe_chunk_rest(wav_path: str, language_code: str, mode: str,
                          max_retries: int = 3) -> dict:
    last_err = None
    for attempt in range(max_retries):
        try:
            with open(wav_path, "rb") as f:
                response = requests.post(
                    SARVAM_API_URL,
                    headers={"api-subscription-key": SARVAM_API_KEY},
                    files={"file": (os.path.basename(wav_path), f, "audio/wav")},
                    data={
                        "model":           "saaras:v3",
                        "mode":            mode,
                        "language_code":   language_code,
                        "with_timestamps": "true",
                    },
                    timeout=120,
                )
            if response.status_code == 429:
                wait = 2 ** attempt
                print(f"rate-limited, retrying in {wait}s... ", end="", flush=True)
                time.sleep(wait)
                continue
            if response.status_code != 200:
                raise RuntimeError(
                    f"Sarvam API error {response.status_code}: {response.text[:300]}"
                )
            return response.json()
        except requests.RequestException as e:
            last_err = e
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Sarvam request failed after {max_retries} retries: {last_err}")


def parse_word_timestamps(data: dict, offset: float, chunk_idx: int) -> list:
    """Parse timestamps object, offset to global timeline. Same parsing as your code."""
    word_timestamps = []
    timestamps_data = data.get("timestamps")
    if timestamps_data:
        words  = timestamps_data.get("words", [])
        starts = timestamps_data.get("start_time_seconds", [])
        ends   = timestamps_data.get("end_time_seconds", [])
        for i, word in enumerate(words):
            w = str(word).strip()
            if not w:
                continue
            word_timestamps.append({
                "word":      w,
                "has_punct": w[-1] in ".?!।",
                "start":     round(offset + (starts[i] if i < len(starts) else 0.0), 3),
                "end":       round(offset + (ends[i]   if i < len(ends)   else 0.0), 3),
                "chunk":     chunk_idx,
            })
    return word_timestamps


# ============================================================
# SENTENCE BUILDING (copied from your transcriber.py)
# ============================================================

def _build_sentences_from_punctuation(timed_words: list) -> list:
    sentences     = []
    current_words = []
    sent_id       = 0

    for w in timed_words:
        current_words.append(w)
        if w["has_punct"]:
            text  = " ".join(cw["word"] for cw in current_words)
            start = current_words[0]["start"]
            end   = current_words[-1]["end"]
            if text.strip() and end > start:
                sentences.append({
                    "id": sent_id, "text": text,
                    "start": round(start, 3), "end": round(end, 3),
                })
                sent_id += 1
            current_words = []

    if current_words:
        text  = " ".join(cw["word"] for cw in current_words)
        start = current_words[0]["start"]
        end   = current_words[-1]["end"]
        if text.strip() and end > start:
            sentences.append({
                "id": sent_id, "text": text,
                "start": round(start, 3), "end": round(end, 3),
            })
    return sentences


# ============================================================
# MAIN TEST PIPELINE (this becomes transcribe_long_audio_sarvam_rest)
# ============================================================

def transcribe_long_audio_rest(input_path: str, language_code: str = "te-IN",
                               mode: str = "codemix") -> dict:
    t0 = time.time()

    with tempfile.TemporaryDirectory() as tmp:
        wav_path = str(Path(tmp) / "full.wav")
        print("  [Audio] Extracting 16kHz mono wav...")
        extract_audio(input_path, wav_path)
        audio = AudioSegment.from_wav(wav_path)
        duration = len(audio) / 1000.0
        print(f"  [Audio] Duration: {duration:.1f}s")

        chunks = find_cut_points(audio)
        print(f"  [Chunk] {len(chunks)} chunks "
              f"(avg {sum(e - s for s, e in chunks) / len(chunks):.1f}s)")

        all_words = []
        transcript_parts = []
        failed_chunks = []

        for i, (start, end) in enumerate(chunks):
            chunk_wav = str(Path(tmp) / f"chunk_{i:03d}.wav")
            audio[int(start * 1000):int(end * 1000)].export(chunk_wav, format="wav")
            print(f"  [Sarvam] [{i + 1}/{len(chunks)}] {start:.1f}s-{end:.1f}s ... ",
                  end="", flush=True)

            try:
                data = transcribe_chunk_rest(chunk_wav, language_code, mode)
            except Exception as e:
                print(f"FAILED: {e}")
                failed_chunks.append(i)
                continue

            transcript_parts.append(data.get("transcript", ""))
            chunk_words = parse_word_timestamps(data, offset=start, chunk_idx=i)

            if not chunk_words:
                print("no timestamps! raw response:")
                print(json.dumps(data, ensure_ascii=False)[:500])
                continue

            all_words.extend(chunk_words)
            print(f"{len(chunk_words)} words")

    full_text = " ".join(p for p in transcript_parts if p)
    sentences = _build_sentences_from_punctuation(all_words)
    elapsed = round(time.time() - t0, 1)

    return {
        "text":                    full_text,
        "language":                language_code,
        "sentences":               sentences,
        "word_timestamps":         all_words,
        "total_sentences":         len(sentences),
        "total_words":             len(all_words),
        "failed_chunks":           failed_chunks,
        "asr_model":               "sarvam/saaras:v3 (chunked REST, native timestamps)",
        "processing_time_seconds": elapsed,
    }


# ============================================================
# OUTPUT / EYEBALL HELPERS
# ============================================================

def to_srt_time(sec: float) -> str:
    ms = int(round(sec * 1000))
    h, rem = divmod(ms, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(items: list, path: Path, text_key: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for n, it in enumerate(items, 1):
            f.write(f"{n}\n{to_srt_time(it['start'])} --> {to_srt_time(it['end'])}\n"
                    f"{it[text_key]}\n\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--language", default="te-IN")
    ap.add_argument("--mode", default="codemix",
                    choices=["transcribe", "verbatim", "translit", "codemix"])
    ap.add_argument("--outdir", default="saaras_test_out")
    args = ap.parse_args()

    if not SARVAM_API_KEY:
        sys.exit("SARVAM_API_KEY not set (env var or .env file).")

    result = transcribe_long_audio_rest(args.input, args.language, args.mode)

    outdir = Path(args.outdir)
    outdir.mkdir(exist_ok=True)

    (outdir / "transcript.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    write_srt(result["word_timestamps"], outdir / "words.srt", "word")
    write_srt(result["sentences"], outdir / "sentences.srt", "text")

    print(f"\n{'=' * 60}\nRESULT\n{'=' * 60}")
    print(f"Model:     {result['asr_model']}")
    print(f"Sentences: {result['total_sentences']}")
    print(f"Words:     {result['total_words']}")
    print(f"Failed chunks: {result['failed_chunks'] or 'none'}")
    print(f"Time:      {result['processing_time_seconds']}s")
    print(f"\nFirst 10 sentences:")
    for s in result["sentences"][:10]:
        print(f"  [{s['start']:.3f}s - {s['end']:.3f}s] {s['text'][:60]}")
    print(f"\nOutputs in {outdir}\\ :")
    print(f"  transcript.json  — full result dict (same shape as transcriber.py)")
    print(f"  words.srt        — one word per cue; load in VLC next to the video")
    print(f"  sentences.srt    — sentence cues; check clip-boundary quality")


if __name__ == "__main__":
    main()