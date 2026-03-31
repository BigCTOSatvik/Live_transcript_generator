import os, time, subprocess, threading, logging, json, re, asyncio
from pathlib import Path
from datetime import datetime
from openai import OpenAI
from flask import Flask, abort, request, redirect

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

RECORDINGS_DIR  = Path(os.environ.get("RECORDINGS_DIR", "/recordings"))
TRANSCRIPTS_DIR = Path(os.environ.get("TRANSCRIPTS_DIR", "/transcripts"))
INTEL_DIR       = Path(os.environ.get("INTEL_DIR", "/intel"))
COMMENTS_DIR    = Path(os.environ.get("COMMENTS_DIR", "/comments"))
POLL_INTERVAL   = int(os.environ.get("POLL_INTERVAL_SECONDS", "30"))
RECORD_MODE     = os.environ.get("RECORD_MODE", "manual")
CHUNK_SECONDS   = int(os.environ.get("CHUNK_SECONDS", "300"))
PORT            = int(os.environ.get("PORT", "8080"))
CREATORS_FILE   = INTEL_DIR / "creators.json"

for d in [RECORDINGS_DIR, TRANSCRIPTS_DIR, INTEL_DIR, COMMENTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

already_processed = set()
recorder_threads  = {}

# ── Creator management ─────────────────────────────────────

def load_creators():
    if CREATORS_FILE.exists():
        try:
            return json.loads(CREATORS_FILE.read_text())
        except Exception:
            pass
    return []

def save_creators(creators):
    CREATORS_FILE.write_text(json.dumps(creators))

# ── Styles ─────────────────────────────────────────────────

STYLE = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=DM+Sans:wght@400;500&display=swap');
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{--green:#1B4332;--orange:#E8722A;--cream:#F2EDE4;--cream-dark:#E8E0D4;--muted:#6b6b6b}
body{background:var(--cream);font-family:'DM Sans',sans-serif;min-height:100vh}
header{background:var(--green);padding:18px 36px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px}
.logo{font-family:'Syne',sans-serif;font-weight:800;font-size:1.1rem;color:var(--cream);text-transform:uppercase;letter-spacing:.05em}
.logo span{color:var(--orange)}
.nav{display:flex;align-items:center;gap:20px}
.nav a{color:rgba(242,237,228,.65);text-decoration:none;font-size:.82rem;transition:color .15s}
.nav a:hover,.nav a.active{color:var(--cream)}
.dot-wrap{display:flex;align-items:center;gap:6px;color:rgba(242,237,228,.7);font-size:.8rem}
.dot{width:7px;height:7px;border-radius:50%;background:#4ade80;animation:p 2s infinite}
@keyframes p{0%,100%{opacity:1}50%{opacity:.3}}
main{max-width:860px;margin:0 auto;padding:44px 24px 80px}
h1{font-family:'Syne',sans-serif;font-size:1.9rem;font-weight:800;color:var(--green);margin-bottom:6px}
h2{font-family:'Syne',sans-serif;font-size:1.2rem;font-weight:800;color:var(--green);margin-bottom:14px}
.sub{color:var(--muted);font-size:.9rem;margin-bottom:36px}
.sec-label{font-family:'Syne',sans-serif;font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.12em;color:var(--muted);margin-bottom:14px}
.list{display:flex;flex-direction:column;gap:10px}
.card{background:#fff;border-radius:10px;border:1px solid var(--cream-dark);padding:16px 22px;display:flex;align-items:center;justify-content:space-between;gap:12px;transition:border-color .15s,box-shadow .15s,transform .15s}
.card:hover{border-color:var(--orange);box-shadow:0 4px 18px rgba(232,114,42,.12);transform:translateY(-1px)}
.cname{font-family:'Syne',sans-serif;font-weight:700;font-size:.92rem;color:var(--green);margin-bottom:3px}
.cmeta{font-size:.76rem;color:var(--muted)}
.btns{display:flex;gap:8px;flex-shrink:0}
.btn{text-decoration:none;font-size:.8rem;padding:6px 13px;border-radius:6px;font-family:'Syne',sans-serif;font-weight:600;transition:opacity .15s;cursor:pointer;border:none;display:inline-block}
.btn-outline{border:1.5px solid var(--cream-dark)!important;color:var(--muted);background:transparent}
.btn-outline:hover{border-color:#aaa!important}
.btn-orange{background:var(--orange);color:#fff}
.btn-green{background:var(--green);color:#fff}
.btn-red{background:#dc2626;color:#fff}
.btn:hover{opacity:.85}
.empty{text-align:center;padding:72px 20px;color:var(--muted)}
.empty-icon{font-size:2.2rem;margin-bottom:14px;opacity:.35}
.etitle{font-family:'Syne',sans-serif;font-size:1rem;font-weight:700;color:var(--green);opacity:.55;margin-bottom:8px}
.back{color:rgba(242,237,228,.6);text-decoration:none;font-size:.85rem;transition:color .15s}
.back:hover{color:var(--cream)}
.divd{color:rgba(242,237,228,.2);margin:0 4px}
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
.refresh-a{font-family:'Syne',sans-serif;font-size:.78rem;font-weight:600;color:var(--green);border:1.5px solid var(--green);border-radius:7px;padding:6px 14px;text-decoration:none;transition:background .15s,color .15s}
.refresh-a:hover{background:var(--green);color:var(--cream)}
.add-form{background:#fff;border-radius:10px;border:1px solid var(--cream-dark);padding:20px 22px;margin-bottom:28px;display:flex;gap:10px;align-items:center}
.add-form input{flex:1;border:1.5px solid var(--cream-dark);border-radius:7px;padding:8px 14px;font-family:'DM Sans',sans-serif;font-size:.9rem;outline:none;transition:border-color .15s}
.add-form input:focus{border-color:var(--orange)}
.creator-status{display:inline-block;width:8px;height:8px;border-radius:50%;background:#4ade80;margin-right:6px}
.summary-box{background:#fff;border:1px solid var(--cream-dark);border-radius:12px;padding:28px;font-size:.9rem;line-height:1.8;white-space:pre-wrap}
.spike-item{background:#fff;border-radius:8px;border:1px solid var(--cream-dark);padding:14px 18px;margin-bottom:10px}
.spike-time{font-family:'Syne',sans-serif;font-weight:700;color:var(--orange);font-size:.82rem;margin-bottom:4px}
.comment-item{padding:10px 0;border-bottom:1px solid var(--cream-dark);font-size:.87rem;line-height:1.5}
.comment-item:last-child{border:none}
.comment-theme{background:var(--cream);border-radius:8px;padding:12px 16px;margin-bottom:8px;font-size:.87rem;line-height:1.5}
@media(max-width:600px){.grid{grid-template-columns:1fr}.icard.full{grid-column:1}}
</style>
"""

def page(title, body):
    return f"""<!DOCTYPE html><html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>{STYLE}</head><body>{body}</body></html>"""

def header(back=None, active=""):
    nav_back = f'<a class="back" href="/">← Back</a><span class="divd">/</span>' if back else ""
    nav_links = f"""<div class="nav">
      <a href="/" {'class="active"' if active=='home' else ''}>Transcripts</a>
      <a href="/creators" {'class="active"' if active=='creators' else ''}>Creators</a>
      <div class="dot-wrap"><div class="dot"></div> Live</div>
    </div>"""
    return f'<header>{nav_back}<div class="logo">Root Labs <span>/ Live Intel</span></div>{nav_links}</header>'

# ── Prompts ────────────────────────────────────────────────

INTEL_PROMPT = """You are a TikTok content strategist analyzing a live stream transcript from a creator in the sleep/wellness supplement space.
Extract the following intelligence. Return ONLY valid JSON, no preamble, no markdown fences.
{
  "hook": {"opening_line": "exact first sentence or two", "hook_type": "one of: problem-agitate, credential-first, scroll-stop-question, story-open, bold-claim, pattern-interrupt", "why_it_works": "1 sentence"},
  "pain_points": ["pain point 1", "pain point 2"],
  "mechanism": {"explanation": "how creator explained the solution", "key_terms_used": ["term1", "term2"]},
  "proof": [{"type": "personal story / customer result / credential / study", "detail": "what they said"}],
  "cta": {"language": "exact CTA wording", "timing": "when they pushed CTA"},
  "loop_structure": "how they repeated/reset their pitch",
  "objections_handled": [{"objection": "doubt raised", "response": "how they addressed it"}],
  "swipe_lines": ["line 1", "line 2", "line 3"],
  "root_labs_applications": ["adaptation for liposomal Magnesium Ashwagandha gummies 1", "adaptation 2", "adaptation 3"]
}
TRANSCRIPT:
"""

SUMMARY_PROMPT = """You are analyzing a full TikTok live session transcript (stitched from multiple chunks) from a creator in the sleep/wellness space.

Write a comprehensive summary covering:
1. OVERVIEW - What was this live about? What was the main product/topic?
2. KEY NARRATIVE ARC - How did the session flow from start to finish?
3. TOP MOMENTS - The 3-5 most impactful things said
4. SALES APPROACH - How did they pitch? What worked?
5. AUDIENCE ENGAGEMENT - What got the most reaction/questions?
6. BEST LINES TO SWIPE - 5 exact lines worth adapting for Root Labs

Be specific. Quote directly where useful. Write in plain prose, not bullet points.

TRANSCRIPT:
"""

SPIKE_PROMPT = """You are analyzing a TikTok live transcript alongside viewer count data to identify what caused traffic spikes.

Viewer data format: [timestamp_seconds: viewer_count]

Instructions:
- Identify moments where viewer count increased significantly (spikes)
- Find what was being said in the transcript around those timestamps
- Explain WHY that content likely drove the spike
- Identify patterns in what holds viewers vs what causes drop-off

Return ONLY valid JSON:
{
  "spikes": [
    {
      "timestamp": "approximate time e.g. 12 min",
      "viewer_change": "e.g. +340 viewers",
      "what_was_said": "quote or paraphrase from transcript",
      "why_it_worked": "explanation"
    }
  ],
  "retention_patterns": ["pattern 1", "pattern 2"],
  "drop_off_triggers": ["what caused viewers to leave"],
  "root_labs_takeaways": ["what Root Labs should replicate"]
}

VIEWER DATA:
{viewer_data}

TRANSCRIPT:
{transcript}
"""

COMMENTS_PROMPT = """You are analyzing TikTok live chat comments from a wellness/supplement live stream.

Identify:
1. TOP THEMES - What are people most talking about?
2. BUYING SIGNALS - Comments showing purchase intent
3. OBJECTIONS - Doubts, concerns, skepticism
4. QUESTIONS - What are people asking most?
5. EMOTIONAL TRIGGERS - What words/phrases got the most reaction?
6. ROOT LABS APPLICATIONS - What does this tell us about our audience?

Return ONLY valid JSON:
{
  "top_themes": ["theme 1", "theme 2", "theme 3"],
  "buying_signals": ["comment or pattern 1", "comment or pattern 2"],
  "objections": ["objection 1", "objection 2"],
  "top_questions": ["question 1", "question 2", "question 3"],
  "emotional_triggers": ["trigger 1", "trigger 2"],
  "root_labs_applications": ["application 1", "application 2", "application 3"]
}

COMMENTS:
"""

# ── Flask ──────────────────────────────────────────────────

app = Flask(__name__)

@app.route("/")
def index():
    files = sorted(TRANSCRIPTS_DIR.glob("*.txt"), key=lambda f: f.stat().st_mtime, reverse=True)
    # group by creator
    by_creator = {}
    for f in files:
        parts = f.stem.split("_", 1)
        creator = parts[0] if len(parts) > 1 else "unknown"
        by_creator.setdefault(creator, []).append(f)

    cards = ""
    for f in files:
        has_intel = (INTEL_DIR / (f.stem + ".json")).exists()
        intel_btn = f'<a class="btn btn-green" href="/analyze/{f.stem}">Intel</a>' if has_intel else f'<a class="btn btn-orange" href="/analyze/{f.stem}">Analyze</a>'
        modified = datetime.fromtimestamp(f.stat().st_mtime).strftime("%b %d %H:%M")
        size = round(f.stat().st_size / 1024, 1)
        # summary and comments buttons
        creator = f.stem.split("_")[0]
        cards += f"""<div class="card">
          <div><div class="cname">{f.stem}</div><div class="cmeta">{modified} · {size} KB</div></div>
          <div class="btns">
            <a class="btn btn-outline" href="/transcript/{f.stem}">Raw</a>
            {intel_btn}
          </div>
        </div>"""

    # creator summary buttons
    summary_btns = ""
    for creator in by_creator:
        chunk_count = len(by_creator[creator])
        summary_btns += f"""<div class="card">
          <div><div class="cname">@{creator}</div><div class="cmeta">{chunk_count} chunks recorded</div></div>
          <div class="btns">
            <a class="btn btn-green" href="/summary/{creator}">Full Summary</a>
            <a class="btn btn-outline" href="/comments/{creator}">Comments</a>
            <a class="btn btn-outline" href="/spikes/{creator}">Traffic Spikes</a>
          </div>
        </div>"""

    count = len(files)
    content = f'<div class="list">{cards}</div>' if files else '<div class="empty"><div class="empty-icon">🎙</div><div class="etitle">No transcripts yet</div><p>Creators will appear here when they go live.</p></div>'

    body = f"""{header(active='home')}
    <main>
      <h1>Live Intel</h1>
      <p class="sub">Auto-recorded and transcribed TikTok lives.</p>
      {f'<h2>By Creator</h2><div class="list" style="margin-bottom:36px">{summary_btns}</div>' if summary_btns else ''}
      <div class="sec-label">{count} chunk transcript{'s' if count != 1 else ''}</div>
      {content}
    </main>"""
    return page("Live Intel - Root Labs", body)

# ── Creators management ────────────────────────────────────

@app.route("/creators")
def creators_page():
    creators = load_creators()
    rows = ""
    for c in creators:
        rows += f"""<div class="card">
          <div><span class="creator-status"></span><div class="cname" style="display:inline">@{c}</div></div>
          <div class="btns">
            <form method="POST" action="/creators/remove" style="margin:0">
              <input type="hidden" name="username" value="{c}">
              <button type="submit" class="btn btn-red">Remove</button>
            </form>
          </div>
        </div>"""

    body = f"""{header(active='creators')}
    <main>
      <h1>Tracked Creators</h1>
      <p class="sub">Add or remove creators to monitor. Changes take effect immediately.</p>
      <form class="add-form" method="POST" action="/creators/add">
        <input type="text" name="username" placeholder="TikTok username (no @)" required>
        <button type="submit" class="btn btn-orange">+ Add Creator</button>
      </form>
      <div class="sec-label">{len(creators)} creator{'s' if len(creators) != 1 else ''} tracked</div>
      <div class="list">{rows if rows else '<div class="empty"><div class="empty-icon">👤</div><div class="etitle">No creators yet</div><p>Add a TikTok username above to start tracking.</p></div>'}</div>
    </main>"""
    return page("Creators - Live Intel", body)

@app.route("/creators/add", methods=["POST"])
def add_creator():
    username = request.form.get("username", "").strip().lstrip("@")
    if username:
        creators = load_creators()
        if username not in creators:
            creators.append(username)
            save_creators(creators)
            ensure_recorder_running(username)
    return redirect("/creators")

@app.route("/creators/remove", methods=["POST"])
def remove_creator():
    username = request.form.get("username", "").strip()
    if username:
        creators = load_creators()
        creators = [c for c in creators if c != username]
        save_creators(creators)
    return redirect("/creators")

# ── Transcript view ────────────────────────────────────────

@app.route("/transcript/<n>")
def view_transcript(n):
    path = TRANSCRIPTS_DIR / f"{n}.txt"
    if not path.exists(): abort(404)
    content = path.read_text()
    body = f"""{header(True)}
    <main>
      <h1 style="margin-bottom:6px">{n}</h1>
      <p class="sub" style="margin-bottom:24px">Raw transcript</p>
      <button class="copy-btn" onclick="navigator.clipboard.writeText(document.getElementById('t').innerText).then(()=>{{this.textContent='✓ Copied';setTimeout(()=>this.textContent='⎘ Copy',2000)}})">⎘ Copy</button>
      <pre id="t">{content}</pre>
    </main>"""
    return page(n, body)

# ── Chunk intel ────────────────────────────────────────────

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
    pain  = "".join(f"<li>{p}</li>" for p in i.get("pain_points", []))
    terms = "".join(f'<span class="tag">{t}</span>' for t in i.get("mechanism", {}).get("key_terms_used", []))
    proof = "".join(f'<div class="pi"><div class="ptype">{p["type"]}</div><div class="pdet">{p["detail"]}</div></div>' for p in i.get("proof", []))
    objs  = "".join(f'<div class="oi"><div class="oq">Q: {o["objection"]}</div><div class="oa">{o["response"]}</div></div>' for o in i.get("objections_handled", []))
    swipes= "".join(f'<div class="swipe" onclick="navigator.clipboard.writeText(this.innerText)">{s}</div>' for s in i.get("swipe_lines", []))
    apps  = "".join(f'<div class="aitem">{a}</div>' for a in i.get("root_labs_applications", []))
    h, m, cta = i.get("hook", {}), i.get("mechanism", {}), i.get("cta", {})
    creator = n.split("_")[0]
    body = f"""{header(True)}
    <main>
      <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:36px;flex-wrap:wrap;gap:12px">
        <div><h1 style="margin-bottom:4px">Intelligence Report</h1><p class="sub">{n}</p></div>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <a class="btn btn-outline" href="/summary/{creator}">Full Summary</a>
          <a class="refresh-a" href="/analyze/{n}/refresh">↻ Re-analyze</a>
        </div>
      </div>
      <div class="grid">
        <div class="icard dark full"><div class="ilabel">Hook</div><div class="big">"{h.get('opening_line','')}"</div><span class="htag">{h.get('hook_type','')}</span><div class="why">{h.get('why_it_works','')}</div></div>
        <div class="icard"><div class="ilabel">Pain Points</div><ul class="ilist">{pain}</ul></div>
        <div class="icard"><div class="ilabel">Mechanism</div><div style="font-size:.86rem;line-height:1.6;margin-bottom:10px">{m.get('explanation','')}</div><div class="tags">{terms}</div></div>
        <div class="icard"><div class="ilabel">Proof Structure</div>{proof}</div>
        <div class="icard dark"><div class="ilabel">CTA</div><div class="cta-text">"{cta.get('language','')}"</div><div class="cta-when">{cta.get('timing','')}</div></div>
        <div class="icard full"><div class="ilabel">Live Loop Structure</div><div class="loop">{i.get('loop_structure','')}</div></div>
        <div class="icard full"><div class="ilabel">Objections Handled</div>{objs}</div>
        <div class="icard"><div class="ilabel">Swipe Lines - click to copy</div>{swipes}</div>
        <div class="icard warm"><div class="ilabel">Root Labs Applications</div>{apps}</div>
      </div>
    </main>"""
    return page(f"Intel - {n}", body)

# ── Full live summary ──────────────────────────────────────

@app.route("/summary/<creator>")
def summary(creator):
    summary_path = INTEL_DIR / f"{creator}_summary.txt"
    if summary_path.exists():
        text = summary_path.read_text()
        body = f"""{header(True)}
        <main>
          <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:28px;flex-wrap:wrap;gap:12px">
            <div><h1 style="margin-bottom:4px">Full Live Summary</h1><p class="sub">@{creator}</p></div>
            <a class="refresh-a" href="/summary/{creator}/refresh">↻ Regenerate</a>
          </div>
          <div class="summary-box">{text}</div>
        </main>"""
        return page(f"Summary - {creator}", body)

    # stitch all chunks for this creator
    chunks = sorted(TRANSCRIPTS_DIR.glob(f"{creator}_*.txt"), key=lambda f: f.stat().st_mtime)
    if not chunks:
        abort(404)

    full_transcript = "\n\n---\n\n".join(f.read_text() for f in chunks)
    # truncate to ~80k chars to stay within context
    if len(full_transcript) > 80000:
        full_transcript = full_transcript[:80000] + "\n\n[truncated]"

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": SUMMARY_PROMPT + full_transcript}],
            temperature=0.4,
        )
        text = response.choices[0].message.content.strip()
        summary_path.write_text(text)
        body = f"""{header(True)}
        <main>
          <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:28px;flex-wrap:wrap;gap:12px">
            <div><h1 style="margin-bottom:4px">Full Live Summary</h1><p class="sub">@{creator} · {len(chunks)} chunks</p></div>
            <a class="refresh-a" href="/summary/{creator}/refresh">↻ Regenerate</a>
          </div>
          <div class="summary-box">{text}</div>
        </main>"""
        return page(f"Summary - {creator}", body)
    except Exception as e:
        log.error(f"Summary failed: {e}")
        abort(500)

@app.route("/spikes/<creator>/refresh")
def refresh_spikes(creator):
    p = INTEL_DIR / f"{creator}_spikes.json"
    if p.exists(): p.unlink()
    return redirect(f"/spikes/{creator}")

@app.route("/summary/<creator>/refresh")
def refresh_summary(creator):
    p = INTEL_DIR / f"{creator}_summary.txt"
    if p.exists(): p.unlink()
    return summary(creator)

# ── Traffic spike analysis ─────────────────────────────────

@app.route("/spikes/<creator>")
def spikes(creator):
    spike_path = INTEL_DIR / f"{creator}_spikes.json"
    viewer_log  = COMMENTS_DIR / f"{creator}_viewers.json"

    if not viewer_log.exists():
        body = f"""{header(True)}
        <main>
          <h1 style="margin-bottom:6px">Traffic Spike Analysis</h1>
          <p class="sub">@{creator}</p>
          <div class="empty"><div class="empty-icon">📈</div>
            <div class="etitle">No viewer data yet</div>
            <p>Viewer count polling starts automatically when a creator goes live.<br>Check back after the next live session.</p>
          </div>
        </main>"""
        return page(f"Spikes - {creator}", body)

    # check viewer log has real data
    try:
        viewer_entries = json.loads(viewer_log.read_text())
        if len(viewer_entries) < 3:
            body = f"""{header(True)}
            <main>
              <h1 style="margin-bottom:6px">Traffic Spike Analysis</h1>
              <p class="sub">@{creator}</p>
              <div class="empty"><div class="empty-icon">📈</div>
                <div class="etitle">Not enough viewer data yet</div>
                <p>Only {len(viewer_entries)} data point(s) collected so far.<br>Need at least a few minutes of live data. Check back soon.</p>
              </div>
            </main>"""
            return page(f"Spikes - {creator}", body)
    except Exception:
        viewer_entries = []

    # invalidate cached spike data if viewer log is newer (more data collected)
    if spike_path.exists():
        try:
            cached_time = spike_path.stat().st_mtime
            viewer_time = viewer_log.stat().st_mtime
            # re-analyze if viewer data is more than 30 min newer than cache
            if viewer_time - cached_time > 1800:
                spike_path.unlink()
        except Exception:
            pass

    if spike_path.exists():
        data = json.loads(spike_path.read_text())
    else:
        chunks = sorted(TRANSCRIPTS_DIR.glob(f"{creator}_*.txt"), key=lambda f: f.stat().st_mtime)
        if not chunks:
            body = f"""{header(True)}
            <main>
              <h1 style="margin-bottom:6px">Traffic Spike Analysis</h1>
              <p class="sub">@{creator}</p>
              <div class="empty"><div class="empty-icon">📈</div>
                <div class="etitle">No transcript data yet</div>
                <p>Waiting for a chunk to finish transcribing.</p>
              </div>
            </main>"""
            return page(f"Spikes - {creator}", body)
        transcript = "\n\n".join(f.read_text() for f in chunks)[:60000]
        viewer_data = viewer_log.read_text()
        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": SPIKE_PROMPT.replace("{viewer_data}", viewer_data).replace("{transcript}", transcript)}],
                temperature=0.3,
            )
            raw = response.choices[0].message.content.strip()
            if raw.startswith("```"): raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
            data = json.loads(raw)
            spike_path.write_text(json.dumps(data, indent=2))
        except Exception as e:
            log.error(f"Spike analysis failed: {e}")
            abort(500)

    spikes_html = ""
    for s in data.get("spikes", []):
        spikes_html += f"""<div class="spike-item">
          <div class="spike-time">{s.get('timestamp','')} &nbsp;·&nbsp; {s.get('viewer_change','')}</div>
          <div style="font-size:.86rem;font-style:italic;margin-bottom:6px">"{s.get('what_was_said','')}"</div>
          <div style="font-size:.84rem;color:var(--muted)">{s.get('why_it_worked','')}</div>
        </div>"""

    ret  = "".join(f'<div class="comment-theme">{r}</div>' for r in data.get("retention_patterns", []))
    drop = "".join(f'<div class="comment-theme">{d}</div>' for d in data.get("drop_off_triggers", []))
    apps = "".join(f'<div class="aitem">{a}</div>' for a in data.get("root_labs_takeaways", []))

    body = f"""{header(True)}
    <main>
      <h1 style="margin-bottom:6px">Traffic Spike Analysis</h1>
      <p class="sub" style="margin-bottom:32px">@{creator}</p>
      <div class="grid">
        <div class="icard full"><div class="ilabel">Spike Moments</div>{spikes_html}</div>
        <div class="icard"><div class="ilabel">What Holds Viewers</div>{ret}</div>
        <div class="icard"><div class="ilabel">Drop-off Triggers</div>{drop}</div>
        <div class="icard warm full"><div class="ilabel">Root Labs Takeaways</div>{apps}</div>
      </div>
    </main>"""
    return page(f"Spikes - {creator}", body)

# ── Comments analysis ──────────────────────────────────────

@app.route("/comments/<creator>")
def comments(creator):
    comments_path = INTEL_DIR / f"{creator}_comments.json"
    raw_comments   = COMMENTS_DIR / f"{creator}_chat.txt"

    if not raw_comments.exists():
        body = f"""{header(True)}
        <main>
          <h1 style="margin-bottom:6px">Comment Intelligence</h1>
          <p class="sub">@{creator}</p>
          <div class="empty"><div class="empty-icon">💬</div>
            <div class="etitle">No comments captured yet</div>
            <p>Chat is saved automatically during recording.<br>Check back after the next live session.</p>
          </div>
        </main>"""
        return page(f"Comments - {creator}", body)

    # require minimum comments before analysis
    raw_lines = [l for l in raw_comments.read_text().splitlines() if l.strip()]
    if len(raw_lines) < 30:
        body = f"""{header(True)}
        <main>
          <h1 style="margin-bottom:6px">Comment Intelligence</h1>
          <p class="sub">@{creator}</p>
          <div class="empty"><div class="empty-icon">💬</div>
            <div class="etitle">Not enough comments yet</div>
            <p>Collected {len(raw_lines)} comment(s) so far. Need at least 30 for meaningful analysis.<br>Check back after more of the live is captured.</p>
          </div>
        </main>"""
        return page(f"Comments - {creator}", body)

    if comments_path.exists():
        # invalidate cache if raw comments have grown significantly since last analysis
        try:
            cached_time = comments_path.stat().st_mtime
            raw_time = raw_comments.stat().st_mtime
            # if raw file is more than 30 min newer than cache, re-analyze
            if raw_time - cached_time > 1800:
                comments_path.unlink()
        except Exception:
            pass

    if comments_path.exists():
        data = json.loads(comments_path.read_text())
    else:
        chat_text = raw_comments.read_text()[:40000]
        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": COMMENTS_PROMPT + chat_text}],
                temperature=0.3,
            )
            raw = response.choices[0].message.content.strip()
            if raw.startswith("```"): raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
            data = json.loads(raw)
            comments_path.write_text(json.dumps(data, indent=2))
        except Exception as e:
            log.error(f"Comments analysis failed: {e}")
            abort(500)

    themes  = "".join(f'<div class="comment-theme">{t}</div>' for t in data.get("top_themes", []))
    buying  = "".join(f'<div class="aitem">{b}</div>' for b in data.get("buying_signals", []))
    objs    = "".join(f'<div class="aitem">{o}</div>' for o in data.get("objections", []))
    qs      = "".join(f'<div class="aitem">{q}</div>' for q in data.get("top_questions", []))
    triggers= "".join(f'<div class="comment-theme">{t}</div>' for t in data.get("emotional_triggers", []))
    apps    = "".join(f'<div class="aitem">{a}</div>' for a in data.get("root_labs_applications", []))

    body = f"""{header(True)}
    <main>
      <h1 style="margin-bottom:6px">Comment Intelligence</h1>
      <p class="sub" style="margin-bottom:32px">@{creator}</p>
      <div class="grid">
        <div class="icard full"><div class="ilabel">Top Themes</div>{themes}</div>
        <div class="icard"><div class="ilabel">Buying Signals</div>{buying}</div>
        <div class="icard"><div class="ilabel">Objections</div>{objs}</div>
        <div class="icard full"><div class="ilabel">Top Questions</div>{qs}</div>
        <div class="icard"><div class="ilabel">Emotional Triggers</div>{triggers}</div>
        <div class="icard warm"><div class="ilabel">Root Labs Applications</div>{apps}</div>
      </div>
    </main>"""
    return page(f"Comments - {creator}", body)

# ── Drive upload ───────────────────────────────────────────

def upload_to_drive(mp4_path):
    # Drive upload disabled - enable by setting DRIVE_FOLDER_ID when ready
    pass

# ── Transcription ──────────────────────────────────────────

def transcribe(mp4_path):
    creator = mp4_path.parent.name
    transcript_path = TRANSCRIPTS_DIR / f"{creator}_{mp4_path.stem}.txt"
    if transcript_path.exists(): return
    log.info(f"Transcribing {mp4_path.name}...")
    threading.Thread(target=upload_to_drive, args=(mp4_path,), daemon=True).start()
    mp3_path = mp4_path.with_suffix(".mp3")
    try:
        subprocess.run(["ffmpeg", "-y", "-i", str(mp4_path), "-vn", "-ar", "16000", "-ac", "1", "-b:a", "32k", str(mp3_path)], capture_output=True)
        with open(mp3_path, "rb") as f:
            result = client.audio.transcriptions.create(model="whisper-1", file=f, response_format="text")
        transcript_path.write_text(result)
        log.info(f"Saved -> {transcript_path}")
        mp3_path.unlink(missing_ok=True)
        mp4_path.unlink(missing_ok=True)
    except Exception as e:
        log.error(f"Transcription failed: {e}")
        mp3_path.unlink(missing_ok=True)

def watch_recordings():
    while True:
        for mp4 in RECORDINGS_DIR.rglob("*.mp4"):
            # skip raw flv-converted files still being processed
            if "_flv" in mp4.stem: continue
            if mp4 in already_processed: continue
            s1 = mp4.stat().st_size
            time.sleep(5)
            s2 = mp4.stat().st_size
            if s1 == s2 and s2 > 0:
                already_processed.add(mp4)
                threading.Thread(target=transcribe, args=(mp4,), daemon=True).start()
        time.sleep(POLL_INTERVAL)

# ── Viewer count polling ───────────────────────────────────

def poll_viewer_count(user, room_id):
    viewer_log = COMMENTS_DIR / f"{user}_viewers.json"
    data = []
    start = time.time()
    log.info(f"Starting viewer count polling for @{user}")
    while True:
        try:
            import urllib.request
            url = f"https://webcast.tiktok.com/webcast/room/info/?room_id={room_id}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                room_data = json.loads(resp.read())
            count = room_data.get("data", {}).get("room", {}).get("stats", {}).get("total_user_count", 0)
            elapsed = int(time.time() - start)
            data.append({"t": elapsed, "viewers": count})
            viewer_log.write_text(json.dumps(data))
        except Exception as e:
            log.warning(f"Viewer poll failed: {e}")
        time.sleep(30)


# ── Chat + viewer capture ──────────────────────────────────

def start_chat_capture(user):
    """Runs in a thread - captures comments and viewer counts via TikTokLive WebSocket"""
    async def _run():
        try:
            from TikTokLive import TikTokLiveClient
            from TikTokLive.events import CommentEvent, ConnectEvent, DisconnectEvent
        except ImportError:
            log.error("TikTokLive not installed - skipping chat capture")
            return

        chat_file    = COMMENTS_DIR / f"{user}_chat.txt"
        viewers_file = COMMENTS_DIR / f"{user}_viewers.json"
        viewer_log   = []
        start_time   = time.time()

        client = TikTokLiveClient(unique_id=f"@{user}")

        @client.on(ConnectEvent)
        async def on_connect(event):
            log.info(f"Chat capture connected for @{user}")

        @client.on(CommentEvent)
        async def on_comment(event):
            ts  = int(time.time() - start_time)
            line = f"[{ts}s] {event.user.unique_id}: {event.comment}\n"
            with open(chat_file, "a", encoding="utf-8") as f:
                f.write(line)

        @client.on(DisconnectEvent)
        async def on_disconnect(event):
            log.info(f"Chat capture disconnected for @{user}")

        # capture viewer count from RoomUserSeqEvent - fires on every viewer change
        try:
            from TikTokLive.events import RoomUserSeqEvent
            @client.on(RoomUserSeqEvent)
            async def on_viewers(event):
                elapsed = int(time.time() - start_time)
                count = getattr(event, 'viewer_count', 0) or getattr(event, 'total_user', 0)
                if count:
                    viewer_log.append({"t": elapsed, "viewers": count})
                    viewers_file.write_text(json.dumps(viewer_log))
        except ImportError:
            pass

        try:
            await client.connect()
        except Exception as e:
            log.warning(f"Chat capture error @{user}: {e}")

    # retry loop
    while True:
        if user not in load_creators():
            break
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(_run())
        except Exception as e:
            log.warning(f"Chat capture loop error @{user}: {e}")
        time.sleep(60)

# ── Recorder ──────────────────────────────────────────────

def ensure_recorder_running(user):
    if user not in recorder_threads or not recorder_threads[user].is_alive():
        t = threading.Thread(target=start_recorder, args=(user,), daemon=True)
        t.start()
        recorder_threads[user] = t
        # also start chat capture in parallel
        threading.Thread(target=start_chat_capture, args=(user,), daemon=True).start()

def start_recorder(user):
    chunk = 0
    while True:
        # check if still in creators list
        if user not in load_creators():
            log.info(f"@{user} removed from creators - stopping recorder")
            break
        chunk += 1
        output_dir = RECORDINGS_DIR / user
        output_dir.mkdir(parents=True, exist_ok=True)
        chat_file  = COMMENTS_DIR / f"{user}_chat.txt"
        cmd = [
            "/root/.local/bin/uv", "run", "python", "src/main.py",
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

# ── Entry point ────────────────────────────────────────────

if __name__ == "__main__":
    creators = load_creators()
    if not creators:
        log.warning("No creators configured - add them via /creators")
    else:
        log.info(f"Starting pipeline for: {creators}")
        for c in creators:
            ensure_recorder_running(c)

    threading.Thread(target=watch_recordings, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT)
