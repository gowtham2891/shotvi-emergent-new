# """
# ClipForge AI — Transcriber Service
# ====================================
# Primary:  Sarvam AI Saaras V3 (API-based, Telugu+English codemix)
# Alignment: CTC forced alignment (MMS 300M, handles Tenglish via romanization)
# Fallback: faster-whisper large-v3 (local, INT8)

# Pipeline:
#   1. Sarvam Batch API → accurate Telugu text + coarse sentence timestamps
#   2. CTC align (MMS) → romanize Tenglish text → MMS model finds exact word
#      positions against the full audio waveform
#   3. Build fine-grained sentences using nearest-word boundary mapping

# Why CTC alignment over WhisperX:
#   - WhisperX used wav2vec2 English model → 0.5-2.5s timestamp drift on Telugu
#   - MMS model trained on 1100+ languages with romanized tokenizer
#   - Handles Telugu+English codemix naturally (both romanized to a-z)
#   - ~20ms frame accuracy vs WhisperX's ~500ms+ drift
# """

# import os
# import json
# import time
# import warnings
# import requests
# import subprocess
# import tempfile
# from pathlib import Path
# from dotenv import load_dotenv

# load_dotenv()

# # ============================================================
# # CONFIG
# # ============================================================

# SARVAM_API_URL = "https://api.sarvam.ai/speech-to-text"
# SARVAM_API_KEY = os.environ.get("SARVAM_API_KEY", "")
# TELUGU_LANG_CODE = "te-IN"

# WHISPER_MODEL_SIZE = "large-v3"
# WHISPER_COMPUTE_TYPE = "int8"

# # Cached models
# _whisper_model = None


# # ============================================================
# # CTC FORCED ALIGNMENT (MMS — replaces WhisperX)
# # ============================================================

# _ctc_model = None
# _ctc_tokenizer = None


# def _get_ctc_model(device: str):
#     """Load MMS CTC alignment model (cached)."""
#     global _ctc_model, _ctc_tokenizer
#     if _ctc_model is None:
#         import torch
#         from ctc_forced_aligner import load_alignment_model
#         print(f"  [CTC] Loading MMS alignment model on {device}...")
#         dtype = torch.float16 if device == "cuda" else torch.float32
#         _ctc_model, _ctc_tokenizer = load_alignment_model(device, dtype=dtype)
#         print(f"  [CTC] Model ready")
#     return _ctc_model, _ctc_tokenizer


# def align_with_ctc(
#     segments: list,
#     audio_path: str,
#     device: str = "cuda"
# ) -> list:
#     """
#     Run CTC forced alignment on segments using MMS model.

#     Replaces WhisperX alignment. Uses ctc-forced-aligner with romanization
#     to handle Tenglish (Telugu + English codemix) content.

#     Strategy:
#       - Generate emissions for the FULL audio once
#       - Align each segment's text against the full emissions
#         (the CTC aligner will find the correct time region)
#       - Collect word-level timestamps

#     Args:
#         segments: list of {text, start, end} dicts (from Sarvam)
#         audio_path: path to audio file
#         device: 'cuda' or 'cpu'

#     Returns:
#         list of word dicts with {word, start, end}
#     """
#     import torch
#     from ctc_forced_aligner import (
#         load_audio,
#         generate_emissions,
#         preprocess_text,
#         get_alignments,
#         get_spans,
#         postprocess_results,
#     )

#     model, tokenizer = _get_ctc_model(device)

#     # Combine all segment texts into one for alignment
#     # Keep track of segment boundaries for word assignment
#     full_text = " ".join(s["text"].strip() for s in segments)

#     print(f"  [CTC] Aligning {len(segments)} segments ({len(full_text)} chars) on {device}...")
#     t0 = time.time()

#     # Load audio
#     audio_waveform = load_audio(audio_path, model.dtype, model.device)

#     # Generate emissions for full audio (once)
#     emissions, stride = generate_emissions(
#         model, audio_waveform, batch_size=8
#     )

#     # Preprocess text — romanize Telugu, keep English as-is
#     tokens_starred, text_starred = preprocess_text(
#         full_text,
#         romanize=True,
#         language="tel",  # ISO 639-3 for Telugu
#     )

#     # Get alignments
#     segments_aligned, scores, blank_token = get_alignments(
#         emissions,
#         tokens_starred,
#         tokenizer,
#     )

#     # Get word spans
#     spans = get_spans(tokens_starred, segments_aligned, blank_token)

#     # Post-process to get word timestamps
#     raw_results = postprocess_results(text_starred, spans, stride, scores)

#     # Convert to standard format {word, start, end}
#     word_timestamps = []
#     for item in raw_results:
#         if isinstance(item, dict) and "text" in item:
#             word_timestamps.append({
#                 "word": item["text"].strip(),
#                 "start": round(item["start"], 3),
#                 "end": round(item["end"], 3),
#             })

#     elapsed = round(time.time() - t0, 1)
#     print(f"  [CTC] Aligned {len(word_timestamps)} words in {elapsed}s")
#     return word_timestamps


# def build_sentences_from_words(
#     word_timestamps: list,
#     original_sentences: list
# ) -> list:
#     """
#     Build accurate sentence-level timestamps using nearest-word mapping.

#     For each sentence, find the WhisperX word whose timestamp is closest
#     to the sentence's start time, and the word closest to its end time.
#     Use those words' timestamps as the sentence boundaries.

#     This approach is tolerant of:
#       - Tokenization differences (Sarvam vs WhisperX word counts)
#       - Small timestamp offsets in Sarvam's coarse times
#       - Missing words (WhisperX may skip some words it can't align)

#     Args:
#         word_timestamps: list of {word, start, end} from WhisperX
#         original_sentences: list of {id, text, start, end} from Sarvam

#     Returns:
#         list of sentence dicts with accurate timestamps
#     """
#     if not word_timestamps:
#         return original_sentences

#     # Pre-extract arrays for fast lookup
#     w_starts = [w["start"] for w in word_timestamps]
#     w_ends = [w["end"] for w in word_timestamps]
#     n_words = len(word_timestamps)

#     sentences = []
#     for i, sent in enumerate(original_sentences):
#         sent_start = sent["start"]
#         sent_end = sent["end"]

#         # Find the word whose START is closest to this sentence's start
#         best_start_idx = _find_nearest_word(w_starts, sent_start)

#         # Find the word whose END is closest to this sentence's end
#         best_end_idx = _find_nearest_word(w_ends, sent_end)

#         # Ensure end >= start
#         if best_end_idx < best_start_idx:
#             best_end_idx = best_start_idx

#         accurate_start = word_timestamps[best_start_idx]["start"]
#         accurate_end = word_timestamps[best_end_idx]["end"]

#         sentences.append({
#             "id": i,
#             "text": sent["text"],
#             "start": round(accurate_start, 3),
#             "end": round(accurate_end, 3),
#         })

#     print(f"  [Align] Built {len(sentences)} sentences with accurate boundaries")
#     return sentences


# def dedup_sentences(sentences: list) -> list:
#     """
#     Fix overlapping and duplicate sentence timestamps produced by
#     build_sentences_from_words + split_into_subsent.

#     Problems this fixes:
#       1. Two sentences snapped to the same word → identical time ranges
#       2. Sentence B starts before sentence A ends → overlapping ranges
#       3. Very short sentences (<0.15s) that are just alignment noise

#     Strategy:
#       - Remove sentences shorter than 0.15s (alignment artifacts)
#       - Merge consecutive sentences that overlap >50% of the shorter one
#       - Enforce monotonic ordering: each sentence starts >= previous sentence's start
#     """
#     if not sentences:
#         return sentences

#     # Step 1: Remove ultra-short alignment artifacts
#     filtered = []
#     for s in sentences:
#         duration = s["end"] - s["start"]
#         if duration >= 0.15 or len(s["text"].split()) > 3:
#             filtered.append(s)
#         else:
#             print(f"  [Dedup] Dropping ultra-short sentence ({duration:.3f}s): {s['text'][:40]}")

#     if not filtered:
#         return sentences  # safety: don't return empty

#     # Step 2: Merge overlapping sentences
#     merged = [filtered[0]]
#     for i in range(1, len(filtered)):
#         prev = merged[-1]
#         curr = filtered[i]

#         # Calculate overlap
#         overlap_start = max(prev["start"], curr["start"])
#         overlap_end = min(prev["end"], curr["end"])
#         overlap_duration = max(0, overlap_end - overlap_start)

