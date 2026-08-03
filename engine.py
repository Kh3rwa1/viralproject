"""engine.py - template introspection, injection, rendering. Stdlib only."""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, StrictUndefined, select_autoescape

ROOT = Path(__file__).resolve().parent
TEMPLATE_DIR = ROOT / "templates_store"
DIST = ROOT / "dist"
DATA = ROOT / "data"

JINJA = Environment(
    autoescape=select_autoescape(
        enabled_extensions=("html", "xml"),
        default_for_string=True,
    ),
    undefined=StrictUndefined,
)


# Fields the pipeline owns. The runtime is allowed to blank/hide only these,
# so template-computed things (initials, categoryLocation) are never touched.
OWNED = [
    "fullName", "shortName", "category", "city", "address",
    "phone", "hours", "review", "rating", "reviewCount",
    "website", "websiteLabel",
]


# ------------------------------------------------------------------ phones

def digits(v) -> str:
    return re.sub(r"\D", "", str(v or ""))


def phone_intl(v) -> str:
    d = digits(v)
    if not d:
        return ""
    if len(d) == 12 and d.startswith("91"):
        return d
    if len(d) == 11 and d.startswith("0"):
        d = d[1:]
    if len(d) == 10:
        return "91" + d
    if len(d) > 12 and d.startswith("91"):
        return d[:12]
    return d


def phone_kind(raw) -> str:
    """mobile | landline | none  (heuristic, tuned for Google Maps IN exports)."""
    s = str(raw or "").strip()
    d = digits(s)
    if not d:
        return "none"
    core = d
    if len(core) == 12 and core.startswith("91"):
        core = core[2:]
    elif len(core) == 11 and core.startswith("0"):
        core = core[1:]
    groups = [g for g in re.split(r"[ \-]+", s) if g]
    if len(core) != 10:
        return "landline"
    # "0657 242 2233" -> 3 groups = STD landline. "094705 50524" -> 2 = mobile.
    if len(groups) >= 3:
        return "landline"
    return "mobile" if core[0] in "6789" else "landline"


def phone_display(raw) -> str:
    s = re.sub(r"\s+", " ", str(raw or "")).strip()
    if s:
        return s
    return ""


# ------------------------------------------------------------------ names

SPLITTERS = re.compile(
    r"\s*[|" + "\u2022\u00b7\u2013\u2014" + r"]\s*|\s+-\s+|\s*,\s+(?=(?:best|top|no\.?\s?1)\b)",
    re.I,
)
KEYWORD_TAIL = re.compile(
    r"\s*[,:|-]?\s*\b(best|top|no\.?\s?1|number\s?1|famous|leading|trusted|"
    r"cheapest|affordable|24x7|near me)\b.*$", re.I)
NON_LATIN = re.compile(r"[^\x00-\x7f]")


def clean_name(raw: str, city: str = "") -> str:
    s = re.sub(r"\s+", " ", str(raw or "")).strip()
    if not s:
        return ""
    parts = [p.strip() for p in SPLITTERS.split(s) if p and p.strip()]
    if parts:
        # prefer the first segment that isn't pure keyword stuffing
        for p in parts:
            if not KEYWORD_TAIL.match(p):
                s = p
                break
        else:
            s = parts[0]
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[\[\{][^\]\}]*[\]\}]", " ", s)
    s = KEYWORD_TAIL.sub("", s)
    if NON_LATIN.search(s) and re.search(r"[A-Za-z]{3}", s):
        s = NON_LATIN.sub(" ", s)
    if city:
        s = re.sub(rf"\s+(in|at|,)\s*{re.escape(city)}\b.*$", "", s, flags=re.I)
    s = re.sub(r"\s+(in|at)\s+[A-Z][a-zA-Z]+$", "", s)
    s = re.sub(r"\s{2,}", " ", s).strip(" -,|&\u00b7")
    if s and s.upper() == s and len(s) > 4:
        s = s.title()
    return s or re.sub(r"\s+", " ", str(raw)).strip()


def short_name(name: str) -> str:
    words = [w for w in name.split() if w]
    return " ".join(words[:4]) if len(words) > 4 else name


def slugify(text: str) -> str:
    t = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()
    return re.sub(r"-{2,}", "-", t)[:60] or "lead"


# ------------------------------------------------------------------ lead record

