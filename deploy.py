"""deploy.py - zip dist/ -> Netlify -> write live URLs back into both CSVs."""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import build as B
import engine

import ssl

API = "https://api.netlify.com/api/v1"
SSL_CTX = ssl._create_unverified_context()


def req(path, token, method="GET", data=None, ctype="application/json"):
    url = path if path.startswith("http") else API + path
    body = data if isinstance(data, (bytes, type(None))) else json.dumps(data).encode()
    r = urllib.request.Request(url, data=body, method=method, headers={
        "Authorization": f"Bearer {token}", "Content-Type": ctype})
    try:
        with urllib.request.urlopen(r, timeout=300, context=SSL_CTX) as resp:
            raw = resp.read().decode() or "{}"
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        sys.exit(f"netlify {e.code}: {e.read().decode()[:400]}")


def zip_dist(folder: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in folder.rglob("*"):
            if p.is_file():
                z.write(p, p.relative_to(folder).as_posix())
    return buf.getvalue()


def patch_csv(path: Path, base: str):
    if not path.exists():
        return
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
        cols = list(rows[0].keys()) if rows else []
    for c in ("live_url", "share_url", "page_status"):
        if c not in cols:
            cols.append(c)
    for r in rows:
        if r.get("slug"):
            url = f"{base.rstrip('/')}/{r['slug']}/"
            r["live_url"] = url
            r["share_url"] = url
            r["page_status"] = "live"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", required=True, help="netlify site name (subdomain)")
    ap.add_argument("--token", default=os.getenv("NETLIFY_TOKEN", ""))
    ap.add_argument("--force", action="store_true", help="allow deploying a filtered build")
    args = ap.parse_args()
    if not args.token:
        sys.exit("set NETLIFY_TOKEN or pass --token")

    state = json.loads(B.STATE.read_text()) if B.STATE.exists() else {}
    if state.get("partial") and not args.force:
        sys.exit("last build was filtered (--limit/--city/--only). Rebuild full or use --force.")

    base = netlify.deploy(engine.DIST, args.site, args.token)
    patch_csv(B.LEADS_CSV, base)
    if state.get("source_csv"):
        patch_csv(Path(state["source_csv"]), base)

    state["base_url"] = base
    state["deployed_at"] = engine.now_iso()
    B.STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")

    print(f"\nlive: {base}")
    for s in state.get("slugs", [])[:3]:
        print(f"  {base}/{s}/")
    print("csv updated with live_url")


if __name__ == "__main__":
    main()
