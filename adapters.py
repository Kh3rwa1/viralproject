"""adapters.py - normalise any Google-Maps-ish CSV into canonical lead dicts."""
from __future__ import annotations

import re
from urllib.parse import unquote, urlparse

import engine

URL_RE = re.compile(r"https?://[^\s,]+", re.I)
RATING_RE = re.compile(r"^([1-5](?:[.,]\d)?)$")
REVIEWS_RE = re.compile(r"^\(?\s*([\d,]{1,7})\s*\)?\s*(reviews?|ratings?)?$", re.I)
PHONE_RE = re.compile(r"^\+?\d[\d\s\-()]{7,18}$")
HOURS_RE = re.compile(r"(open\s*24|opens?\b|closes?\b|closed\b|\d{1,2}\s?[ap]\.?m|\d{1,2}[:.]\d{2})", re.I)
ADDR_RE = re.compile(r"(road|rd\b|street|st\b|lane|marg|nagar|colony|market|near|floor|"
                     r"opp\b|chowk|path|bhavan|complex|block|sector|plot|no\.|\d{6})", re.I)
LATLNG = re.compile(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)")
LATLNG2 = re.compile(r"@(-?\d+\.\d+),(-?\d+\.\d+)")

NOISE = {"", "-", ".", "directions", "website", "call", "share", "save", "menu",
         "order online", "wheelchair accessible entrance", "no reviews",
         "sponsored", "ad", "results", "view", "profile"}

SOCIAL = {"facebook.com": "Facebook page", "instagram.com": "Instagram profile",
          "linkedin.com": "LinkedIn profile", "x.com": "X profile",
          "twitter.com": "X profile", "youtube.com": "YouTube channel",
          "wa.me": "WhatsApp", "api.whatsapp.com": "WhatsApp",
          "t.me": "Telegram"}
DIRECTORY = {"justdial.com": "JustDial listing", "sulekha.com": "Sulekha listing",
             "indiamart.com": "IndiaMART listing", "practo.com": "Practo profile",
             "lawrato.com": "LawRato profile", "vakilsearch.com": "Directory listing",
             "yellowpages": "Directory listing", "tradeindia.com": "Directory listing",
             "bing.com": "Directory listing", "quikr.com": "Directory listing"}
BUILDER = {"business.site": "Google business site", "wixsite.com": "Wix site",
           "blogspot.com": "Blogspot", "wordpress.com": "WordPress.com site",
           "weebly.com": "Weebly site", "godaddysites.com": "GoDaddy site",
           "sites.google.com": "Google Sites"}
SKIP_HOSTS = ("google.com", "google.co", "gstatic.com", "schema.org", "goo.gl",
              "maps.app.goo.gl", "ggpht.com", "googleusercontent.com")

CATEGORY_HINT = re.compile(r"^(?:[\w&/' -]{3,40})$")
CATEGORY_WORDS = re.compile(
    r"(lawyer|advocate|attorney|law firm|legal|notary|dentist|dental|clinic|hospital|"
    r"doctor|physio|coaching|tutor|institute|school|academy|gym|fitness|yoga|salon|spa|"
    r"parlour|boutique|restaurant|cafe|caterer|photographer|studio|builder|contractor|"
    r"interior|architect|electrician|plumber|travel|agency|consultant|accountant|"
    r"chartered|real estate|property|automobile|repair|service)", re.I)


def host(url: str) -> str:
    try:
        return (urlparse(url).netloc or "").lower().replace("www.", "")
    except Exception:
        return ""


def classify_website(url: str):
    """-> (kind, label). kind in none|social|directory|builder|real"""
    if not url:
        return "none", ""
    h = host(url)
    if not h or any(s in h for s in SKIP_HOSTS):
        return "none", ""
    for dom, lab in SOCIAL.items():
        if dom in h:
            return "social", lab
    for dom, lab in DIRECTORY.items():
        if dom in h:
            return "directory", lab
    for dom, lab in BUILDER.items():
        if dom in h:
            return "builder", lab
    return "real", h


def latlng(text: str):
    m = LATLNG.search(text or "") or LATLNG2.search(text or "")
    return (m.group(1), m.group(2)) if m else ("", "")


def search_context(text: str):
    """niche + city out of a '/maps/search/lawyers+in+jamshedpur' style URL."""
    m = re.search(r"/maps/search/([^/?&]+)", text or "")
    if not m:
        return "", ""
    q = unquote(m.group(1)).replace("+", " ").replace("%20", " ")
    parts = re.split(r"\bin\b", q, maxsplit=1, flags=re.I)
    niche = parts[0].strip(" ,-").title()
    city = parts[1].strip(" ,-").title() if len(parts) > 1 else ""
    return niche, city


