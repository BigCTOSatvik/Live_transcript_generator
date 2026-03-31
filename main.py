import os, time, subprocess, threading, logging, json
from pathlib import Path
from datetime import datetime
from openai import OpenAI
from flask import Flask, abort

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

for d in [RECORDINGS_DIR, TRANSCRIPTS_DIR, INTEL_DIR]:
    d.mkdir(parents=True, exist_ok=True)

already_processed = set()

STYLE = """
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{--green:#1B4332;--orange:#E8722A;--cream:#F2EDE4;--cream-dark:#E8E0D4;--muted:#6b6b6b}
body{background:var(--cream);font-family:'DM Sans',sans-serif;min-height:100vh}
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=DM+Sans:wght@400;500&display=swap');
header{background:var(--green);padding:18px 36px;display:flex;align-items:center;justify-content:space-between}
.logo{font-family:'Syne',sans-serif;font-weight:800;font-size:1.1rem;color:var(--cream);text-transform:uppercase;letter-spacing:.05em}
.logo span{color:var(--orange)}
.dot-wrap{display:flex;align-items:center;gap:6px;color:rgba(242,237,228,.7);font-size:.8rem}
.dot{width:7px;height:7px;border-radius:50%;background:#4ade80;animation:p 2s infinite}
@keyframes p{0%,100%{opacity:1}50%{opacity:.3}}
main{max-width:860px;margin:0 auto;padding:44px 24px 80px}
h1{font-family:'Syne',sans-serif;font-size:1.9rem;font-weight:800;color:var(--green);margin-bottom:6px}
.sub{color:var(--muted);font-size:.9rem;margin-bottom:36px}
.watch-bar{background:var(--green);border-radius:10px;padding:16px 22px;display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:36px}
.wlabel{font-family:'Syne',sans-serif;font-size:.7rem;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:rgba(242,237,228,.5);white-space:nowrap}
.chip{background:rgba(255,255,255,.12);color:var(--cream);font-size:.82rem;padding:3px 12px;border-radius:99px;border:1px solid rgba(255,255,255,.15)}
.sec-label{font-family:'Syne',sans-serif;font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.12em;color:var(--muted);margin-bottom:14px}
.list{display:flex;flex-direction:column;gap:10px}
.card{background:#fff;border-radius:10px;border:1px solid var(--cream-dark);padding:16px 22px;display:flex;align-items:center;justify-content:space-between;gap:12px;transition:border-color .15s,box-shadow .15s,transform .15s}
.card:hover{border-color:var(--orange);box-shadow:0 4px 18px rgba(232,114,42,.12);transform:translateY(-1px)}
.cname{font-family:'Syne',sans-serif;font-weight:700;font-size:.92rem;color:var(--green);margin-bottom:3px}
.cmeta{font-size:.76rem;color:var(--muted)}
.btns{display:flex;gap:8px;flex-shrink:0}
.btn{text-decoration:none;font-size:.8rem;padding:6px 13px;border-radius:6px;font-family:'Syne',sans-serif;font-weight:600;transition:opacity .15s}
.btn-outline{border:1.5px solid var(--cream-dark);color:var(--muted)}
.btn-outline:hover{border-color:#aaa}
.btn-orange{background:var(--orange);color:#fff}
.btn-green{background:var(--green);color:#fff}
.btn:hover{opacity:.85}
.empty{text-align:center;padding:72px 20px;color:var(--muted)}
.empty-icon{font-size:2.2rem;margin-bottom:14px;opacity:.35}
.etitle{font-family:'Syne',sans-serif;font-size:1rem;font-weight:700;color:var(--green);opacity:.55;margin-bottom:8px}
.back{color:rgba(242,237,228,.6);text-decoration:none;font-size:.85rem;transition:color .15s}
.back:hover{color:var(--cream)}
.div{color:rgba(242,237,228,.2);margin:0 4px}
pre{background:#fff;border:1px solid var(--cream-dark);border-radius:10px;padding:28px;font-size:.88rem;line-height:1.8;white-space:pre-wrap;word-break:break-word}
.copy-btn{display:inline-flex;align-items:center;gap:8px;background:var(--orange);color:#fff;border:none;border-radius:8px;padding:9px 18px;font-family:'Syne',sans-serif;font-weight:600;font-size:.82rem;cursor:pointer;margin-bottom:24px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.icard{background:#fff;border-radius:12px;border:1px solid var(--cream-dark);padding:22px}
.icard.full{grid-column:1/-1}
.icard.dark{background:var(--green);border-color:var(--green)}
.icard.warm{background:#fdf0e8;border-color:#f0d5c0}
.ilabel{font-family:'Syne',sans-serif;font-size:.67rem;font-weight:700;text-transform:uppercase;letter-spacing:.12em;color:var(--muted);margin-bottom:10px}
.icard.dark .ilabel{color:rgba(242,237,228,.45)}
.icard.warm .ilabel{color:var(--orange)}
.big{font-family:'Syne',sans-serif;font-size:1.05rem;font-weight:700;line-height:1.4;color:var(--green);margin-bottom:8px}
.icard.dark .big{color:var(--cream)}
.htag{display:inline-block;background:var(--orange);color:#fff;font-size:.7rem;font-weight:600;font-family:'Syne',sans-serif;padding:2px 10px;border-radius:99px;margin-bottom:8px;text-transform:uppercase}
.why{font-size:.83rem;color:var(--muted);line-height:1.5}
.icard.dark .why{color:rgba(242,237,228,.65)}
.tags{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.tag{background:var(--cream);border:1px solid var(--cream-dark);font-size:.78rem;padding:3px 11px;border-radius:99px}
.ilist{list-style:none;display:flex;flex-direction:column;gap:7px}
.ilist li{font-size:.86rem;line-height:1.5;padding-left:16px;position:relative}
.ilist li::before{content:"—";position:absolute;left:0;color:var(--orange)}
.icard.dark .ilist li{color:rgba(242,237,228,.85)}
.pi{margin-bottom:10px;padding-bottom:10px;border-bottom:1px solid var(--cream-dark)}
.pi:last-child{border:none;margin:0;padding:0}
.ptype{font-family:'Syne',sans-serif;font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--orange);margin-bottom:3px}
.pdet{font-size:.84rem;line-height:1.5}
.oi{margin-bottom:12px;padding-bottom:12px;border-bottom:1px solid var(--cream-dark)}
.oi:last-child{border:none;margin:0;padding:0}
.oq{font-size:.8rem;color:var(--muted);margin-bottom:3px}
.oa{font-size:.86rem;line-height:1.5}
.swipe{background:var(--cream);border-left:3px solid var(--orange);border-radius:0 8px 8px 0;padding:9px 13px;font-size:.86rem;font-style:italic;line-height:1.5;margin-bottom:7px;cursor:pointer;transition:background .15s}
.swipe:last-child{margin:0}
.swipe:hover{background:var(--cream-dark)}
.aitem{background:#fff;border-radius:7px;padding:10px 14px;font-size:.86rem;line-height:1.5;margin-bottom:7px;border:1px solid var(--cream-dark)}
.aitem:last-child{margin:0}
.cta-text{font-family:'Syne',sans-serif;font-size:.95rem;font-weight:600;color:var(--cream);margin-bottom:6px;line-height:1.4}
.cta-when{font-size:.8rem;color:rgba(242,237,228,.55)}
.loop{font-size:.88rem;line-height:1.65}
.refresh-a{float:right;font-family:'Syne',sans-serif;font-size:.78rem;font-weight:600;color:var(--green);border:1.5px solid var(--green);border-radius:7px;padding:6px 14px;text-decoration:none;transition:background .15s,color .15s}
.refresh-a:hover{background:var(--green);color:var(--cream)}
@media(max-width:600px){.grid{grid-template-columns:1fr}.icard.full{grid-column:1}}
</style>
"""

