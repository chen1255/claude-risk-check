# -*- coding: utf-8 -*-
"""分析工具测试：analysis/auc.py 与 analysis/calibration.py。

验证：
  · DeLong AUC/SE 在全分离、并列、部分区分三类数据上的取值
  · 阈值 P/R 的混淆矩阵、分数段分箱边界
  · Spearman ρ 与单调方向
  · 维度单独 AUC、置换重要性、VIF（含奇异退化）
  · 亚组划分正确
  · 校准：Brier 边界、Murphy 分解恒等式、reliability 分箱
  · 分析脚本确实复用 claude_risk_check.compute（不重写评分逻辑）
  · 两个 CLI 端到端可跑通
"""

import csv
import json
import os
import random
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "scripts"), os.path.join(ROOT, "analysis")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import claude_risk_check as model      # noqa: E402
import score_from_dataset as sfd       # noqa: E402
import auc as aucmod                   # noqa: E402
import calibration as calmod           # noqa: E402

DIMS = [d["id"] for d in model.DIMENSIONS]


def all_min():
    return {q["id"]: 0 for q in model.QUESTIONS}


def all_max():
    return {q["id"]: len(q["options"]) - 1 for q in model.QUESTIONS}


def _record(sid, label, score=None, risks=None, q3=0, q7=0):
    return {
        "sample_id": sid, "label": label,
        "score": score if score is not None else 0,
        "levelId": "low", "level": "低风险", "answered": len(model.QUESTIONS),
        "answers": {"q3": q3, "q7": q7},
        "dim_risks": dict(risks) if risks else {d: 0.0 for d in DIMS},
    }


def _write_csv(rows, headers=None):
    path = tempfile.mktemp(suffix=".csv")
    qids = [q["id"] for q in model.QUESTIONS]
    headers = headers or (["sample_id", "label"] + qids)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return path


class TestDelong(unittest.TestCase):
    def test_perfect_separation(self):
        scores = [10, 20, 30, 40]
        labels = [0, 0, 1, 1]
        auc, se = aucmod.delong_auc_se(scores, labels)
        self.assertEqual(auc, 1.0)
        self.assertEqual(se, 0.0)  # 完全分离 → 方差为 0

    def test_all_ties_is_half(self):
        auc, se = aucmod.delong_auc_se([50, 50, 50, 50], [1, 1, 0, 0])
        self.assertEqual(auc, 0.5)
        self.assertEqual(se, 0.0)

    def test_partial_discrimination(self):
        # pos=[20,40,60], neg=[10,30,50] → AUC=2/3，DeLong SE=sqrt(2/27)
        scores = [10, 20, 30, 40, 50, 60]
        labels = [0, 1, 0, 1, 0, 1]
        auc, se = aucmod.delong_auc_se(scores, labels)
        self.assertAlmostEqual(auc, 2.0 / 3.0, places=9)
        self.assertAlmostEqual(se, (2.0 / 27.0) ** 0.5, places=9)

    def test_z_test_against_half(self):
        scores = [10, 20, 30, 40, 50, 60]
        labels = [0, 1, 0, 1, 0, 1]
        auc, se = aucmod.delong_auc_se(scores, labels)
        res = aucmod.auc_z_vs_half(auc, se)
        self.assertAlmostEqual(res["z"], (2.0 / 3.0 - 0.5) / (2.0 / 27.0) ** 0.5, places=6)
        self.assertTrue(0.0 <= res["p"] <= 1.0)

    def test_degenerate_se_gives_conservative_p(self):
        self.assertEqual(aucmod.auc_z_vs_half(1.0, 0.0)["p"], 0.0)
        self.assertEqual(aucmod.auc_z_vs_half(0.5, 0.0)["p"], 1.0)

    def test_single_class_returns_none(self):
        self.assertEqual(aucmod.delong_auc_se([1, 2, 3], [1, 1, 1]), (None, None))


class TestThresholds(unittest.TestCase):
    def test_threshold_metrics(self):
        scores = [10, 20, 50, 70]
        labels = [0, 0, 1, 1]
        m = aucmod.threshold_metrics(scores, labels, 40)
        self.assertEqual((m["tp"], m["fp"], m["fn"], m["tn"]), (2, 0, 0, 2))
        self.assertEqual(m["precision"], 1.0)
        self.assertEqual(m["recall"], 1.0)
        self.assertEqual(m["specificity"], 1.0)

        m2 = aucmod.threshold_metrics(scores, labels, 60)
        self.assertEqual((m2["tp"], m2["fn"]), (1, 1))
        self.assertEqual(m2["recall"], 0.5)

    def test_threshold_zero_predicts_all_positive(self):
        m = aucmod.threshold_metrics([10, 20, 50, 70], [0, 0, 1, 1], 0)
        self.assertEqual((m["tp"], m["fp"], m["fn"], m["tn"]), (2, 2, 0, 0))
        self.assertEqual(m["precision"], 0.5)
        self.assertEqual(m["specificity"], 0.0)

    def test_level_thresholds_match_model(self):
        self.assertEqual(aucmod.LEVEL_THRESHOLDS, [18, 40, 65])


