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

    def test_dark_cinematic_visual_approval_gate(self):
        lead = engine.lead_record({
            "name": "Apex Luxury Dental Clinic",
            "category": "Dental Clinics",
            "city": "Kolkata",
            "phone": "9876543210",
            "address": "12 Park Street, Opposite City Mall",
            "rating": "4.9",
            "reviews": "128"
        }, "apex-luxury-dental")

        artifact_dir = Path("/Users/dulorai/.gemini/antigravity/brain/0307b4a0-8eb7-43a0-852d-7166f9fe4a6f")
        artifact_dir.mkdir(parents=True, exist_ok=True)

        html = engine.render_full_page("dental_dark_cinematic", lead, live=False)
        (artifact_dir / "dark_cinematic_rendered.html").write_text(html, encoding="utf-8")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            # 1. Desktop Viewport 1440x900
            page_errors = []
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()
            page.on("pageerror", lambda err: page_errors.append(str(err)))

            page.set_content(html)
            page.wait_for_timeout(500)

            # Assert video hero & poster exist
            video_exists = page.query_selector("video.hero-video") is not None
            poster_exists = page.query_selector("img.hero-poster") is not None
            self.assertTrue(video_exists, "Missing video.hero-video in dark_cinematic")
            self.assertTrue(poster_exists, "Missing img.hero-poster in dark_cinematic")
            self.assertEqual(len(page_errors), 0, f"Encountered page errors: {page_errors}")

            # Capture Viewport Screenshot
            page.screenshot(path=str(artifact_dir / "dark_cinematic_desktop_1440.png"))
            # Capture Full Page Screenshot
            page.screenshot(path=str(artifact_dir / "dark_cinematic_fullpage_1440.png"), full_page=True)

            context.close()

            # 2. Mobile Viewport 390x844 (iPhone 14)
            page_errors_mobile = []
            context_mobile = browser.new_context(viewport={"width": 390, "height": 844})
            page_mobile = context_mobile.new_page()
            page_mobile.on("pageerror", lambda err: page_errors_mobile.append(str(err)))

            page_mobile.set_content(html)
            page_mobile.wait_for_timeout(500)

            # Assert mobile sticky bar is visible
            mobile_bar_visible = page_mobile.eval_on_selector(".mobile-sticky-bar", "el => getComputedStyle(el).display !== 'none'")
            self.assertTrue(mobile_bar_visible, "Mobile sticky bar should be visible on 390x844 viewport")
            self.assertEqual(len(page_errors_mobile), 0, f"Encountered mobile page errors: {page_errors_mobile}")

            # Capture Mobile Screenshot
            page_mobile.screenshot(path=str(artifact_dir / "dark_cinematic_mobile_390.png"))

            context_mobile.close()
            browser.close()


if __name__ == "__main__":
    unittest.main()