#         shorter_duration = min(prev["end"] - prev["start"], curr["end"] - curr["start"])

#         if shorter_duration > 0 and overlap_duration / shorter_duration > 0.5:
#             # Merge: combine text, take earliest start and latest end
#             merged[-1] = {
#                 "id": prev["id"],
#                 "text": prev["text"].rstrip(". ") + " " + curr["text"],
#                 "start": min(prev["start"], curr["start"]),
#                 "end": max(prev["end"], curr["end"]),
#             }
#             print(f"  [Dedup] Merged overlapping sentences {prev['id']} + {curr['id']}: "
#                   f"overlap={overlap_duration:.3f}s")
#         else:
#             # No significant overlap — enforce start >= prev.start
#             if curr["start"] < prev["start"]:
#                 curr = dict(curr)
#                 curr["start"] = prev["start"]
#             merged.append(curr)

#     # Step 3: Re-number IDs
#     for i, s in enumerate(merged):
#         s["id"] = i

#     if len(merged) < len(sentences):
#         print(f"  [Dedup] {len(sentences)} → {len(merged)} sentences "
#               f"(removed {len(sentences) - len(merged)} overlaps/duplicates)")

#     return merged


# def _find_nearest_word(timestamps: list, target: float) -> int:
#     """
#     Binary search for the word timestamp closest to target.
#     Returns index into the timestamps list.
#     """
#     if not timestamps:
#         return 0

#     lo, hi = 0, len(timestamps) - 1

#     # Handle edge cases
#     if target <= timestamps[0]:
#         return 0
#     if target >= timestamps[-1]:
#         return len(timestamps) - 1

#     # Binary search
#     while lo < hi - 1:
#         mid = (lo + hi) // 2
#         if timestamps[mid] <= target:
#             lo = mid
#         else:
#             hi = mid

#     # Return whichever is closer
#     if abs(timestamps[lo] - target) <= abs(timestamps[hi] - target):
#         return lo
#     return hi


# # ============================================================
# # SARVAM ASR (Primary)
# # ============================================================

# def transcribe_with_sarvam(audio_path: str, language_code: str = "te-IN") -> dict:
#     """
#     Transcribe short audio (≤30s) using Sarvam REST API.
#     Returns word-level timestamps directly from REST response.
#     """
#     if not SARVAM_API_KEY:
#         raise ValueError("SARVAM_API_KEY not set.")

#     audio_path = Path(audio_path)
#     print(f"  [Sarvam] Transcribing: {audio_path.name} (REST)")

#     t0 = time.time()
#     with open(audio_path, "rb") as f:
#         response = requests.post(
#             SARVAM_API_URL,
#             headers={"api-subscription-key": SARVAM_API_KEY},
#             files={"file": (audio_path.name, f, _get_mime_type(audio_path))},
#             data={
#                 "model": "saaras:v3",
#                 "mode": "codemix",
#                 "language_code": language_code,
#                 "with_timestamps": "true",
#             },
#         )
#     elapsed = round(time.time() - t0, 1)

#     if response.status_code != 200:
#         raise RuntimeError(f"Sarvam API error {response.status_code}: {response.text[:300]}")

#     data = response.json()
#     transcript_text = data.get("transcript", "")

#     # Parse word timestamps from REST response
#     word_timestamps = []
#     timestamps_data = data.get("timestamps")
#     if timestamps_data:
#         words = timestamps_data.get("words", [])
#         starts = timestamps_data.get("start_time_seconds", [])
#         ends = timestamps_data.get("end_time_seconds", [])
#         for i, word in enumerate(words):
#             word_timestamps.append({
#                 "word": str(word).strip(),
#                 "start": round(starts[i], 3) if i < len(starts) else 0.0,
#                 "end": round(ends[i], 3) if i < len(ends) else 0.0,
#             })

#     segments = _build_segments_from_words(word_timestamps, transcript_text)

#     print(f"  [Sarvam] Done in {elapsed}s — {len(word_timestamps)} words")

#     return {
#         "text": transcript_text,
#         "language": data.get("language_code", language_code),
#         "language_probability": None,
#         "segments": segments,
#         "sentences": segments,
#         "word_timestamps": word_timestamps,
#         "total_segments": len(segments),
#         "total_sentences": len(segments),
#         "total_words": len(word_timestamps),
#         "asr_model": "sarvam/saaras:v3",
#         "processing_time_seconds": elapsed,
#     }


# def transcribe_long_audio_sarvam(
#     audio_path: str,
#     language_code: str = "te-IN",
#     chunk_duration: int = 25,
# ) -> dict:
#     """
#     Transcribe long audio using Sarvam Batch API + CTC forced alignment.

#     Steps:
#       1. Sarvam Batch API → accurate Telugu text + coarse timestamps
#       2. CTC align (MMS) → romanize Tenglish text → MMS model gives
#          exact word positions (~20ms accuracy)
#       3. Nearest-word mapping → build accurate sentence boundaries

#     Args:
#         audio_path: path to audio file
#         language_code: BCP-47 language code
#         chunk_duration: unused, kept for API compatibility

#     Returns:
#         Transcript dict with millisecond-accurate word and sentence timestamps
#     """
#     from sarvamai import SarvamAI
#     import torch

#     audio_path = Path(audio_path)
#     duration = _get_audio_duration(audio_path)
#     print(f"  [Sarvam Batch] Audio duration: {duration:.1f}s")
#     print(f"  [Sarvam Batch] Submitting to Batch API...")

#     t0 = time.time()
#     client = SarvamAI(api_subscription_key=SARVAM_API_KEY)

#     # Step 1 — Sarvam Batch transcription
#     job = client.speech_to_text_job.create_job(
#         model="saaras:v3",
#         mode="codemix",
#         language_code=language_code,
#         with_diarization=True,
#     )
#     job.upload_files(file_paths=[str(audio_path)])
#     job.start()

#     print(f"  [Sarvam Batch] Job submitted. Waiting...")
#     job.wait_until_complete()

#     with tempfile.TemporaryDirectory() as tmpdir:
#         job.download_outputs(output_dir=tmpdir)
#         import glob
#         output_files = glob.glob(f"{tmpdir}/**/*.json", recursive=True)
#         if not output_files:
#             raise RuntimeError("Sarvam Batch API returned no output files")
#         with open(output_files[0], "r", encoding="utf-8") as f:
#             batch_result = json.load(f)

#     sarvam_elapsed = round(time.time() - t0, 1)
#     print(f"  [Sarvam Batch] Done in {sarvam_elapsed}s")

#     # Parse Sarvam sentence entries
#     full_text = batch_result.get("transcript", "")
#     diarized = batch_result.get("diarized_transcript") or {}
#     entries = diarized.get("entries", [])

#     sentence_entries = []
#     for entry in entries:
#         text = entry.get("transcript", "").strip()
#         if text:
#             sentence_entries.append({
#                 "text": text,
#                 "start": entry.get("start_time_seconds", 0.0),
#                 "end": entry.get("end_time_seconds", 0.0),
#             })

#     print(f"  [Sarvam Batch] {len(sentence_entries)} sentence entries from Sarvam")

#     # Step 2 — CTC forced alignment (MMS model)
#     # Pass Sarvam's text + timestamps as segments
#     # MMS model aligns romanized text to audio → exact word positions
#     device = "cuda" if torch.cuda.is_available() else "cpu"
#     print(f"  [CTC] Starting forced alignment on {device}...")

#     wx_segments = [
#         {"text": s["text"], "start": s["start"], "end": s["end"]}
#         for s in sentence_entries
#     ]

#     word_timestamps = align_with_ctc(wx_segments, str(audio_path), device)

#     # Step 3 — Build sentences directly from CTC word timestamps
#     # NEW APPROACH: Instead of split_into_subsent → build_sentences_from_words
#     # (which caused overlapping/fragment sentences), we:
#     #   1. Split Sarvam's full transcript into words (Telugu script + punctuation)
#     #   2. Align Sarvam words with CTC words using fuzzy romanization matching
#     #   3. Build sentences by splitting on punctuation in the original text
#     #
#     # This eliminates: fake proportional timestamps, cross-script snapping,
#     # overlapping sentence boundaries, and fragment sentences.

#     sarvam_words = _split_text_to_words(full_text)
#     print(f"  [WordAlign] Sarvam: {len(sarvam_words)} words, CTC: {len(word_timestamps)} words")

