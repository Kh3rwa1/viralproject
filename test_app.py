import unittest
import io
import json
import shutil
import tempfile
from pathlib import Path
from datetime import datetime, timezone

import app
import licenses
import engine
import jobs
import core


class TestLeadPagesFixes(unittest.TestCase):

    def setUp(self):
        self.client = app.app.test_client()
        self.app_context = app.app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    def test_sanitize_url(self):
        # Valid URLs
        self.assertEqual(engine.sanitize_url("https://example.com"), "https://example.com")
        self.assertEqual(engine.sanitize_url("http://example.com"), "http://example.com")
        self.assertEqual(engine.sanitize_url("tel:+919831194050"), "tel:+919831194050")
        self.assertEqual(engine.sanitize_url("https://wa.me/919831194050"), "https://wa.me/919831194050")
        self.assertEqual(engine.sanitize_url("example.com"), "https://example.com")

        # Dangerous malicious URLs stripped
        self.assertEqual(engine.sanitize_url("javascript:alert(1)"), "")
        self.assertEqual(engine.sanitize_url("data:text/html,<script>alert(1)</script>"), "")
        self.assertEqual(engine.sanitize_url("vbscript:msgbox(1)"), "")

    def test_licenses_check_and_conn_safety(self):
        # Issue a new key
        k_info = licenses.new_key("test@example.com", "trial", days=30)
        key = k_info["key"]
        
        # Check key
        row, err = licenses.check(key)
        self.assertIsNone(err)
        self.assertEqual(row["plan"], "trial")
        self.assertEqual(row["max_rows"], 25)
        self.assertEqual(row["remaining"], 25)

    def test_api_upload_auto_capping(self):
        # Create trial key
        k_info = licenses.new_key("trial_user@example.com", "trial", days=30)
        key = k_info["key"]

        with self.client.session_transaction() as sess:
            sess["key"] = key

        # Generate CSV with 50 valid leads
        csv_data = "name,phone,city,category\n"
        for i in range(50):
            csv_data += f"Business {i+1},+9198765432{i:02d},Kolkata,Coaching\n"

        data = {
            "template": "coaching",
            "file": (io.BytesIO(csv_data.encode("utf-8")), "test_leads.csv")
        }

        resp = self.client.post("/api/upload", data=data, content_type="multipart/form-data")
        self.assertEqual(resp.status_code, 200)
        res = resp.get_json()
        self.assertEqual(res["buildable"], 25)  # Trial plan limit capped to 25
        self.assertNotIn("error", res)

    def test_job_disk_recovery(self):
        k_info = licenses.new_key("recover_user@example.com", "starter", days=30)
        key = k_info["key"]
        job = jobs.new_job(key)
        jid = job["id"]

        # Create dummy state.json in job folder
        folder = Path(job["folder"])
        summary = {"built": 10, "template": "coaching", "base_url": "https://test.app"}
        (folder / "state.json").write_text(json.dumps(summary), encoding="utf-8")

        # Clear in-memory JOBS
        jobs.JOBS.clear()
        self.assertNotIn(jid, jobs.JOBS)

        # Retrieve job via jobs.get - should recover from disk
        recovered = jobs.get(jid, key)
        self.assertIsNotNone(recovered)
        self.assertEqual(recovered["state"], "done")
        self.assertEqual(recovered["summary"]["built"], 10)


if __name__ == "__main__":
    unittest.main()
