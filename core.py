"""core.py - generation pipeline shared by the CLI and web app."""
from __future__ import annotations

import csv
import json
import shutil
from html import escape
from pathlib import Path

import adapters
import engine

ADDED = ["slug", "share_url", "whatsapp_ready", "page_status", "built_at", "template"]


def read_csv(path: Path):
    with Path(path).open(newline="", encoding="utf-8-sig", errors="replace") as f:
        r = csv.DictReader(f)
        return list(r), (r.fieldnames or [])


def plan_rows(rows, fieldnames, *, limit=0, city="", only="", keep_real=False):
    """Dry-run friendly: returns (kept, dropped, breakdown) without writing anything."""
    records = adapters.normalise(rows, fieldnames)
    kept, dropped, seen_phone, seen_slug = [], [], set(), {}
    breakdown = {
        "already_has_website": 0,
        "missing_phone": 0,
        "missing_name": 0,
        "duplicate_phone": 0,
    }

    for r in records:
        why, status = "", ""
        if not r["name"]:
            why, status = "no name", "skipped_missing_name"
            breakdown["missing_name"] += 1
        elif not engine.digits(r["phone"]):
            why, status = "no phone", "skipped_missing_phone"
            breakdown["missing_phone"] += 1
        elif r["website_kind"] == "real" and not keep_real:
            why, status = f"already has a site ({adapters.host(r['website'])})", "skipped_existing_website"
            breakdown["already_has_website"] += 1
        elif city and city.lower() not in (r["city"] or "").lower():
            why, status = "city filter", "skipped_filter"
        elif only and only.lower() not in r["name"].lower():
            why, status = "name filter", "skipped_filter"
        else:
            key = engine.phone_intl(r["phone"])
            if key in seen_phone:
                why, status = "duplicate phone", "skipped_duplicate_phone"
                breakdown["duplicate_phone"] += 1
            else:
                seen_phone.add(key)

        if why:
            r["page_status"] = status
            r["why"] = why
            dropped.append({
                "name": r["name"] or f"row {r['_row'] + 2}",
                "why": why,
                "status": status,
                "row_index": r["_row"],
                "record": r,
            })
            continue

        base = engine.slugify(r["name"] or r["city"])
        n = seen_slug.get(base, 0) + 1
        seen_slug[base] = n
        r["slug"] = base if n == 1 else f"{base}-{n}"
        r["page_status"] = "buildable"
        kept.append(r)
        if limit and len(kept) >= limit:
            break

    return kept, dropped, breakdown


