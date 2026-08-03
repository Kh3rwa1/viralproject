"""app.py - LeadPages product UI. Install Flask to run."""
from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path

from flask import (Flask, jsonify, request, send_file, send_from_directory,
                   session)

import core
import engine
import jobs
import licenses

ROOT = Path(__file__).resolve().parent
SITE = ROOT / "site"

app = Flask(__name__)
is_prod = (os.getenv("FLASK_ENV") == "production" or
           os.getenv("RENDER") is not None or
           os.getenv("RAILWAY_ENVIRONMENT") is not None)
app_secret = os.getenv("APP_SECRET")
if is_prod and not app_secret:
    raise RuntimeError("CRITICAL SECURITY ERROR: APP_SECRET environment variable must be set in production.")
app.secret_key = app_secret or "dev-secret-key-change-in-production"
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024


def auth():
    k = request.headers.get("X-Access-Key") or session.get("key")
    if not k:
        auth_hdr = request.headers.get("Authorization", "")
        if auth_hdr.startswith("Bearer "):
            k = auth_hdr[7:].strip()
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
    return send_from_directory(SITE / "app", "index.html")


@app.post("/api/auth")
def api_auth():
    row, err = licenses.check((request.json or {}).get("key", ""))
    if err:
        return jsonify({"ok": False, "error": err}), 401
    session["key"] = row["key"]
    return jsonify({"ok": True, "plan": row["plan"], "remaining": row["remaining"],
                    "max_rows": row["max_rows"], "can_deploy": bool(row.get("can_deploy")),
                    "can_index": bool(row.get("can_index")), "can_live": bool(row.get("can_deploy"))})


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
                    "max_rows": row["max_rows"], "can_deploy": bool(row.get("can_deploy")),
                    "can_index": bool(row.get("can_index")), "can_live": bool(row.get("can_deploy"))})


@app.get("/api/templates")
def api_templates():
    row, err = auth()
    if err:
        return jsonify({"error": err}), 401
    templates = [
        {
            "id": t.get("id", ""),
            "name": t.get("name", ""),
            "label": t.get("label", t.get("name", "")),
            "category": t.get("category", ""),
            "layout": t.get("layout", ""),
            "description": t.get("description", ""),
            "thumbnail": t.get("thumbnail", ""),
            "badges": t.get("badges", []),
            "version": t.get("version", 1),
        }
        for t in engine.list_templates()
        if t.get("active", True)
    ]
    return jsonify(templates)


@app.post("/api/upload")
def api_upload():
    row, err = auth()
    if err:
        return jsonify({"error": err}), 401
    if jobs.running_for(row["key"]) >= jobs.MAX_JOBS_PER_KEY:
        return jsonify({"error": "you already have a build running"}), 429

    template = (request.form.get("template") or "").strip()
    valid_templates = {t.get("id", t.get("name")) for t in engine.list_templates()}
    valid_templates.update({"coaching", "dentist", "lawyer"})
    valid_templates.update(engine.BUSINESS_CATEGORIES.keys())
    if not template or template not in valid_templates:
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
    kept, dropped = core.plan_rows(rows, fields, keep_real=False)
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
    if o.get("live") and not row.get("can_index"):
        return jsonify({"error": "publishing indexable (dofollow) pages requires the Pro or Agency plan"}), 402
    if not o.get("accept_terms"):
        return jsonify({"error": "you must accept the fair-use terms"}), 400
    if not job.get("template"):
        return jsonify({"error": "step 1 missing: pick a business type"}), 400
    jobs.start_build(job, {"template": job["template"],
                           "limit": job.get("limit", row["max_rows"]),
                           "city": o.get("city", ""), "only": o.get("only", ""),
                           "live": bool(o.get("live")), "keep_real": False,
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
    if not row.get("can_deploy"):
        return jsonify({"error": "Netlify publishing requires Starter, Pro, or Agency plan"}), 403
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


# Ensure workspace exists on import (for gunicorn)

# Ensure workspace exists on import (for gunicorn)
jobs.WORKSPACE.mkdir(exist_ok=True)
jobs.cleanup(days=7)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
