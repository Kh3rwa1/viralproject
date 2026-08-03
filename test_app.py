import unittest
from unittest.mock import patch
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
        self.assertEqual(engine.sanitize_url("example.com"), "https://example.com")

        # Dangerous malicious URLs or unsupported schemes stripped
        self.assertEqual(engine.sanitize_url("javascript:alert(1)"), "")
        self.assertEqual(engine.sanitize_url("data:text/html,<script>alert(1)</script>"), "")
        self.assertEqual(engine.sanitize_url("vbscript:msgbox(1)"), "")
        self.assertEqual(engine.sanitize_url("tel:+919831194050"), "")

    @unittest.mock.patch("netlify.ensure_site")
    @unittest.mock.patch("netlify.deploy_to_site")
    def test_cli_deploy_end_to_end(self, mock_deploy_to_site, mock_ensure_site):
        import deploy
        import build as B

        mock_ensure_site.return_value = {"id": "site123", "name": "test-site", "url": "https://test-site.netlify.app"}
        mock_deploy_to_site.return_value = "deploy123"

        tmp_dir = Path(tempfile.mkdtemp())
        try:
            csv_path = tmp_dir / "input.csv"
            csv_path.write_text("name,phone,city,category\nApex Coaching,+919831194050,Kolkata,Coaching\n", encoding="utf-8")

            tmp_state = tmp_dir / "state.json"
            tmp_dist = tmp_dir / "dist"
            tmp_leads = tmp_dir / "leads.csv"

            with patch.object(B, "ROOT", tmp_dir), \
                 patch.object(B, "STATE", tmp_state), \
                 patch.object(B, "LEADS_CSV", tmp_leads), \
                 patch.object(engine, "DIST", tmp_dist):

                core.generate(csv_path, "coaching", tmp_dir, limit=5, city="Kolkata", base_url="http://localhost:8080")

                state_data = {
                    "template": "coaching", "source_csv": str(csv_path),
                    "limit": 5, "city": "Kolkata", "only": "", "keep_real": True,
                    "site_name": "test-site", "partial": False, "slugs": ["apex-coaching"]
                }
                tmp_state.write_text(json.dumps(state_data), encoding="utf-8")

                with patch("sys.argv", ["deploy.py", "--site", "test-site", "--token", "fake_token"]):
                    deploy.main()

                mock_ensure_site.assert_called_once_with("test-site", "fake_token")
                mock_deploy_to_site.assert_called_once_with(tmp_dist, "site123", "fake_token")

                updated_state = json.loads(tmp_state.read_text())
                self.assertEqual(updated_state["base_url"], "https://test-site.netlify.app")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

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


    def test_starter_deploy_preserves_noindex(self):
        k_info = licenses.new_key("starter_user@example.com", "starter", days=30)
        key = k_info["key"]
        row, err = licenses.check(key)
        self.assertTrue(row["can_deploy"])
        self.assertFalse(row["can_index"])

        job = jobs.new_job(key)
        opts = {"template": "coaching", "live": False, "keep_real": False}
        job["opts"] = opts

        with patch("netlify.ensure_site") as mock_ensure, \
             patch("netlify.deploy_to_site") as mock_deploy, \
             patch("core.generate") as mock_generate:
            mock_ensure.return_value = {"id": "test_site_id", "url": "https://test.netlify.app"}
            mock_deploy.return_value = None

            jobs.start_deploy(job, "test-subdomain", "token_123")
            import time
            time.sleep(0.5)

            # Ensure core.generate was called with live=False (noindex preserved for Starter)
            self.assertTrue(mock_generate.called)
            called_kwargs = mock_generate.call_args.kwargs if mock_generate.call_args.kwargs else {}
            if not called_kwargs and len(mock_generate.call_args.args) >= 7:
                self.assertIn("live", mock_generate.call_args[1])
            self.assertFalse(mock_generate.call_args[1]["live"])

    def test_api_templates_response(self):
        client = app.app.test_client()
        k_info = licenses.new_key("tpl_tester@example.com", "starter", days=30)
        resp = client.get("/api/templates", headers={"X-Access-Key": k_info["key"]})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(len(data), 50)
        self.assertIn("id", data[0])
        self.assertIn("category", data[0])
        self.assertIn("layout", data[0])


if __name__ == "__main__":
    unittest.main()
