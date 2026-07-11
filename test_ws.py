"""
DISCOVERY TEST v2: does Sarvam's streaming WS return word-level timestamps?
Streams probe.wav to wss://api.sarvam.ai/speech-to-text/ws and prints
every raw message received. We're looking for any per-word timing fields.

Changes vs v1:
  - high_vad_sensitivity=true + vad_signals=true in the URL
  - 2s of silence appended after the audio (gives VAD an end-of-speech)
  - tries 3 plausible flush-signal message shapes at the end
  - waits 15s for final transcripts

Setup:  pip install websockets python-dotenv
Usage:  python test_ws.py            (expects probe.wav, 16kHz mono s16le)
        python test_ws.py other.wav
"""

import asyncio
import base64
import json
import os
import sys
import wave

import websockets
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ.get("SARVAM_API_KEY", "")
WS_URL = (
    "wss://api.sarvam.ai/speech-to-text/ws"
    "?language-code=te-IN"
    "&model=saaras:v3"
    "&mode=codemix"
    "&sample_rate=16000"
    "&input_audio_codec=pcm_s16le"
    "&high_vad_sensitivity=true"
    "&vad_signals=true"
    "&with_timestamps=true"
)

CHUNK_MS = 100  # send 100ms of audio per message


async def run(wav_file: str):
    with wave.open(wav_file, "rb") as wf:
        assert wf.getframerate() == 16000, "wav must be 16kHz (re-make with ffmpeg)"
        assert wf.getnchannels() == 1, "wav must be mono"
        pcm = wf.readframes(wf.getnframes())

    bytes_per_chunk = int(16000 * 2 * CHUNK_MS / 1000)  # 16k samples/s * 2 bytes
    chunks = [pcm[i:i + bytes_per_chunk] for i in range(0, len(pcm), bytes_per_chunk)]

    # Append 2s of silence so VAD can detect end-of-speech
    silence_chunk = b"\x00" * bytes_per_chunk
    chunks += [silence_chunk] * 20

    print(f"Streaming {len(pcm) / 32000:.1f}s of audio "
          f"(+2s silence) in {len(chunks)} chunks...\n")

    async with websockets.connect(
        WS_URL,
        additional_headers={"Api-Subscription-Key": API_KEY},
        max_size=None,
    ) as ws:

        async def receiver():
            try:
                async for msg in ws:
                    try:
                        parsed = json.loads(msg)
                        print("<<< RECEIVED:")
                        print(json.dumps(parsed, ensure_ascii=False, indent=2))
                        print()
                    except json.JSONDecodeError:
                        print(f"<<< RECEIVED (non-JSON, {len(msg)} bytes)")
            except websockets.ConnectionClosed as e:
                print(f"[connection closed: code={e.code} reason={e.reason}]")

        recv_task = asyncio.create_task(receiver())

        for chunk in chunks:
            await ws.send(json.dumps({
                "audio": {
                    "data": base64.b64encode(chunk).decode("ascii"),
                    "sample_rate": "16000",
                    "encoding": "audio/wav",
                }
            }))
            await asyncio.sleep(CHUNK_MS / 1000)  # real-time pacing

        print(">>> all audio sent, trying flush signals...\n")
        for flush_msg in ({"event": "flush"}, {"signal": "flush"}, {"type": "flush"}):
            try:
                print(f">>> sending flush attempt: {flush_msg}")
                await ws.send(json.dumps(flush_msg))
                await asyncio.sleep(2)
            except websockets.ConnectionClosed:
                print("[socket closed during flush attempts]")
                break

        print("\n>>> waiting 15s for final transcripts...\n")
        try:
            await asyncio.sleep(15)
        finally:
            recv_task.cancel()


if __name__ == "__main__":
    if not API_KEY:
        sys.exit("SARVAM_API_KEY not set.")
    wav = sys.argv[1] if len(sys.argv) > 1 else "probe.wav"
    asyncio.run(run(wav))