import io
import json
import re
import shutil
import tempfile
import time
import unittest
from pathlib import Path

import core
import engine


class TestStandaloneGenerator(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.outdir = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_single_lead_generation(self):
        csv_content = "name,category,city,phone\nBrightPath,Coaching Centre,Kolkata,9876543210\n"
        csv_path = self.outdir / "input.csv"
        csv_path.write_text(csv_content, encoding="utf-8")

        summary = core.generate(csv_path, "coaching", self.outdir, base_url="https://site.netlify.app")

        self.assertEqual(summary["built"], 1)
        page_file = self.outdir / "dist" / "brightpath" / "index.html"
        self.assertTrue(page_file.exists())

        html = page_file.read_text(encoding="utf-8")
        self.assertIn("BrightPath", html)
        self.assertIn("9876543210", html)
        self.assertIn("https://wa.me/919876543210", html)
        self.assertNotIn("{{", html)
        self.assertNotIn("}}", html)

    def test_multiple_leads_no_cross_leakage(self):
        csv_content = (
            "name,category,city,phone,address,website,maps_url\n"
            "Alpha Coaching,Education,Kolkata,9876543210,12 Park Street,https://alpha.com,https://maps.google.com/?q=alpha\n"
            "Beta Academy,Coaching,Mumbai,9123456789,45 MG Road,https://beta.com,https://maps.google.com/?q=beta\n"
        )
        csv_path = self.outdir / "input.csv"
        csv_path.write_text(csv_content, encoding="utf-8")

        core.generate(csv_path, "coaching", self.outdir, keep_real=True, base_url="https://site.netlify.app")

        alpha_html = (self.outdir / "dist" / "alpha-coaching" / "index.html").read_text(encoding="utf-8")
        beta_html = (self.outdir / "dist" / "beta-academy" / "index.html").read_text(encoding="utf-8")

        # Assert Alpha page has Alpha data and NO Beta data
        self.assertIn("Alpha Coaching", alpha_html)
        self.assertIn("9876543210", alpha_html)
        self.assertIn("12 Park Street", alpha_html)
        self.assertNotIn("Beta Academy", alpha_html)
        self.assertNotIn("9123456789", alpha_html)
        self.assertNotIn("45 MG Road", alpha_html)
        self.assertNotIn("https://beta.com", alpha_html)

        # Assert Beta page has Beta data and NO Alpha data
        self.assertIn("Beta Academy", beta_html)
        self.assertIn("9123456789", beta_html)
        self.assertIn("45 MG Road", beta_html)
        self.assertNotIn("Alpha Coaching", beta_html)
        self.assertNotIn("9876543210", beta_html)
        self.assertNotIn("12 Park Street", beta_html)
        self.assertNotIn("https://alpha.com", beta_html)

    def test_malicious_input_and_xss_escaping(self):
        csv_content = (
            "name,category,city,phone\n"
            "\"<script>alert('xss')</script>\",Coaching,Kolkata,9876543210\n"
            "\"<img src=x onerror=alert(1)>\",Dentist,Mumbai,9831194050\n"
            "\"D'Souza Dental & Skin Clinic\",Dentist,Goa,9470550524\n"
            "\"Tom & Jerry Coaching\",Coaching,Delhi,9123456780\n"
        )
        csv_path = self.outdir / "input.csv"
        csv_path.write_text(csv_content, encoding="utf-8")

        summary = core.generate(csv_path, "coaching", self.outdir)
        self.assertEqual(summary["built"], 4)

        for slug in summary["slugs"]:
            page_file = self.outdir / "dist" / slug / "index.html"
            self.assertTrue(page_file.exists())
            html = page_file.read_text(encoding="utf-8")

            # Assert no raw executable tags exist outside encoded strings
            self.assertNotIn("<script>alert('xss')</script>", html)
            self.assertNotIn("<img src=x onerror=alert(1)>", html)

            # Assert path containment
            self.assertTrue(page_file.resolve().is_relative_to((self.outdir / "dist").resolve()))

    def test_json_ld_validity(self):
        csv_content = (
            "name,category,city,phone,address\n"
            "BrightPath Coaching,Coaching Centre,Kolkata,9876543210,12 Park Street\n"
        )
        csv_path = self.outdir / "input.csv"
        csv_path.write_text(csv_content, encoding="utf-8")

        core.generate(csv_path, "coaching", self.outdir, base_url="https://site.netlify.app")

        html = (self.outdir / "dist" / "brightpath-coaching" / "index.html").read_text(encoding="utf-8")
        match = re.search(r'<script type="application/ld\+json">\s*(\{.*?\})\s*</script>', html, re.S)
        self.assertIsNotNone(match)

        json_ld_str = match.group(1)
        schema_obj = json.loads(json_ld_str)

        self.assertEqual(schema_obj["@context"], "https://schema.org")
        self.assertEqual(schema_obj["@type"], "LocalBusiness")
        self.assertEqual(schema_obj["name"], "BrightPath Coaching")
        self.assertEqual(schema_obj["telephone"], "+919876543210")
        self.assertEqual(schema_obj["address"], "12 Park Street")

    def test_category_compatibility_warnings(self):
        csv_content = (
            "name,category,city,phone\n"
            "Pandey Legal Services,Lawyer,Jamshedpur,9470550524\n"
        )
        csv_path = self.outdir / "input.csv"
        csv_path.write_text(csv_content, encoding="utf-8")

        summary = core.generate(csv_path, "coaching", self.outdir)
        self.assertTrue(len(summary["warnings"]) > 0)
        self.assertIn("may not match", summary["warnings"][0])

    def test_build_manifest_creation(self):
        csv_content = "name,category,city,phone\nBrightPath,Coaching,Kolkata,9876543210\n"
        csv_path = self.outdir / "input.csv"
        csv_path.write_text(csv_content, encoding="utf-8")

        core.generate(csv_path, "coaching", self.outdir, base_url="https://site.netlify.app")

        manifest_file = self.outdir / "build-manifest.json"
        self.assertTrue(manifest_file.exists())
        self.assertFalse((self.outdir / "dist" / "build-manifest.json").exists())

        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        self.assertEqual(manifest["template"], "coaching")
        self.assertEqual(manifest["expectedPages"], 1)
        self.assertEqual(manifest["generatedPages"], 1)
        self.assertEqual(manifest["failedPages"], 0)
        self.assertEqual(len(manifest["pages"]), 1)
        self.assertEqual(manifest["pages"][0]["slug"], "brightpath")

    def test_missing_optional_fields(self):
        csv_content = "name,phone\nMinimal Business,9876543210\n"
        csv_path = self.outdir / "input.csv"
        csv_path.write_text(csv_content, encoding="utf-8")

        summary = core.generate(csv_path, "coaching", self.outdir)
        self.assertEqual(summary["built"], 1)

        page_file = self.outdir / "dist" / "minimal-business" / "index.html"
        self.assertTrue(page_file.exists())
        html = page_file.read_text(encoding="utf-8")
        self.assertNotIn("undefined", html)
        self.assertNotIn("{{", html)

    def test_duplicate_names_slug_deduplication(self):
        csv_content = (
            "name,category,city,phone\n"
            "BrightPath Coaching,Coaching,Kolkata,9876543210\n"
            "BrightPath Coaching,Coaching,Kolkata,9876543211\n"
        )
        csv_path = self.outdir / "input.csv"
        csv_path.write_text(csv_content, encoding="utf-8")

        core.generate(csv_path, "coaching", self.outdir)

        p1 = self.outdir / "dist" / "brightpath-coaching" / "index.html"
        p2 = self.outdir / "dist" / "brightpath-coaching-2" / "index.html"

        self.assertTrue(p1.exists())
        self.assertTrue(p2.exists())

    def test_benchmark_1000_leads(self):
        rows = ["name,category,city,phone"]
        for i in range(1000):
            rows.append(f"Business {i+1},Coaching,City {i%10},98765{i:05d}")

        csv_path = self.outdir / "input.csv"
        csv_path.write_text("\n".join(rows), encoding="utf-8")

        t0 = time.time()
        summary = core.generate(csv_path, "coaching", self.outdir, base_url="https://site.netlify.app")
        elapsed = time.time() - t0

        self.assertEqual(summary["built"], 1000)
        generated_pages = list((self.outdir / "dist").glob("*/index.html"))
        self.assertEqual(len(generated_pages), 1000)
        print(f"\n[BENCHMARK] 1,000 leads built in {elapsed:.2f} seconds")

    def test_benchmark_5000_leads(self):
        rows = ["name,category,city,phone"]
        for i in range(5000):
            rows.append(f"Enterprise Lead {i+1},Coaching,City {i%20},98700{i:05d}")

        csv_path = self.outdir / "input_5k.csv"
        csv_path.write_text("\n".join(rows), encoding="utf-8")

        t0 = time.time()
        summary = core.generate(csv_path, "coaching", self.outdir, base_url="https://site.netlify.app")
        elapsed = time.time() - t0

        self.assertEqual(summary["built"], 5000)
        generated_pages = list((self.outdir / "dist").glob("*/index.html"))
        self.assertEqual(len(generated_pages), 5000)
        print(f"\n[BENCHMARK] 5,000 leads built in {elapsed:.2f} seconds")


    def test_all_registered_templates_render(self):
        from collections import Counter
        templates = engine.list_templates()
        self.assertEqual(len(templates), 50)

        counts = Counter(t["category"] for t in templates)
        self.assertEqual(len(counts), 10)
        self.assertTrue(all(c == 5 for c in counts.values()))

        expected_layouts = {
            "clean_product", "dark_cinematic", "aurora_glass", "retro_editorial", "friendly_illustrated"
        }
        for cat in counts:
            cat_layouts = {t["layout"] for t in templates if t["category"] == cat}
            self.assertEqual(cat_layouts, expected_layouts)

        full_lead = engine.lead_record({
            "name": "Apex Business Services",
            "category": "Dental Clinic",
            "city": "Kolkata",
            "address": "12 Park Street",
            "phone": "9876543210",
            "lat": "22.5726",
            "lng": "88.3639",
            "rating": "4.9",
            "reviews": "85",
            "hours": "9 AM - 7 PM"
        }, "apex-business", base_url="https://example.netlify.app")

        sparse_lead = engine.lead_record({
            "name": "Minimal Clinic",
            "category": "Medical Clinic"
        }, "minimal-clinic", base_url="https://example.netlify.app")

        for item in templates:
            with self.subTest(template=item["id"], condition="full"):
                html = engine.render_full_page(item["id"], full_lead, live=False)
                engine.validate_rendered_page(html, full_lead, template_name=item["id"])
                self.assertIn("22.5726%2C88.3639", html)

            with self.subTest(template=item["id"], condition="sparse"):
                html = engine.render_full_page(item["id"], sparse_lead, live=False)
                engine.validate_rendered_page(html, sparse_lead, template_name=item["id"])
                self.assertNotIn("undefined", html)
                self.assertNotIn("{{", html)

    def test_multiword_category_resolution(self):
        meta_home = engine.get_template_meta("home_services_clean_product")
        self.assertEqual(meta_home["category"], "home_services")
        self.assertEqual(meta_home["layout"], "clean_product")

        meta_estate = engine.get_template_meta("real_estate_aurora_glass")
        self.assertEqual(meta_estate["category"], "real_estate")
        self.assertEqual(meta_estate["layout"], "aurora_glass")

        lead = engine.lead_record({
            "name": "Quick Fix Plumbing",
            "category": "Plumber",
            "city": "Mumbai",
            "address": "45 MG Road",
            "phone": "9820098200"
        }, "quick-fix-plumbing")

        html_home = engine.render_full_page("home_services_clean_product", lead)
        self.assertIn("Emergency Plumbing", html_home)

    def test_map_coordinate_priority(self):
        lead = engine.lead_record({
            "name": "Random Clinic",
            "city": "Delhi",
            "address": "10 Connaught Place",
            "lat": "28.6139",
            "lng": "77.2090"
        }, "random-clinic")

        self.assertIn("q=28.6139%2C77.2090", lead["mapsEmbedUrl"])


if __name__ == "__main__":
    unittest.main()