class TestSegments(unittest.TestCase):
    def test_segment_boundaries(self):
        scores = [0, 17, 18, 39, 40, 64, 65, 100]
        labels = [1] * 8
        segs = aucmod.segment_stats(scores, labels)
        self.assertEqual([s["levelId"] for s in segs], ["low", "mid", "elevated", "high"])
        self.assertEqual([s["n"] for s in segs], [2, 2, 2, 2])
        self.assertEqual(segs[0]["hi"], 17)
        self.assertEqual(segs[3]["hi"], 100)

    def test_empty_segment(self):
        segs = aucmod.segment_stats([10, 10], [1, 0])
        self.assertEqual([s["n"] for s in segs], [2, 0, 0, 0])
        self.assertIsNone(segs[1]["ban_rate"])


class TestSpearman(unittest.TestCase):
    def test_monotone_increasing(self):
        self.assertAlmostEqual(aucmod.spearman([1, 2, 3, 4], [10, 20, 30, 40]), 1.0, places=9)

    def test_monotone_decreasing(self):
        self.assertAlmostEqual(aucmod.spearman([1, 2, 3, 4], [40, 30, 20, 10]), -1.0, places=9)

    def test_constant_is_none(self):
        self.assertIsNone(aucmod.spearman([1, 2, 3, 4], [5, 5, 5, 5]))

    def test_test_returns_p_in_range(self):
        res = aucmod.spearman_test([1, 2, 3, 4, 5, 6], [0, 0, 0, 1, 1, 1])
        self.assertGreater(res["rho"], 0)
        self.assertTrue(0.0 <= res["p"] <= 1.0)


class TestDimensionImportance(unittest.TestCase):
    def _records(self):
        recs = []
        for i in range(8):
            label = 1 if i < 4 else 0
            risks = {d: 0.0 for d in DIMS}
            risks["network"] = 1.0 if label == 1 else 0.0
            recs.append(_record("r%d" % i, label, score=100 if label else 0, risks=risks))
        return recs

    def test_dimension_aucs(self):
        dims = aucmod.dimension_aucs(self._records())
        self.assertEqual(dims["network"]["auc"], 1.0)
        self.assertEqual(dims["behavior"]["auc"], 0.5)  # 常数维度 → 全并列

    def test_permutation_importance_identifies_driver(self):
        base, imp = aucmod.permutation_importance(self._records(), n_perm=50)
        self.assertEqual(base, 1.0)
        self.assertGreater(imp["network"]["auc_drop_mean"], 0.0)
        # 其余维度为常数，打乱后无变化 → 重要性应为 0
        self.assertEqual(imp["behavior"]["auc_drop_mean"], 0.0)

    def test_vif_singular_when_constant_dimension(self):
        vif, note = aucmod.vif_table(self._records())
        self.assertIsNone(vif)
        self.assertIsNotNone(note)

    def test_vif_on_independent_dimensions(self):
        rng = random.Random(7)
        recs = [_record("r%d" % i, i % 2,
                        risks={d: rng.random() for d in DIMS}) for i in range(60)]
        vif, note = aucmod.vif_table(recs)
        self.assertIsNone(note)
        self.assertEqual(set(vif), set(DIMS))
        for v in vif.values():
            self.assertGreaterEqual(v, 1.0 - 1e-9)


class TestSubgroups(unittest.TestCase):
    def _records(self):
        return [
            _record("a", 1, score=90, q3=2, q7=3),
            _record("b", 0, score=10, q3=0, q7=0),
            _record("c", 1, score=80, q3=2, q7=2),
            _record("d", 1, score=20, q3=0, q7=1),
        ]

    def test_group_sizes(self):
        g = aucmod.subgroup_analysis(self._records())
        self.assertEqual(g["newAccount"]["n"], 2)   # q7∈{2,3}
        self.assertEqual(g["oldAccount"]["n"], 2)   # q7∈{0,1}
        self.assertEqual(g["supportedRegion"]["n"], 2)  # q3==0
        self.assertEqual(g["otherRegion"]["n"], 2)      # q3∈{1,2}

    def test_single_class_subgroup_auc_is_none(self):
        g = aucmod.subgroup_analysis(self._records())
        self.assertIsNone(g["newAccount"]["auc"])       # 全是已封
        self.assertEqual(g["oldAccount"]["auc"], 1.0)


