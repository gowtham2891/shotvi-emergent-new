import requests, json, os
from dotenv import load_dotenv
load_dotenv()

# use any chunk wav, or make one: ffmpeg -i video.mp4 -vn -ac 1 -ar 16000 -t 20 probe.wav
for mode in ["transcribe", "codemix", "verbatim"]:
    with open("probe.wav", "rb") as f:
        r = requests.post(
            "https://api.sarvam.ai/speech-to-text",
            headers={"api-subscription-key": os.environ["SARVAM_API_KEY"]},
            files={"file": ("probe.wav", f, "audio/wav")},
            data={"model": "saaras:v3", "mode": mode,
                  "language_code": "te-IN", "with_timestamps": "true"},
        )
    print(f"\n===== mode={mode} =====")
    print(json.dumps(r.json().get("timestamps"), ensure_ascii=False, indent=2)[:1500])