def lead_record(row: dict, slug: str, *, base_url="", site_name="Previews") -> dict:
    phone_raw = row.get("phone", "")
    phone_intl_num = phone_intl(phone_raw)
    kind = row.get("phone_kind") or phone_kind(phone_raw)
    wa_enabled = (kind == "mobile")

    page_url = (
        f"{base_url.rstrip('/')}/{slug}/"
        if base_url
        else f"/{slug}/"
    )

    full_name = row.get("name_full") or row.get("name") or ""
    short_n = short_name(row.get("name") or full_name)
    category = row.get("category") or "Local Business"
    city = row.get("city") or ""

    return {
        "slug": slug,
        "fullName": full_name,
        "shortName": short_n,
        "category": category,
        "city": city,
        "address": row.get("address") or "",
        "phone": phone_raw or "",
        "phoneDisplay": phone_display(phone_raw),
        "phoneIntl": phone_intl_num,
        "whatsappUrl": (
            f"https://wa.me/{phone_intl_num}"
            if wa_enabled and phone_intl_num
            else ""
        ),
        "waEnabled": wa_enabled,
        "rating": str(row.get("rating") or ""),
        "reviewCount": str(row.get("reviews") or ""),
        "review": row.get("review") or "",
        "hours": row.get("hours") or "",
        "website": row.get("website") or "",
        "websiteLabel": row.get("website_label") or "",
        "mapsUrl": row.get("maps_url") or "",
        "latitude": str(row.get("lat") or row.get("latitude") or ""),
        "longitude": str(row.get("lng") or row.get("longitude") or ""),
        "pageUrl": page_url,
        "pageTitle": f"{full_name} — {category} in {city}" if city else f"{full_name} — {category}",
        "pageDescription": (
            f"Contact {full_name}, a {category} serving {city}." if city else f"Contact {full_name}, a {category}."
        ),
        "siteName": site_name,
        "builtAt": now_iso(),
    }


def render_full_page(template_source: str, lead: dict, *, schema=None, live=False) -> str:
    if schema is None:
        schema = {
            "@context": "https://schema.org",
            "@type": "LocalBusiness",
            "name": lead["fullName"],
            "telephone": f"+{lead['phoneIntl']}" if lead["phoneIntl"] else "",
            "address": lead["address"],
            "url": lead["pageUrl"],
        }
    template = JINJA.from_string(template_source)
    return template.render(
        lead=lead,
        schema=schema,
        live=live,
    )


REQUIRED_TEMPLATE_FIELDS = [
    "lead.fullName",
    "lead.category",
    "lead.city",
    "lead.phoneIntl",
]

DEMO_VALUES = [
    "BrightPath",
    "9876543210",
    "Sample Business",
]


def validate_template(template_source: str) -> list[str]:
    errors = []
    for field in REQUIRED_TEMPLATE_FIELDS:
        if field not in template_source:
            errors.append(f"Missing template field: {field}")
    for demo in DEMO_VALUES:
        if demo in template_source:
            errors.append(f"Found hardcoded demo value: '{demo}'")
    return errors


def page_title(lead: dict) -> str:
    bits = [b for b in [lead["shortName"], lead["category"], lead["city"]] if b]
    if len(bits) >= 3:
        return f"{bits[0]} - {bits[1]} in {bits[2]}"
    return " - ".join(bits) or "Consultation"


def page_desc(lead: dict) -> str:
    who = lead["shortName"] or "this business"
    cat = (lead["category"] or "professional").lower()
    city = lead["city"]
    tail = f" in {city}" if city else ""
    return f"Request a consultation with {who}, {cat}{tail}. Tap to call or message directly."



# ------------------------------------------------------------------ template introspection

LEAD_BLOCK = re.compile(r"const\s+LEAD\s*=\s*\{.*?\}\s*;", re.S)
SITE_BLOCK = re.compile(r"const\s+SITE\s*=\s*\{.*?\}\s*;", re.S)
PEXELS_VIDEO = re.compile(r"videos\.pexels\.com/video-files/(\d+)/", re.I)
OG_IMAGE = re.compile(r"""<meta[^>]+property=["']og:image["'][^>]+content=["']([^"']+)""", re.I)
POSTER = re.compile(r"""<video[^>]+poster=["']([^"']+)""", re.I)
THEME = re.compile(r"""<meta[^>]+name=["']theme-color["'][^>]+content=["']([^"']+)""", re.I)
TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
FIELD = re.compile(r"""data-field=["']([\w-]+)["']""")
SITE_FIELD = re.compile(r"""data-site=["']([\w-]+)["']""")


