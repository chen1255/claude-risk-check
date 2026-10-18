#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auc.py — 验证计划（docs/validation-plan.md §5）的主分析

在「真实封号案例」数据集上，对 claude-risk-check 的 0–100 分做区分度与阈值分析：

  1. ROC-AUC + Bootstrap 95% CI（复用 scripts/score_from_dataset 的实现）
  2. DeLong 方差估计 → AUC 是否显著 > 0.5（拒绝 H0）
  3. 阈值 18 / 40 / 65 处的 Precision / Recall / 特异度
  4. 四个等级的分数段实际封号率
  5. 单调性：分数 vs 标签的 Spearman ρ
  6. 维度重要性：各维度单独 AUC + 置换重要性
  7. 共线性：维度相关矩阵求逆得到 VIF
  8. 亚组：新号 vs 老号、支持区 vs 其他区

铁律：分数一律来自 claude_risk_check.compute（经由 score_from_dataset.load_dataset），
绝不重写评分逻辑——否则验证的就不是被测工具本身。

用法:
    python analysis/auc.py data/pilot.csv
    python analysis/auc.py data/pilot.csv --json --bootstrap 2000 --out result.json
"""

import argparse
import json
import math
import os
import random
import sys
from statistics import NormalDist

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_ROOT, os.path.join(_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import claude_risk_check as model            # noqa: E402
import score_from_dataset as sfd             # noqa: E402
import power_auc as power                    # noqa: E402

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

_NORM = NormalDist()

# 阈值与分段直接从 questions.json 的 levels 派生，避免与工具模型脱节（单一来源）
LEVEL_THRESHOLDS = [lv["max"] for lv in model.LEVELS[:-1]]          # [18, 40, 65]
SEGMENTS = []                                                       # [(lo, hi, level)]
_lo = 0
for _lv in model.LEVELS:
    SEGMENTS.append((_lo, _lv["max"], _lv))
    _lo = _lv["max"]


# ---------- 基础统计 ----------
def _safe_div(a, b):
    return None if not b else a / float(b)


def _sample_var(values):
    n = len(values)
    if n < 2:
        return 0.0
    mu = sum(values) / n
    return sum((v - mu) ** 2 for v in values) / (n - 1)


def delong_auc_se(scores, labels):
    """DeLong 方差估计 → (AUC, SE)。缺类返回 (None, None)。

    用「放置值（placement value）」形式，对并列（tie）给 0.5，比 Hanley–McNeil
    近似更稳健；两组各 ≥2 时用 DeLong，否则退化为 Hanley–McNeil。
    """
    pos = [scores[i] for i, l in enumerate(labels) if l == 1]
    neg = [scores[i] for i, l in enumerate(labels) if l == 0]
    m, n = len(pos), len(neg)
    if m == 0 or n == 0:
        return None, None

    v10 = [_safe_div(sum(1.0 if x > y else 0.5 if x == y else 0.0 for y in neg), n)
           for x in pos]
    v01 = [_safe_div(sum(1.0 if x > y else 0.5 if x == y else 0.0 for x in pos), m)
           for y in neg]
    auc = sum(v10) / m

    if m >= 2 and n >= 2:
        var = _sample_var(v10) / m + _sample_var(v01) / n
        se = math.sqrt(max(var, 0.0))
    else:
        # 组内只有 1 例时样本方差无定义，退回 Hanley–McNeil 近似
        se = power.auc_se(auc, m, n)
    return auc, se


def auc_z_vs_half(auc, se):
    """AUC 与 0.5 的单样本检验（DeLong/正态近似）。返回 dict。"""
    if auc is None or se is None:
        return {"z": None, "p": None, "note": "样本不足或单类缺失，无法检验"}
    if se <= 0:
        return {"z": None, "p": 0.0 if auc > 0.5 else 1.0,
                "note": "SE=0（完全分离或样本退化），给出保守 p"}
    z = (auc - 0.5) / se
    p = 2.0 * (1.0 - _NORM.cdf(abs(z)))
    return {"z": z, "p": p, "note": None}


def threshold_metrics(scores, labels, t):
    """分数 ≥ t 判为「已封」时的混淆矩阵与派生指标。"""
    tp = fp = fn = tn = 0
    for s, l in zip(scores, labels):
        pred = 1 if s >= t else 0
        if l == 1:
            tp += 1 if pred else 0
            fn += 0 if pred else 1
        else:
            fp += 1 if pred else 0
            tn += 0 if pred else 1
    return {
        "threshold": t,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": _safe_div(tp, tp + fp),
        "recall": _safe_div(tp, tp + fn),
        "specificity": _safe_div(tn, tn + fp),
        "fpr": _safe_div(fp, fp + tn),
        "accuracy": _safe_div(tp + tn, tp + tn + fp + fn),
    }


def segment_stats(scores, labels):
    """四个分数段（0–17 / 18–39 / 40–64 / 65–100）的实际封号率。"""
    out = []
    for lo, hi, lv in SEGMENTS:
        idx = [i for i, s in enumerate(scores) if lo <= s < hi]
        n = len(idx)
        banned = sum(1 for i in idx if labels[i] == 1)
        out.append({
            "levelId": lv["id"], "level": lv["name"], "lo": lo, "hi": hi - 1,
            "n": n, "banned": banned, "ban_rate": _safe_div(banned, n),
        })
    return out


# ---------- 单调性 ----------
def _pearson(a, b):
    n = len(a)
    if n < 2:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    num = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    da = math.sqrt(sum((v - ma) ** 2 for v in a))
    db = math.sqrt(sum((v - mb) ** 2 for v in b))
    if da == 0 or db == 0:
        return None
    return num / (da * db)


def spearman(x, y):
    """Spearman ρ（秩相关），沿用 score_from_dataset 的平均秩处理并列。"""
    if len(x) < 2 or len(x) != len(y):
        return None
    return _pearson(sfd._rankdata(x), sfd._rankdata(y))


def spearman_test(x, y):
    """Spearman ρ + 大样本正态近似 p 值（H0: ρ=0）。"""
    rho = spearman(x, y)
    n = len(x)
    if rho is None or n < 3:
        return {"rho": rho, "z": None, "p": None, "n": n}
    z = rho * math.sqrt(n - 1)
    p = 2.0 * (1.0 - _NORM.cdf(abs(z)))
    return {"rho": rho, "z": z, "p": p, "n": n}


# ---------- 维度重要性 ----------
def dimension_aucs(labelled):
    """各维度单独对标签的 AUC（维度间存在共线性，仅作单变量参考）。"""
    labels = [r["label"] for r in labelled]
    out = {}
    for d in model.DIMENSIONS:
        vals = [r["dim_risks"][d["id"]] for r in labelled]
        out[d["id"]] = {
            "name": d["name"], "weight": d["weight"],
            "auc": sfd.auc_score(vals, labels),
        }
    return out


def permutation_importance(labelled, n_perm=200, seed=20260401):
    """置换重要性：打乱单个维度的风险值后，全模型 AUC 的下降幅度。

    以「原始总分（Σ 权重×维度风险，未取整）」为模型输出，逐维度打乱后重算 AUC，
    重要性 = 基线 AUC − 打乱后 AUC 的均值。注意维度间共线性会摊薄单维度重要性。
    """
    labels = [r["label"] for r in labelled]
    w = {d["id"]: d["weight"] for d in model.DIMENSIONS}
    base_raw = [sum(w[d["id"]] * r["dim_risks"][d["id"]] for d in model.DIMENSIONS)
                for r in labelled]
    base_auc = sfd.auc_score(base_raw, labels)
    rng = random.Random(seed)
    out = {}
    for d in model.DIMENSIONS:
        drops = []
        original = [r["dim_risks"][d["id"]] for r in labelled]
        for _ in range(n_perm):
            shuffled = list(original)
            rng.shuffle(shuffled)
            perm_scores = [base_raw[i] - w[d["id"]] * original[i] + w[d["id"]] * shuffled[i]
                           for i in range(len(labelled))]
            a = sfd.auc_score(perm_scores, labels)
            if base_auc is not None and a is not None:
                drops.append(base_auc - a)
        out[d["id"]] = {
            "name": d["name"], "weight": d["weight"], "n_perm": n_perm,
            "auc_drop_mean": (sum(drops) / len(drops)) if drops else None,
        }
    return base_auc, out


# ---------- 共线性（VIF） ----------
def _corr_matrix(vectors):
    k = len(vectors)
    n = len(vectors[0]) if k else 0
    means = [sum(v) / n for v in vectors]
    sds = [math.sqrt(_sample_var(v)) for v in vectors]
    r = [[1.0] * k for _ in range(k)]
    for i in range(k):
        for j in range(i + 1, k):
            if sds[i] == 0 or sds[j] == 0:
                c = 0.0
            else:
                cov = sum((vectors[i][t] - means[i]) * (vectors[j][t] - means[j])
                          for t in range(n)) / (n - 1)
                c = cov / (sds[i] * sds[j])
            r[i][j] = r[j][i] = c
    return r, sds


def _invert(matrix):
    """高斯–约当法求逆，奇异则抛 ValueError。"""
    n = len(matrix)
    a = [row[:] + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(matrix)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[piv][col]) < 1e-12:
            raise ValueError("矩阵奇异")
        a[col], a[piv] = a[piv], a[col]
        pv = a[col][col]
        for j in range(2 * n):
            a[col][j] /= pv
        for r in range(n):
            if r != col and a[r][col] != 0.0:
                f = a[r][col]
                for j in range(2 * n):
                    a[r][j] -= f * a[col][j]
    return [row[n:] for row in a]


def vif_table(labelled):
    """方差膨胀因子：相关矩阵逆的对角元即 VIF（标准化自变量的经典结论）。

    返回 (dict, note)：某维度方差为 0（常数）时矩阵奇异，返回 (None, 说明)。
    """
    vectors = [[r["dim_risks"][d["id"]] for r in labelled] for d in model.DIMENSIONS]
    r_mat, sds = _corr_matrix(vectors)
    if any(sd == 0 for sd in sds):
        return None, "存在方差为 0 的维度，相关矩阵奇异，无法计算 VIF"
    try:
        inv = _invert(r_mat)
    except ValueError:
        return None, "相关矩阵奇异（维度高度共线），无法计算 VIF"
    return {model.DIMENSIONS[i]["id"]: inv[i][i] for i in range(len(vectors))}, None


# ---------- 亚组 ----------
def _subgroup(labelled, predicate):
    sub = [r for r in labelled if predicate(r)]
    scores = [r["score"] for r in sub]
    labels = [r["label"] for r in sub]
    banned = [s for s, l in zip(scores, labels) if l == 1]
    survived = [s for s, l in zip(scores, labels) if l == 0]
    return {
        "n": len(sub), "banned": len(banned), "survived": len(survived),
        "mean_score": round(sum(scores) / len(scores), 1) if scores else None,
        "mean_banned": round(sum(banned) / len(banned), 1) if banned else None,
        "mean_survived": round(sum(survived) / len(survived), 1) if survived else None,
        "auc": sfd.auc_score(scores, labels),
    }


def subgroup_analysis(labelled):
    """亚组：账号年龄（新号 q7∈{2,3} vs 老号 q7∈{0,1}）、出口地区（支持区 q3=0 vs 其他）。"""
    def q(r, qid, default=-1):
        return r["answers"].get(qid, default)

    return {
        "newAccount": _subgroup(labelled, lambda r: q(r, "q7") >= 2),
        "oldAccount": _subgroup(labelled, lambda r: 0 <= q(r, "q7") <= 1),
        "supportedRegion": _subgroup(labelled, lambda r: q(r, "q3") == 0),
        "otherRegion": _subgroup(labelled, lambda r: q(r, "q3") in (1, 2)),
    }


# ---------- 汇总 ----------
def analyze(records, meta, n_boot=1000, n_perm=200, seed=20260401):
    labelled = [r for r in records if r["label"] is not None]
    scores = [r["score"] for r in labelled]
    labels = [r["label"] for r in labelled]

    result = {
        "meta": meta,
        "nLabelled": len(labelled),
        "nBanned": sum(1 for l in labels if l == 1),
        "nSurvived": sum(1 for l in labels if l == 0),
    }
    if not scores or result["nBanned"] == 0 or result["nSurvived"] == 0:
        result["error"] = "缺少标签或单类缺失，无法做区分度分析（仅给出描述统计）"
        return result

    auc, se = delong_auc_se(scores, labels)
    a = sfd.auc_score(scores, labels)
    ci = sfd.bootstrap_ci(scores, labels, n_boot=n_boot, seed=seed)

    base_raw_auc, perm = permutation_importance(labelled, n_perm=n_perm, seed=seed)
    vif, vif_note = vif_table(labelled)

    result["discrimination"] = {
        "auc": a,
        "auc_ci95": [ci[0], ci[1]] if ci else None,
        "bootstrap": n_boot,
        "seed": seed,
        "delong_se": se,
        "vs_half": auc_z_vs_half(auc, se),
    }
    result["thresholds"] = [threshold_metrics(scores, labels, t) for t in LEVEL_THRESHOLDS]
    result["segments"] = segment_stats(scores, labels)
    result["monotonicity"] = spearman_test(scores, labels)
    result["dimensions"] = dimension_aucs(labelled)
    result["permutationImportance"] = {"baseRawAuc": base_raw_auc, "byDimension": perm}
    result["vif"] = {"values": vif, "note": vif_note}
    result["subgroups"] = subgroup_analysis(labelled)
    return result


def _round_floats(obj, nd=4):
    if isinstance(obj, float):
        return round(obj, nd)
    if isinstance(obj, dict):
        return {k: _round_floats(v, nd) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round_floats(v, nd) for v in obj]
    return obj


def _fmt(x, nd=4):
    return "—" if x is None else ("%%.%df" % nd) % x


def print_report(res):
    meta = res["meta"]
    print("数据集：%s" % meta["csv"])
    print("读入 %d 行，成功打分 %d 例，跳过 %d 例，无标签 %d 例"
          % (meta["rowsInFile"], meta["scored"], meta["skipped"], meta["unlabelled"]))
    if "error" in res:
        print("!! %s" % res["error"])
        return
    d = res["discrimination"]
    print("样本：已封 %d / 未封 %d（合计 %d）"
          % (res["nBanned"], res["nSurvived"], res["nLabelled"]))
    print()
    print("【主分析 · 区分度】")
    print("  AUC = %s" % _fmt(d["auc"]))
    if d["auc_ci95"]:
        print("  AUC 95%% CI = [%s, %s]（Bootstrap %d 次）"
              % (_fmt(d["auc_ci95"][0]), _fmt(d["auc_ci95"][1]), d["bootstrap"]))
    vh = d["vs_half"]
    if vh["z"] is not None:
        print("  DeLong 检验 vs 0.5：z = %s，p = %s" % (_fmt(vh["z"], 3), _fmt(vh["p"], 4)))
    else:
        print("  DeLong 检验 vs 0.5：%s" % vh["note"])
    print("  基线（随机）AUC = 0.5000")
    print()
    print("【阈值 · Precision / Recall】")
    print("  %-8s %-6s %-10s %-10s %-10s" % ("阈值", "TP/FP", "Precision", "Recall", "特异度"))
    for t in res["thresholds"]:
        print("  ≥%-7d %-6s %-10s %-10s %-10s"
              % (t["threshold"], "%d/%d" % (t["tp"], t["fp"]),
                 _fmt(t["precision"], 3), _fmt(t["recall"], 3), _fmt(t["specificity"], 3)))
    print()
    print("【分箱 · 各段实际封号率】")
    for s in res["segments"]:
        rate = "—" if s["ban_rate"] is None else "%.1f%%" % (s["ban_rate"] * 100)
        print("  %-8s [%3d–%3d] n=%-5d 封号率 %s"
              % (s["level"], s["lo"], s["hi"], s["n"], rate))
    print()
    mono = res["monotonicity"]
    print("【单调性】Spearman ρ = %s（p = %s, n = %d）"
          % (_fmt(mono["rho"], 3), _fmt(mono["p"], 4), mono["n"]))
    print()
    print("【维度重要性】单维度 AUC / 置换重要性（AUC 下降）")
    for d_ in model.DIMENSIONS:
        dim = res["dimensions"][d_["id"]]
        pi = res["permutationImportance"]["byDimension"][d_["id"]]
        print("  %-10s 权重 %-3d 单维度AUC %-6s 置换下降 %s"
              % (dim["name"], dim["weight"], _fmt(dim["auc"], 3), _fmt(pi["auc_drop_mean"], 4)))
    vif = res["vif"]
    if vif["values"]:
        print("  VIF：" + "，".join("%s %.2f" % (model.DIMENSIONS[i]["name"], vif["values"][model.DIMENSIONS[i]["id"]])
                                  for i in range(len(model.DIMENSIONS))))
    else:
        print("  VIF：%s" % vif["note"])
    print()
    print("【亚组】")
    for key, label in (("newAccount", "新号"), ("oldAccount", "老号"),
                       ("supportedRegion", "支持区"), ("otherRegion", "其他区")):
        g = res["subgroups"][key]
        print("  %-6s n=%-5d 已封/未封 %d/%d  均分 %s  AUC %s"
              % (label, g["n"], g["banned"], g["survived"],
                 _fmt(g["mean_score"], 1), _fmt(g["auc"], 3)))
    print()
    print("提醒：本结果须按 docs/validation-plan.md 的预注册流程一次性解读；")
    print("      任何事后改动或重复检验都必须显式标注为「探索性」。")


def main():
    ap = argparse.ArgumentParser(
        description="claude-risk-check 主分析（AUC / DeLong / 阈值 / 分箱 / 维度 / 亚组）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：python analysis/auc.py data/pilot.csv --bootstrap 2000 --json",
    )
    ap.add_argument("csv_path", help="输入数据集 CSV 路径")
    ap.add_argument("--bootstrap", type=int, default=1000, help="Bootstrap 次数，默认 1000")
    ap.add_argument("--permutations", type=int, default=200, help="置换重要性次数，默认 200")
    ap.add_argument("--seed", type=int, default=20260401, help="随机种子，默认 20260401")
    ap.add_argument("--allow-partial", action="store_true", help="允许答案不全（默认跳过不完整样本）")
    ap.add_argument("--out", help="把完整结果 JSON 写入文件")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出到 stdout")
    args = ap.parse_args()

    records, meta = sfd.load_dataset(args.csv_path, allow_partial=args.allow_partial)
    result = analyze(records, meta, n_boot=args.bootstrap,
                     n_perm=args.permutations, seed=args.seed)
    result = _round_floats(result)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print_report(result)
    if args.out:
        print("完整结果已写入：%s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
