# TikTok Live Intel Pipeline

Records TikTok lives from target creators and auto-transcribes them using OpenAI Whisper.

## How it works

1. Monitors creator handles in automatic mode
2. Records any live session to MP4 as it happens
3. Detects when recording finishes
4. Sends to Whisper API - transcript saved as .txt

## Railway setup

### 1. Environment variables (set in Railway dashboard)

| Variable | Description | Example |
|---|---|---|
| `OPENAI_API_KEY` | Your OpenAI key | `sk-...` |
| `TIKTOK_USERS` | Comma-separated handles to monitor | `drewreviews,paulthepharmacist` |
| `RECORD_MODE` | `automatic` or `manual` | `automatic` |
| `RECORD_INTERVAL_MINUTES` | How often to poll for live status | `5` |
| `POLL_INTERVAL_SECONDS` | How often watcher checks for new MP4s | `30` |

### 2. Volumes (set in Railway dashboard)

Add two volumes so recordings and transcripts persist across deploys:

- `/recordings` - raw MP4 files
- `/transcripts` - .txt transcripts

### 3. Cookies (optional but recommended)

TikTok may block requests without auth. To add cookies:
- Log into TikTok in Chrome
- Use EditThisCookie extension to export cookies as JSON
- Save as `cookies.json` and add to repo root

### 4. Deploy

```
# push to github, connect repo to Railway
# set env vars
# deploy
```

## Output

For every live recorded, you get:
- `/recordings/username_TIMESTAMP.mp4`
- `/transcripts/username_TIMESTAMP.txt`

Feed the .txt files into the intelligence layer (next step) for hook/script analysis.