def page(title, body):
    return f"""<!DOCTYPE html><html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>{STYLE}</head><body>{body}</body></html>"""

def header(back=None):
    nav = f'<a class="back" href="/">← Back</a><span class="div">/</span>' if back else ""
    return f'<header>{nav}<div class="logo">Root Labs <span>/ Live Intel</span></div><div class="dot-wrap"><div class="dot"></div> Monitoring</div></header>'

INTEL_PROMPT = """You are a TikTok content strategist analyzing a live stream transcript from a creator in the sleep/wellness supplement space.

Extract the following intelligence. Return ONLY valid JSON, no preamble, no markdown fences.

{
  "hook": {
    "opening_line": "exact first sentence or two",
    "hook_type": "one of: problem-agitate, credential-first, scroll-stop-question, story-open, bold-claim, pattern-interrupt",
    "why_it_works": "1 sentence explanation"
  },
  "pain_points": ["pain point 1 as the creator framed it", "pain point 2"],
  "mechanism": {
    "explanation": "how the creator explained why the product/solution works",
    "key_terms_used": ["term1", "term2"]
  },
  "proof": [
    {"type": "e.g. personal story / customer result / credential / study", "detail": "what they said"}
  ],
  "cta": {
    "language": "exact or close CTA wording",
    "timing": "when they pushed CTA e.g. after proof, repeatedly, at end"
  },
  "loop_structure": "describe how they repeated or reset their pitch across the live",
  "objections_handled": [
    {"objection": "question or doubt raised", "response": "how they addressed it"}
  ],
  "swipe_lines": ["memorable line 1", "memorable line 2", "memorable line 3"],
  "root_labs_applications": [
    "specific way Root Labs could adapt this for liposomal Magnesium Ashwagandha gummies",
    "specific way 2",
    "specific way 3"
  ]
}

TRANSCRIPT:
"""

