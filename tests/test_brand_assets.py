"""Marketplace naming and offline brand-image contracts."""

from __future__ import annotations

import json
import struct
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "stiebel_dhe_connect"
BRAND = INTEGRATION / "brand"


class BrandAssetTests(unittest.TestCase):
    def test_catalog_display_name_keeps_the_existing_domain(self) -> None:
        manifest = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))
        hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "Stiebel Eltron DHE Connect")
        self.assertEqual(hacs["name"], manifest["name"])
        self.assertEqual(manifest["domain"], "stiebel_dhe_connect")
        self.assertEqual(INTEGRATION.name, manifest["domain"])

    def test_square_artwork_uses_icon_names_and_expected_png_dimensions(self) -> None:
        self.assertEqual(
            {path.name for path in BRAND.iterdir()},
            {"icon.png", "icon@2x.png"},
        )
        for filename, size in (("icon.png", 256), ("icon@2x.png", 512)):
            with self.subTest(filename=filename):
                data = (BRAND / filename).read_bytes()
                self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
                self.assertEqual(data[12:16], b"IHDR")
                self.assertEqual(struct.unpack(">II", data[16:24]), (size, size))

    def test_ha_serves_all_brand_variants_using_only_local_artwork(self) -> None:
        from homeassistant.components.brands import _read_brand_file
        from homeassistant.components.brands.const import ALLOWED_IMAGES

        icon = (BRAND / "icon.png").read_bytes()
        high_resolution_icon = (BRAND / "icon@2x.png").read_bytes()
        for image in sorted(ALLOWED_IMAGES):
            with self.subTest(image=image):
                self.assertIn(_read_brand_file(BRAND, image), (icon, high_resolution_icon))
        self.assertEqual(_read_brand_file(BRAND, "icon@2x.png"), high_resolution_icon)
        self.assertEqual(_read_brand_file(BRAND, "logo.png"), icon)
