import os
import time
import subprocess
import threading
import logging
import json
from pathlib import Path
from datetime import datetime
from openai import OpenAI
from flask import Flask, render_template, abort, jsonify

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

RECORDINGS_DIR  = Path(os.environ.get("RECORDINGS_DIR", "/recordings"))
TRANSCRIPTS_DIR = Path(os.environ.get("TRANSCRIPTS_DIR", "/transcripts"))
INTEL_DIR       = Path(os.environ.get("INTEL_DIR", "/intel"))
POLL_INTERVAL   = int(os.environ.get("POLL_INTERVAL_SECONDS", "30"))
CREATORS        = [u.strip() for u in os.environ.get("TIKTOK_USERS", "").split(",") if u.strip()]
RECORD_MODE     = os.environ.get("RECORD_MODE", "automatic")
RECORD_INTERVAL = os.environ.get("RECORD_INTERVAL_MINUTES", "5")
PORT            = int(os.environ.get("PORT", "8080"))

RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
INTEL_DIR.mkdir(parents=True, exist_ok=True)

already_processed = set()

INTEL_PROMPT = """You are a TikTok content strategist analyzing a live stream transcript from a creator in the sleep/wellness supplement space.

Extract the following intelligence from this transcript. Return ONLY valid JSON, no preamble, no markdown fences.

{
  "hook": {
    "opening_line": "exact first sentence or two",
    "hook_type": "one of: problem-agitate, credential-first, scroll-stop-question, story-open, bold-claim, pattern-interrupt",
    "why_it_works": "1 sentence explanation"
  },
  "pain_points": [
    "pain point 1 as the creator framed it",
    "pain point 2"
  ],
  "mechanism": {
    "explanation": "how the creator explained why the product/solution works",
    "key_terms_used": ["term1", "term2"]
  },
  "proof": [
    {"type": "type of proof e.g. personal story / customer result / credential / study", "detail": "what they said"}
  ],
  "cta": {
    "language": "exact or close-to-exact CTA wording",
    "timing": "when in the live they pushed CTA e.g. after proof, repeatedly, at end"
  },
  "loop_structure": "describe how they repeated or reset their pitch across the live",
  "objections_handled": [
    {"objection": "question or doubt raised", "response": "how they addressed it"}
  ],
  "swipe_lines": [
    "memorable or highly adaptable line 1",
    "memorable or highly adaptable line 2",
    "memorable or highly adaptable line 3"
  ],
  "root_labs_applications": [
    "specific way Root Labs could adapt this for liposomal Magnesium Ashwagandha gummies",
    "specific way 2",
    "specific way 3"
  ]
}

TRANSCRIPT:
"""

# ── Flask ──────────────────────────────────────────────────

app = Flask(__name__)

@app.route("/")
def index():
    files = sorted(TRANSCRIPTS_DIR.glob("*.txt"), key=lambda f: f.stat().st_mtime, reverse=True)
    transcripts = []
    for f in files:
        stat = f.stat()
        intel_exists = (INTEL_DIR / (f.stem + ".json")).exists()
        transcripts.append({
            "name": f.stem,
            "size_kb": round(stat.st_size / 1024, 1),
            "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%b %d, %Y %H:%M"),
            "has_intel": intel_exists,
        })
    return render_template("index.html", transcripts=transcripts, creators=CREATORS)

@app.route("/transcript/<n>")
def view_transcript(n):
    path = TRANSCRIPTS_DIR / f"{n}.txt"
    if not path.exists():
        abort(404)
    content = path.read_text()
    return render_template("transcript.html", name=n, content=content)

@app.route("/analyze/<n>")
def analyze(n):
    intel_path = INTEL_DIR / f"{n}.json"
    # return cached if exists
    if intel_path.exists():
        intel = json.loads(intel_path.read_text())
        return render_template("intel.html", name=n, intel=intel)

    transcript_path = TRANSCRIPTS_DIR / f"{n}.txt"
    if not transcript_path.exists():
        abort(404)

    transcript = transcript_path.read_text()
    if not transcript.strip():
        abort(400)

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": INTEL_PROMPT + transcript}],
            temperature=0.3,
        )
        raw = response.choices[0].message.content.strip()
        # strip markdown fences if model added them
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        intel = json.loads(raw)
        intel_path.write_text(json.dumps(intel, indent=2))
        return render_template("intel.html", name=n, intel=intel)
    except Exception as e:
        log.error(f"Analysis failed: {e}")
        abort(500)

@app.route("/analyze/<n>/refresh")
def refresh_analysis(n):
    intel_path = INTEL_DIR / f"{n}.json"
    if intel_path.exists():
        intel_path.unlink()
    return analyze(n)

# ── Transcription ──────────────────────────────────────────

def transcribe(mp4_path: Path):
    transcript_path = TRANSCRIPTS_DIR / (mp4_path.stem + ".txt")
    if transcript_path.exists():
        return
    log.info(f"Transcribing {mp4_path.name} ...")
    try:
        with open(mp4_path, "rb") as f:
            result = client.audio.transcriptions.create(
                model="whisper-1", file=f, response_format="text"
            )
        transcript_path.write_text(result)
        log.info(f"Transcript saved -> {transcript_path}")
    except Exception as e:
        log.error(f"Transcription failed for {mp4_path.name}: {e}")

def watch_recordings():
    log.info(f"Watching {RECORDINGS_DIR} for new recordings...")
    while True:
        for mp4 in RECORDINGS_DIR.glob("*.mp4"):
            if mp4 in already_processed:
                continue
            size1 = mp4.stat().st_size
            time.sleep(10)
            size2 = mp4.stat().st_size
            if size1 == size2 and size2 > 0:
                already_processed.add(mp4)
                threading.Thread(target=transcribe, args=(mp4,), daemon=True).start()
        time.sleep(POLL_INTERVAL)

# ── Recorder ──────────────────────────────────────────────

def start_recorder(user: str):
    cmd = [
        "python", "src/main.py",
        "-user", user,
        "-mode", RECORD_MODE,
        "-output", str(RECORDINGS_DIR),
        "-automatic_interval", RECORD_INTERVAL,
    ]
    cookies_path = Path("/app/cookies.json")
    if cookies_path.exists():
        cmd += ["-cookies", str(cookies_path)]
    log.info(f"Starting recorder for @{user}")
    while True:
        try:
            subprocess.run(cmd, cwd="/recorder")
        except Exception as e:
            log.error(f"Recorder crashed for @{user}: {e}")
        time.sleep(60)

# ── Entry point ────────────────────────────────────────────

if __name__ == "__main__":
    if not CREATORS:
        log.error("No TIKTOK_USERS set.")
        exit(1)

    log.info(f"Starting pipeline for: {CREATORS}")

    for creator in CREATORS:
        threading.Thread(target=start_recorder, args=(creator,), daemon=True).start()

    threading.Thread(target=watch_recordings, daemon=True).start()

    app.run(host="0.0.0.0", port=PORT)