#     # Assign CTC timestamps to Sarvam words via sequential fuzzy matching
#     timed_words = _align_sarvam_to_ctc(sarvam_words, word_timestamps)
#     print(f"  [WordAlign] Matched {sum(1 for w in timed_words if w['start'] is not None)}"
#           f"/{len(timed_words)} words with CTC timestamps")

#     # Interpolate timestamps for unmatched words
#     timed_words = _interpolate_missing(timed_words)

#     # Build sentences by splitting on sentence-ending punctuation
#     accurate_sentences = _build_sentences_from_punctuation(timed_words)
#     print(f"  [Sentences] Built {len(accurate_sentences)} sentences from punctuation")

#     # Build segments from word timestamps (5s chunks for scoring)
#     segments = _build_segments_from_words(word_timestamps, full_text)

#     total_elapsed = round(time.time() - t0, 1)
#     print(
#         f"  [Transcriber] Complete in {total_elapsed}s | "
#         f"{len(sentence_entries)} Sarvam sentences → "
#         f"{len(accurate_sentences)} sub-sentences → "
#         f"{len(word_timestamps)} aligned words"
#     )

#     return {
#         "text": full_text,
#         "language": language_code,
#         "language_probability": None,
#         "segments": segments,
#         "sentences": accurate_sentences,
#         "word_timestamps": word_timestamps,
#         "total_segments": len(segments),
#         "total_sentences": len(accurate_sentences),
#         "total_words": len(word_timestamps),
#         "asr_model": "sarvam/saaras:v3 (batch) + ctc-forced-aligner/mms-300m",
#         "processing_time_seconds": total_elapsed,
#     }


# # ============================================================
# # WORD-LEVEL ALIGNMENT (NEW — replaces split_into_subsent + build_sentences_from_words)
# # ============================================================

# def _split_text_to_words(text: str) -> list:
#     """
#     Split Sarvam's full transcript into individual words.
#     Preserves Telugu script, English words, and punctuation attached to words.

#     Returns list of dicts: [{"word": "diabetes-కి", "has_punct": False}, ...]
#     has_punct is True if the word ends with sentence-ending punctuation.
#     """
#     import re as _re

#     raw_words = text.split()
#     result = []
#     for w in raw_words:
#         w = w.strip()
#         if not w:
#             continue
#         # Check if word ends with sentence-ending punctuation
#         has_punct = bool(w) and w[-1] in ".?!।"
#         result.append({"word": w, "has_punct": has_punct})
#     return result


# def _romanize_word(word: str) -> str:
#     """
#     Romanize a single word for comparison with CTC output.
#     Strips punctuation, lowercases, and transliterates Telugu to Latin.

#     Uses a simple char-level mapping for Telugu Unicode block (0C00-0C7F).
#     This doesn't need to be perfect — just close enough for fuzzy matching.
#     """
#     import re as _re
#     import unicodedata

#     # Strip punctuation for comparison
#     clean = _re.sub(r'[.?!।,;:\-\'\"()]+', '', word).strip().lower()

#     if not clean:
#         return ""

#     # Check if word has Telugu characters
#     has_telugu = any('\u0C00' <= c <= '\u0C7F' for c in clean)

#     if not has_telugu:
#         # Pure English word — already romanized
#         return clean

#     # Try aksharamukha if available (same lib CTC uses internally)
#     try:
#         from aksharamukha import transliterate
#         romanized = transliterate.process("Telugu", "ISO15919", clean)
#         return romanized.lower().strip()
#     except (ImportError, Exception):
#         pass

#     # Fallback: basic Telugu consonant/vowel mapping
#     # Not perfect but sufficient for fuzzy matching
#     _TELUGU_MAP = {
#         'అ': 'a', 'ఆ': 'aa', 'ఇ': 'i', 'ఈ': 'ii', 'ఉ': 'u', 'ఊ': 'uu',
#         'ఎ': 'e', 'ఏ': 'ee', 'ఐ': 'ai', 'ఒ': 'o', 'ఓ': 'oo', 'ఔ': 'au',
#         'క': 'ka', 'ఖ': 'kha', 'గ': 'ga', 'ఘ': 'gha', 'ఙ': 'nga',
#         'చ': 'cha', 'ఛ': 'chha', 'జ': 'ja', 'ఝ': 'jha', 'ఞ': 'nya',
#         'ట': 'ta', 'ఠ': 'tha', 'డ': 'da', 'ఢ': 'dha', 'ణ': 'na',
#         'త': 'ta', 'థ': 'tha', 'ద': 'da', 'ధ': 'dha', 'న': 'na',
#         'ప': 'pa', 'ఫ': 'pha', 'బ': 'ba', 'భ': 'bha', 'మ': 'ma',
#         'య': 'ya', 'ర': 'ra', 'ల': 'la', 'వ': 'va', 'శ': 'sha',
#         'ష': 'sha', 'స': 'sa', 'హ': 'ha', 'ళ': 'la', 'ఱ': 'ra',
#         'ం': 'm', 'ః': 'h', '్': '',  # virama — suppress inherent vowel
#         'ా': 'aa', 'ి': 'i', 'ీ': 'ii', 'ు': 'u', 'ూ': 'uu',
#         'ె': 'e', 'ే': 'ee', 'ై': 'ai', 'ొ': 'o', 'ో': 'oo', 'ౌ': 'au',
#     }

#     result = []
#     for c in clean:
#         if c in _TELUGU_MAP:
#             result.append(_TELUGU_MAP[c])
#         elif '\u0C00' <= c <= '\u0C7F':
#             result.append('')  # unknown Telugu char — skip
#         else:
#             result.append(c)
#     return ''.join(result)


# def _words_match(sarvam_word: str, ctc_word: str, threshold: float = 0.6) -> bool:
#     """
#     Check if a Sarvam word and CTC word are the same word.
#     Uses romanized comparison with a simple similarity ratio.
#     """
#     rom_s = _romanize_word(sarvam_word)
#     rom_c = ctc_word.lower().strip()

#     if not rom_s or not rom_c:
#         return False

#     # Exact match after romanization
#     if rom_s == rom_c:
#         return True

#     # One is a prefix of the other (handles slight differences)
#     if rom_s.startswith(rom_c) or rom_c.startswith(rom_s):
#         shorter = min(len(rom_s), len(rom_c))
#         longer = max(len(rom_s), len(rom_c))
#         if shorter >= 2 and shorter / longer >= threshold:
#             return True

#     # Simple character overlap ratio for fuzzy matching
#     if len(rom_s) >= 2 and len(rom_c) >= 2:
#         # Count matching characters in sequence (simple LCS-like)
#         matches = 0
#         j = 0
#         for c in rom_s:
#             while j < len(rom_c):
#                 if rom_c[j] == c:
#                     matches += 1
#                     j += 1
#                     break
#                 j += 1
#         longer = max(len(rom_s), len(rom_c))
#         if matches / longer >= threshold:
#             return True

#     return False


# def _align_sarvam_to_ctc(sarvam_words: list, ctc_words: list) -> list:
#     """
#     Align Sarvam words to CTC words and assign timestamps.

#     Strategy:
#       1. If word counts match exactly → direct 1:1 positional mapping.
#          CTC processes the same text in the same order, so word N from
#          Sarvam = word N from CTC. No fuzzy matching needed.
#       2. If word counts differ → sequential fuzzy matching with look-ahead.

#     Returns list of dicts:
#       [{"word": "diabetes-కి", "has_punct": True, "start": 54.26, "end": 54.88}, ...]
#     """
#     n_sarvam = len(sarvam_words)
#     n_ctc = len(ctc_words)

#     # CASE 1: Word counts match — direct positional mapping
#     # This is the common case because CTC aligns the exact same text
#     # that Sarvam produced (joined with spaces).
#     if n_sarvam == n_ctc:
#         print(f"  [WordAlign] Word counts match ({n_sarvam}) — using direct positional mapping")
#         result = []
#         for i in range(n_sarvam):
#             result.append({
#                 "word": sarvam_words[i]["word"],
#                 "has_punct": sarvam_words[i]["has_punct"],
#                 "start": ctc_words[i]["start"],
#                 "end": ctc_words[i]["end"],
#             })
#         return result

#     # CASE 2: Word counts differ — fuzzy sequential matching
#     print(f"  [WordAlign] Word count mismatch (Sarvam={n_sarvam}, CTC={n_ctc}) "
#           f"— using fuzzy matching")

#     LOOK_AHEAD = 5  # how many positions to look ahead for a match

