# -*- coding: utf-8 -*-
"""环境探测分类逻辑测试（纯函数，无网络依赖）。"""

import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import probe  # noqa: E402


class TestClassifyIpType(unittest.TestCase):
    def test_datacenter(self):
        for org in ("Amazon.com, Inc.", "DigitalOcean, LLC", "Google Cloud",
                    "Hetzner Online GmbH", "Alibaba (US) Technology Co."):
            self.assertEqual(probe.classify_ip_type(org), 2, org)

    def test_proxy(self):
        for org in ("Mullvad VPN AB", "NordVPN", "Tor Exit Node"):
            self.assertEqual(probe.classify_ip_type(org), 3, org)

    def test_residential(self):
        for org in ("Comcast Cable Communications", "Verizon Business"):
            self.assertEqual(probe.classify_ip_type(org), 0, org)

    def test_unknown(self):
        self.assertEqual(probe.classify_ip_type(""), 1)
        self.assertEqual(probe.classify_ip_type(None), 1)


class TestClassifyRegion(unittest.TestCase):
    def test_supported(self):
        self.assertEqual(probe.classify_region("US"), 0)
        self.assertEqual(probe.classify_region("jp"), 0)

    def test_unsupported(self):
        self.assertEqual(probe.classify_region("CN"), 2)
        self.assertEqual(probe.classify_region("RU"), 2)

    def test_unknown(self):
        self.assertEqual(probe.classify_region(""), 1)


class TestClassifyEnv(unittest.TestCase):
    def test_contradiction_cn_lang_utc8_overseas(self):
        self.assertEqual(probe.classify_env_consistency("Asia/Shanghai", "zh-CN", "US"), 2)
        self.assertEqual(probe.classify_env_consistency("China Standard Time", "zh-CN", "JP"), 2)

    def test_english_ok(self):
        self.assertEqual(probe.classify_env_consistency("America/New_York", "en-US", "US"), 0)

    def test_partial(self):
        self.assertEqual(probe.classify_env_consistency("Asia/Tokyo", "ja-JP", "JP"), 1)

    def test_insufficient_info(self):
        self.assertIsNone(probe.classify_env_consistency("Asia/Shanghai", "zh-CN", "CN"))
        self.assertIsNone(probe.classify_env_consistency("", "en-US", "US"))


class TestDetectAnswers(unittest.TestCase):
    def test_offline_degrades_gracefully(self):
        with mock.patch.object(probe, "fetch_ip_info", return_value={}):
            presets, notes = probe.detect_answers(timeout=0.1)
        self.assertIsInstance(presets, dict)
        self.assertTrue(any("未能获取出口 IP" in n for n in notes))

    def test_with_info_suggests_q1_q3(self):
        info = {"country": "US", "org": "DigitalOcean, LLC"}
        with mock.patch.object(probe, "fetch_ip_info", return_value=info):
            presets, _ = probe.detect_answers(timeout=0.1)
        self.assertEqual(presets.get("q1"), 2)  # 机房 IP
        self.assertEqual(presets.get("q3"), 0)  # 支持区


if __name__ == "__main__":
    unittest.main()