def template_path(name: str) -> Path:
    for cand in (
        TEMPLATE_DIR / f"{name}.html",
        TEMPLATE_DIR / name / "source.html",
        TEMPLATE_DIR / name,
    ):
        if cand.is_file():
            return cand
    raise SystemExit(f"template not found: {name} (looked in {TEMPLATE_DIR})")


def list_templates() -> list[dict]:
    out = []
    if not TEMPLATE_DIR.exists():
        return out
    for p in sorted(TEMPLATE_DIR.glob("*.html")):
        out.append(inspect_template(p))
    for d in sorted(x for x in TEMPLATE_DIR.iterdir() if x.is_dir()):
        src = d / "source.html"
        if src.exists():
            out.append(inspect_template(src))
    return out


def guess_og_image(src: str) -> str:
    m = OG_IMAGE.search(src)
    if m and "__" not in m.group(1):
        return m.group(1)
    m = PEXELS_VIDEO.search(src)
    if m:
        vid = m.group(1)
        return (
            f"https://images.pexels.com/videos/{vid}/"
            f"pexels-photo-{vid}.jpeg?auto=compress&w=1200"
        )
    m = POSTER.search(src)
    return m.group(1) if m else ""


def inspect_template(path: Path) -> dict:
    src = path.read_text(encoding="utf-8")
    name = path.stem if path.suffix == ".html" and path.stem != "source" else path.parent.name
    t = TITLE.search(src)
    accent = THEME.search(src)
    contract = "LEAD" if LEAD_BLOCK.search(src) else "SITE" if SITE_BLOCK.search(src) else "GENERIC"
    return {
        "name": name,
        "file": str(path),
        "label": name.replace("-", " ").replace("_", " ").title(),
        "title_sample": re.sub(r"\s+", " ", t.group(1)).strip() if t else "",
        "accent": accent.group(1) if accent else "#120d0b",
        "contract": contract,
        "fields": sorted(set(FIELD.findall(src) + SITE_FIELD.findall(src))),
        "og_image": guess_og_image(src),
    }


# ------------------------------------------------------------------ injected JS

GATE_HTML = (
    "<head><meta charset='utf-8'><meta name='robots' content='noindex,nofollow'>"
    "<title>Preview</title></head>"
    "<body style=\"margin:0;height:100vh;display:grid;place-items:center;"
    "background:#120d0b;color:#f2ede4;font:15px system-ui\">"
    "<p>This preview link is not active.</p></body>"
)

ROUTER = """
/* ==== injected by build.py - multi-lead router ==== */
const __LEADS__ = __PAYLOAD__;
const __ORDER__ = __ORDER__;
const __OWNED__ = __OWNED__;
function __pickLeadId() {
  var q = new URLSearchParams(location.search).get("id");
  if (q && __LEADS__[q]) return q;
  var segs = location.pathname.replace(/index\\.html?$/, "").split("/").filter(Boolean);
  var last = segs.pop();
  if (last && __LEADS__[last]) return last;
  return (__ORDER__ && __ORDER__[0]) || Object.keys(__LEADS__)[0] || null;
}
const __ID__ = __pickLeadId();
const LEAD = Object.assign({}, __LEADS__[__ID__] || {});
/* ==== end router ==== */
"""

SITE_ADAPTER = """
const SITE = (function (L) {
  var q = encodeURIComponent(((L.fullName || L.shortName || "") + " " + (L.address || "")).trim());
  var phone = L.phoneIntl ? "+" + L.phoneIntl : (L.phone || "");
  return {
    city: L.city || "",
    name: L.fullName || L.shortName || "",
    shortName: L.shortName || L.fullName || "",
    phone: phone,
    phoneDisplay: L.phone || phone,
    whatsapp: (L.waEnabled && L.phoneIntl) ? "https://wa.me/" + L.phoneIntl : (L.phoneIntl ? "tel:+" + L.phoneIntl : "#"),
    category: L.category || "",
    website: L.website || "#",
    maps: L.mapsUrl || "https://www.google.com/maps/search/?api=1&query=" + q
  };
})(LEAD);
"""