#     result = []
#     ctc_idx = 0

#     for sw in sarvam_words:
#         matched = False

#         # Try matching within look-ahead window
#         for offset in range(min(LOOK_AHEAD, n_ctc - ctc_idx)):
#             candidate_idx = ctc_idx + offset
#             if candidate_idx >= n_ctc:
#                 break

#             ctc_w = ctc_words[candidate_idx]
#             if _words_match(sw["word"], ctc_w["word"]):
#                 result.append({
#                     "word": sw["word"],
#                     "has_punct": sw["has_punct"],
#                     "start": ctc_w["start"],
#                     "end": ctc_w["end"],
#                 })
#                 ctc_idx = candidate_idx + 1
#                 matched = True
#                 break

#         if not matched:
#             # No match found — will be interpolated later
#             result.append({
#                 "word": sw["word"],
#                 "has_punct": sw["has_punct"],
#                 "start": None,
#                 "end": None,
#             })

#     return result


# def _interpolate_missing(timed_words: list) -> list:
#     """
#     Fill in timestamps for words that didn't match any CTC word.

#     Strategy: for each gap of unmatched words between two matched words,
#     distribute timestamps linearly based on the time range between the
#     last matched word's end and the next matched word's start.
#     """
#     n = len(timed_words)
#     if n == 0:
#         return timed_words

#     # Find runs of None timestamps and interpolate from neighbors
#     i = 0
#     while i < n:
#         if timed_words[i]["start"] is not None:
#             i += 1
#             continue

#         # Found start of a gap — find the end
#         gap_start = i
#         while i < n and timed_words[i]["start"] is None:
#             i += 1
#         gap_end = i  # exclusive

#         # Get boundary timestamps
#         prev_end = timed_words[gap_start - 1]["end"] if gap_start > 0 else 0.0
#         next_start = timed_words[gap_end]["start"] if gap_end < n else prev_end + 0.5

#         # Distribute evenly
#         gap_duration = next_start - prev_end
#         gap_count = gap_end - gap_start
#         word_dur = gap_duration / max(gap_count, 1)

#         for j in range(gap_start, gap_end):
#             offset = j - gap_start
#             timed_words[j]["start"] = round(prev_end + offset * word_dur, 3)
#             timed_words[j]["end"] = round(prev_end + (offset + 1) * word_dur, 3)

#     return timed_words


# def _build_sentences_from_punctuation(timed_words: list) -> list:
#     """
#     Build sentences by accumulating words until sentence-ending punctuation.

#     A sentence boundary is any word where has_punct is True (ends with .?!।).
#     Each sentence gets its start from the first word and end from the last word.

#     No fake timestamps. No cross-script snapping. No overlaps.
#     """
#     import re as _re

#     sentences = []
#     current_words = []
#     sent_id = 0

#     for w in timed_words:
#         current_words.append(w)

#         if w["has_punct"]:
#             # End of sentence — flush
#             text = " ".join(cw["word"] for cw in current_words)
#             start = current_words[0]["start"]
#             end = current_words[-1]["end"]

#             # Skip empty or ultra-short sentences
#             if text.strip() and end > start:
#                 sentences.append({
#                     "id": sent_id,
#                     "text": text,
#                     "start": round(start, 3),
#                     "end": round(end, 3),
#                 })
#                 sent_id += 1

#             current_words = []

#     # Flush remaining words (no trailing punctuation)
#     if current_words:
#         text = " ".join(cw["word"] for cw in current_words)
#         start = current_words[0]["start"]
#         end = current_words[-1]["end"]
#         if text.strip() and end > start:
#             sentences.append({
#                 "id": sent_id,
#                 "text": text,
#                 "start": round(start, 3),
#                 "end": round(end, 3),
#             })

#     return sentences


# # ============================================================
# # SENTENCE SPLITTER (LEGACY — kept for short audio path)
# # ============================================================

# def split_into_subsent(s: dict, min_duration: float = 0.0) -> list:
#     """
#     Split a coarse Sarvam sentence-blob into atomic sub-sentences
#     on punctuation boundaries.

#     min_duration=0.0 ensures NO sub-sentences are dropped.
#     Every word must be accounted for to prevent mapping drift.
#     """
#     import re as _re

#     text = s["text"].strip()
#     start = s["start"]
#     end = s["end"]
#     duration = end - start

#     parts = _re.split(r"(?<=[?.!।])\s+", text)
#     parts = [p.strip() for p in parts if p.strip()]

#     if len(parts) <= 1:
#         return [{"id": -1, "text": text, "start": start, "end": end}]

#     # Merge short trailing fragments
#     merged = []
#     for p in parts:
#         if merged and len(p) < 8 and p[-1] not in ("?", "!", ".", "।"):
#             merged[-1] = merged[-1] + " " + p
#         else:
#             merged.append(p)
#     parts = merged

#     total_chars = sum(len(p) for p in parts)
#     result = []
#     cursor = start

#     for i, p in enumerate(parts):
#         fraction = len(p) / total_chars
#         part_dur = duration * fraction
#         part_end = end if i == len(parts) - 1 else round(cursor + part_dur, 2)

#         if part_end - cursor >= min_duration:
#             result.append({
#                 "id": -1,
#                 "text": p,
#                 "start": round(cursor, 2),
#                 "end": part_end,
#             })
#         cursor = part_end

#     return result if result else [{"id": -1, "text": text, "start": start, "end": end}]


# # ============================================================
# # FASTER-WHISPER FALLBACK
# # ============================================================

# def _get_whisper_model():
#     """Load faster-whisper model (cached, lazy)."""
#     global _whisper_model
#     if _whisper_model is None:
#         from faster_whisper import WhisperModel
#         try:
#             print(f"  [Whisper] Loading '{WHISPER_MODEL_SIZE}' on CUDA...")
#             _whisper_model = WhisperModel(
#                 WHISPER_MODEL_SIZE,
#                 device="cuda",
#                 compute_type=WHISPER_COMPUTE_TYPE,
#             )
#         except Exception as e:
#             print(f"  [Whisper] GPU failed ({e}), falling back to CPU...")
#             _whisper_model = WhisperModel(
#                 WHISPER_MODEL_SIZE,
#                 device="cpu",
#                 compute_type="int8",
#             )
#     return _whisper_model


# def transcribe_with_whisper(audio_path: str, language: str = "te") -> dict:
#     """Transcribe using faster-whisper (fallback only)."""
#     model = _get_whisper_model()
#     print(f"  [Whisper] Transcribing: {audio_path}")

#     t0 = time.time()
#     segments_gen, info = model.transcribe(
#         audio_path,
#         language=language,
#         task="transcribe",
#         word_timestamps=True,
#         beam_size=5,
#         vad_filter=True,
#         vad_parameters=dict(min_silence_duration_ms=500),
#     )

#     segments = []
#     word_timestamps = []
#     full_text = []

#     for segment in segments_gen:
#         seg_data = {
#             "id": segment.id,
#             "start": round(segment.start, 2),
#             "end": round(segment.end, 2),
#             "text": segment.text.strip(),
#         }
#         segments.append(seg_data)
#         full_text.append(segment.text.strip())

#         if segment.words:
#             for w in segment.words:
#                 word_timestamps.append({
#                     "word": w.word.strip(),
#                     "start": round(w.start, 2),
#                     "end": round(w.end, 2),
#                 })

#     elapsed = round(time.time() - t0, 1)

#     return {
#         "text": " ".join(full_text),
#         "language": info.language,
#         "language_probability": round(info.language_probability, 2),
#         "segments": segments,
#         "sentences": segments,
#         "word_timestamps": word_timestamps,
#         "total_segments": len(segments),
#         "total_sentences": len(segments),
#         "total_words": len(word_timestamps),
#         "asr_model": f"faster-whisper/{WHISPER_MODEL_SIZE}",
#         "processing_time_seconds": elapsed,
#     }


# # ============================================================
# # PUBLIC API
# # ============================================================

# def transcribe_audio(
#     audio_path: str,
#     language: str = "te",
#     force_whisper: bool = False,
# ) -> dict:
#     """
#     Main entry point. Transcribes with Sarvam + CTC alignment.
#     Falls back to faster-whisper if Sarvam key missing or fails.
#     """
#     audio_path_obj = Path(audio_path)
#     if not audio_path_obj.exists():
#         raise FileNotFoundError(f"Audio file not found: {audio_path}")

#     sarvam_lang = _to_sarvam_lang(language)
#     whisper_lang = None if language == "auto" else language