app = Flask(__name__)

@app.route("/")
def index():
    files = sorted(TRANSCRIPTS_DIR.glob("*.txt"), key=lambda f: f.stat().st_mtime, reverse=True)
    cards = ""
    for f in files:
        stat = f.stat()
        has_intel = (INTEL_DIR / (f.stem + ".json")).exists()
        intel_btn = f'<a class="btn btn-green" href="/analyze/{f.stem}">View Intel</a>' if has_intel else f'<a class="btn btn-orange" href="/analyze/{f.stem}">Analyze</a>'
        modified = datetime.fromtimestamp(stat.st_mtime).strftime("%b %d, %Y %H:%M")
        size = round(stat.st_size / 1024, 1)
        cards += f"""<div class="card">
          <div><div class="cname">{f.stem}</div><div class="cmeta">{modified} &nbsp;·&nbsp; {size} KB</div></div>
          <div class="btns"><a class="btn btn-outline" href="/transcript/{f.stem}">Raw</a>{intel_btn}</div>
        </div>"""

    chips = "".join(f'<div class="chip">@{c}</div>' for c in CREATORS)
    watch = f'<div class="watch-bar"><div class="wlabel">Watching</div><div style="display:flex;gap:8px;flex-wrap:wrap">{chips}</div></div>' if CREATORS else ""
    count = len(files)
    label = f'{count} transcript{"s" if count != 1 else ""}'
    content = f'<div class="list">{cards}</div>' if files else '<div class="empty"><div class="empty-icon">🎙</div><div class="etitle">No transcripts yet</div><p>Waiting for a tracked creator to go live.</p></div>'

    body = f"""{header()}
    <main>
      <h1>Creator Transcripts</h1>
      <p class="sub">Auto-recorded and transcribed TikTok lives.</p>
      {watch}
      <div class="sec-label">{label}</div>
      {content}
    </main>"""
    return page("Live Intel - Root Labs", body)

@app.route("/transcript/<n>")
def view_transcript(n):
    path = TRANSCRIPTS_DIR / f"{n}.txt"
    if not path.exists(): abort(404)
    content = path.read_text()
    body = f"""{header(True)}
    <main>
      <h1 style="margin-bottom:6px">{n}</h1>
      <p class="sub" style="margin-bottom:24px">Raw transcript</p>
      <button class="copy-btn" onclick="navigator.clipboard.writeText(document.getElementById('t').innerText).then(()=>{{this.textContent='✓ Copied';setTimeout(()=>this.textContent='⎘ Copy',2000)}})">⎘ Copy transcript</button>
      <pre id="t">{content}</pre>
    </main>"""
    return page(n, body)

@app.route("/analyze/<n>")
def analyze(n):
    intel_path = INTEL_DIR / f"{n}.json"
    if intel_path.exists():
        return render_intel(n, json.loads(intel_path.read_text()))
    transcript_path = TRANSCRIPTS_DIR / f"{n}.txt"
    if not transcript_path.exists(): abort(404)
    transcript = transcript_path.read_text()
    if not transcript.strip(): abort(400)
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": INTEL_PROMPT + transcript}],
            temperature=0.3,
        )
        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"): raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        intel = json.loads(raw)
        intel_path.write_text(json.dumps(intel, indent=2))
        return render_intel(n, intel)
    except Exception as e:
        log.error(f"Analysis failed: {e}")
        abort(500)

@app.route("/analyze/<n>/refresh")
def refresh_analysis(n):
    p = INTEL_DIR / f"{n}.json"
    if p.exists(): p.unlink()
    return analyze(n)

