#!/usr/bin/env python3
"""Regression tests for unified zh-rCN supplement translations and GT5 auto-brightness overlay."""
from __future__ import annotations

import pathlib
import re
import runpy
import tempfile
import unittest
import xml.etree.ElementTree as ET

REPO = pathlib.Path(__file__).resolve().parent.parent
PATCH_MOD = runpy.run_path(str(REPO / "scripts/rom-patch-source.py"))


class ZhCnTranslationsAndOverlayTest(unittest.TestCase):
    def test_all_zh_cn_supplement_xmls_valid_and_unique(self):
        root = REPO / "gsi/translations/zh-rCN"
        xmls = sorted(root.rglob("infinity_zh_cn_extra.xml"))
        self.assertGreaterEqual(len(xmls), 20, "Expected >=20 unified Infinity-X 3.12 zh-rCN supplement XMLs")
        total = 0
        raw_amp = re.compile(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)")
        for path in xmls:
            text = path.read_text(encoding="utf-8")
            self.assertIsNone(raw_amp.search(text), f"Unescaped '&' in {path}")
            tree = ET.fromstring(text)
            seen = set()
            for el in tree:
                self.assertIn(el.tag, ("string", "string-array", "plurals"))
                name = el.attrib.get("name")
                self.assertTrue(name, f"Missing name attribute in {path}")
                key = (el.tag, name)
                self.assertNotIn(key, seen, f"Duplicate key {key} in {path}")
                seen.add(key)
                total += 1
        self.assertGreaterEqual(total, 8500)

    def test_patch_infinity_zh_cn_translations_filters_upstream_and_missing_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = pathlib.Path(tmp)
            val_dir = src / "packages/apps/Launcher3/res/values"
            zh_dir = src / "packages/apps/Launcher3/res/values-zh-rCN"
            val_dir.mkdir(parents=True)
            zh_dir.mkdir(parents=True)
            # Default English strings define only 2 keys: qsb_search_hint and weather_settings_title
            (val_dir / "infinity_strings.xml").write_text(
                '<?xml version="1.0" encoding="utf-8"?>\n'
                '<resources>\n'
                '    <string name="qsb_search_hint">Search</string>\n'
                '    <string name="weather_settings_title">Weather settings</string>\n'
                '</resources>\n',
                encoding="utf-8",
            )
            # Upstream zh-rCN already defines qsb_search_hint
            (zh_dir / "infinity_strings.xml").write_text(
                '<?xml version="1.0" encoding="utf-8"?>\n'
                '<resources>\n'
                '    <string name="qsb_search_hint">已有上游翻译</string>\n'
                '</resources>\n',
                encoding="utf-8",
            )
            merged = PATCH_MOD["patch_infinity_zh_cn_translations"](src)
            self.assertEqual(merged, 1)
            extra = ET.parse(zh_dir / "infinity_zh_cn_extra.xml").getroot()
            names = {el.attrib["name"] for el in extra}
            # Existing upstream key skipped; keys absent from default values/ skipped; missing default key merged
            self.assertEqual(names, {"weather_settings_title"})

    def test_gt5_auto_brightness_overlay_monotonic_and_balanced(self):
        cfg = REPO / "gsi/overlay/gt5/frameworks/base/core/res/res/values/config.xml"
        root = ET.parse(cfg).getroot()
        bools = {el.attrib["name"]: el.text.strip() for el in root.findall("bool")}
        self.assertEqual(bools.get("config_automatic_brightness_available"), "true")
        levels = [int(i.text.strip()) for i in root.find("integer-array[@name='config_autoBrightnessLevels']")]
        nits = [float(i.text.strip()) for i in root.find("array[@name='config_autoBrightnessDisplayValuesNits']")]
        self.assertEqual(len(nits), len(levels) + 1)
        self.assertEqual(levels, sorted(set(levels)))
        self.assertEqual(nits, sorted(nits))


if __name__ == "__main__":
    unittest.main()