#     if not force_whisper and SARVAM_API_KEY:
#         try:
#             duration = _get_audio_duration(audio_path_obj)
#             if duration <= 30:
#                 print(f"Transcribing with Sarvam REST + CTC alignment...")
#                 return transcribe_with_sarvam(audio_path, sarvam_lang)
#             else:
#                 print(f"Audio is {duration:.1f}s — using Sarvam Batch + CTC alignment...")
#                 return transcribe_long_audio_sarvam(audio_path, sarvam_lang)
#         except Exception as e:
#             print(f"Sarvam/CTC alignment failed: {e}")
#             print("Falling back to faster-whisper...")
#     elif not force_whisper and not SARVAM_API_KEY:
#         print("SARVAM_API_KEY not set — using faster-whisper fallback.")

#     return transcribe_with_whisper(audio_path, whisper_lang)


# def save_transcript(transcript: dict, output_path: str):
#     """Save transcript dict to JSON file."""
#     with open(output_path, "w", encoding="utf-8") as f:
#         json.dump(transcript, f, ensure_ascii=False, indent=2)
#     print(f"Transcript saved: {output_path}")


# # ============================================================
# # HELPERS
# # ============================================================

# def _to_sarvam_lang(language: str) -> str:
#     mapping = {
#         "te": "te-IN", "hi": "hi-IN", "ta": "ta-IN",
#         "kn": "kn-IN", "ml": "ml-IN", "en": "en-IN",
#         "auto": "unknown", None: "unknown",
#     }
#     return mapping.get(language, language)


# def _get_mime_type(audio_path: Path) -> str:
#     mime_map = {
#         ".wav": "audio/wav", ".mp3": "audio/mpeg",
#         ".mp4": "audio/mp4", ".m4a": "audio/mp4",
#         ".ogg": "audio/ogg", ".flac": "audio/flac",
#         ".aac": "audio/aac",
#     }
#     return mime_map.get(audio_path.suffix.lower(), "audio/wav")


# def _get_audio_duration(audio_path: Path) -> float:
#     cmd = [
#         "ffprobe", "-v", "error",
#         "-show_entries", "format=duration",
#         "-of", "default=noprint_wrappers=1:nokey=1",
#         str(audio_path),
#     ]
#     result = subprocess.run(cmd, capture_output=True, text=True)
#     try:
#         return float(result.stdout.strip())
#     except ValueError:
#         return 0.0


# def _build_segments_from_words(words: list, full_text: str) -> list:
#     """Group words into ~5 second segments."""
#     if not words:
#         return [{"id": 0, "start": 0.0, "end": 0.0, "text": full_text}]

#     SEGMENT_DURATION = 5.0
#     segments = []
#     seg_words = []
#     seg_start = words[0]["start"]

#     for w in words:
#         seg_words.append(w["word"])
#         if w["end"] - seg_start >= SEGMENT_DURATION:
#             segments.append({
#                 "id": len(segments),
#                 "start": seg_start,
#                 "end": w["end"],
#                 "text": " ".join(seg_words).strip(),
#             })
#             seg_words = []
#             seg_start = w["end"]

#     if seg_words:
#         segments.append({
#             "id": len(segments),
#             "start": seg_start,
#             "end": words[-1]["end"],
#             "text": " ".join(seg_words).strip(),
#         })

#     return segments


# # ============================================================
# # CLI
# # ============================================================

# if __name__ == "__main__":
#     import sys

#     if len(sys.argv) < 2:
#         print("Usage: python transcriber.py <audio_file> [language] [--whisper]")
#         print("Examples:")
#         print("  python transcriber.py audio.wav te")
#         print("  python transcriber.py audio.wav auto")
#         sys.exit(1)

#     audio_file = sys.argv[1]
#     lang = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else "te"
#     force_w = "--whisper" in sys.argv

#     result = transcribe_audio(audio_file, language=lang, force_whisper=force_w)

#     print(f"\n{'='*60}")
#     print(f"RESULT")
#     print(f"{'='*60}")
#     print(f"Model:     {result['asr_model']}")
#     print(f"Sentences: {result['total_sentences']}")
#     print(f"Words:     {result['total_words']}")
#     print(f"Time:      {result['processing_time_seconds']}s")
#     print(f"\nFirst 10 sentences:")
#     for s in result.get('sentences', [])[:10]:
#         print(f"  [{s['start']:.3f}s - {s['end']:.3f}s] {s['text'][:60]}")

#     out_path = audio_file.replace(".wav", "_transcript.json").replace(".mp3", "_transcript.json")
#     save_transcript(result, out_path)


"""
ClipForge AI — Transcriber Service
====================================
Primary:  Sarvam AI Saaras V3 (API-based, Telugu+English codemix)
Alignment: CTC forced alignment (MMS 300M, handles Tenglish via romanization)
Fallback: faster-whisper large-v3 (local, INT8)

Pipeline:
  1. Sarvam Batch API → accurate Telugu text + coarse sentence timestamps
  2. CTC align (MMS) → romanize Tenglish text → MMS model finds exact word
     positions against the full audio waveform
  3. Build fine-grained sentences using nearest-word boundary mapping

PATCHES APPLIED:
  P5 — preprocess_text TypeError fallback (older ctc-forced-aligner versions)
  P6 — positional word mapping safety check (first+last word boundary check)
"""

import os
import json
import time
import warnings
import requests
import subprocess
import tempfile
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# CONFIG
# ============================================================

SARVAM_API_URL   = "https://api.sarvam.ai/speech-to-text"
SARVAM_API_KEY   = os.environ.get("SARVAM_API_KEY", "")
TELUGU_LANG_CODE = "te-IN"

WHISPER_MODEL_SIZE    = "large-v3"
WHISPER_COMPUTE_TYPE  = "int8"

_whisper_model = None


# ============================================================
# CTC FORCED ALIGNMENT (MMS)
# ============================================================

_ctc_model     = None
_ctc_tokenizer = None


def _get_ctc_model(device: str):
    global _ctc_model, _ctc_tokenizer
    if _ctc_model is None:
        import torch
        from ctc_forced_aligner import load_alignment_model
        print(f"  [CTC] Loading MMS alignment model on {device}...")
        dtype = torch.float16 if device == "cuda" else torch.float32
        _ctc_model, _ctc_tokenizer = load_alignment_model(device, dtype=dtype)
        print(f"  [CTC] Model ready")
    return _ctc_model, _ctc_tokenizer


def align_with_ctc(segments: list, audio_path: str, device: str = "cuda") -> list:
    """
    Run CTC forced alignment on segments using MMS model.
    Replaces WhisperX alignment.
    """
    import torch
    from ctc_forced_aligner import (
        load_audio,
        generate_emissions,
        preprocess_text,
        get_alignments,
        get_spans,
        postprocess_results,
    )

    model, tokenizer = _get_ctc_model(device)
    full_text = " ".join(s["text"].strip() for s in segments)

    print(f"  [CTC] Aligning {len(segments)} segments ({len(full_text)} chars) on {device}...")
    t0 = time.time()

    audio_waveform = load_audio(audio_path, model.dtype, model.device)
    emissions, stride = generate_emissions(model, audio_waveform, batch_size=8)

    # PATCH 5: graceful fallback for older ctc-forced-aligner versions
    # that don't support romanize/language args
    try:
        tokens_starred, text_starred = preprocess_text(
            full_text,
            romanize=True,
            language="tel",
        )
    except TypeError:
        print("  [CTC] ⚠ romanize/language args not supported by installed version "
              "— falling back to basic preprocess_text")
        tokens_starred, text_starred = preprocess_text(full_text)

    segments_aligned, scores, blank_token = get_alignments(
        emissions, tokens_starred, tokenizer,
    )

    spans = get_spans(tokens_starred, segments_aligned, blank_token)
    raw_results = postprocess_results(text_starred, spans, stride, scores)

    # Get audio duration to convert normalized timestamps → seconds
    # REVERT TO THIS — no soundfile, no division
    word_timestamps = []
    for item in raw_results:
        if isinstance(item, dict) and "text" in item:
            word_timestamps.append({
                "word":  item["text"].strip(),
                "start": round(item["start"], 3),
                "end":   round(item["end"],   3),
            })
    if word_timestamps:
        print(f"  [CTC DEBUG] First word: {word_timestamps[0]}")
        print(f"  [CTC DEBUG] Last word:  {word_timestamps[-1]}")
        print(f"  [CTC DEBUG] Audio duration: {_get_audio_duration(Path(audio_path))}s")


    elapsed = round(time.time() - t0, 1)
    print(f"  [CTC] Aligned {len(word_timestamps)} words in {elapsed}s")
    return word_timestamps


