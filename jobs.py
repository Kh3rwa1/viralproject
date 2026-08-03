"""jobs.py - one job = one folder. No shared output between users."""
from __future__ import annotations

import shutil
import threading
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

import core
import licenses
import netlify

WORKSPACE = Path(__file__).resolve().parent / "workspace"
JOBS: dict[str, dict] = {}
LOCK = threading.Lock()
MAX_JOBS_PER_KEY = 2


def safe_key_dir(key: str) -> str:
    return "".join(ch for ch in key.upper() if ch.isalnum())


def new_job(key: str) -> dict:
    jid = uuid.uuid4().hex[:12]
    folder = WORKSPACE / safe_key_dir(key) / jid
    folder.mkdir(parents=True, exist_ok=True)
    job = {"id": jid, "key": key, "folder": str(folder), "state": "new",
           "progress": 0, "total": 0, "message": "", "summary": None,
           "live_url": "", "template": "", "stage": "created",
           "created": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    with LOCK:
        JOBS[jid] = job
    return job


def get(jid, key):
    j = JOBS.get(jid)
    if j and j["key"] == key:
        return j
    folder = WORKSPACE / safe_key_dir(key) / jid
    if folder.exists() and folder.is_dir():
        import json
        state_file = folder / "state.json"
        summary = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else None
        st = "done" if summary else "uploaded" if (folder / "input.csv").exists() else "new"
        built_cnt = summary.get("built", 0) if summary else 0
        job = {"id": jid, "key": key, "folder": str(folder), "state": st,
               "progress": built_cnt, "total": built_cnt,
               "message": f"{built_cnt} pages ready" if st == "done" else "",
               "summary": summary, "live_url": summary.get("base_url", "") if summary else "",
               "template": summary.get("template", "") if summary else "",
               "stage": st, "created": "", "opts": {}}
        with LOCK:
            JOBS[jid] = job
        return job
    return None


def running_for(key):
    return sum(1 for j in JOBS.values()
               if j["key"] == key and j["state"] in ("running", "deploying"))


def start_build(job, opts):
    job["opts"] = opts

    def run():
        try:
            job["state"] = "running"
            job["message"] = "generating pages..."

            def prog(done, total):
                job["progress"], job["total"] = done, total

            summary = core.generate(
                Path(job["folder"]) / "input.csv", opts["template"], job["folder"],
                limit=opts.get("limit", 0), city=opts.get("city", ""),
                only=opts.get("only", ""), live=opts.get("live", False),
                keep_real=opts.get("keep_real", False),
                base_url=opts.get("base_url", ""),
                site_name=opts.get("site_name", "Previews"), progress=prog)
            licenses.spend(job["key"], summary["built"], summary["template"])
            job["summary"] = summary
            job["progress"] = job["total"] = summary["built"]
            job["state"] = "done"
            job["stage"] = "built"
            job["message"] = f"{summary['built']} pages ready"
        except Exception as e:
            job["state"] = "error"
            job["message"] = str(e)
            traceback.print_exc()
            traceback.print_exc()

    threading.Thread(target=run, daemon=True).start()


def start_deploy(job, site_name, token):
    def run():
        try:
            job["state"] = "deploying"
            job["message"] = "verifying Netlify site..."
            site_info = netlify.ensure_site(site_name, token)
            url = site_info["url"]
            job["live_url"] = url

            job["message"] = "generating pages with live URL..."
            opts = job.get("opts", {})
            template = (job.get("summary") or {}).get("template") or job.get("template") or "coaching"
            core.generate(Path(job["folder"]) / "input.csv", template,
                          job["folder"], limit=opts.get("limit", 0), city=opts.get("city", ""),
                          only=opts.get("only", ""), live=bool(opts.get("live", False)),
                          keep_real=opts.get("keep_real", False), base_url=url, site_name=site_name)

            job["message"] = "uploading to Netlify..."
            netlify.deploy_to_site(Path(job["folder"]) / "dist", site_info["id"], token)
            job["state"] = "deployed"
            job["stage"] = "deployed"
            job["message"] = url
        except Exception as e:
            import traceback
            traceback.print_exc()
            job["state"] = "error"
            job["message"] = str(e)

    threading.Thread(target=run, daemon=True).start()


def cleanup(days=7):
    cutoff = datetime.now(timezone.utc).timestamp() - days * 86400
    for user in WORKSPACE.glob("*"):
        for jf in user.glob("*"):
            if jf.is_dir() and jf.stat().st_mtime < cutoff:
                shutil.rmtree(jf, ignore_errors=True)
