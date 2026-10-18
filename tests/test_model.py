# -*- coding: utf-8 -*-
"""评分模型测试：与网页版公式一致、阈值边界、取整一致、JSON 合法性、非法输入。

关键点：Python 的 round() 是“银行家舍入”，JS 的 Math.round() 是“四舍五入”，
在 x.5 上结果不同。CLI 已改用 floor(x+0.5) 与 JS 对齐，这里给出断言。
"""

import json
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import claude_risk_check as m  # noqa: E402


def all_min_answers():
    return {q["id"]: 0 for q in m.QUESTIONS}


def all_max_answers():
    return {q["id"]: len(q["options"]) - 1 for q in m.QUESTIONS}


class TestModel(unittest.TestCase):
    def test_all_min_is_zero_low(self):
        score, rows = m.compute(all_min_answers())
        self.assertEqual(score, 0)
        self.assertEqual(m.level_of(score)["id"], "low")
        self.assertEqual(m.advice_list(all_min_answers()), [])

    def test_all_max_is_high(self):
        score, _ = m.compute(all_max_answers())
        self.assertGreaterEqual(score, 65)
        self.assertEqual(m.level_of(score)["id"], "high")
        # 每题最高风险选项中有建议文案的条数，应被完整列出
        expected = sum(1 for q in m.QUESTIONS if q["options"][-1][2])
        self.assertEqual(len(m.advice_list(all_max_answers())), expected)

    def test_score_range(self):
        for ans in (all_min_answers(), all_max_answers()):
            score, _ = m.compute(ans)
            self.assertTrue(0 <= score <= 100)

    def test_threshold_boundaries(self):
        # 等级阈值：<18 low；<40 mid；<65 elevated；>=65 high
        cases = {0: "low", 17: "low", 18: "mid", 39: "mid",
                 40: "elevated", 64: "elevated", 65: "high", 100: "high"}
        for score, expect in cases.items():
            self.assertEqual(m.level_of(score)["id"], expect, f"score={score}")

    def test_round_half_up_matches_js(self):
        # JS Math.round: 0.5→1, 1.5→2, 2.5→3, 17.5→18；Python round 会给出 0/2/2/18
        self.assertEqual(m._round_half_up(0.5), 1)
        self.assertEqual(m._round_half_up(1.5), 2)
        self.assertEqual(m._round_half_up(2.5), 3)
        self.assertEqual(m._round_half_up(17.5), 18)
        self.assertNotEqual(m._round_half_up(2.5), round(2.5))  # 与银行家舍入不同

    def test_dimension_contributions_sum_to_total(self):
        raw_total, rows = m.compute_raw(all_max_answers())
        self.assertAlmostEqual(sum(r["contrib"] for r in rows), raw_total, places=9)

    def test_advice_sorted_desc(self):
        items = m.advice_list(all_max_answers())
        scores = [it["score"] for it in items]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_result_is_json_serialisable(self):
        with mock.patch("builtins.print"):
            result = m.print_report(all_min_answers(), color=False)
            m.print_report(all_max_answers(), color=False)
        text = json.dumps(result, ensure_ascii=False)
        self.assertIn('"score"', text)
        self.assertIn('"dimensions"', text)

    def test_invalid_input_is_rejected_then_accepted(self):
        q0 = m.QUESTIONS[0]
        saved = m.QUESTIONS
        try:
            m.QUESTIONS = [q0]
            # 非法字符串 → 越界数字 → 合法数字
            with mock.patch("builtins.input", side_effect=["abc", "99", "1"]):
                ans = m.ask_quiz()
            self.assertEqual(ans, {q0["id"]: 0})
            # 输入 q 退出
            with mock.patch("builtins.input", side_effect=["q"]):
                with self.assertRaises(SystemExit):
                    m.ask_quiz()
        finally:
            m.QUESTIONS = saved

    def test_preset_default_used_on_enter(self):
        q0 = m.QUESTIONS[0]
        saved = m.QUESTIONS
        try:
            m.QUESTIONS = [q0]
            with mock.patch("builtins.input", side_effect=[""]):
                ans = m.ask_quiz(presets={q0["id"]: 2})
            self.assertEqual(ans[q0["id"]], 2)
        finally:
            m.QUESTIONS = saved


if __name__ == "__main__":
    unittest.main()