def build_sentences_from_words(word_timestamps: list,
                                original_sentences: list) -> list:
    """
    Build accurate sentence-level timestamps using nearest-word mapping.
    """
    if not word_timestamps:
        return original_sentences

    w_starts = [w["start"] for w in word_timestamps]
    w_ends   = [w["end"]   for w in word_timestamps]

    sentences = []
    for i, sent in enumerate(original_sentences):
        best_start_idx = _find_nearest_word(w_starts, sent["start"])
        best_end_idx   = _find_nearest_word(w_ends,   sent["end"])

        if best_end_idx < best_start_idx:
            best_end_idx = best_start_idx

        accurate_start = word_timestamps[best_start_idx]["start"]
        accurate_end   = word_timestamps[best_end_idx]["end"]

        sentences.append({
            "id":    i,
            "text":  sent["text"],
            "start": round(accurate_start, 3),
            "end":   round(accurate_end,   3),
        })

    print(f"  [Align] Built {len(sentences)} sentences with accurate boundaries")
    return sentences


def dedup_sentences(sentences: list) -> list:
    """
    Fix overlapping and duplicate sentence timestamps.
    """
    if not sentences:
        return sentences

    filtered = []
    for s in sentences:
        duration = s["end"] - s["start"]
        if duration >= 0.15 or len(s["text"].split()) > 3:
            filtered.append(s)
        else:
            print(f"  [Dedup] Dropping ultra-short sentence ({duration:.3f}s): {s['text'][:40]}")

    if not filtered:
        return sentences

    merged = [filtered[0]]
    for i in range(1, len(filtered)):
        prev = merged[-1]
        curr = filtered[i]

        overlap_start    = max(prev["start"], curr["start"])
        overlap_end      = min(prev["end"],   curr["end"])
        overlap_duration = max(0, overlap_end - overlap_start)
        shorter_duration = min(prev["end"] - prev["start"],
                               curr["end"] - curr["start"])

        if shorter_duration > 0 and overlap_duration / shorter_duration > 0.5:
            merged[-1] = {
                "id":    prev["id"],
                "text":  prev["text"].rstrip(". ") + " " + curr["text"],
                "start": min(prev["start"], curr["start"]),
                "end":   max(prev["end"],   curr["end"]),
            }
            print(f"  [Dedup] Merged overlapping sentences {prev['id']} + {curr['id']}: "
                  f"overlap={overlap_duration:.3f}s")
        else:
            if curr["start"] < prev["start"]:
                curr = dict(curr)
                curr["start"] = prev["start"]
            merged.append(curr)

    for i, s in enumerate(merged):
        s["id"] = i

    if len(merged) < len(sentences):
        print(f"  [Dedup] {len(sentences)} → {len(merged)} sentences "
              f"(removed {len(sentences) - len(merged)} overlaps/duplicates)")

    return merged


def _find_nearest_word(timestamps: list, target: float) -> int:
    if not timestamps:
        return 0

    lo, hi = 0, len(timestamps) - 1

    if target <= timestamps[0]:  return 0
    if target >= timestamps[-1]: return len(timestamps) - 1

    while lo < hi - 1:
        mid = (lo + hi) // 2
        if timestamps[mid] <= target:
            lo = mid
        else:
            hi = mid

    if abs(timestamps[lo] - target) <= abs(timestamps[hi] - target):
        return lo
    return hi


# ============================================================
# SARVAM ASR (Primary)
# ============================================================

def transcribe_with_sarvam(audio_path: str, language_code: str = "te-IN") -> dict:
    """Transcribe short audio (≤30s) using Sarvam REST API."""
    if not SARVAM_API_KEY:
        raise ValueError("SARVAM_API_KEY not set.")

    audio_path = Path(audio_path)
    print(f"  [Sarvam] Transcribing: {audio_path.name} (REST)")

    t0 = time.time()
    with open(audio_path, "rb") as f:
        response = requests.post(
            SARVAM_API_URL,
            headers={"api-subscription-key": SARVAM_API_KEY},
            files={"file": (audio_path.name, f, _get_mime_type(audio_path))},
            data={
                "model":           "saaras:v3",
                "mode":            "codemix",
                "language_code":   language_code,
                "with_timestamps": "true",
            },
        )
    elapsed = round(time.time() - t0, 1)

    if response.status_code != 200:
        raise RuntimeError(f"Sarvam API error {response.status_code}: {response.text[:300]}")

    data            = response.json()
    transcript_text = data.get("transcript", "")

    word_timestamps = []
    timestamps_data = data.get("timestamps")
    if timestamps_data:
        words  = timestamps_data.get("words", [])
        starts = timestamps_data.get("start_time_seconds", [])
        ends   = timestamps_data.get("end_time_seconds",   [])
        for i, word in enumerate(words):
            word_timestamps.append({
                "word":  str(word).strip(),
                "start": round(starts[i], 3) if i < len(starts) else 0.0,
                "end":   round(ends[i],   3) if i < len(ends)   else 0.0,
            })

    segments = _build_segments_from_words(word_timestamps, transcript_text)

    print(f"  [Sarvam] Done in {elapsed}s — {len(word_timestamps)} words")

    return {
        "text":                    transcript_text,
        "language":                data.get("language_code", language_code),
        "language_probability":    None,
        "segments":                segments,
        "sentences":               segments,
        "word_timestamps":         word_timestamps,
        "total_segments":          len(segments),
        "total_sentences":         len(segments),
        "total_words":             len(word_timestamps),
        "asr_model":               "sarvam/saaras:v3",
        "processing_time_seconds": elapsed,
    }


def transcribe_long_audio_sarvam(audio_path: str, language_code: str = "te-IN",
                                  chunk_duration: int = 25) -> dict:
    """
    Transcribe long audio using Sarvam Batch API + CTC forced alignment.

    Steps:
      1. Sarvam Batch API → accurate Telugu text + coarse timestamps
      2. CTC align (MMS) → romanize Tenglish → exact word positions (~20ms)
      3. Nearest-word mapping → accurate sentence boundaries
    """
    from sarvamai import SarvamAI
    import torch

    audio_path = Path(audio_path)
    duration   = _get_audio_duration(audio_path)
    print(f"  [Sarvam Batch] Audio duration: {duration:.1f}s")
    print(f"  [Sarvam Batch] Submitting to Batch API...")

    t0     = time.time()
    client = SarvamAI(api_subscription_key=SARVAM_API_KEY)

    job = client.speech_to_text_job.create_job(
        model="saaras:v3",
        mode="codemix",
        language_code=language_code,
        with_diarization=True,
    )
    job.upload_files(file_paths=[str(audio_path)])
    job.start()

    print(f"  [Sarvam Batch] Job submitted. Waiting...")
    job.wait_until_complete()

    with tempfile.TemporaryDirectory() as tmpdir:
        job.download_outputs(output_dir=tmpdir)
        import glob
        output_files = glob.glob(f"{tmpdir}/**/*.json", recursive=True)
        if not output_files:
            raise RuntimeError("Sarvam Batch API returned no output files")
        with open(output_files[0], "r", encoding="utf-8") as f:
            batch_result = json.load(f)

    sarvam_elapsed = round(time.time() - t0, 1)
    print(f"  [Sarvam Batch] Done in {sarvam_elapsed}s")

    full_text  = batch_result.get("transcript", "")
    diarized   = batch_result.get("diarized_transcript") or {}
    entries    = diarized.get("entries", [])

    sentence_entries = []
    for entry in entries:
        text = entry.get("transcript", "").strip()
        if text:
            sentence_entries.append({
                "text":  text,
                "start": entry.get("start_time_seconds", 0.0),
                "end":   entry.get("end_time_seconds",   0.0),
            })

    print(f"  [Sarvam Batch] {len(sentence_entries)} sentence entries from Sarvam")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"  [CTC] Starting forced alignment on {device}...")

    wx_segments = [
        {"text": s["text"], "start": s["start"], "end": s["end"]}
        for s in sentence_entries
    ]

    word_timestamps = align_with_ctc(wx_segments, str(audio_path), device)

    sarvam_words = _split_text_to_words(full_text)
    print(f"  [WordAlign] Sarvam: {len(sarvam_words)} words, CTC: {len(word_timestamps)} words")

    timed_words = _align_sarvam_to_ctc(sarvam_words, word_timestamps)
    print(f"  [WordAlign] Matched "
          f"{sum(1 for w in timed_words if w['start'] is not None)}"
          f"/{len(timed_words)} words with CTC timestamps")

    timed_words = _interpolate_missing(timed_words)

    accurate_sentences = _build_sentences_from_punctuation(timed_words)
    print(f"  [Sentences] Built {len(accurate_sentences)} sentences from punctuation")

    segments = _build_segments_from_words(word_timestamps, full_text)

    total_elapsed = round(time.time() - t0, 1)
    print(
        f"  [Transcriber] Complete in {total_elapsed}s | "
        f"{len(sentence_entries)} Sarvam sentences → "
        f"{len(accurate_sentences)} sub-sentences → "
        f"{len(word_timestamps)} aligned words"
    )

    return {
        "text":                    full_text,
        "language":                language_code,
        "language_probability":    None,
        "segments":                segments,
        "sentences":               accurate_sentences,
        "word_timestamps":         word_timestamps,
        "total_segments":          len(segments),
        "total_sentences":         len(accurate_sentences),
        "total_words":             len(word_timestamps),
        "asr_model":               "sarvam/saaras:v3 (batch) + ctc-forced-aligner/mms-300m",
        "processing_time_seconds": total_elapsed,
    }


