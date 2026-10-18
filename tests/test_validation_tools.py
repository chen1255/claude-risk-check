# -*- coding: utf-8 -*-
"""验证工具测试：scripts/power_auc.py 与 scripts/score_from_dataset.py。

验证：
  · 样本量核算满足目标功效、对参数单调、非法输入报错
  · 打分管线确实复用 claude_risk_check（不重写评分逻辑）
  · CSV 两种答案格式（answers JSON 列 / q1..q16 列）均可解析
  · 越界与不完整样本被正确识别
  · AUC 与 Bootstrap CI 在全分离数据上给出 1.0
"""

import csv
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import claude_risk_check as model  # noqa: E402


def _load(script_name, module_name):
    path = os.path.join(ROOT, "scripts", script_name)
    spec = importlib.util.spec_from_file_location(module_name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


power = _load("power_auc.py", "power_auc_mod")
scorer = _load("score_from_dataset.py", "score_from_dataset_mod")


def all_min():
    return {q["id"]: 0 for q in model.QUESTIONS}


def all_max():
    return {q["id"]: len(q["options"]) - 1 for q in model.QUESTIONS}


class TestPowerAuc(unittest.TestCase):
    def test_rejects_auc_not_above_half(self):
        for bad in (0.5, 0.4, 1.0, 1.2):
            with self.assertRaises(ValueError):
                power.required_n(bad)

    def test_rejects_nonpositive_ratio(self):
        with self.assertRaises(ValueError):
            power.required_n(0.65, ratio=0.0)

    def test_higher_auc_needs_fewer_samples(self):
        ns = [power.required_n(a)[0] for a in (0.55, 0.60, 0.65, 0.70, 0.75, 0.80)]
        self.assertEqual(ns, sorted(ns, reverse=True), "AUC 越高所需样本应越少")

    def test_stronger_power_needs_more_samples(self):
        n80 = power.required_n(0.65, power=0.80)[0]
        n90 = power.required_n(0.65, power=0.90)[0]
        self.assertLess(n80, n90)

    def test_achieved_power_meets_target(self):
        for auc in (0.60, 0.65, 0.70):
            for target in (0.80, 0.90):
                n_pos, n_neg, pw = power.required_n(auc, power=target)
                self.assertGreaterEqual(round(pw, 6), target - 1e-9,
                                        "auc=%s power=%s 实际功效不足" % (auc, target))
                self.assertGreater(n_pos, 0)
                self.assertGreater(n_neg, 0)

    def test_one_less_sample_undershoots(self):
        """确认求得的是“最小”满足功效的样本量，而非过估。

        注意：比较必须同比例缩小两组，混用 (n-1, n) 会因为阴性组偏多而虚高功效。
        """
        n_pos, _, _ = power.required_n(0.65, power=0.80, ratio=1.0)
        self.assertLess(power.achieved_power(0.65, n_pos - 1, n_pos - 1), 0.80)

    def test_ratio_scales_negative_group(self):
        n_pos, n_neg, _ = power.required_n(0.70, ratio=2.0)
        self.assertAlmostEqual(n_neg, n_pos * 2, delta=1)

    def test_ci_half_width_shrinks_with_n(self):
        self.assertGreater(power.ci_half_width(0.65, 50, 50),
                           power.ci_half_width(0.65, 500, 500))


class TestAnswerParsing(unittest.TestCase):
    def test_answers_json_column(self):
        row = {"answers": json.dumps({"q1": 2, "q2": 1})}
        ans, err = scorer.parse_answers(row, ["answers"])
        self.assertIsNone(err)
        self.assertEqual(ans, {"q1": 2, "q2": 1})

    def test_q_columns(self):
        headers = ["q1", "q2", "q7"]
        row = {"q1": "3", "q2": "1", "q7": ""}
        ans, err = scorer.parse_answers(row, headers)
        self.assertIsNone(err)
        self.assertEqual(ans, {"q1": 3, "q2": 1})  # 空值被忽略

    def test_invalid_json_column(self):
        ans, err = scorer.parse_answers({"answers": "{oops"}, ["answers"])
        self.assertIsNone(ans)
        self.assertIn("JSON", err)

    def test_no_answer_source(self):
        ans, err = scorer.parse_answers({"sample_id": "x"}, ["sample_id"])
        self.assertIsNone(ans)
        self.assertIsNotNone(err)

    def test_non_integer_answer_rejected(self):
        ans, err = scorer.parse_answers({"answers": '{"q1": "abc"}'}, ["answers"])
        self.assertIsNone(ans)

    def test_validate_out_of_range(self):
        clean, problems = scorer.validate_answers({"q1": 99, "q2": 0})
        self.assertNotIn("q1", clean)
        self.assertTrue(any(p.startswith("q1") for p in problems))
        self.assertIn("q2", clean)

    def test_validate_incomplete(self):
        clean, problems = scorer.validate_answers({"q1": 0})
        self.assertEqual(len(problems), len(model.QUESTIONS) - 1)


class TestLabelParsing(unittest.TestCase):
    def test_labels(self):
        for raw in ("banned", "BANNED", "封号", "已封", "1"):
            self.assertEqual(scorer.parse_label(raw), 1)
        for raw in ("survived", "ok", "未封", "0"):
            self.assertEqual(scorer.parse_label(raw), 0)
        for raw in ("", None, "maybe", "??"):
            self.assertIsNone(scorer.parse_label(raw))


class TestScoring(unittest.TestCase):
    def test_scoring_uses_model(self):
        """管线结果必须与 claude_risk_check.compute 完全一致。"""
        ans = all_max()
        score, _ = model.compute(ans)
        clean, problems = scorer.validate_answers(ans)
        self.assertEqual(problems, [])
        got, _rows = model.compute(clean)
        self.assertEqual(got, score)
        self.assertEqual(model.level_of(got)["id"], "high")

    def test_auc_perfect_separation(self):
        scores = [100, 95, 90, 80, 0, 5, 10, 20]
        labels = [1, 1, 1, 1, 0, 0, 0, 0]
        self.assertEqual(scorer.auc_score(scores, labels), 1.0)

    def test_auc_reversed_is_zero(self):
        scores = [0, 5, 10, 20, 100, 95, 90, 80]
        labels = [1, 1, 1, 1, 0, 0, 0, 0]
        self.assertEqual(scorer.auc_score(scores, labels), 0.0)

    def test_auc_ties_are_half(self):
        scores = [50, 50, 50, 50]
        labels = [1, 1, 0, 0]
        self.assertEqual(scorer.auc_score(scores, labels), 0.5)

    def test_auc_single_class_is_none(self):
        self.assertIsNone(scorer.auc_score([1, 2, 3], [1, 1, 1]))

    def test_bootstrap_ci_contains_point(self):
        scores = [100, 95, 90, 80, 70, 60, 0, 5, 10, 20, 30, 40]
        labels = [1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0]
        a = scorer.auc_score(scores, labels)
        ci = scorer.bootstrap_ci(scores, labels, n_boot=300)
        self.assertIsNotNone(ci)
        self.assertLessEqual(ci[0], a)
        self.assertGreaterEqual(ci[1], a)


class TestEndToEnd(unittest.TestCase):
    def _write_csv(self, rows, headers=None):
        path = tempfile.mktemp(suffix=".csv")
        qids = [q["id"] for q in model.QUESTIONS]
        headers = headers or (["sample_id", "label"] + qids)
        with open(path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=headers)
            w.writeheader()
            for r in rows:
                w.writerow(r)
        return path

    def test_cli_full_pipeline(self):
        banned = all_max()
        survived = all_min()
        rows = []
        for i in range(4):
            r = {"sample_id": "b%d" % i, "label": "banned"}
            r.update({k: str(v) for k, v in banned.items()})
            rows.append(r)
        for i in range(4):
            r = {"sample_id": "s%d" % i, "label": "survived"}
            r.update({k: str(v) for k, v in survived.items()})
            rows.append(r)
        path = self._write_csv(rows)
        out = tempfile.mktemp(suffix="_scored.csv")
        try:
            proc = subprocess.run(
                [sys.executable, os.path.join(ROOT, "scripts", "score_from_dataset.py"),
                 path, "--out", out, "--auc", "--json"],
                capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            summary = json.loads(proc.stdout)
            self.assertEqual(summary["scored"], 8)
            self.assertEqual(summary["skipped"], 0)
            self.assertEqual(summary["banned"]["mean"], 100.0)
            self.assertEqual(summary["survived"]["mean"], 0.0)
            self.assertEqual(summary["auc"], 1.0)
            self.assertEqual(summary["auc_ci95"], [1.0, 1.0])
            self.assertTrue(os.path.exists(out))
            with open(out, encoding="utf-8") as f:
                self.assertEqual(len(list(csv.DictReader(f))), 8)
        finally:
            for p in (path, out):
                if os.path.exists(p):
                    os.remove(p)

    def test_cli_skips_incomplete_and_bad_index(self):
        good = all_max()
        rows = [
            dict({"sample_id": "ok", "label": "banned"},
                 **{k: str(v) for k, v in good.items()}),
            {"sample_id": "bad", "label": "banned", "q1": "99"},  # 越界 + 其余缺失
        ]
        path = self._write_csv(rows)
        try:
            proc = subprocess.run(
                [sys.executable, os.path.join(ROOT, "scripts", "score_from_dataset.py"),
                 path, "--json"],
                capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            summary = json.loads(proc.stdout)
            self.assertEqual(summary["scored"], 1)
            self.assertEqual(summary["skipped"], 1)
        finally:
            os.remove(path)

    def test_cli_allow_partial(self):
        rows = [{"sample_id": "p", "label": "survived", "q1": "0", "q2": "0"}]
        path = self._write_csv(rows, headers=["sample_id", "label", "q1", "q2"])
        try:
            proc = subprocess.run(
                [sys.executable, os.path.join(ROOT, "scripts", "score_from_dataset.py"),
                 path, "--allow-partial", "--json"],
                capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            summary = json.loads(proc.stdout)
            self.assertEqual(summary["scored"], 1)
            self.assertEqual(summary["skipped"], 0)
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