def render_intel(n, i):
    pain = "".join(f"<li>{p}</li>" for p in i.get("pain_points", []))
    terms = "".join(f'<span class="tag">{t}</span>' for t in i.get("mechanism", {}).get("key_terms_used", []))
    proof = "".join(f'<div class="pi"><div class="ptype">{p["type"]}</div><div class="pdet">{p["detail"]}</div></div>' for p in i.get("proof", []))
    objs = "".join(f'<div class="oi"><div class="oq">Q: {o["objection"]}</div><div class="oa">{o["response"]}</div></div>' for o in i.get("objections_handled", []))
    swipes = "".join(f'<div class="swipe" onclick="navigator.clipboard.writeText(this.innerText)">{s}</div>' for s in i.get("swipe_lines", []))
    apps = "".join(f'<div class="aitem">{a}</div>' for a in i.get("root_labs_applications", []))
    h = i.get("hook", {})
    m = i.get("mechanism", {})
    cta = i.get("cta", {})

    body = f"""{header(True)}
    <main>
      <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:36px;flex-wrap:wrap;gap:12px">
        <div><h1 style="margin-bottom:4px">Intelligence Report</h1><p class="sub">{n}</p></div>
        <a class="refresh-a" href="/analyze/{n}/refresh">↻ Re-analyze</a>
      </div>
      <div class="grid">
        <div class="icard dark full">
          <div class="ilabel">Hook</div>
          <div class="big">"{h.get('opening_line','')}"</div>
          <span class="htag">{h.get('hook_type','')}</span>
          <div class="why">{h.get('why_it_works','')}</div>
        </div>
        <div class="icard">
          <div class="ilabel">Pain Points</div>
          <ul class="ilist">{pain}</ul>
        </div>
        <div class="icard">
          <div class="ilabel">Mechanism</div>
          <div style="font-size:.86rem;line-height:1.6;margin-bottom:10px">{m.get('explanation','')}</div>
          <div class="tags">{terms}</div>
        </div>
        <div class="icard">
          <div class="ilabel">Proof Structure</div>
          {proof}
        </div>
        <div class="icard dark">
          <div class="ilabel">CTA</div>
          <div class="cta-text">"{cta.get('language','')}"</div>
          <div class="cta-when">{cta.get('timing','')}</div>
        </div>
        <div class="icard full">
          <div class="ilabel">Live Loop Structure</div>
          <div class="loop">{i.get('loop_structure','')}</div>
        </div>
        <div class="icard full">
          <div class="ilabel">Objections Handled</div>
          {objs}
        </div>
        <div class="icard">
          <div class="ilabel">Swipe Lines - click to copy</div>
          {swipes}
        </div>
        <div class="icard warm">
          <div class="ilabel">Root Labs Applications</div>
          {apps}
        </div>
      </div>
    </main>"""
    return page(f"Intel - {n}", body)

# Transcription

def transcribe(mp4_path):
    # name transcript as username_originalfilename.txt
    creator = mp4_path.parent.name
    transcript_name = f"{creator}_{mp4_path.stem}.txt"
    transcript_path = TRANSCRIPTS_DIR / transcript_name
    if transcript_path.exists(): return
    log.info(f"Transcribing {mp4_path.name}...")
    try:
        with open(mp4_path, "rb") as f:
            result = client.audio.transcriptions.create(model="whisper-1", file=f, response_format="text")
        transcript_path.write_text(result)
        log.info(f"Saved -> {transcript_path}")
    except Exception as e:
        log.error(f"Transcription failed: {e}")

def watch_recordings():
    while True:
        for mp4 in RECORDINGS_DIR.rglob("*.mp4"):
            if mp4 in already_processed: continue
            s1 = mp4.stat().st_size
            time.sleep(5)
            s2 = mp4.stat().st_size
            if s1 == s2 and s2 > 0:
                already_processed.add(mp4)
                threading.Thread(target=transcribe, args=(mp4,), daemon=True).start()
        time.sleep(POLL_INTERVAL)

CHUNK_SECONDS = int(os.environ.get("CHUNK_SECONDS", "300"))

def start_recorder(user):
    chunk = 0
    while True:
        chunk += 1
        output_dir = RECORDINGS_DIR / user
        output_dir.mkdir(parents=True, exist_ok=True)
        cmd = [
            "python", "src/main.py",
            "-user", user,
            "-mode", "manual",
            "-output", str(output_dir),
            "-duration", str(CHUNK_SECONDS),
        ]
        log.info(f"@{user} chunk {chunk} starting ({CHUNK_SECONDS}s)...")
        try:
            subprocess.run(cmd, cwd="/recorder")
            log.info(f"@{user} chunk {chunk} done")
        except Exception as e:
            log.error(f"Recorder error @{user}: {e}")
        time.sleep(2)

if __name__ == "__main__":
    if not CREATORS: log.error("No TIKTOK_USERS set."); exit(1)
    for c in CREATORS:
        threading.Thread(target=start_recorder, args=(c,), daemon=True).start()
    threading.Thread(target=watch_recordings, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT)