GENERIC_FILL = """
/* ==== injected: generic filler (template has no LEAD contract) ==== */
var lead = LEAD;
(function () {
  document.querySelectorAll("[data-field]").forEach(function (el) {
    var v = lead[el.dataset.field];
    if (v) el.textContent = v;
  });
  document.querySelectorAll(".phone-link,[href^='tel:']").forEach(function (a) {
    if (lead.phoneIntl) a.href = "tel:+" + lead.phoneIntl;
  });
  document.querySelectorAll(".maps-link").forEach(function (a) {
    a.href = lead.mapsUrl || "https://www.google.com/maps/search/?api=1&query=" +
      encodeURIComponent((lead.fullName || "") + " " + (lead.address || ""));
  });
})();
"""

RUNTIME = r"""
<script>
/* ==== injected by build.py - shared runtime patches ==== */
(function () {
  var L;
  try { L = lead; } catch (e) { try { L = LEAD; } catch (e2) { return; } }
  if (!L) return;
  var OWNED = (typeof __OWNED__ !== "undefined") ? __OWNED__ : [];
  var HIDE = ".meta-row,.proof-item,.hero-location,.footer-list li,.floating-tag,.rating-block";

  /* 1. never leak the previous lead's placeholder text */
  document.querySelectorAll("[data-field]").forEach(function (el) {
    var k = el.dataset.field;
    if (OWNED.indexOf(k) === -1) return;
    var v = L[k];
    if (v === undefined || v === null || String(v).trim() === "") {
      el.textContent = "";
      var row = el.closest(HIDE);
      if (row) row.hidden = true;
    }
  });

  /* 2. landline leads: no dead WhatsApp button */
  if (L.waEnabled === false) {
    document.querySelectorAll(".submit span").forEach(function (s) {
      s.textContent = "Call to request";
    });
    var intro = document.querySelector(".modal-intro");
    if (intro && L.shortName) {
      intro.textContent = "This listing shows a landline. Tap below to call " +
        L.shortName + " directly.";
    }
    document.addEventListener("submit", function (ev) {
      if (!ev.target.closest("form")) return;
      ev.preventDefault();
      ev.stopImmediatePropagation();
      if (L.phoneIntl) location.href = "tel:+" + L.phoneIntl;
    }, true);
  }

  /* 3. keep the existing social / directory profile visible */
  if (L.website) {
    var list = document.querySelector(".footer-list");
    if (list) {
      var li = document.createElement("li");
      var a = document.createElement("a");
      a.href = L.website;
      a.target = "_blank";
      a.rel = "noopener";
      a.textContent = L.websiteLabel || "View current profile";
      li.appendChild(a);
      list.appendChild(li);
    }
  }

  /* 4. share meta + pretty URL */
  function meta(sel, val) {
    var m = document.querySelector(sel);
    if (m && val) m.setAttribute("content", val);
  }
  meta('meta[property="og:title"]', document.title);
  meta('meta[property="og:url"]', location.origin + "/" + (L.slug || "") + "/");

  /* 5. Top Bar Directory Switcher for all generated leads */
  if (typeof __ORDER__ !== "undefined" && typeof __LEADS__ !== "undefined" && __ORDER__.length > 0) {
  /* 5. Floating Bottom Switcher Widget for generated multi-lead previews */
  if (typeof __ORDER__ !== "undefined" && typeof __LEADS__ !== "undefined" && __ORDER__.length > 1) {
    var pill = document.createElement("div");
    pill.id = "__leads_pill__";
    pill.style.cssText = "position:fixed;bottom:20px;right:20px;z-index:999999;background:rgba(15,23,42,0.92);backdrop-filter:blur(12px);color:#f8fafc;padding:8px 14px;display:flex;align-items:center;gap:10px;box-shadow:0 8px 24px rgba(0,0,0,0.4);font-family:system-ui,-apple-system,sans-serif;font-size:13px;border-radius:999px;border:1px solid rgba(255,255,255,0.15);";

    var badge = document.createElement("span");
    badge.style.cssText = "background:#3b82f6;color:#fff;padding:3px 9px;border-radius:12px;font-weight:700;font-size:11px;white-space:nowrap;";
    badge.textContent = __ORDER__.length + " Pages";
    pill.appendChild(badge);

    var sel = document.createElement("select");
    sel.style.cssText = "background:#1e293b;color:#f8fafc;border:1px solid #475569;padding:4px 8px;border-radius:6px;font-weight:600;outline:none;cursor:pointer;max-width:200px;text-overflow:ellipsis;font-size:12px;";
    
    var currIndex = 0;
    for (var i = 0; i < __ORDER__.length; i++) {
      var s = __ORDER__[i];
      var item = __LEADS__[s];
      if (!item) continue;
      var opt = document.createElement("option");
      opt.value = s;
      opt.textContent = (i + 1) + ". " + (item.shortName || item.fullName || s);
      if (s === (L.slug || __ID__)) {
        opt.selected = true;
        currIndex = i;
      }
      sel.appendChild(opt);
    }
    sel.onchange = function () {
      var base = location.pathname.replace(/\/([^\/]+)\/?$/, "/");
      location.href = base + "?id=" + this.value;
    };
    pill.appendChild(sel);

    var prevBtn = document.createElement("button");
    prevBtn.style.cssText = "background:#334155;color:#fff;border:none;padding:3px 9px;border-radius:6px;cursor:pointer;font-weight:700;font-size:12px;";
    prevBtn.innerHTML = "&larr;";
    prevBtn.title = "Previous Lead";
    prevBtn.onclick = function () {
      var prevIdx = (currIndex - 1 + __ORDER__.length) % __ORDER__.length;
      var base = location.pathname.replace(/\/([^\/]+)\/?$/, "/");
      location.href = base + "?id=" + __ORDER__[prevIdx];
    };
    pill.appendChild(prevBtn);

    var nextBtn = document.createElement("button");
    nextBtn.style.cssText = "background:#3b82f6;color:#fff;border:none;padding:3px 9px;border-radius:6px;cursor:pointer;font-weight:700;font-size:12px;";
    nextBtn.innerHTML = "&rarr;";
    nextBtn.title = "Next Lead";
    nextBtn.onclick = function () {
      var nextIdx = (currIndex + 1) % __ORDER__.length;
      var base = location.pathname.replace(/\/([^\/]+)\/?$/, "/");
      location.href = base + "?id=" + __ORDER__[nextIdx];
    };
    pill.appendChild(nextBtn);

    document.body.appendChild(pill);
  }
})();
</script>
"""