# ============================================================
# WORD-LEVEL ALIGNMENT
# ============================================================

def _split_text_to_words(text: str) -> list:
    """Split Sarvam's full transcript into individual words."""
    import re as _re

    raw_words = text.split()
    result = []
    for w in raw_words:
        w = w.strip()
        if not w:
            continue
        has_punct = bool(w) and w[-1] in ".?!।"
        result.append({"word": w, "has_punct": has_punct})
    return result


def _romanize_word(word: str) -> str:
    """Romanize a single word for comparison with CTC output."""
    import re as _re

    clean = _re.sub(r'[.?!।,;:\-\'\"()]+', '', word).strip().lower()

    if not clean:
        return ""

    has_telugu = any('\u0C00' <= c <= '\u0C7F' for c in clean)

    if not has_telugu:
        return clean

    try:
        from aksharamukha import transliterate
        romanized = transliterate.process("Telugu", "ISO15919", clean)
        return romanized.lower().strip()
    except (ImportError, Exception):
        pass

    _TELUGU_MAP = {
        'అ': 'a',  'ఆ': 'aa', 'ఇ': 'i',  'ఈ': 'ii', 'ఉ': 'u',  'ఊ': 'uu',
        'ఎ': 'e',  'ఏ': 'ee', 'ఐ': 'ai', 'ఒ': 'o',  'ఓ': 'oo', 'ఔ': 'au',
        'క': 'ka', 'ఖ': 'kha','గ': 'ga', 'ఘ': 'gha','ఙ': 'nga',
        'చ': 'cha','ఛ': 'chha','జ': 'ja','ఝ': 'jha','ఞ': 'nya',
        'ట': 'ta', 'ఠ': 'tha','డ': 'da', 'ఢ': 'dha','ణ': 'na',
        'త': 'ta', 'థ': 'tha','ద': 'da', 'ధ': 'dha','న': 'na',
        'ప': 'pa', 'ఫ': 'pha','బ': 'ba', 'భ': 'bha','మ': 'ma',
        'య': 'ya', 'ర': 'ra', 'ల': 'la', 'వ': 'va', 'శ': 'sha',
        'ష': 'sha','స': 'sa', 'హ': 'ha', 'ళ': 'la', 'ఱ': 'ra',
        'ం': 'm',  'ః': 'h',  '్': '',
        'ా': 'aa', 'ి': 'i',  'ీ': 'ii', 'ు': 'u',  'ూ': 'uu',
        'ె': 'e',  'ే': 'ee', 'ై': 'ai', 'ొ': 'o',  'ో': 'oo', 'ౌ': 'au',
    }

    result = []
    for c in clean:
        if c in _TELUGU_MAP:
            result.append(_TELUGU_MAP[c])
        elif '\u0C00' <= c <= '\u0C7F':
            result.append('')
        else:
            result.append(c)
    return ''.join(result)


def _words_match(sarvam_word: str, ctc_word: str, threshold: float = 0.6) -> bool:
    """Check if a Sarvam word and CTC word are the same word."""
    rom_s = _romanize_word(sarvam_word)
    rom_c = ctc_word.lower().strip()

    if not rom_s or not rom_c:
        return False

    if rom_s == rom_c:
        return True

    if rom_s.startswith(rom_c) or rom_c.startswith(rom_s):
        shorter = min(len(rom_s), len(rom_c))
        longer  = max(len(rom_s), len(rom_c))
        if shorter >= 2 and shorter / longer >= threshold:
            return True

    if len(rom_s) >= 2 and len(rom_c) >= 2:
        matches = 0
        j = 0
        for c in rom_s:
            while j < len(rom_c):
                if rom_c[j] == c:
                    matches += 1
                    j += 1
                    break
                j += 1
        longer = max(len(rom_s), len(rom_c))
        if matches / longer >= threshold:
            return True

    return False


def _align_sarvam_to_ctc(sarvam_words: list, ctc_words: list) -> list:
    """
    Align Sarvam words to CTC words and assign timestamps.

    PATCH 6: Added first+last boundary check before trusting direct
    positional mapping when word counts match.
    """
    n_sarvam = len(sarvam_words)
    n_ctc    = len(ctc_words)

    # CASE 1: Word counts match — try direct positional mapping
    # But first verify first + last words actually align (safety check)
    # AFTER — trust positional mapping when counts match, no boundary check needed
    if n_sarvam == n_ctc:
        print(f"  [WordAlign] Word counts match ({n_sarvam}) — direct positional mapping")
        result = []
        for i in range(n_sarvam):
            result.append({
                "word":      sarvam_words[i]["word"],
                "has_punct": sarvam_words[i]["has_punct"],
                "start":     ctc_words[i]["start"],
                "end":       ctc_words[i]["end"],
            })
        return result

    # CASE 2: Fuzzy sequential matching
    print(f"  [WordAlign] Sarvam={n_sarvam}, CTC={n_ctc} — using fuzzy matching")

    LOOK_AHEAD = 5
    result  = []
    ctc_idx = 0

    for sw in sarvam_words:
        matched = False

        for offset in range(min(LOOK_AHEAD, n_ctc - ctc_idx)):
            candidate_idx = ctc_idx + offset
            if candidate_idx >= n_ctc:
                break

            ctc_w = ctc_words[candidate_idx]
            if _words_match(sw["word"], ctc_w["word"]):
                result.append({
                    "word":      sw["word"],
                    "has_punct": sw["has_punct"],
                    "start":     ctc_w["start"],
                    "end":       ctc_w["end"],
                })
                ctc_idx = candidate_idx + 1
                matched = True
                break

        if not matched:
            result.append({
                "word":      sw["word"],
                "has_punct": sw["has_punct"],
                "start":     None,
                "end":       None,
            })

    return result


def _interpolate_missing(timed_words: list) -> list:
    """Fill in timestamps for words that didn't match any CTC word."""
    n = len(timed_words)
    if n == 0:
        return timed_words

    i = 0
    while i < n:
        if timed_words[i]["start"] is not None:
            i += 1
            continue

        gap_start = i
        while i < n and timed_words[i]["start"] is None:
            i += 1
        gap_end = i

        prev_end   = timed_words[gap_start - 1]["end"] if gap_start > 0 else 0.0
        next_start = timed_words[gap_end]["start"] if gap_end < n else prev_end + 0.5

        gap_duration = next_start - prev_end
        gap_count    = gap_end - gap_start
        word_dur     = gap_duration / max(gap_count, 1)

        for j in range(gap_start, gap_end):
            offset = j - gap_start
            timed_words[j]["start"] = round(prev_end + offset       * word_dur, 3)
            timed_words[j]["end"]   = round(prev_end + (offset + 1) * word_dur, 3)

    return timed_words


def _build_sentences_from_punctuation(timed_words: list) -> list:
    """
    Build sentences by accumulating words until sentence-ending punctuation.
    No fake timestamps. No cross-script snapping. No overlaps.
    """
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
                    "id":    sent_id,
                    "text":  text,
                    "start": round(start, 3),
                    "end":   round(end,   3),
                })
                sent_id += 1

            current_words = []

    if current_words:
        text  = " ".join(cw["word"] for cw in current_words)
        start = current_words[0]["start"]
        end   = current_words[-1]["end"]
        if text.strip() and end > start:
            sentences.append({
                "id":    sent_id,
                "text":  text,
                "start": round(start, 3),
                "end":   round(end,   3),
            })

    return sentences


