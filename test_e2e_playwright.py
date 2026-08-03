"""test_e2e_playwright.py - End-to-end browser testing for LeadPages app."""
import unittest
import threading
import time
import socket
from pathlib import Path
from playwright.sync_api import sync_playwright

import app
import core
import engine
import licenses


def find_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


class TestE2EPlaywright(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = find_free_port()
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        app.app.config["TESTING"] = True
        
        # Start Flask app server in background thread
        def run_server():
            app.app.run(host="127.0.0.1", port=cls.port, use_reloader=False, threaded=True)
            
        cls.server_thread = threading.Thread(target=run_server, daemon=True)
        cls.server_thread.start()
        time.sleep(1.0)
        
        # Create test license key
        k_info = licenses.new_key("e2e_user@example.com", "starter", days=30)
        cls.test_key = k_info["key"]

    def test_app_ui_and_zero_buildable_upload_flow(self):
        page_errors = []
        console_logs = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()

            page.on("pageerror", lambda err: page_errors.append(str(err)))
            page.on("console", lambda msg: console_logs.append(msg.text) if msg.type == "error" else None)

            # 1. Sign in with access key
            page.goto(f"{self.base_url}/app")
            page.fill("#key", self.test_key)
            page.click("button[onclick*='signin']")
            page.wait_for_selector("#catTabs")

            # Assert 50 templates loaded in selector
            templates = page.query_selector_all(".type")
            self.assertGreaterEqual(len(templates), 50)

            # Pick first template
            templates[0].click()

            # 2. Prepare zero-buildable CSV upload
            csv_path = Path("test_zero_buildable.csv")
            csv_path.write_text(
                "Business Name,Phone,Website\n"
                "Dr. Smith Dentistry,9123456789,drsmithdental.com\n"
                "City Dental Clinic,9000011111,www.citydental.com\n",
                encoding="utf-8"
            )

            try:
                # Upload CSV file and trigger upload()
                page.set_input_files("#file", str(csv_path))
                page.evaluate("upload()")

                # Verify clean notice appears without JS exceptions
                page.wait_for_selector("#report")
                report_text = page.inner_text("#report")

                self.assertIn("0 websites banengi", report_text)
                self.assertIn("CSV cleaned successfully", report_text)
                self.assertEqual(len(page_errors), 0, f"Encountered page errors: {page_errors}")

                # Verify build button is hidden/disabled for 0 buildable rows
                build_btn_hidden = page.eval_on_selector("#buildBtn", "el => el.classList.contains('hide') || el.disabled")
                self.assertTrue(build_btn_hidden)

            finally:
                if csv_path.exists():
                    csv_path.unlink()

            browser.close()

    def test_multi_viewport_landing_pages_rendering(self):
        lead = engine.lead_record({
            "name": "Apex Dental Clinic",
            "category": "Dental Clinics",
            "city": "Kolkata",
            "phone": "9876543210",
            "address": "12 Park Street, Opposite City Mall",
            "rating": "4.9",
            "reviews": "128"
        }, "apex-dental-clinic")

        layouts = [
            "dental_clean_product",
            "dental_dark_cinematic",
            "dental_aurora_glass",
            "dental_retro_editorial",
            "dental_friendly_illustrated"
        ]

        viewports = [
            {"width": 375, "height": 812, "name": "mobile_375"},
            {"width": 430, "height": 932, "name": "mobile_430"},
            {"width": 768, "height": 1024, "name": "tablet_768"},
            {"width": 1440, "height": 900, "name": "desktop_1440"},
            {"width": 1920, "height": 1080, "name": "desktop_1920"}
        ]

        artifact_dir = Path("/Users/dulorai/.gemini/antigravity/brain/0307b4a0-8eb7-43a0-852d-7166f9fe4a6f")
        artifact_dir.mkdir(parents=True, exist_ok=True)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            for l_id in layouts:
                html = engine.render_full_page(l_id, lead, live=False)

                for vp in viewports:
                    page_errors = []
                    context = browser.new_context(viewport={"width": vp["width"], "height": vp["height"]})
                    page = context.new_page()
                    page.on("pageerror", lambda err: page_errors.append(str(err)))

                    page.set_content(html)
                    page.wait_for_timeout(300)

                    # Verify video and poster fallback exist
                    video_exists = page.query_selector("video") is not None
                    poster_exists = page.query_selector("img.hero-poster") is not None

                    self.assertTrue(video_exists, f"Missing hero video in {l_id} at {vp['name']}")
                    self.assertTrue(poster_exists, f"Missing hero poster in {l_id} at {vp['name']}")
                    self.assertEqual(len(page_errors), 0, f"Page error in {l_id} at {vp['name']}: {page_errors}")

                    # Test FAQ toggle
                    faq_btn = page.query_selector(".faq-trigger")
                    if faq_btn:
                        faq_btn.click()

                    # Save screenshots for desktop (1440x900) and mobile (375x812)
                    if vp["name"] == "desktop_1440":
                        img_path = artifact_dir / f"agency_{l_id}_desktop.png"
                        page.screenshot(path=str(img_path))
                    elif vp["name"] == "mobile_375":
                        img_path = artifact_dir / f"agency_{l_id}_mobile.png"
                        page.screenshot(path=str(img_path))

                    context.close()

            browser.close()


if __name__ == "__main__":
    unittest.main()
