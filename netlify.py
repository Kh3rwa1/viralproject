"""netlify.py - deploy a folder with the user's own token."""
from __future__ import annotations

import io
import json
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import ssl

API = "https://api.netlify.com/api/v1"
SSL_CTX = ssl._create_unverified_context()


class DeployError(Exception):
    pass


def log_debug(msg):
    try:
        with open(Path(__file__).parent / "netlify_debug.log", "a") as f:
            f.write(str(msg) + "\n")
    except Exception:
        pass


def _req(path, token, method="GET", data=None, ctype="application/json"):
    url = path if path.startswith("http") else API + path
    body = data if isinstance(data, (bytes, type(None))) else json.dumps(data).encode()
    r = urllib.request.Request(url, data=body, method=method,
                               headers={"Authorization": f"Bearer {token}",
                                        "Content-Type": ctype})
    try:
        log_debug(f"_req START: {method} {url}")
        with urllib.request.urlopen(r, timeout=300, context=SSL_CTX) as resp:
            raw = resp.read().decode() or "{}"
            log_debug(f"_req OK: {method} {url} -> len {len(raw)}")
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        err = f"netlify {e.code}: {e.read().decode()[:300]}"
        log_debug(f"_req HTTPError: {method} {url} -> {err}")
        raise DeployError(err)
    except Exception as e:
        log_debug(f"_req Exception: {method} {url} -> {e}")
        raise DeployError(str(e))


def zip_folder(folder: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in Path(folder).rglob("*"):
            if p.is_file():
                z.write(p, p.relative_to(folder).as_posix())
    return buf.getvalue()


def ensure_site(site_name: str, token: str) -> dict:
    token = (token or "").strip()
    if not token:
        raise DeployError("Netlify token is required.")

    site_name = site_name.strip().lower().replace("https://", "").replace("http://", "").split(".")[0]
    if not site_name:
        site_name = "lead-previews"

    # 1. Obtain account identifier via /user (always allowed for all PAT tokens)
    account_id = ""
    try:
        u = _req("/user", token)
        if isinstance(u, dict):
            account_id = u.get("account_id") or u.get("id") or ""
    except Exception as e:
        print("[NETLIFY DEBUG] /user error:", e)

    # Fallback to /accounts if /user did not yield account_id
    if not account_id:
        try:
            accs = _req("/accounts", token)
            if isinstance(accs, list) and len(accs) > 0:
                account_id = accs[0].get("slug") or accs[0].get("id") or ""
        except Exception as e:
            print("[NETLIFY DEBUG] /accounts error:", e)

    print("[NETLIFY DEBUG] account_id:", account_id)
    site = None

    # 2. Search for existing site by name or ID
    if account_id:
        try:
            sites = _req(f"/{account_id}/sites", token)
            if isinstance(sites, list):
                site = next((s for s in sites if isinstance(s, dict) and (s.get("name") == site_name or s.get("id") == site_name)), None)
        except Exception as e:
            print(f"[NETLIFY DEBUG] /{account_id}/sites error:", e)

    if not site:
        try:
            sites = _req("/sites?filter=all", token)
            if isinstance(sites, list):
                site = next((s for s in sites if isinstance(s, dict) and (s.get("name") == site_name or s.get("id") == site_name)), None)
        except Exception as e:
            print("[NETLIFY DEBUG] /sites?filter=all error:", e)

    # 3. Create site under account_id if not found
    if not site and account_id:
        try:
            print(f"[NETLIFY DEBUG] Creating site under /{account_id}/sites...")
            site = _req(f"/{account_id}/sites", token, "POST", {"name": site_name})
        except Exception as e:
            print(f"[NETLIFY DEBUG] POST /{account_id}/sites error:", e)
            try:
                sites = _req(f"/{account_id}/sites", token)
                if isinstance(sites, list):
                    site = next((s for s in sites if isinstance(s, dict) and s.get("name") == site_name), None)
            except Exception:
                pass
            if not site:
                import secrets
                try:
                    site = _req(f"/{account_id}/sites", token, "POST", {"name": f"{site_name}-{secrets.token_hex(2)}"})
                except Exception as e2:
                    print(f"[NETLIFY DEBUG] POST /{account_id}/sites suffix error:", e2)

    print("[NETLIFY DEBUG] Final site:", site.get("id") if site else None)
    if not site or not site.get("id"):
        raise DeployError(f"Could not find or create site '{site_name}' on Netlify. Please check your Netlify Access Token.")

    url = site.get("ssl_url") or site.get("url") or f"https://{site.get('name', site_name)}.netlify.app"
    return {
        "id": site["id"],
        "name": site.get("name", site_name),
        "url": url,
    }


def deploy_to_site(folder: Path, site_id: str, token: str) -> str:
    token = (token or "").strip()
    if not token:
        raise DeployError("Netlify token is required.")

    dep = _req(f"/sites/{site_id}/deploys", token, "POST",
               zip_folder(folder), "application/zip")

    for _ in range(80):
        d = _req(f"/deploys/{dep['id']}", token)
        if d.get("state") in ("ready", "current"):
            break
        if d.get("state") == "error":
            raise DeployError("Netlify build failed")
        time.sleep(3)

    return dep.get("id", "")


def deploy(folder: Path, site_name: str, token: str) -> str:
    site_info = ensure_site(site_name, token)
    deploy_to_site(folder, site_info["id"], token)
    return site_info["url"]

