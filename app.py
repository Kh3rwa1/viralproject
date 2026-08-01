"""app.py - LeadPages product UI. Install Flask to run."""
from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path

from flask import (Flask, jsonify, request, send_file, send_from_directory,
                   session)
from flask_cors import CORS

import core
import engine
import jobs
import licenses

ROOT = Path(__file__).resolve().parent
SITE = ROOT / "site"

app = Flask(__name__)
app.secret_key = os.getenv("APP_SECRET", os.urandom(24).hex())
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
CORS(app, supports_credentials=True, origins=["https://leadpages-main.netlify.app", "https://leadpages-app-production.up.railway.app", "http://127.0.0.1:8000", "http://localhost:8000"])


def auth():
    k = session.get("key")
    if not k:
        return None, "not signed in"
    return licenses.check(k)


@app.get("/")
def landing():
    return send_from_directory(SITE, "index.html")


@app.get("/terms")
def terms():
    return send_from_directory(SITE, "terms.html")


@app.get("/og.svg")
def og_svg():
    return send_from_directory(SITE, "og.svg")


@app.get("/og.jpg")
def og_jpg_alias():
    return send_from_directory(SITE, "og.jpg")


@app.get("/app")
def tool():
    return UI


@app.post("/api/auth")
def api_auth():
    row, err = licenses.check((request.json or {}).get("key", ""))
    if err:
        return jsonify({"ok": False, "error": err}), 401
    session["key"] = row["key"]
    return jsonify({"ok": True, "plan": row["plan"], "remaining": row["remaining"],
                    "max_rows": row["max_rows"], "can_live": bool(row["can_live"])})


@app.post("/api/logout")
def api_logout():
    session.clear()
    return jsonify({"ok": True})


@app.get("/api/me")
def api_me():
    row, err = auth()
    if err:
        return jsonify({"ok": False, "error": err}), 401
    return jsonify({"ok": True, "plan": row["plan"], "remaining": row["remaining"],
                    "max_rows": row["max_rows"], "can_live": bool(row["can_live"])})


@app.get("/api/templates")
def api_templates():
    row, err = auth()
    if err:
        return jsonify({"error": err}), 401
    return jsonify([{"name": t["name"], "label": t["label"], "accent": t["accent"],
                     "contract": t["contract"]} for t in engine.list_templates()])


@app.post("/api/upload")
def api_upload():
    row, err = auth()
    if err:
        return jsonify({"error": err}), 401
    if jobs.running_for(row["key"]) >= jobs.MAX_JOBS_PER_KEY:
        return jsonify({"error": "you already have a build running"}), 429

    template = (request.form.get("template") or "").strip()
    templates = {t["name"] for t in engine.list_templates()}
    if not template or template not in templates:
        return jsonify({"error": "step 1: pick a business type first"}), 400

    f = request.files.get("file")
    if not f or not f.filename.lower().endswith(".csv"):
        return jsonify({"error": "upload a .csv"}), 400

    job = jobs.new_job(row["key"])
    job["template"] = template
    job["stage"] = "uploaded"
    dest = Path(job["folder"]) / "input.csv"
    f.save(dest)

    rows, fields = core.read_csv(dest)
    kept, dropped = core.plan_rows(rows, fields, keep_real=True)
    if not kept:
        return jsonify({"error": "No valid leads found in CSV."}), 400

    if row["remaining"] <= 0:
        return jsonify({"error": "You have 0 credits remaining. Please top up or enter a new key."}), 402

    max_allowed = min(row["max_rows"], row["remaining"])
    if max_allowed <= 0:
        return jsonify({"error": "You have 0 credits remaining."}), 402

    extra_dropped = max(0, len(kept) - max_allowed)
    kept = kept[:max_allowed]
    job["limit"] = max_allowed

    return jsonify({"job": job["id"], "total_rows": len(rows), "buildable": len(kept),
                    "dropped": len(dropped) + extra_dropped, "dropped_detail": dropped[:8],
                    "sample": [{"name": r["name"], "city": r["city"],
                                "phone": r["phone"], "wa": r["phone_kind"] == "mobile"}
                               for r in kept[:5]]})