def is_noise(v: str) -> bool:
    return v.strip().lower() in NOISE


def _scan(cells: list[str]) -> dict:
    """Heuristic pass over unlabeled / duplicated columns."""
    got = {"urls": [], "hours": [], "text": []}
    for c in cells:
        v = re.sub(r"\s+", " ", str(c or "")).strip()
        if not v or is_noise(v):
            continue
        if URL_RE.match(v):
            got["urls"].append(v)
            continue
        if RATING_RE.match(v) and "rating" not in got:
            got["rating"] = v.replace(",", ".")
            continue
        m = REVIEWS_RE.match(v)
        if m and "reviews" not in got and (m.group(2) or "(" in v):
            got["reviews"] = m.group(1).replace(",", "")
            continue
        if PHONE_RE.match(v) and "phone" not in got and 10 <= len(engine.digits(v)) <= 13:
            got["phone"] = v
            continue
        if HOURS_RE.search(v) and len(v) < 60:
            got["hours"].append(v)
            continue
        if ADDR_RE.search(v) and len(v) > 12 and "address" not in got:
            got["address"] = v
            continue
        got["text"].append(v)
    return got


def _pick_review(texts: list[str]) -> str:
    for t in texts:
        if 40 <= len(t) <= 240 and " " in t and not t.endswith("\u2026") and not URL_RE.match(t):
            return t
    return ""


def _pick_category(texts: list[str], fallback: str) -> str:
    for t in texts:
        if CATEGORY_WORDS.search(t) and len(t) <= 40 and CATEGORY_HINT.match(t):
            return t.title()
    return fallback


HEADERS = {
    "name": ("name", "title", "business", "business_name", "company"),
    "phone": ("phone", "phone_number", "mobile", "contact", "telephone"),
    "address": ("address", "full_address", "location", "street"),
    "website": ("website", "site", "url", "web"),
    "rating": ("rating", "stars", "score", "avg_rating"),
    "reviews": ("reviews", "review_count", "ratings", "user_ratings_total", "num_reviews"),
    "category": ("category", "type", "main_category", "niche"),
    "city": ("city", "town", "locality"),
    "hours": ("hours", "opening_hours", "timing", "working_hours"),
    "review": ("review", "review_text", "snippet", "top_review"),
    "maps_url": ("maps_url", "google_maps", "map_link", "place_url", "link"),
}


def _by_header(row: dict) -> dict:
    out = {}
    lowered = {str(k or "").strip().lower(): (v or "") for k, v in row.items()}
    for canon, aliases in HEADERS.items():
        for key, val in lowered.items():
            if key in aliases and str(val).strip():
                out[canon] = re.sub(r"\s+", " ", str(val)).strip()
                break
    return out


def normalise(rows: list[dict], fieldnames: list[str]) -> list[dict]:
    """Returns canonical records; keeps `_row` = index in the source CSV."""
    out = []
    blob = " ".join(str(x) for x in (fieldnames or []))
    niche_h, city_h = search_context(blob)

    for i, row in enumerate(rows):
        cells = [str(v or "") for v in row.values()]
        raw_blob = " ".join(cells)
        niche_r, city_r = search_context(raw_blob)
        named = _by_header(row)
        scan = _scan(cells)

        urls = named.get("website", "") and [named["website"]] or scan["urls"]
        maps_url = named.get("maps_url", "")
        website, wkind, wlabel = "", "none", ""
        for u in urls:
            if "google.com/maps" in u or "maps.app.goo.gl" in u:
                maps_url = maps_url or u
                continue
            k, lab = classify_website(u)
            if k != "none" and not website:
                website, wkind, wlabel = u, k, lab

        city = named.get("city") or city_r or city_h
        name_raw = named.get("name") or (scan["text"][0] if scan["text"] else "")
        name = engine.clean_name(name_raw, city)
        phone = named.get("phone") or scan.get("phone", "")
        lat, lng = latlng(maps_url or raw_blob)

        out.append({
            "_row": i,
            "name": name,
            "name_full": re.sub(r"\s+", " ", name_raw).strip(),
            "category": named.get("category") or _pick_category(scan["text"], niche_r or niche_h),
            "city": city,
            "address": named.get("address") or scan.get("address", ""),
            "phone": phone,
            "phone_kind": engine.phone_kind(phone),
            "rating": named.get("rating") or scan.get("rating", ""),
            "reviews": named.get("reviews") or scan.get("reviews", ""),
            "hours": named.get("hours") or (scan["hours"][0] if scan["hours"] else ""),
            "review": named.get("review") or _pick_review(scan["text"][1:]),
            "website": website,
            "website_kind": wkind,
            "website_label": wlabel,
            "maps_url": maps_url,
            "lat": lat,
            "lng": lng,
        })
    return out
