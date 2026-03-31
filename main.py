import os
import time
import subprocess
import threading
import logging
from pathlib import Path
from openai import OpenAI

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

RECORDINGS_DIR = Path(os.environ.get("RECORDINGS_DIR", "/recordings"))
TRANSCRIPTS_DIR = Path(os.environ.get("TRANSCRIPTS_DIR", "/transcripts"))
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL_SECONDS", "30"))
CREATORS = [u.strip() for u in os.environ.get("TIKTOK_USERS", "").split(",") if u.strip()]
RECORD_MODE = os.environ.get("RECORD_MODE", "automatic")
RECORD_INTERVAL = os.environ.get("RECORD_INTERVAL_MINUTES", "5")

RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

already_processed = set()


def transcribe(mp4_path: Path):
    transcript_path = TRANSCRIPTS_DIR / (mp4_path.stem + ".txt")
    if transcript_path.exists():
        return

    log.info(f"Transcribing {mp4_path.name} ...")
    try:
        with open(mp4_path, "rb") as f:
            result = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                response_format="text"
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
            # wait until file hasn't grown for 10s (recording finished)
            size1 = mp4.stat().st_size
            time.sleep(10)
            size2 = mp4.stat().st_size
            if size1 == size2 and size2 > 0:
                already_processed.add(mp4)
                threading.Thread(target=transcribe, args=(mp4,), daemon=True).start()
        time.sleep(POLL_INTERVAL)


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

    log.info(f"Starting recorder for @{user} in {RECORD_MODE} mode")
    while True:
        try:
            subprocess.run(cmd, cwd="/recorder")
        except Exception as e:
            log.error(f"Recorder crashed for @{user}: {e}")
        log.info(f"Restarting recorder for @{user} in 60s...")
        time.sleep(60)


if __name__ == "__main__":
    if not CREATORS:
        log.error("No TIKTOK_USERS set. Add them as comma-separated env var.")
        exit(1)

    log.info(f"Starting pipeline for: {CREATORS}")

    # start one recorder thread per creator
    for creator in CREATORS:
        t = threading.Thread(target=start_recorder, args=(creator,), daemon=True)
        t.start()

    # watcher runs on main thread
    watch_recordings()