@app.post("/api/build/<jid>")
def api_build(jid):
    row, err = auth()
    if err:
        return jsonify({"error": err}), 401
    job = jobs.get(jid, row["key"])
    if not job:
        return jsonify({"error": "job not found"}), 404
    o = request.json or {}
    if o.get("live") and not row["can_live"]:
        return jsonify({"error": "publishing indexable pages needs the Pro plan"}), 402
    if not o.get("accept_terms"):
        return jsonify({"error": "you must accept the fair-use terms"}), 400
    if not job.get("template"):
        return jsonify({"error": "step 1 missing: pick a business type"}), 400
    jobs.start_build(job, {"template": job["template"],
                           "limit": job.get("limit", row["max_rows"]),
                           "city": o.get("city", ""), "only": o.get("only", ""),
                           "live": bool(o.get("live")), "keep_real": True,
                           "site_name": o.get("site_name", "Previews")})
    return jsonify({"ok": True})


@app.get("/api/job/<jid>")
def api_job(jid):
    row, err = auth()
    if err:
        return jsonify({"error": err}), 401
    job = jobs.get(jid, row["key"])
    if not job:
        return jsonify({"error": "job not found"}), 404
    return jsonify({k: job[k] for k in
                    ("id", "state", "progress", "total", "message", "summary", "live_url")})


@app.post("/api/deploy/<jid>")
def api_deploy(jid):
    row, err = auth()
    if err:
        return jsonify({"error": err}), 401
    job = jobs.get(jid, row["key"])
    if not job or job["state"] not in ("done", "deployed"):
        return jsonify({"error": "build not ready"}), 400
    o = request.json or {}
    token, site = o.get("token", "").strip(), o.get("site", "").strip().lower()
    if not token or not site:
        return jsonify({"error": "netlify token + site name required"}), 400
    jobs.start_deploy(job, site, token)
    return jsonify({"ok": True})


@app.get("/api/zip/<jid>")
def api_zip(jid):
    row, err = auth()
    if err:
        return jsonify({"error": err}), 401
    job = jobs.get(jid, row["key"])
    if not job or not job["summary"]:
        return jsonify({"error": "nothing built"}), 404
    buf = io.BytesIO()
    dist = Path(job["folder"]) / "dist"
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in dist.rglob("*"):
            if p.is_file():
                z.write(p, p.relative_to(dist).as_posix())
    buf.seek(0)
    return send_file(buf, mimetype="application/zip", as_attachment=True,
                     download_name=f"pages-{jid}.zip")


@app.get("/api/csv/<jid>")
def api_csv(jid):
    row, err = auth()
    if err:
        return jsonify({"error": err}), 401
    job = jobs.get(jid, row["key"])
    if not job:
        return jsonify({"error": "job not found"}), 404
    if job["state"] != "deployed":
        return jsonify({"error": "step 3 pending: publish the sites first, "
                                 "then your CSV will include the live links"}), 409
    p = Path(job["folder"]) / "clean.csv"
    if not p.exists():
        p = Path(job["folder"]) / "leads.csv"
    if not p.exists():
        return jsonify({"error": "no csv yet"}), 404
    return send_file(p, as_attachment=True, download_name="clean-leads-with-links.csv")


@app.get("/api/csv_data/<jid>")
def api_csv_data(jid):
    row, err = auth()
    if err:
        return jsonify({"error": err}), 401
    job = jobs.get(jid, row["key"])
    if not job:
        return jsonify({"error": "job not found"}), 404
    p = Path(job["folder"]) / "clean.csv"
    if not p.exists():
        p = Path(job["folder"]) / "leads.csv"
    if not p.exists():
        return jsonify({"error": "no csv yet"}), 404
    rows, fields = core.read_csv(p)
    return jsonify({"fields": fields, "rows": rows, "total": len(rows)})


@app.get("/p/<jid>/")
@app.get("/p/<jid>/<path:sub>")
def preview(jid, sub="index.html"):
    row, err = auth()
    if err:
        return "sign in first", 401
    job = jobs.get(jid, row["key"])
    if not job:
        return "not found", 404
    if sub.endswith("/") or "." not in sub.rsplit("/", 1)[-1]:
        sub = sub.rstrip("/") + "/index.html"
    return send_from_directory(Path(job["folder"]) / "dist", sub)


