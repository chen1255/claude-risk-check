# -*- coding: utf-8 -*-
"""数据源与双端一致性测试。

验证：
  · questions.json 结构合法（复用 scripts/build_questions.py 的 validate）
  · questions.js 与 questions.json 完全一致（无漂移）
  · index.html 不再内嵌数据，而是外链 questions.js
  · questions.json 自身可被严格解析（utf-8 / 无 BOM / JSON 合法）
"""

import importlib.util
import json
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JSON_PATH = os.path.join(ROOT, "questions.json")
JS_PATH = os.path.join(ROOT, "questions.js")
HTML_PATH = os.path.join(ROOT, "index.html")


def load_build_module():
    spec = importlib.util.spec_from_file_location(
        "build_questions", os.path.join(ROOT, "scripts", "build_questions.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = load_build_module()
        cls.pack = cls.build.load_pack()

    def test_json_is_plain_utf8_without_bom(self):
        raw = open(JSON_PATH, "rb").read()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), "questions.json 不应带 BOM")
        raw.decode("utf-8")  # 必须能按 utf-8 解码
        json.loads(raw.decode("utf-8"))  # 必须合法

    def test_schema_valid(self):
        self.build.validate(self.pack)  # 不抛异常即通过

    def test_weight_sum_is_100(self):
        self.assertEqual(sum(d["weight"] for d in self.pack["dimensions"]), 100)

    def test_questions_js_matches_source(self):
        expected = self.build.render(self.pack)
        with open(JS_PATH, "r", encoding="utf-8") as f:
            actual = f.read()
        self.assertEqual(actual, expected,
                         "questions.js 与 questions.json 不一致，请运行 scripts/build_questions.py")

    def test_questions_js_is_loadable_shape(self):
        with open(JS_PATH, "r", encoding="utf-8") as f:
            text = f.read()
        self.assertTrue(text.lstrip().startswith("/*"), "应有生成头注释")
        self.assertIn("window.RISK_PACK = ", text)
        self.assertTrue(text.rstrip().endswith(";"))

    def test_index_html_externalises_data(self):
        html = open(HTML_PATH, "r", encoding="utf-8").read()
        self.assertIn('src="questions.js"', html, "index.html 应外链 questions.js")
        # 不应再内嵌 DIMENSIONS / QUESTIONS 数据数组
        self.assertNotIn("const DIMENSIONS = [", html)
        self.assertNotIn("const QUESTIONS = [", html)
        self.assertNotIn("家庭 / 住宅 IP（宽带原生 IP）", html, "选项文案不应再硬编码在 HTML 中")

    def test_levels_cover_full_range(self):
        maxes = [lv["max"] for lv in self.pack["levels"]]
        self.assertEqual(maxes, sorted(maxes))
        self.assertGreaterEqual(maxes[-1], 101)


if __name__ == "__main__":
    unittest.main()
