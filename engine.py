"""engine.py - template introspection, injection, rendering. Stdlib only."""
from __future__ import annotations

import json
import re
import unicodedata
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

ROOT = Path(__file__).resolve().parent
TEMPLATE_DIR = ROOT / "templates_store"
DIST = ROOT / "dist"
DATA = ROOT / "data"

JINJA = Environment(
    loader=FileSystemLoader([str(TEMPLATE_DIR), str(TEMPLATE_DIR / "layouts"), str(TEMPLATE_DIR / "partials")]),
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


def sanitize_url(url: str, allowed_schemes=("http", "https")) -> str:
    if not url:
        return ""
    u = str(url).strip()
    if re.match(r'^(javascript|data|vbscript):', u, re.I):
        return ""
    parsed = urllib.parse.urlparse(u)
    if parsed.scheme.lower() in allowed_schemes:
        return u
    if not parsed.scheme and "." in u and not u.startswith(("/", "\\")):
        return f"https://{u}"
    return ""


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
    latitude = str(row.get("lat") or row.get("latitude") or "").strip()
    longitude = str(row.get("lng") or row.get("longitude") or "").strip()
    address = str(row.get("address") or "").strip()

    if latitude and longitude:
        map_query = f"{latitude},{longitude}"
    elif address:
        map_query = ", ".join(x for x in [address, city] if x)
    elif full_name and city:
        map_query = f"{full_name}, {city}"
    else:
        map_query = ""

    maps_embed_url = (
        "https://www.google.com/maps?q=" + urllib.parse.quote(map_query) + "&z=17&output=embed"
        if map_query else ""
    )

    return {
        "slug": slug,
        "fullName": full_name,
        "shortName": short_n,
        "category": category,
        "city": city,
        "address": address,
        "fullAddress": address,
        "phone": phone_raw or "",
        "phoneDisplay": phone_display(phone_raw),
        "phoneIntl": phone_intl_num,
        "phoneHref": f"tel:+{phone_intl_num}" if phone_intl_num else "",
        "whatsappHref": f"https://wa.me/{phone_intl_num}" if wa_enabled and phone_intl_num else "",
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
        "website": sanitize_url(row.get("website") or ""),
        "websiteLabel": row.get("website_label") or "",
        "mapsUrl": sanitize_url(row.get("maps_url") or ""),
        "mapsEmbedUrl": maps_embed_url,
        "latitude": latitude,
        "longitude": longitude,
        "pageUrl": page_url,
        "pageTitle": f"{full_name} — {category} in {city}" if city else f"{full_name} — {category}",
        "pageDescription": (
            f"Contact {full_name}, a {category} serving {city}." if city else f"Contact {full_name}, a {category}."
        ),
        "siteName": site_name,
        "builtAt": now_iso(),
    }


BUSINESS_CATEGORIES = {
    "dental": "Dental Clinics",
    "medical": "Medical Clinics",
    "law": "Law Firms",
    "home_services": "Home Services",
    "cosmetic": "Cosmetic & Plastic Surgery Clinics",
    "real_estate": "Real Estate Agencies",
    "coaching": "Coaching Institutes & Training Centers",
    "accounting": "Accounting & Tax Firms",
    "auto": "Auto Repair & Car Detailing Shops",
    "veterinary": "Veterinary Clinics",
}

CATEGORY_ALIASES = {
    "dental": [
        "dentist", "dental clinic", "dental care", "orthodontist",
        "prosthodontist", "periodontist", "oral surgeon",
    ],
    "medical": [
        "medical clinic", "doctor", "physician", "health clinic",
        "hospital", "diagnostic center", "polyclinic",
    ],
    "law": [
        "lawyer", "law firm", "advocate", "attorney", "legal services", "solicitor",
    ],
    "home_services": [
        "plumber", "plumbing", "electrician", "electrical", "roofing contractor",
        "roofer", "hvac contractor", "air conditioning repair", "heating contractor", "home services",
    ],
    "cosmetic": [
        "plastic surgeon", "cosmetic surgeon", "cosmetic clinic", "aesthetic clinic",
        "hair transplant clinic", "skin clinic", "dermatologist",
    ],
    "real_estate": [
        "real estate agency", "real estate agent", "property consultant",
        "realtor", "property dealer", "real estate consultant",
    ],
    "coaching": [
        "coaching center", "coaching institute", "training center",
        "tuition center", "education center", "academy", "computer training school",
    ],
    "accounting": [
        "accountant", "accounting firm", "tax consultant", "chartered accountant",
        "certified public accountant", "cpa", "ca firm", "bookkeeping service",
    ],
    "auto": [
        "auto repair shop", "car repair", "car detailing", "auto body shop",
        "mechanic", "car service center", "vehicle repair",
    ],
    "veterinary": [
        "veterinarian", "veterinary clinic", "animal hospital",
        "pet clinic", "veterinary hospital", "pet care",
    ],
}


def detect_business_category(raw_category: str) -> str:
    value = (raw_category or "").strip().lower()
    for category_id, aliases in CATEGORY_ALIASES.items():
        if any(alias in value for alias in aliases):
            return category_id
    return ""


def load_category_pack(category_id: str) -> dict:
    pack_file = TEMPLATE_DIR / "categories" / f"{category_id}.json"
    if pack_file.exists():
        try:
            return json.loads(pack_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def get_template_meta(template_id: str) -> dict:
    tpl_id = (template_id or "coaching_clean_product").strip().lower()
    aliases = {
        "dentist": "dental_clean_product",
        "dental": "dental_clean_product",
        "lawyer": "law_clean_product",
        "law": "law_clean_product",
        "coaching": "coaching_clean_product",
        "dental_modern": "dental_clean_product",
        "law_modern": "law_clean_product",
        "coaching_modern": "coaching_clean_product",
    }
    tpl_id = aliases.get(tpl_id, tpl_id)

    for item in list_templates():
        if item.get("id") == tpl_id:
            return item

    # Fallback if unknown
    parts = tpl_id.rsplit("_", 1)
    cat_id = parts[0] if len(parts) > 1 else "coaching"
    layout_id = parts[1] if len(parts) > 1 else "clean_product"
    return {
        "id": tpl_id,
        "name": tpl_id.replace("_", " ").title(),
        "category": cat_id,
        "layout": layout_id,
        "active": True
    }


def render_full_page(template_name: str, lead: dict, *, schema=None, live=False) -> str:
    meta = get_template_meta(template_name)
    cat_id = meta.get("category", "coaching")
    layout_id = meta.get("layout", "modern")

    category_pack = load_category_pack(cat_id)

    layout_file = f"layouts/{layout_id}.html"
    if not (TEMPLATE_DIR / layout_file).exists():
        layout_file = "layouts/modern.html"

    template = JINJA.get_template(layout_file)

    if schema is None:
        schema = {
            "@context": "https://schema.org",
            "@type": "LocalBusiness",
            "name": lead["fullName"],
            "description": lead.get("pageDescription", ""),
            "url": lead["pageUrl"],
            "address": lead.get("fullAddress") or lead.get("address") or "",
        }
        if lead.get("phoneIntl"):
            schema["telephone"] = f"+{lead['phoneIntl']}"

    return template.render(
        lead=lead,
        category_pack=category_pack,
        schema=schema,
        live=live,
        current_year=datetime.now(timezone.utc).year,
    )


def list_templates() -> list[dict]:
    reg_path = TEMPLATE_DIR / "registry.json"
    if reg_path.exists():
        try:
            return json.loads(reg_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def template_path(name: str) -> Path:
    meta = get_template_meta(name)
    layout_id = meta.get("layout", "modern")
    p = TEMPLATE_DIR / "layouts" / f"{layout_id}.html"
    if p.exists():
        return p
    return TEMPLATE_DIR / "layouts" / "modern.html"


def inspect_template(path: Path) -> dict:
    return {
        "name": path.stem,
        "file": str(path),
        "label": path.stem.replace("-", " ").replace("_", " ").title(),
        "title_sample": "Sample Business",
        "accent": "#12634a",
        "contract": "LEAD",
        "fields": ["fullName", "shortName", "category", "phoneIntl", "pageTitle", "pageDescription", "pageUrl"],
        "og_image": "",
    }


# ------------------------------------------------------------------ injected JS

# ------------------------------------------------------------------ renderers


GATE_HTML = (
    "<div style=\"margin:0;height:100vh;display:grid;place-items:center;"
    "background:#120d0b;color:#f2ede4;font:15px system-ui\">"
    "<p>This preview link is not active.</p></div>"
)


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

