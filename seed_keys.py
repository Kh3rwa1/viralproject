"""seed_keys.py — inserts the pre-generated keys. Run once: python seed_keys.py"""
from datetime import datetime, timedelta, timezone
import csv
import licenses

KEYS = {
"trial": ["LP-7QK2-M4XR-9TVB","LP-B3ND-7HSQ-2WKF","LP-Z9MT-4PRC-6XJD","LP-K5WV-8QNB-3HFT",
"LP-R2XC-9JMD-7VKS","LP-T8HF-3BZQ-5NWP","LP-M4JR-6VXK-8QTC","LP-W7SD-2NPH-4RZB",
"LP-C3VB-5KQM-9XFT","LP-N6TP-8WRJ-2DSH","LP-X9QK-4FBV-7MCN","LP-D5RH-9TZW-3JPQ",
"LP-V2NM-7CXB-6KSF","LP-H8FT-3QDR-9WVZ","LP-Q4BJ-6MHP-2TXN","LP-S7CW-9VKT-5RDM",
"LP-J3ZP-2XNF-8BQH","LP-F6KV-5RTM-4WCD","LP-P9DN-7HJB-3ZQX","LP-G2TR-4SVC-6NMK"],

"starter": ["LP-4HXB-2QNW-8TRD","LP-9MKC-6FVJ-3PZS","LP-2TWQ-7BDH-5XNR","LP-6RJV-3ZKM-9CFT",
"LP-8PNS-5HQX-2VBW","LP-3DFM-9TCR-7KJZ","LP-7VXH-4NBP-6QMS","LP-5CZT-8WRK-3FDJ",
"LP-9QBN-2MVH-4XPT","LP-4KRW-7SFC-8ZDM","LP-6NHJ-3XQV-5TBR","LP-2SPD-9CMK-7WFN",
"LP-8TVZ-5RJB-3HQX","LP-3MFC-6DNW-9KPS","LP-7BQR-4TZH-2VJM","LP-5XWK-8PNC-6RDF",
"LP-9JHT-3VBS-4MQZ","LP-4CNM-7KRD-8XWP","LP-6ZFB-2QTJ-5HVN","LP-8WDS-9MXC-3PKR"],

"pro": ["LP-K7QM-3XTV-9BND","LP-R4WC-8JZP-5HFS","LP-M9BT-2VKD-7QXN","LP-T3PJ-6RSH-4WCZ",
"LP-B8NF-9DMQ-2KVR","LP-W5XS-4TCB-8JPH","LP-C2VD-7QNM-6ZFT","LP-N6HR-3KWX-9BSJ",
"LP-Z9TP-5FMC-4RDQ","LP-H4JB-8VNW-3XKS","LP-V7QN-2DTR-5MCF","LP-D3ZM-9HXK-7BWP",
"LP-Q8SC-4RJV-6NTD","LP-J5FW-7BQZ-2HMX","LP-X2KT-6PDN-8VRC","LP-S9MB-3WFH-5QJZ",
"LP-F6RD-8CXT-9NKW","LP-P4VH-5ZBM-3TQS","LP-G7NW-2JKC-6DFR","LP-Y3XQ-9MTB-4HPV"],

"agency": ["LP-A5TN-7RQW-2FMC","LP-E8KD-3BVJ-9XHS","LP-U2WM-6ZPT-5CNR","LP-L9FB-4HXQ-8DKV",
"LP-A3JC-8NMR-6TWZ","LP-E6PV-2SKD-4BQF","LP-U7HT-9WCX-3ZNM","LP-L4QB-5RJP-7VDS",
"LP-A8XN-3FTK-9MHW","LP-E5DR-6QBV-2CJZ","LP-U3MP-4XSH-8WFT","LP-L6VK-9NDC-5QRB",
"LP-A9WJ-2HZM-7TPX","LP-E4CF-7BRQ-3SNV","LP-U8ZD-5MTW-6KHJ","LP-L2NQ-8VXP-4FCB",
"LP-A7RS-3DKT-9WMZ","LP-E9BH-6JVN-5XQC","LP-U5TF-2WPM-8RDK","LP-L3XV-9CQB-7HNS"],
}

DAYS = {"trial": 14, "starter": 365, "pro": 365, "agency": 31}


def main():
    now = datetime.now(timezone.utc)
    added, skipped, rows = 0, 0, []
    with licenses.conn() as c:
        for plan, keys in KEYS.items():
            credits = licenses.PLANS[plan][0]
            exp = (now + timedelta(days=DAYS[plan])).isoformat(timespec="seconds")
            for k in keys:
                if c.execute("SELECT 1 FROM keys WHERE key=?", (k,)).fetchone():
                    skipped += 1
                    continue
                c.execute("INSERT INTO keys(key,email,plan,credits,created,expires,note)"
                          " VALUES(?,?,?,?,?,?,?)",
                          (k, "", plan, credits, now.isoformat(timespec="seconds"),
                           exp, "batch-1 unassigned"))
                rows.append({"key": k, "plan": plan, "credits": credits,
                             "expires": exp[:10], "assigned_to": ""})
                added += 1

    with open("keys_issued.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["key", "plan", "credits", "expires", "assigned_to"])
        w.writeheader(); w.writerows(rows)

    print(f"added {added} keys, skipped {skipped} existing → keys_issued.csv")
    for plan in KEYS:
        print(f"  {plan:<8} 20 keys · {licenses.PLANS[plan][0]} credits · "
              f"{DAYS[plan]}d validity")


if __name__ == "__main__":
    main()
