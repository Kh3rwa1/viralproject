"""licenses.py - issue keys and track credits. Run manually after payment."""
from __future__ import annotations

import argparse
import secrets
import sqlite3
import string
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB = Path(__file__).resolve().parent / "licenses.db"
ALPHA = string.ascii_uppercase + string.digits

PLANS = {
    # name:      (credits, max_rows_per_job, can_publish_live)
    "trial":     (25,    25,   False),
    "starter":   (500,   400,  False),
    "pro":       (3000,  1500, True),
    "agency":    (12000, 5000, True),
}


DEFAULT_KEYS = {
    "trial": ["LP-7QK2-M4XR-9TVB", "LP-B3ND-7HSQ-2WKF", "LP-Z9MT-4PRC-6XJD", "LP-K5WV-8QNB-3HFT", "LP-CO4B-79HQ-R49B"],
    "starter": ["LP-4HXB-2QNW-8TRD", "LP-9MKC-6FVJ-3PZS", "LP-2TWQ-7BDH-5XNR"],
    "pro": ["LP-K7QM-3XTV-9BND", "LP-R4WC-8JZP-5HFS", "LP-M9BT-2VKD-7QXN"],
    "agency": ["LP-3KUF-GPDN-3HZQ", "LP-A5TN-7RQW-2FMC", "LP-E8KD-3BVJ-9XHS", "LP-U2WM-6ZPT-5CNR"]
}


def conn():
    init_db()
    return sqlite3.connect(DB)


def init_db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    try:
        with c:
            c.execute("""CREATE TABLE IF NOT EXISTS keys(
                key TEXT PRIMARY KEY, email TEXT, plan TEXT, credits INTEGER,
                used INTEGER DEFAULT 0, created TEXT, expires TEXT,
                active INTEGER DEFAULT 1, note TEXT)""")
            c.execute("""CREATE TABLE IF NOT EXISTS usage(
                id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT, pages INTEGER,
                template TEXT, at TEXT)""")
            
            count = c.execute("SELECT COUNT(*) FROM keys").fetchone()[0]
            if count == 0:
                now = datetime.now(timezone.utc)
                exp = (now + timedelta(days=365)).isoformat(timespec="seconds")
                for plan, keys in DEFAULT_KEYS.items():
                    credits = PLANS[plan][0]
                    for k in keys:
                        c.execute("INSERT OR IGNORE INTO keys(key,email,plan,credits,created,expires,note) VALUES(?,?,?,?,?,?,?)",
                                  (k, "admin@leadpages", plan, credits, now.isoformat(timespec="seconds"), exp, "seeded"))
    finally:
        c.close()


def make_key() -> str:
    part = lambda: "".join(secrets.choice(ALPHA) for _ in range(4))
    return f"LP-{part()}-{part()}-{part()}"


def new_key(email, plan="starter", days=365, note=""):
    init_db()
    if plan not in PLANS:
        raise SystemExit(f"plan must be one of {list(PLANS)}")
    credits = PLANS[plan][0]
    k = make_key()
    now = datetime.now(timezone.utc)
    exp = (now + timedelta(days=days)).isoformat(timespec="seconds")
    c = sqlite3.connect(DB)
    try:
        with c:
            c.execute("INSERT INTO keys(key,email,plan,credits,created,expires,note) "
                      "VALUES(?,?,?,?,?,?,?)",
                      (k, email, plan, credits, now.isoformat(timespec="seconds"), exp, note))
    finally:
        c.close()
    return {"key": k, "plan": plan, "credits": credits, "expires": exp}


def check(key: str):
    """-> (row_dict, error_string_or_None)."""
    init_db()
    key = (key or "").strip().upper()
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    try:
        row = c.execute("SELECT * FROM keys WHERE key=?", (key,)).fetchone()
    finally:
        c.close()
    if not row:
        return None, "invalid key"
    if not row["active"]:
        return None, "key disabled"
    if row["expires"]:
        try:
            exp_dt = datetime.fromisoformat(row["expires"])
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            if exp_dt < datetime.now(timezone.utc):
                return None, "key expired"
        except Exception:
            pass
    d = dict(row)
    d["remaining"] = max(0, d["credits"] - d["used"])
    d["max_rows"], d["can_live"] = PLANS.get(d["plan"], PLANS["starter"])[1:]
    return d, None


def spend(key: str, pages: int, template: str = ""):
    init_db()
    key = (key or "").strip().upper()
    pages = max(0, int(pages))
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    try:
        with c:
            row = c.execute("SELECT credits, used FROM keys WHERE key=? AND active=1", (key,)).fetchone()
            if not row:
                raise ValueError("invalid key")
            if row["credits"] - row["used"] < pages:
                raise ValueError("not enough credits")
            c.execute("UPDATE keys SET used = used + ? WHERE key=?", (pages, key))
            c.execute("INSERT INTO usage(key,pages,template,at) VALUES(?,?,?,?)",
                      (key, pages, template, now))
    finally:
        c.close()


def topup(key, credits):
    c = sqlite3.connect(DB)
    try:
        with c:
            c.execute("UPDATE keys SET credits = credits + ? WHERE key=?",
                      (int(credits), key.strip().upper()))
    finally:
        c.close()


def disable(key):
    c = sqlite3.connect(DB)
    try:
        with c:
            c.execute("UPDATE keys SET active=0 WHERE key=?", (key.strip().upper(),))
    finally:
        c.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new")
    n.add_argument("email")
    n.add_argument("--plan", default="starter")
    n.add_argument("--days", type=int, default=365)
    n.add_argument("--note", default="")
    t = sub.add_parser("topup")
    t.add_argument("key")
    t.add_argument("credits", type=int)
    d = sub.add_parser("disable")
    d.add_argument("key")
    sub.add_parser("list")
    a = ap.parse_args()

    if a.cmd == "new":
        print(new_key(a.email, a.plan, a.days, a.note))
    elif a.cmd == "topup":
        topup(a.key, a.credits)
        print("topped up")
    elif a.cmd == "disable":
        disable(a.key)
        print("disabled")
    else:
        with conn() as c:
            for r in c.execute("SELECT * FROM keys ORDER BY created DESC"):
                print(f"{r['key']}  {r['plan']:<8} {r['used']}/{r['credits']:<6} "
                      f"{r['email']:<28} {'ok' if r['active'] else 'off'}")
