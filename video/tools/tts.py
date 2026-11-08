"""Generate narration clips for one video part with ElevenLabs.

Usage: python video/tools/tts.py video/part-1/lines.json video/voice/part-1 [--model eleven_v4] [--only l1a,l2]
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

VOICE_ID = "CzlzlG52P2Tvaktl7R52"
API_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=mp3_44100_128"
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def read_api_key() -> str:
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("ELEVENLABS_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"')
    sys.exit("ELEVENLABS_API_KEY is not set in .env")


def synthesize(text: str, model: str, api_key: str) -> bytes:
    body = {
        "text": text,
        "model_id": model,
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.85, "style": 0.0, "use_speaker_boost": True},
    }
    request = urllib.request.Request(
        API_URL.format(voice=VOICE_ID),
        data=json.dumps(body).encode("utf-8"),
        headers={"xi-api-key": api_key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        sys.exit(f"ElevenLabs returned {error.code}: {error.read().decode('utf-8', 'replace')}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("lines")
    parser.add_argument("out_dir")
    parser.add_argument("--model", default="eleven_v4")
    parser.add_argument("--only", default="")
    args = parser.parse_args()

    lines = json.loads(Path(args.lines).read_text(encoding="utf-8"))
    wanted = set()
    if args.only:
        wanted = set(args.only.split(","))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    api_key = read_api_key()

    for line in lines:
        if wanted and line["id"] not in wanted:
            continue
        audio = synthesize(line["text"], args.model, api_key)
        path = out_dir / f"{line['id']}.mp3"
        path.write_bytes(audio)
        print(f"{path} ({len(audio) // 1024} KB)")


if __name__ == "__main__":
    main()
