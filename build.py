"""build.py - CLI wrapper around core.generate()."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import core
import engine

ROOT = engine.ROOT
DIST = engine.DIST
DATA = engine.DATA
STATE = ROOT / "state.json"
LEADS_CSV = DATA / "leads.csv"
CONSOLE = ROOT / "preview.html"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=False, help="path to the scraper export")
    ap.add_argument("--template", required=False, help="file name in templates_store (no .html)")
    ap.add_argument("--templates", action="store_true", help="list detected templates and exit")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--city", default="")
    ap.add_argument("--only", default="", help="substring match on business name")
    ap.add_argument("--live", action="store_true", help="drop noindex (paid client only)")
    ap.add_argument("--keep-real-sites", action="store_true")
    ap.add_argument("--base-url", default="", help="e.g. https://previews.netlify.app")
    ap.add_argument("--site-name", default="Previews")
    ap.add_argument("--no-update-csv", action="store_true")
    args = ap.parse_args()

    if args.templates or not (args.csv and args.template):
        found = engine.list_templates()
        if not found:
            print(f"no templates in {engine.TEMPLATE_DIR} - drop a .html file there.")
        for t in found:
            print(f"- {t['name']:<14} contract={t['contract']:<8} accent={t['accent']} "
                  f"fields={len(t['fields'])}  og={'yes' if t['og_image'] else 'no'}")
        if found:
            (engine.TEMPLATE_DIR / "_index.json").write_text(
                json.dumps(found, indent=2), encoding="utf-8")
        if args.templates or not found:
            return
        sys.exit("pass --csv and --template")

    src_csv = Path(args.csv)
    tpl_path = engine.template_path(args.template)
    meta = engine.inspect_template(tpl_path)
    print(f"template: {meta['name']}  contract={meta['contract']}  fields={meta['fields']}")

    summary = core.generate(
        src_csv, args.template, ROOT, limit=args.limit, city=args.city,
        only=args.only, live=args.live, keep_real=args.keep_real_sites,
        base_url=args.base_url, site_name=args.site_name,
        update_csv=not args.no_update_csv)

    console_source = ROOT / "leads.csv"
    if not args.no_update_csv:
        updated = ROOT / "updated.csv"
        if updated.exists():
            backup = src_csv.with_suffix(src_csv.suffix + ".bak")
            if not backup.exists():
                shutil.copy2(src_csv, backup)
            shutil.copy2(updated, src_csv)
        leads = ROOT / "leads.csv"
        DATA.mkdir(parents=True, exist_ok=True)
        if leads.exists():
            shutil.copy2(leads, LEADS_CSV)
            console_source = LEADS_CSV

    STATE.write_text(json.dumps({
        "template": summary["template"], "source_csv": str(src_csv),
        "built_at": summary["built_at"], "count": summary["built"],
        "live": summary["live"], "base_url": summary["base_url"],
        "partial": summary["partial"], "slugs": summary["slugs"],
    }, indent=2), encoding="utf-8")

    if console_source.exists():
        core.build_console(_console_records(console_source), args.base_url, CONSOLE)

    print(f"\nbuilt {summary['built']} pages - dropped {summary['dropped']}")
    print(f"index.html = {summary['index_kb']} KB - stubs = {len(summary['slugs'])} x ~1 KB")
    for d in summary["dropped_detail"][:12]:
        print(f"  skip: {d['name'][:44]:<46} {d['why']}")
    if summary["dropped"] > 12:
        print(f"  ... +{summary['dropped'] - 12} more")
    print(f"\ncsv updated - console: {CONSOLE}")
    print("local test:  python3 -m http.server 8080 --directory dist")
    print(f"then open:   http://localhost:8080/{summary['slugs'][0]}/")


def _console_records(path: Path):
    import csv

    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        out.append({
            **r,
            "_intl": engine.phone_intl(r.get("phone", "")),
            "_wa": r.get("whatsapp_ready") == "yes",
            "_reviews_n": int(engine.digits(r.get("reviews", "")) or 0),
        })
    return out


if __name__ == "__main__":
    main()