STUB = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<meta name="description" content="__DESC__">
__ROBOTS__<link rel="canonical" href="__CANON__">
<meta property="og:type" content="website">
<meta property="og:site_name" content="__SITE__">
<meta property="og:title" content="__TITLE__">
<meta property="og:description" content="__DESC__">
<meta property="og:url" content="__CANON__">
__OGIMG__<meta name="twitter:card" content="summary_large_image">
<meta http-equiv="refresh" content="0;url=__TARGET__">
<style>html,body{height:100%;margin:0;background:#120d0b;color:#f2ede4;
font:15px system-ui;display:grid;place-items:center}</style>
</head><body><p>Opening...</p>
<script>location.replace("__TARGET__");</script></body></html>
"""


def esc(v: str) -> str:
    s = re.sub(r"&(?![a-zA-Z0-9#]+;)", "&amp;", str(v or ""))
    return s.replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")


# ------------------------------------------------------------------ renderers

def _head_inject(src: str, block: str) -> str:
    m = re.search(r"<head[^>]*>", src, re.I)
    if not m:
        return block + src
    i = m.end()
    return src[:i] + "\n" + block + src[i:]


GATE_HTML = (
    "<div style=\"margin:0;height:100vh;display:grid;place-items:center;"
    "background:#120d0b;color:#f2ede4;font:15px system-ui\">"
    "<p>This preview link is not active.</p></div>"
)

ROUTER = """
/* ==== injected by build.py - multi-lead router ==== */
const __LEADS__ = __PAYLOAD_JSON__;
const __ORDER__ = __ORDER_JSON__;
const __OWNED__ = __OWNED_JSON__;
function __pickLeadId() {
  var q = new URLSearchParams(location.search).get("id");
  if (q && __LEADS__[q]) return q;
  var segs = location.pathname.replace(/index\\.html?$/, "").split("/").filter(Boolean);
  var last = segs.pop();
  if (last && __LEADS__[last]) return last;
  return (__ORDER__ && __ORDER__[0]) || Object.keys(__LEADS__)[0] || null;
}
const __ID__ = __pickLeadId();
const LEAD = Object.assign({}, __LEADS__[__ID__] || {});
/* ==== end router ==== */
"""


def render_app(src: str, leads: dict, order: list, meta: dict, live: bool = False) -> str:
    """One index.html holding every lead. ~1 template + N * ~0.4 KB of JSON."""
    router = (ROUTER
              .replace("__PAYLOAD_JSON__", json.dumps(leads, ensure_ascii=False, separators=(",", ":")))
              .replace("__ORDER_JSON__", json.dumps(order))
              .replace("__OWNED_JSON__", json.dumps(OWNED)))

    if LEAD_BLOCK.search(src):
        out = LEAD_BLOCK.sub(lambda _: router, src, count=1)
    elif SITE_BLOCK.search(src):
        out = SITE_BLOCK.sub(lambda _: router + SITE_ADAPTER, src, count=1)
    else:
        out = re.sub(r"</body>", "<script>" + router + GENERIC_FILL + "</script></body>",
                     src, count=1, flags=re.I)

    out = re.sub(r'<meta[^>]+name=["\']robots["\'][^>]*>\s*', "", out, flags=re.I)
    head = "" if live else '<meta name="robots" content="noindex,nofollow">\n'
    head += (f'<meta property="og:image" content="{esc(meta.get("og_image", ""))}">\n'
             if meta.get("og_image") else "")
    out = _head_inject(out, head)

    parts = out.rpartition("</body>")
    if parts[1]:
        return parts[0] + RUNTIME + "</body>" + parts[2]
    return out + RUNTIME


def render_stub(lead: dict, meta: dict, site_name: str, base_url: str, live: bool) -> str:
    canon = f"{base_url.rstrip('/')}/{lead['slug']}/" if base_url else f"/{lead['slug']}/"
    target = f"{base_url.rstrip('/')}/?id={lead['slug']}" if base_url else f"../?id={lead['slug']}"
    img = meta.get("og_image", "")
    return (STUB
            .replace("__TITLE__", esc(page_title(lead)))
            .replace("__DESC__", esc(page_desc(lead)))
            .replace("__CANON__", esc(canon))
            .replace("__SITE__", esc(site_name))
            .replace("__TARGET__", target)
            .replace("__OGIMG__", f'<meta property="og:image" content="{esc(img)}">\n' if img else "")
            .replace("__ROBOTS__", "" if live else '<meta name="robots" content="noindex,nofollow">\n'))


TEMPLATE_DEMO_VALUES = {
    "coaching": ["BrightPath", "9876543210", "Sample Business"],
    "dentist": ["Dr Tanmoy Das", "9831194050", "K J Sanyal Road"],
    "lawyer": ["Ravi Shankar Pandey", "9470550524", "Sharda Bhavan"],
}


REQUIRED_TEMPLATE_FIELDS = [
    "lead.fullName", "lead.shortName", "lead.category",
    "lead.phoneIntl", "lead.pageTitle", "lead.pageDescription", "lead.pageUrl",
]


def validate_template(src: str) -> list[str]:
    errs = []
    if "<title>" not in src:
        errs.append("Missing <title> tag")
    if "lead." not in src:
        errs.append("No {{ lead.* }} variables found")
    for field in REQUIRED_TEMPLATE_FIELDS:
        if field not in src:
            errs.append(f"Missing required field: {field}")
    return errs


def validate_rendered_page(html: str, lead: dict, template_name: str = ""):
    if not html.strip():
        raise ValueError(f"Empty page generated for {lead.get('slug')}")

    if re.search(r'\{\{.*?\}\}|\{\%.*?\%\}', html, re.S):
        raise ValueError(f"Unresolved Jinja tag found in page for {lead.get('slug')}")

    if "<title>" not in html:
        raise ValueError(f"Missing <title> tag in page for {lead.get('slug')}")

    if 'rel="canonical"' not in html and "rel='canonical'" not in html:
        raise ValueError(f"Missing canonical link in page for {lead.get('slug')}")

    # Verify JSON-LD parsing
    ld_matches = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    for ld in ld_matches:
        try:
            data = json.loads(ld.strip())
            if not isinstance(data, dict):
                raise ValueError("JSON-LD is not a valid JSON object")
        except Exception as e:
            raise ValueError(f"Invalid JSON-LD in page for {lead.get('slug')}: {e}")

    # Check for hardcoded demo values
    tpl_key = (template_name or "").lower()
    demos = TEMPLATE_DEMO_VALUES.get(tpl_key, [])
    lead_str = json.dumps(lead)
    for demo in demos:
        if demo in html and demo not in lead_str:
            raise ValueError(f"Hardcoded demo value '{demo}' found in generated page for {lead.get('slug')}")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