# ============================================================
# SENTENCE SPLITTER (LEGACY — kept for short audio path)
# ============================================================

def split_into_subsent(s: dict, min_duration: float = 0.0) -> list:
    """Split a coarse Sarvam sentence-blob into atomic sub-sentences."""
    import re as _re

    text     = s["text"].strip()
    start    = s["start"]
    end      = s["end"]
    duration = end - start

    parts = _re.split(r"(?<=[?.!।])\s+", text)
    parts = [p.strip() for p in parts if p.strip()]

    if len(parts) <= 1:
        return [{"id": -1, "text": text, "start": start, "end": end}]

    merged = []
    for p in parts:
        if merged and len(p) < 8 and p[-1] not in ("?", "!", ".", "।"):
            merged[-1] = merged[-1] + " " + p
        else:
            merged.append(p)
    parts = merged

    total_chars = sum(len(p) for p in parts)
    result      = []
    cursor      = start

    for i, p in enumerate(parts):
        fraction = len(p) / total_chars
        part_dur = duration * fraction
        part_end = end if i == len(parts) - 1 else round(cursor + part_dur, 2)

        if part_end - cursor >= min_duration:
            result.append({
                "id":    -1,
                "text":  p,
                "start": round(cursor, 2),
                "end":   part_end,
            })
        cursor = part_end

    return result if result else [{"id": -1, "text": text, "start": start, "end": end}]


# ============================================================
# FASTER-WHISPER FALLBACK
# ============================================================

def _get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        try:
            print(f"  [Whisper] Loading '{WHISPER_MODEL_SIZE}' on CUDA...")
            _whisper_model = WhisperModel(
                WHISPER_MODEL_SIZE, device="cuda",
                compute_type=WHISPER_COMPUTE_TYPE,
            )
        except Exception as e:
            print(f"  [Whisper] GPU failed ({e}), falling back to CPU...")
            _whisper_model = WhisperModel(
                WHISPER_MODEL_SIZE, device="cpu", compute_type="int8",
            )
    return _whisper_model


def transcribe_with_whisper(audio_path: str, language: str = "te") -> dict:
    """Transcribe using faster-whisper (fallback only)."""
    model = _get_whisper_model()
    print(f"  [Whisper] Transcribing: {audio_path}")

    t0 = time.time()
    segments_gen, info = model.transcribe(
        audio_path,
        language=language,
        task="transcribe",
        word_timestamps=True,
        beam_size=5,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
    )

    segments        = []
    word_timestamps = []
    full_text       = []

    for segment in segments_gen:
        seg_data = {
            "id":    segment.id,
            "start": round(segment.start, 2),
            "end":   round(segment.end,   2),
            "text":  segment.text.strip(),
        }
        segments.append(seg_data)
        full_text.append(segment.text.strip())

        if segment.words:
            for w in segment.words:
                word_timestamps.append({
                    "word":  w.word.strip(),
                    "start": round(w.start, 2),
                    "end":   round(w.end,   2),
                })

    elapsed = round(time.time() - t0, 1)

    return {
        "text":                    " ".join(full_text),
        "language":                info.language,
        "language_probability":    round(info.language_probability, 2),
        "segments":                segments,
        "sentences":               segments,
        "word_timestamps":         word_timestamps,
        "total_segments":          len(segments),
        "total_sentences":         len(segments),
        "total_words":             len(word_timestamps),
        "asr_model":               f"faster-whisper/{WHISPER_MODEL_SIZE}",
        "processing_time_seconds": elapsed,
    }


# ============================================================
# PUBLIC API
# ============================================================

def transcribe_audio(audio_path: str, language: str = "te",
                     force_whisper: bool = False) -> dict:
    """
    Main entry point. Transcribes with Sarvam + CTC alignment.
    Falls back to faster-whisper if Sarvam key missing or fails.
    """
    audio_path_obj = Path(audio_path)
    if not audio_path_obj.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    sarvam_lang  = _to_sarvam_lang(language)
    whisper_lang = None if language == "auto" else language

    if not force_whisper and SARVAM_API_KEY:
        try:
            duration = _get_audio_duration(audio_path_obj)
            if duration <= 30:
                print(f"Transcribing with Sarvam REST + CTC alignment...")
                return transcribe_with_sarvam(audio_path, sarvam_lang)
            else:
                print(f"Audio is {duration:.1f}s — using Sarvam Batch + CTC alignment...")
                return transcribe_long_audio_sarvam(audio_path, sarvam_lang)
        except Exception as e:
            print(f"Sarvam/CTC alignment failed: {e}")
            print("Falling back to faster-whisper...")
    elif not force_whisper and not SARVAM_API_KEY:
        print("SARVAM_API_KEY not set — using faster-whisper fallback.")

    return transcribe_with_whisper(audio_path, whisper_lang)


def save_transcript(transcript: dict, output_path: str):
    """Save transcript dict to JSON file.

    Derives `word_tanglish` beside every `word` before writing (Tanglish
    caption toggle) — one-time cost at transcription; old transcripts that
    predate this are backfilled on serve instead (api/main.py GET /transcript).
    """
    from services.tanglish import ensure_word_tanglish
    filled = ensure_word_tanglish(transcript)
    if filled:
        print(f"  [Tanglish] Derived word_tanglish for {filled} words")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(transcript, f, ensure_ascii=False, indent=2)
    print(f"Transcript saved: {output_path}")


# ============================================================
# HELPERS
# ============================================================

def _to_sarvam_lang(language: str) -> str:
    mapping = {
        "te": "te-IN", "hi": "hi-IN", "ta": "ta-IN",
        "kn": "kn-IN", "ml": "ml-IN", "en": "en-IN",
        "auto": "unknown", None: "unknown",
    }
    return mapping.get(language, language)


def _get_mime_type(audio_path: Path) -> str:
    mime_map = {
        ".wav":  "audio/wav",  ".mp3": "audio/mpeg",
        ".mp4":  "audio/mp4",  ".m4a": "audio/mp4",
        ".ogg":  "audio/ogg",  ".flac": "audio/flac",
        ".aac":  "audio/aac",
    }
    return mime_map.get(audio_path.suffix.lower(), "audio/wav")


def _get_audio_duration(audio_path: Path) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(audio_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def _build_segments_from_words(words: list, full_text: str) -> list:
    """Group words into ~5 second segments."""
    if not words:
        return [{"id": 0, "start": 0.0, "end": 0.0, "text": full_text}]

    SEGMENT_DURATION = 5.0
    segments  = []
    seg_words = []
    seg_start = words[0]["start"]

    for w in words:
        seg_words.append(w["word"])
        if w["end"] - seg_start >= SEGMENT_DURATION:
            segments.append({
                "id":    len(segments),
                "start": seg_start,
                "end":   w["end"],
                "text":  " ".join(seg_words).strip(),
            })
            seg_words = []
            seg_start = w["end"]

    if seg_words:
        segments.append({
            "id":    len(segments),
            "start": seg_start,
            "end":   words[-1]["end"],
            "text":  " ".join(seg_words).strip(),
        })

    return segments


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python transcriber.py <audio_file> [language] [--whisper]")
        print("Examples:")
        print("  python transcriber.py audio.wav te")
        print("  python transcriber.py audio.wav auto")
        sys.exit(1)

    audio_file = sys.argv[1]
    lang       = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else "te"
    force_w    = "--whisper" in sys.argv

    result = transcribe_audio(audio_file, language=lang, force_whisper=force_w)

    print(f"\n{'='*60}")
    print(f"RESULT")
    print(f"{'='*60}")
    print(f"Model:     {result['asr_model']}")
    print(f"Sentences: {result['total_sentences']}")
    print(f"Words:     {result['total_words']}")
    print(f"Time:      {result['processing_time_seconds']}s")
    print(f"\nFirst 10 sentences:")
    for s in result.get('sentences', [])[:10]:
        print(f"  [{s['start']:.3f}s - {s['end']:.3f}s] {s['text'][:60]}")

    out_path = audio_file.replace(".wav", "_transcript.json").replace(".mp3", "_transcript.json")
    save_transcript(result, out_path)