UI = r"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>LeadPages - generator</title><style>
*{box-sizing:border-box}body{margin:0;font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;background:#f6f5f0;color:#141414}
body:before{content:"";position:fixed;inset:0;pointer-events:none;background-image:linear-gradient(#e2e0d8 1px,transparent 1px),linear-gradient(90deg,#e2e0d8 1px,transparent 1px);background-size:80px 80px;opacity:.45}
.wrap{position:relative;max-width:780px;margin:0 auto;padding:30px 20px 90px}.top{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:18px}
h1{font-size:25px;margin:0;color:#12634a;letter-spacing:-.03em}.sub{color:#6b6963;margin:4px 0 0;font-size:14px}.card{background:#fffefb;border:1px solid #e2e0d8;border-radius:18px;padding:20px;margin-bottom:14px;box-shadow:0 18px 44px -30px rgba(20,20,20,.35);transition:.35s}
.card h3{margin:0 0 12px;font-size:15px;letter-spacing:.02em}.card h3 span{display:inline-grid;place-items:center;width:28px;height:28px;border-radius:99px;background:#e8f0ea;color:#12634a;margin-right:8px;font-size:13px}
input,button{font:inherit;border-radius:12px;border:1px solid #d9d6cb;padding:12px 13px;background:#fbfaf6;color:#141414;width:100%}button{background:#12634a;color:white;border:0;font-weight:700;cursor:pointer;margin-top:10px;box-shadow:0 10px 22px -15px rgba(18,99,74,.9)}button.ghost{background:#141414;color:white}button.light{background:#fffefb;color:#12634a;border:1px solid #cfe0d5;box-shadow:none}button:disabled{opacity:.45;cursor:not-allowed}.err{color:#b42318;font-size:13px;margin-top:8px}.muted{color:#6b6963;font-size:13px}.hide{display:none}
.pill{display:inline-block;background:#e8f0ea;color:#12634a;border:1px solid #cfe0d5;border-radius:999px;padding:5px 11px;font-size:12px;margin:4px 6px 0 0}.types{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}.type{display:flex;align-items:center;justify-content:flex-start;gap:9px;background:#fbfaf6;color:#141414;border:1px solid #e2e0d8;box-shadow:none;margin:0;text-align:left}.type.on{border-color:#12634a;background:#e8f0ea;color:#12634a}.type:disabled{opacity:.38}.sw{width:16px;height:16px;border-radius:5px;border:1px solid rgba(0,0,0,.12)}
[data-lock]{opacity:.42;pointer-events:none}[data-lock].open{opacity:1;pointer-events:auto}.bar{height:8px;background:#ece9df;border-radius:99px;overflow:hidden;margin-top:12px}.bar i{display:block;height:100%;background:#12634a;width:0;transition:.3s}.chk{display:flex;gap:9px;margin-top:12px;align-items:flex-start}.chk input{width:auto;margin-top:4px}.row{display:flex;gap:10px}.row>*{flex:1}table{width:100%;border-collapse:collapse;font-size:13px;margin-top:9px}td,th{padding:8px;border-bottom:1px solid #ece9df;text-align:left}a{color:#12634a}@media(max-width:620px){.row,.top{display:block}.wrap{padding-inline:14px}}
.table-scroll{max-height:300px;overflow-y:auto;margin-top:10px;border:1px solid #e2e0d8;border-radius:12px;background:#fff}
</style></head><body><div class=wrap>
<div class=top><div><h1>leadpages.</h1><p class=sub>Business type chuno, list upload karo, live karo, CSV le lo.</p></div><a href=/ class=muted>Sales page</a></div>

<div class=card id=gate><h3><span>0</span>Access key</h3>
<input id=key placeholder="LP-XXXX-XXXX-XXXX" autocomplete=off>
<button onclick=signin()>Unlock</button><div class=err id=gateErr></div>
<p class=muted style=margin-top:12px>No key? Telegram pe <a href="https://t.me/dulork" target="_blank" style="color:#12634a;font-weight:700">@dulork</a> se key le lo.</p></div>

<div id=app class=hide>
<div class=card><h3>Your plan</h3><div id=me></div><button class=light onclick=logout()>Sign out</button></div>

<div class=card id=s1><h3><span>1</span>Kaunsa business?</h3>
  <div id=types class=types></div>
  <div class=err id=t1></div></div>

<div class=card id=s2 data-lock><h3><span>2</span>List upload karo</h3>
  <input type=file id=file accept=.csv disabled>
  <button id=upBtn disabled onclick=upload()>Check karo</button>
  <div class=err id=statusErr></div>
  <div id=report class=hide></div>
  <div class=chk><input type=checkbox id=terms disabled><label for=terms class=muted style=margin:0>I confirm I can contact these businesses and will not publish pages that impersonate them. Pages stay noindex until a client signs.</label></div>
  <button id=buildBtn class=hide onclick=build()>Websites banao</button>
  <div class=bar><i id=barI></i></div><div class=muted id=status></div></div>

<div class=card id=s3 data-lock><h3><span>3</span>Live karo</h3>
  <div class=row><input id=site placeholder="jsr-previews" disabled><input id=token type=password placeholder="Netlify token (save nahi hota)" disabled></div>
  <button id=depBtn disabled onclick=deploy()>Publish karo</button>
  <div class=muted id=depStatus></div>
  <div id=liveList class=hide></div></div>

<div class=card id=s4 data-lock><h3><span>4</span>Saaf CSV download</h3>
  <p class=muted>Har lead ka live link isi file me aayega.</p>
  <div id=csvPreview class="hide table-scroll"></div>
  <div style="margin-top:12px">
    <button id=csvBtn disabled onclick=dl('csv')>CSV download karo</button>
    <button class=ghost id=zipBtn disabled onclick=dl('zip')>Backup .zip</button>
  </div></div>
</div></div><script>
let JOB=null,ME=null,TPL=null,POLL=null;
const $=i=>document.getElementById(i);
const api=(u,o={})=>fetch(u,{headers:{'Content-Type':'application/json'},...o}).then(r=>r.json());
function unlock(id){const el=$(id);el.classList.add('open');el.querySelectorAll('input,button').forEach(e=>e.disabled=false);el.scrollIntoView({behavior:'smooth',block:'center'})}
async function signin(){const r=await api('/api/auth',{method:'POST',body:JSON.stringify({key:$('key').value})});if(!r.ok){$('gateErr').textContent=r.error;return}boot(r)}
async function logout(){await api('/api/logout',{method:'POST'});location.reload()}
function boot(m){ME=m;$('gate').classList.add('hide');$('app').classList.remove('hide');$('me').innerHTML=`<span class=pill>${m.plan}</span><span class=pill>${m.remaining} credits left</span><span class=pill>max ${m.max_rows} rows/job</span>`;loadTypes()}
async function loadTypes(){const ts=await api('/api/templates');if(ts.error){$('t1').textContent=ts.error;return}$('types').innerHTML=ts.map(t=>`<button class="type" data-n="${t.name}" onclick="pickType(this)"><span class="sw" style="background:${t.accent}"></span>${t.label}</button>`).join('')||'<p class=muted>No templates found.</p>'}
function pickType(b){document.querySelectorAll('.type').forEach(x=>x.classList.remove('on'));b.classList.add('on');TPL=b.dataset.n;$('t1').textContent='';unlock('s2')}
async function upload(){if(!TPL){$('t1').textContent='Pehle business type chuno';return}const f=$('file').files[0];if(!f){$('statusErr').textContent='CSV file chuno';return}$('statusErr').textContent='';const fd=new FormData();fd.append('file',f);fd.append('template',TPL);const r=await fetch('/api/upload',{method:'POST',body:fd}).then(r=>r.json());if(r.error){$('statusErr').textContent=r.error;return}JOB=r.job;$('report').classList.remove('hide');const noteNotice=r.notice?`<div style="background:#fef3c7;color:#92400e;padding:8px 12px;border-radius:10px;margin:8px 0;font-size:13px">⚠️ ${r.notice}</div>`:'';$('report').innerHTML=`${noteNotice}<b>${r.buildable}</b> websites banengi · ${r.dropped} hate<table>${r.sample.map(s=>`<tr><td>${s.name}</td><td>${s.city}</td><td>${s.phone}</td><td>${s.wa?'WhatsApp':'call only'}</td></tr>`).join('')}</table><p class=muted>Skipped: ${r.dropped_detail.map(d=>d.why).join(', ')||'none'}</p>`;$('terms').disabled=false;$('buildBtn').disabled=false;$('buildBtn').classList.remove('hide')}
async function build(){if(!$('terms').checked){alert('fair-use box tick karo');return}$('buildBtn').disabled=true;const r=await api('/api/build/'+JOB,{method:'POST',body:JSON.stringify({site_name:$('site').value||'Previews',accept_terms:true})});if(r.error){$('statusErr').textContent=r.error;$('buildBtn').disabled=false;return}poll()}
async function loadLiveAndCsv(j){
  const data = await api('/api/csv_data/' + JOB);
  if (data && data.rows && data.rows.length) {
    const baseUrl = (j.live_url || '').replace(/\/$/, '');
    $('liveList').classList.remove('hide');
    $('liveList').innerHTML = `<h4 style="margin:12px 0 6px">All Deployed Websites (${data.rows.length}):</h4><div class=table-scroll><table><thead><tr><th>#</th><th>Business Name</th><th>City</th><th>Live Link</th></tr></thead><tbody>${data.rows.map((r,i)=>{
      const name = r.name || r.name_full || r.slug || 'Business';
      const city = r.city || '';
      const url = r.share_url || (baseUrl + '/' + (r.slug || '') + '/');
      return `<tr><td>${i+1}</td><td><b>${name}</b></td><td>${city}</td><td><a href="${url}" target=_blank style="font-weight:700;color:#12634a">Open Site ↗</a></td></tr>`;
    }).join('')}</tbody></table></div>`;
    
    $('csvPreview').classList.remove('hide');
    $('csvPreview').innerHTML = `<table><thead><tr><th>#</th><th>Business Name</th><th>City</th><th>Phone</th><th>Deployed Website</th></tr></thead><tbody>${data.rows.map((r,i)=>{
      const name = r.name || r.name_full || r.slug || 'Business';
      const city = r.city || '';
      const phone = r.phone || '';
      const url = r.share_url || (baseUrl + '/' + (r.slug || '') + '/');
      return `<tr><td>${i+1}</td><td><b>${name}</b></td><td>${city}</td><td>${phone}</td><td><a href="${url}" target=_blank style="color:#12634a">${url}</a></td></tr>`;
    }).join('')}</tbody></table>`;
  }
}
function poll(){clearInterval(POLL);POLL=setInterval(async()=>{const j=await api('/api/job/'+JOB);if(j.error){$('status').textContent=j.error;clearInterval(POLL);return}$('status').textContent=j.message||j.state;if(j.total)$('barI').style.width=(100*j.progress/j.total)+'%';if(j.state==='done'){clearInterval(POLL);$('barI').style.width='100%';$('status').innerHTML=`${j.summary.built} pages ready · <a href="/p/${JOB}/${j.summary.slugs[0]}/" target=_blank>preview one</a>`;unlock('s3');api('/api/me').then(m=>$('me').innerHTML=`<span class=pill>${m.plan}</span><span class=pill>${m.remaining} credits left</span>`)}if(j.state==='deployed'){clearInterval(POLL);$('depStatus').innerHTML=`live -> <a href="${j.live_url}" target=_blank>${j.live_url}</a>`;unlock('s4');loadLiveAndCsv(j)}if(j.state==='error'){clearInterval(POLL);$('status').textContent='error: '+j.message;$('depStatus').textContent=j.message}},1500)}
async function deploy(){$('depBtn').disabled=true;$('depStatus').textContent='deploying...';const r=await api('/api/deploy/'+JOB,{method:'POST',body:JSON.stringify({token:$('token').value,site:$('site').value})});if(r.error){$('depStatus').textContent=r.error;$('depBtn').disabled=false;return}poll()}
function dl(k){location.href=`/api/${k}/${JOB}`}
api('/api/me').then(m=>{if(m.ok)boot(m)}).catch(()=>{});
</script></body></html>"""

# Ensure workspace exists on import (for gunicorn)
jobs.WORKSPACE.mkdir(exist_ok=True)
jobs.cleanup(days=7)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
