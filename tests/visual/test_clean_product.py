"""test_clean_product.py - Comprehensive visual approval gate test for Template 5: Clean Product."""
import os
import unittest
from pathlib import Path
from playwright.sync_api import sync_playwright

import engine


class TestCleanProductVisualGate(unittest.TestCase):
    def test_clean_product_visual_gate(self):
        lead = engine.lead_record({
            "name": "Apex Dental Clinic",
            "category": "Dental Clinics",
            "city": "Kolkata",
            "phone": "9876543210",
            "address": "12 Park Street, Opposite City Mall",
            "rating": "4.9",
            "reviews": "128"
        }, "apex-dental-clinic")

        artifact_dir = Path(os.environ.get("TEST_ARTIFACT_DIR", "test-results/clean-product"))
        artifact_dir.mkdir(parents=True, exist_ok=True)

        html = engine.render_full_page("dental_clean_product", lead, live=False)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            # 1. Desktop Viewport (1440x900)
            page_errors = []
            context_desktop = browser.new_context(viewport={"width": 1440, "height": 900})
            page_desktop = context_desktop.new_page()
            page_desktop.on("pageerror", lambda err: page_errors.append(str(err)))

            page_desktop.set_content(html)
            page_desktop.wait_for_timeout(800)

            # A. Hero Elements Existence
            hero_sec = page_desktop.query_selector("section.product-hero")
            video_el = page_desktop.query_selector("video.product-screen__video")
            poster_el = page_desktop.query_selector("img.product-screen__poster")

            self.assertIsNotNone(hero_sec, "Missing section.product-hero in clean_product.html")
            self.assertIsNotNone(video_el, "Missing video.product-screen__video in clean_product.html")
            self.assertIsNotNone(poster_el, "Missing img.product-screen__poster in clean_product.html")

            # B. Video Source URL
            source_el = page_desktop.query_selector("video.product-screen__video source")
            source_url = source_el.get_attribute("src") if source_el else ""
            self.assertTrue("pexels" in source_url or "dental-check" in source_url, f"Unexpected source URL: {source_url}")

            # C. Absolute Video Positioning
            video_position = page_desktop.eval_on_selector("video.product-screen__video", "el => getComputedStyle(el).position")
            self.assertEqual(video_position, "absolute")

            # D. Video Ready State & Poster Opacity
            hero_has_ready = page_desktop.eval_on_selector("section.product-hero", "el => el.classList.contains('video-ready')")
            self.assertTrue(hero_has_ready, "Hero section missing 'video-ready' class after render")

            poster_opacity = page_desktop.eval_on_selector("img.product-screen__poster", "el => Number.parseFloat(getComputedStyle(el).opacity)")
            self.assertLess(poster_opacity, 0.1, "Poster should disappear after successful video playback")

            # E. Zero Horizontal Overflow
            has_no_overflow = page_desktop.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth")
            self.assertTrue(has_no_overflow, "Horizontal overflow detected on desktop viewport!")

            # F. CTA Above the Fold
            cta_above_fold = page_desktop.evaluate("""() => {
                const cta = document.querySelector('a.product-button--primary');
                if (!cta) return false;
                const rect = cta.getBoundingClientRect();
                return rect.top >= 0 && rect.top < window.innerHeight;
            }""")
            self.assertTrue(cta_above_fold, "Main CTA is not above the fold on desktop viewport!")

            # G. Zero Page Errors
            self.assertEqual(len(page_errors), 0, f"Page error in clean_product: {page_errors}")

            # Capture Desktop Hero & Full-Page Screenshots
            page_desktop.screenshot(path=str(artifact_dir / "clean_product_desktop_hero.png"))
            page_desktop.screenshot(path=str(artifact_dir / "clean_product_desktop_fullpage.png"), full_page=True)

            context_desktop.close()

            # 2. Mobile Viewport (390x844 — iPhone 14)
            page_errors_mobile = []
            context_mobile = browser.new_context(viewport={"width": 390, "height": 844})
            page_mobile = context_mobile.new_page()
            page_mobile.on("pageerror", lambda err: page_errors_mobile.append(str(err)))

            page_mobile.set_content(html)
            page_mobile.wait_for_timeout(800)

            # Mobile Horizontal Overflow Check
            has_no_mobile_overflow = page_mobile.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth")
            self.assertTrue(has_no_mobile_overflow, "Horizontal overflow detected on mobile viewport!")

            # Mobile Sticky Actions Visibility Check
            mobile_actions_visible = page_mobile.evaluate("""() => {
                const el = document.querySelector('.mobile-actions');
                if (!el) return false;
                const style = getComputedStyle(el);
                return style.display !== 'none' && style.visibility !== 'hidden';
            }""")
            self.assertTrue(mobile_actions_visible, "Mobile sticky actions bar is not visible on mobile viewport!")

            self.assertEqual(len(page_errors_mobile), 0, f"Mobile page error in clean_product: {page_errors_mobile}")

            # Capture Mobile Hero & Full-Page Screenshots
            page_mobile.screenshot(path=str(artifact_dir / "clean_product_mobile_hero.png"))
            page_mobile.screenshot(path=str(artifact_dir / "clean_product_mobile_fullpage.png"), full_page=True)

            context_mobile.close()

            # 3. Reduced-Motion Fallback Test
            context_rm = browser.new_context(viewport={"width": 1440, "height": 900})
            page_rm = context_rm.new_page()
            page_rm.emulate_media(reduced_motion="reduce")
            page_rm.set_content(html)
            page_rm.wait_for_timeout(300)

            video_rm_display = page_rm.eval_on_selector("video.product-screen__video", "el => getComputedStyle(el).display")
            self.assertEqual(video_rm_display, "none", "Video should be display:none under reduced motion")

            context_rm.close()
            browser.close()


if __name__ == "__main__":
    unittest.main()
