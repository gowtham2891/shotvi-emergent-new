"""
ClipForge AI — TEST: Deepgram Nova-3 for Telugu + native word timestamps
=========================================================================
No chunking needed: the pre-recorded endpoint accepts long files directly
(hours-long audio is fine) and returns word-level timestamps natively.

Runs the SAME file through two configs so you can compare Tenglish handling:
  1. language=te     (monolingual Telugu — watch what happens to English words)
  2. language=multi  (code-switching mode — Telugu is NOT officially in the
                      supported set; included to see actual behavior)

Output matches transcriber.py conventions:
  transcript.json (same dict shape), words.srt, sentences.srt

Setup:  pip install requests python-dotenv        (ffmpeg on PATH)
        Add DEEPGRAM_API_KEY to your .env
Usage:  python test_deepgram_nova3.py video.mp4
        python test_deepgram_nova3.py video.mp4 --outdir dg_test_out
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

load_dotenv()

DEEPGRAM_API_URL = "https://api.deepgram.com/v1/listen"
DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY", "")


def extract_audio(input_path: str, out_wav: str) -> None:
    cmd = ["ffmpeg", "-y", "-i", input_path,
           "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", out_wav]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr[-2000:], file=sys.stderr)
        sys.exit(f"ffmpeg failed with code {result.returncode}")


def transcribe_deepgram(wav_path: str, language: str) -> dict:
    params = {
        "model": "nova-3",
        "language": language,
        "smart_format": "true",   # punctuation + formatting (needed for sentence building)
        "punctuate": "true",
    }
    with open(wav_path, "rb") as f:
        r = requests.post(
            DEEPGRAM_API_URL,
            headers={"Authorization": f"Token {DEEPGRAM_API_KEY}",
                     "Content-Type": "audio/wav"},
            params=params,
            data=f,          # streams the file; fine for long audio
            timeout=600,
        )
    if r.status_code != 200:
        raise RuntimeError(f"Deepgram error {r.status_code}: {r.text[:300]}")
    return r.json()


def parse_result(data: dict) -> dict:
    """Convert Deepgram response to transcriber.py's shape."""
    alt = data["results"]["channels"][0]["alternatives"][0]
    full_text = alt.get("transcript", "")

    word_timestamps = []
    for w in alt.get("words", []):
        word = (w.get("punctuated_word") or w.get("word") or "").strip()
        if not word:
            continue
        word_timestamps.append({
            "word":      word,
            "has_punct": word[-1] in ".?!।",
            "start":     round(w["start"], 3),
            "end":       round(w["end"], 3),
            "language":  w.get("language"),  # populated in multi mode
            "confidence": round(w.get("confidence", 0.0), 3),
        })
    return {"text": full_text, "words": word_timestamps}


def build_sentences(timed_words: list) -> list:
    sentences, current, sent_id = [], [], 0
    for w in timed_words:
        current.append(w)
        if w["has_punct"]:
            text = " ".join(cw["word"] for cw in current)
            start, end = current[0]["start"], current[-1]["end"]
            if text.strip() and end > start:
                sentences.append({"id": sent_id, "text": text,
                                  "start": round(start, 3), "end": round(end, 3)})
                sent_id += 1
            current = []
    if current:
        text = " ".join(cw["word"] for cw in current)
        start, end = current[0]["start"], current[-1]["end"]
        if text.strip() and end > start:
            sentences.append({"id": sent_id, "text": text,
                              "start": round(start, 3), "end": round(end, 3)})
    return sentences


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


def run_config(wav_path: str, language: str, outdir: Path) -> None:
    label = f"nova-3 / language={language}"
    print(f"\n[Deepgram] {label} ... ", end="", flush=True)
    t0 = time.time()
    try:
        raw = transcribe_deepgram(wav_path, language)
    except Exception as e:
        print(f"FAILED: {e}")
        return
    elapsed = round(time.time() - t0, 1)

    parsed = parse_result(raw)
    sentences = build_sentences(parsed["words"])
    print(f"{len(parsed['words'])} words, {len(sentences)} sentences, {elapsed}s")

    # Tenglish survival check: how many Latin-script words came through?
    latin = [w for w in parsed["words"] if w["word"][0].isascii() and w["word"][0].isalpha()]
    print(f"  Latin-script (likely English) words in output: {len(latin)}")
    if latin[:8]:
        print(f"  e.g. {', '.join(w['word'] for w in latin[:8])}")

    sub = outdir / f"lang_{language}"
    sub.mkdir(parents=True, exist_ok=True)
    result = {
        "text":                    parsed["text"],
        "language":                language,
        "sentences":               sentences,
        "word_timestamps":         parsed["words"],
        "total_sentences":         len(sentences),
        "total_words":             len(parsed["words"]),
        "failed_chunks":           [],
        "asr_model":               f"deepgram/{label} (native word timestamps)",
        "processing_time_seconds": elapsed,
    }
    (sub / "transcript.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    write_srt(parsed["words"], sub / "words.srt", "word")
    write_srt(sentences, sub / "sentences.srt", "text")

    print(f"  First 5 sentences:")
    for s in sentences[:5]:
        print(f"    [{s['start']:.3f}s - {s['end']:.3f}s] {s['text'][:60]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--outdir", default="deepgram_test_out")
    args = ap.parse_args()

    if not DEEPGRAM_API_KEY:
        sys.exit("DEEPGRAM_API_KEY not set (env var or .env file).")

    outdir = Path(args.outdir)
    outdir.mkdir(exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        wav_path = str(Path(tmp) / "full.wav")
        print("[Audio] Extracting 16kHz mono wav...")
        extract_audio(args.input, wav_path)

        run_config(wav_path, "te", outdir)      # monolingual Telugu
        run_config(wav_path, "multi", outdir)   # code-switching mode (unofficial for te)

    print(f"\nOutputs in {outdir}/lang_te and {outdir}/lang_multi")
    print("Compare words.srt against your Saaras+CTC words.srt in VLC.")


if __name__ == "__main__":
    main()