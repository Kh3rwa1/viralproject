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
    """Dry-run friendly: returns (kept, dropped) without writing anything."""
    records = adapters.normalise(rows, fieldnames)
    kept, dropped, seen_phone, seen_slug = [], [], set(), {}
    for r in records:
        why = ""
        if not r["name"]:
            why = "no name"
        elif not engine.digits(r["phone"]):
            why = "no phone"
        elif r["website_kind"] == "real" and not keep_real:
            why = f"already has a site ({adapters.host(r['website'])})"
        elif city and city.lower() not in (r["city"] or "").lower():
            why = "city filter"
        elif only and only.lower() not in r["name"].lower():
            why = "name filter"
        else:
            key = engine.phone_intl(r["phone"])
            if key in seen_phone:
                why = "duplicate phone"
            else:
                seen_phone.add(key)
        if why:
            dropped.append({"name": r["name"] or f"row {r['_row'] + 2}", "why": why})
            continue
        base = engine.slugify(r["name"] or r["city"])
        n = seen_slug.get(base, 0) + 1
        seen_slug[base] = n
        r["slug"] = base if n == 1 else f"{base}-{n}"
        kept.append(r)
        if limit and len(kept) >= limit:
            break
    return kept, dropped


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


CATEGORY_KEYWORDS = {
    "coaching": ["coaching", "education", "tuition", "classes", "school", "academy", "learning", "institute"],
    "dentist": ["dentist", "dental", "teeth", "orthodontist", "clinic"],
    "lawyer": ["lawyer", "advocate", "legal", "attorney", "law", "solicitor"],
}


def check_category_compatibility(template: str, kept: list[dict]) -> list[str]:
    warnings = []
    tpl_key = template.lower()
    keywords = CATEGORY_KEYWORDS.get(tpl_key, [])
    if not keywords:
        return warnings

    mismatched = 0
    for r in kept:
        cat = (r.get("category") or "").lower()
        if cat and not any(kw in cat for kw in keywords):
            mismatched += 1

    if mismatched > 0:
        warnings.append(
            f"Warning: {mismatched} lead(s) may not match the selected {template.title()} template."
        )
    return warnings


def generate(csv_path, template, outdir, *, limit=0, city="", only="",
             live=False, keep_real=False, base_url="", site_name="Previews",
             update_csv=True, progress=None):
    """Writes outdir/dist/** and outdir/leads.csv. Returns a summary dict."""
    outdir = Path(outdir)
    dist = outdir / "dist"
    tpl_path = engine.template_path(template)
    meta = engine.inspect_template(tpl_path)
    tpl_src = tpl_path.read_text(encoding="utf-8")

    # Validate template before generating
    tpl_errs = engine.validate_template(tpl_src)
    if tpl_errs:
        raise ValueError(f"Template validation failed for {template}: {'; '.join(tpl_errs)}")

    rows, fieldnames = read_csv(csv_path)
    kept, dropped = plan_rows(rows, fieldnames, limit=limit, city=city,
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
        html = engine.render_full_page(tpl_src, lead, live=live)
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
        "template": meta["name"],
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
        by_row = {r["_row"]: r for r in kept}
        out_fields = list(fieldnames) + [c for c in ADDED if c not in fieldnames]
        for i, row in enumerate(rows):
            r = by_row.get(i)
            if r:
                url = f"{base_url.rstrip('/')}/{r['slug']}/" if base_url else f"/{r['slug']}/"
                row.update({"slug": r["slug"], "share_url": url,
                            "whatsapp_ready": "yes" if r["_wa"] else "no",
                            "page_status": "built", "built_at": built_at,
                            "template": meta["name"]})
            else:
                row.setdefault("page_status", "skipped")
                for c in ADDED:
                    row.setdefault(c, "")
        with (outdir / "updated.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=out_fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)

        clean_cols = ["name", "city", "phone", "share_url"]
        with (outdir / "clean.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=clean_cols)
            w.writeheader()
            for r in kept:
                url = f"{base_url.rstrip('/')}/{r['slug']}/" if base_url else f"/{r['slug']}/"
                w.writerow({
                    "name": r.get("name") or r.get("name_full") or r.get("slug", ""),
                    "city": r.get("city") or "",
                    "phone": r.get("phone") or "",
                    "share_url": url,
                })

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

    summary = {"template": meta["name"], "built": len(kept), "dropped": len(dropped),
               "dropped_detail": dropped[:50], "slugs": order, "live": live,
               "built_at": built_at, "base_url": base_url, "warnings": warnings,
               "partial": bool(limit or city or only),
               "index_kb": round((dist / "index.html").stat().st_size / 1024)}
    (outdir / "state.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary

