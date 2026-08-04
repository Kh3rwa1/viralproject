"""test_luminous_cinema.py - Visual approval gate test for Template 3: Luminous Cinema."""
import os
import unittest
from pathlib import Path
from playwright.sync_api import sync_playwright

import engine


class TestLuminousCinemaVisualGate(unittest.TestCase):
    def test_luminous_cinema_visual_gate(self):
        lead = engine.lead_record({
            "name": "Apex Dental Clinic",
            "category": "Dental Clinics",
            "city": "Kolkata",
            "phone": "9876543210",
            "address": "12 Park Street, Opposite City Mall",
            "rating": "4.9",
            "reviews": "128"
        }, "apex-dental-clinic")

        artifact_dir = Path(os.environ.get("TEST_ARTIFACT_DIR", "test-results/luminous-cinema"))
        artifact_dir.mkdir(parents=True, exist_ok=True)

        html = engine.render_full_page("dental_dark_cinematic", lead, live=False)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            page_errors = []
            context_desktop = browser.new_context(viewport={"width": 1440, "height": 900})
            page_desktop = context_desktop.new_page()
            page_desktop.on("pageerror", lambda err: page_errors.append(str(err)))

            page_desktop.set_content(html)
            page_desktop.wait_for_timeout(800)

            hero_sec = page_desktop.query_selector("section.luminous-hero")
            video_el = page_desktop.query_selector("video.luminous-hero__video")
            poster_el = page_desktop.query_selector("img.luminous-hero__poster")

            self.assertIsNotNone(hero_sec)
            self.assertIsNotNone(video_el)
            self.assertIsNotNone(poster_el)

            source_el = page_desktop.query_selector("video.luminous-hero__video source")
            source_url = source_el.get_attribute("src") if source_el else ""
            self.assertTrue("pexels" in source_url or "dental-check" in source_url)

            video_position = page_desktop.eval_on_selector("video.luminous-hero__video", "el => getComputedStyle(el).position")
            self.assertEqual(video_position, "absolute")

            bg_color = page_desktop.eval_on_selector("section.luminous-hero", "el => getComputedStyle(el).backgroundColor")
            self.assertTrue("253" in bg_color or "255" in bg_color)

            self.assertEqual(len(page_errors), 0)

            page_desktop.screenshot(path=str(artifact_dir / "luminous_cinema_desktop_hero.png"))
            page_desktop.screenshot(path=str(artifact_dir / "luminous_cinema_desktop_fullpage.png"), full_page=True)

            context_desktop.close()

            context_mobile = browser.new_context(viewport={"width": 390, "height": 844})
            page_mobile = context_mobile.new_page()
            page_mobile.set_content(html)
            page_mobile.wait_for_timeout(800)

            page_mobile.screenshot(path=str(artifact_dir / "luminous_cinema_mobile_hero.png"))
            page_mobile.screenshot(path=str(artifact_dir / "luminous_cinema_mobile_fullpage.png"), full_page=True)

            context_mobile.close()
            browser.close()


if __name__ == "__main__":
    unittest.main()