class TestAnalyze(unittest.TestCase):
    def test_single_class_reports_error(self):
        recs = [_record("a", 1, score=90), _record("b", 1, score=80)]
        res = aucmod.analyze(recs, {"csv": "x"}, n_boot=10, n_perm=5)
        self.assertIn("error", res)

    def test_full_analysis_keys(self):
        recs = [
            _record("a", 1, score=90, q3=2, q7=3, risks={d: 0.0 for d in DIMS}),
            _record("b", 0, score=10, q3=0, q7=0, risks={d: 0.0 for d in DIMS}),
        ]
        recs[0]["dim_risks"]["network"] = 1.0
        res = aucmod.analyze(recs, {"csv": "x"}, n_boot=20, n_perm=5)
        for key in ("discrimination", "thresholds", "segments", "monotonicity",
                    "dimensions", "permutationImportance", "vif", "subgroups"):
            self.assertIn(key, res)
        # JSON 可序列化（不含 inf/nan）
        json.dumps(res)


class TestCalibration(unittest.TestCase):
    def test_brier_constant_prediction(self):
        # 预测一律 0.5（分数 50），实际全为 1 → (0.5-1)^2 = 0.25
        self.assertAlmostEqual(calmod.brier_score([50, 50, 50, 50], [1, 1, 1, 1]), 0.25, places=9)

    def test_brier_perfect(self):
        self.assertAlmostEqual(calmod.brier_score([100, 0], [1, 0]), 0.0, places=9)

    def test_baseline_brier(self):
        # 封号率 0.5 的常数预测 → 0.25
        self.assertAlmostEqual(calmod.baseline_brier([1, 0, 1, 0]), 0.25, places=9)

    def test_skill_score(self):
        self.assertAlmostEqual(calmod.brier_skill_score(0.1, 0.2), 0.5, places=9)
        self.assertEqual(calmod.brier_skill_score(0.2, 0.2), 0.0)
        self.assertLess(calmod.brier_skill_score(0.3, 0.2), 0.0)

    def test_reliability_bins(self):
        bins = calmod.reliability_bins([10, 20, 50, 70], [0, 0, 1, 1])
        self.assertEqual([b["n"] for b in bins], [1, 1, 1, 1])
        self.assertAlmostEqual(bins[0]["mean_predicted"], 0.10, places=9)
        self.assertAlmostEqual(bins[2]["observed"], 1.0, places=9)
        self.assertAlmostEqual(bins[0]["gap"], 0.10, places=9)

    def test_decomposition_identity(self):
        scores = [10, 20, 50, 70]
        labels = [0, 0, 1, 1]
        bins = calmod.reliability_bins(scores, labels)
        dec = calmod.decompose(bins, labels)
        bs = calmod.brier_score(scores, labels)
        self.assertAlmostEqual(
            bs, dec["reliability"] - dec["resolution"] + dec["uncertainty"], places=9)

    def test_calibration_single_class_error(self):
        res = calmod.analyze([_record("a", 1, score=90)], {"csv": "x"})
        self.assertIn("error", res)


class TestReuseModelCompute(unittest.TestCase):
    def test_load_dataset_scores_equal_model(self):
        ans = all_max()
        expected, _ = model.compute(ans)
        row = {"sample_id": "x", "label": "banned"}
        row.update({k: str(v) for k, v in ans.items()})
        path = _write_csv([row])
        try:
            recs, meta = sfd.load_dataset(path)
            self.assertEqual(recs[0]["score"], expected)
            self.assertEqual(meta["scored"], 1)
        finally:
            os.remove(path)


class TestCli(unittest.TestCase):
    def _sep_csv(self):
        rows = []
        for i in range(4):
            r = {"sample_id": "b%d" % i, "label": "banned"}
            r.update({k: str(v) for k, v in all_max().items()})
            rows.append(r)
        for i in range(4):
            r = {"sample_id": "s%d" % i, "label": "survived"}
            r.update({k: str(v) for k, v in all_min().items()})
            rows.append(r)
        return _write_csv(rows)

    def test_auc_cli(self):
        path = self._sep_csv()
        try:
            proc = subprocess.run(
                [sys.executable, os.path.join(ROOT, "analysis", "auc.py"),
                 path, "--json", "--bootstrap", "200", "--permutations", "20"],
                capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            res = json.loads(proc.stdout)
            self.assertEqual(res["nBanned"], 4)
            self.assertEqual(res["nSurvived"], 4)
            self.assertEqual(res["discrimination"]["auc"], 1.0)
        finally:
            os.remove(path)

    def test_calibration_cli(self):
        path = self._sep_csv()
        try:
            proc = subprocess.run(
                [sys.executable, os.path.join(ROOT, "analysis", "calibration.py"),
                 path, "--json"],
                capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            res = json.loads(proc.stdout)
            self.assertIn("brier", res)
            self.assertIsNotNone(res["brierSkillScore"])
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