def write_cleanup_files(outdir: Path, rows: list[dict], fieldnames: list[str],
                        kept: list[dict], dropped: list[dict],
                        template: str = "", base_url: str = "", built_at: str = ""):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    # 1. clean.csv — buildable businesses only
    clean_cols = ["slug", "name", "category", "city", "address", "phone", "share_url"]
    with (outdir / "clean.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=clean_cols)
        w.writeheader()
        for r in kept:
            url = f"{base_url.rstrip('/')}/{r['slug']}/" if base_url else f"/{r['slug']}/"
            w.writerow({
                "slug": r.get("slug", ""),
                "name": r.get("name") or r.get("name_full") or r.get("slug", ""),
                "category": r.get("category", ""),
                "city": r.get("city", ""),
                "address": r.get("address", ""),
                "phone": r.get("phone", ""),
                "share_url": url,
            })

    # 2. removed.csv — excluded businesses with reason and status column
    removed_cols = ["name", "phone", "city", "category", "website", "reason", "status"]
    with (outdir / "removed.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=removed_cols)
        w.writeheader()
        for d in dropped:
            r = d.get("record", {})
            w.writerow({
                "name": d.get("name", r.get("name", "")),
                "phone": r.get("phone", ""),
                "city": r.get("city", ""),
                "category": r.get("category", ""),
                "website": r.get("website", ""),
                "reason": d.get("why", ""),
                "status": d.get("status", "skipped"),
            })

    # 3. updated.csv — original rows with status information
    dropped_by_row = {d.get("row_index"): d for d in dropped if "row_index" in d}
    kept_by_row = {r["_row"]: r for r in kept}
    out_fields = list(fieldnames or []) + ["status", "reason"] + [c for c in ADDED if c not in (fieldnames or [])]

    formatted_rows = []
    for i, row in enumerate(rows):
        row_copy = dict(row)
        k = kept_by_row.get(i)
        d = dropped_by_row.get(i)
        if k:
            url = f"{base_url.rstrip('/')}/{k['slug']}/" if base_url else f"/{k['slug']}/"
            row_copy.update({
                "status": "buildable",
                "reason": "",
                "slug": k["slug"],
                "share_url": url,
                "whatsapp_ready": "yes" if k.get("_wa") else "no",
                "page_status": "built" if built_at else "buildable",
                "built_at": built_at,
                "template": template
            })
        elif d:
            row_copy.update({
                "status": d.get("status", "skipped"),
                "reason": d.get("why", ""),
                "page_status": d.get("status", "skipped"),
            })
            for c in ADDED:
                row_copy.setdefault(c, "")
        else:
            row_copy.setdefault("status", "skipped")
            row_copy.setdefault("reason", "")
            row_copy.setdefault("page_status", "skipped")
            for c in ADDED:
                row_copy.setdefault(c, "")
        formatted_rows.append(row_copy)

    with (outdir / "updated.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=out_fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(formatted_rows)


def build_console(records, base_url, console_path: Path):
    rows = sorted(records, key=lambda r: -int(r.get("_reviews_n", 0)))
    cells = []
    for r in rows:
        link = f"{base_url.rstrip('/')}/{r['slug']}/" if base_url else f"dist/{r['slug']}/index.html"
        wa = (
            f"<a href='https://wa.me/{escape(r['_intl'])}?text="
            f"Hi%20-%20I%20made%20a%20free%20preview%20page%20for%20you%3A%20"
            f"{escape(link, quote=True)}' target='_blank'>WhatsApp</a>"
        ) if r["_wa"] else "<i>landline</i>"
        cells.append(
            f"<tr><td>{escape(r['name'])}</td><td>{escape(r['city'])}</td>"
            f"<td>{escape(r['rating'] or '-')} ({escape(r['reviews'] or '0')})</td>"
            f"<td>{escape(r['phone'])}</td><td><a href='{escape(link, quote=True)}' target='_blank'>open</a></td>"
            f"<td>{wa}</td></tr>")
    console_path.write_text(
        "<!doctype html><meta charset='utf-8'><meta name='robots' content='noindex'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Outreach console</title><style>body{font:14px system-ui;margin:24px;"
        "background:#faf8f4}table{border-collapse:collapse;width:100%}"
        "td,th{border-bottom:1px solid #ddd;padding:9px;text-align:left}"
        "a{color:#7f3039}</style><h2>Outreach console</h2>"
        "<table><tr><th>Name</th><th>City</th><th>Rating</th><th>Phone</th>"
        "<th>Page</th><th>Pitch</th></tr>" + "".join(cells) + "</table>",
        encoding="utf-8")


def validate_build(dist: Path, leads: list[dict], template_name: str = ""):
    expected = len(leads)
    generated_files = [p for p in dist.glob("*/index.html")]
    actual = len(generated_files)

    if actual != expected:
        raise RuntimeError(
            f"Expected {expected} pages, generated {actual}"
        )

    for lead in leads:
        slug = lead["slug"]
        page_file = dist / slug / "index.html"
        if not page_file.exists():
            raise RuntimeError(f"Missing expected page for slug: {slug}")

        html = page_file.read_text(encoding="utf-8")
        engine.validate_rendered_page(html, lead, template_name=template_name)


ROOT_INDEX = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="robots" content="noindex,nofollow">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Business Previews</title>
</head>
<body style="margin:0;height:100vh;display:grid;place-items:center;background:#120d0b;color:#f2ede4;font:15px system-ui">
  <main style="text-align:center">
    <h1>Business Previews</h1>
    <p>Open the preview link shared with you.</p>
  </main>
</body>
</html>
"""


def check_category_compatibility(template: str, kept: list[dict]) -> list[str]:
    warnings = []
    meta = engine.get_template_meta(template)
    expected_cat = meta.get("category", "")

    mismatched = []
    for r in kept:
        detected = engine.detect_business_category(r.get("category") or "")
        if detected and expected_cat and detected != expected_cat:
            mismatched.append(r.get("name", "Unknown lead"))

    if mismatched:
        tpl_label = meta.get("name", template.replace("_", " ").title())
        warnings.append(
            f"Warning: {len(mismatched)} lead(s) may not match the selected {tpl_label} template."
        )
    return warnings


def generate(csv_path, template, outdir, *, limit=0, city="", only="",
             live=False, keep_real=False, base_url="", site_name="Previews",
             update_csv=True, progress=None):
    """Writes outdir/dist/** and outdir/leads.csv. Returns a summary dict."""
    outdir = Path(outdir)
    dist = outdir / "dist"

    rows, fieldnames = read_csv(csv_path)
    kept, dropped, breakdown = plan_rows(rows, fieldnames, limit=limit, city=city,
                                         only=only, keep_real=keep_real)
    if not kept:
        raise ValueError("every row was filtered out - nothing to build")

    warnings = check_category_compatibility(template, kept)
    for w in warnings:
        print(w)

    leads, order = {}, []
    for r in kept:
        lead = engine.lead_record(r, r["slug"], base_url=base_url, site_name=site_name)
        leads[r["slug"]] = lead
        order.append(r["slug"])
        r["_intl"] = lead["phoneIntl"]
        r["_wa"] = lead["waEnabled"]
        r["_reviews_n"] = int(engine.digits(r["reviews"]) or 0)

    if dist.exists():
        shutil.rmtree(dist)
    dist.mkdir(parents=True)

    # Copy static assets if present
    assets_dir = dist / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    static_src = engine.ROOT / "static_assets"
    if static_src.exists():
        shutil.copytree(static_src, assets_dir, dirs_exist_ok=True)

    # Write root index
    (dist / "index.html").write_text(ROOT_INDEX, encoding="utf-8")

    # Write standalone full index.html for each lead
    for i, slug in enumerate(order):
        lead = leads[slug]
        html = engine.render_full_page(template, lead, live=live)
        page_dir = dist / slug
        page_dir.mkdir(parents=True, exist_ok=True)
        (page_dir / "index.html").write_text(html, encoding="utf-8")

        if progress and (i % 25 == 0 or i == len(order) - 1):
            progress(i + 1, len(order))

    # Validate build output
    validate_build(dist, [leads[s] for s in order], template_name=template)

    (dist / "404.html").write_text(
        "<!doctype html><meta charset='utf-8'><meta name='robots' content='noindex,nofollow'>"
        "<title>Not found</title><style>body{display:grid;place-items:center;height:100vh;"
        "margin:0;background:#120d0b;color:#f2ede4;font:15px system-ui}</style>"
        "<p>Nothing here.</p>", encoding="utf-8")
    (dist / "robots.txt").write_text(
        "User-agent: *\nAllow: /\n" if live else "User-agent: *\nDisallow: /\n",
        encoding="utf-8")

    built_at = engine.now_iso()

    # Write build manifest inside private job directory (not in public dist/)
    manifest = {
        "template": template,
        "templateVersion": 2,
        "expectedPages": len(order),
        "generatedPages": len(order),
        "failedPages": 0,
        "baseUrl": base_url,
        "builtAt": built_at,
        "warnings": warnings,
        "pages": [
            {
                "slug": s,
                "path": f"{s}/index.html",
                "url": leads[s]["pageUrl"],
            }
            for s in order
        ],
    }
    (outdir / "build-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    if update_csv:
        write_cleanup_files(outdir, rows, fieldnames, kept, dropped,
                            template=template, base_url=base_url, built_at=built_at)

        cols = ["slug", "name", "category", "city", "address", "phone", "whatsapp_ready",
                "rating", "reviews", "hours", "website", "maps_url", "share_url",
                "page_status", "built_at"]
        with (outdir / "leads.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for r in kept:
                url = f"{base_url.rstrip('/')}/{r['slug']}/" if base_url else f"/{r['slug']}/"
                w.writerow({**{k: r.get(k, "") for k in cols},
                            "whatsapp_ready": "yes" if r["_wa"] else "no",
                            "share_url": url, "page_status": "built",
                            "built_at": built_at})

    summary = {"template": template, "built": len(kept), "dropped": len(dropped),
               "dropped_detail": dropped[:50], "slugs": order, "live": live,
               "built_at": built_at, "base_url": base_url, "warnings": warnings,
               "partial": bool(limit or city or only),
               "index_kb": round((dist / "index.html").stat().st_size / 1024)}
    (outdir / "state.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary

