"""deploy.py - zip dist/ -> Netlify -> write live URLs back into CSVs."""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

import build as B
import engine
import netlify


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

    site_info = netlify.ensure_site(args.site, args.token)
    base = site_info["url"]

    # Regenerate pages with live Netlify base URL before uploading
    if state.get("template") and state.get("source_csv"):
        import core
        core.generate(
            csv_path=Path(state["source_csv"]),
            template=state["template"],
            outdir=B.ROOT,
            limit=state.get("limit", 0),
            city=state.get("city", ""),
            only=state.get("only", ""),
            live=state.get("live", False),
            keep_real=state.get("keep_real", True),
            base_url=base,
            site_name=state.get("site_name", "Previews"),
        )

    netlify.deploy_to_site(engine.DIST, site_info["id"], args.token)

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
