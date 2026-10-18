#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
score_from_dataset.py — 验证计划（docs/validation-plan.md §7）的打分管线

把「真实封号案例」数据集（CSV）逐条送进 claude-risk-check 的评分模型，
输出每例的分数与等级，并给出分组统计与（标签齐全时的）快速 AUC。

铁律：本脚本 **直接调用 claude_risk_check.compute**，绝不重写评分逻辑——
否则验证的就不是被测工具本身了（评分逻辑唯一来源见 questions.json）。

输入 CSV 需包含：
    · sample_id、label（banned / survived）
    · 答案二选一：
        a) answers 列，内容为 JSON 对象 {"q1":2,"q2":1,...}
        b) q1..q16 共 16 列，每列为选项下标（0 起）

用法:
    python scripts/score_from_dataset.py data/pilot.csv
    python scripts/score_from_dataset.py data/pilot.csv --out scored.csv --auc
    python scripts/score_from_dataset.py data/pilot.csv --json --allow-partial
"""

import argparse
import csv
import json
import os
import random
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import claude_risk_check as model  # noqa: E402

BANNED = {"banned", "ban", "封号", "已封", "1", "true"}
SURVIVED = {"survived", "ok", "未封", "存活", "0", "false"}


def parse_label(raw):
    """归一化标签 → 1(已封) / 0(未封) / None。"""
    s = str(raw or "").strip().lower()
    if s in BANNED:
        return 1
    if s in SURVIVED:
        return 0
    return None


def parse_answers(row, headers):
    """从一行 CSV 中解析 {qid: option_index}。失败返回 (None, 原因)。"""
    if "answers" in headers and (row.get("answers") or "").strip():
        try:
            data = json.loads(row["answers"])
        except Exception as e:
            return None, "answers 列 JSON 解析失败: %s" % e
        if not isinstance(data, dict):
            return None, "answers 列不是 JSON 对象"
        out = {}
        for k, v in data.items():
            try:
                out[str(k)] = int(v)
            except Exception:
                return None, "答案值非法: %r" % (v,)
        return out, None

    out = {}
    for q in model.QUESTIONS:
        if q["id"] not in headers:
            continue
        raw = (row.get(q["id"]) or "").strip()
        if raw == "":
            continue
        try:
            out[q["id"]] = int(raw)
        except Exception:
            return None, "%s 列值非法: %r" % (q["id"], raw)
    return (out or None), (None if out else "未找到 answers 列，也没有 q1..q16 列")


def validate_answers(ans):
    """校验每道题的选项下标是否越界。返回 (清洗后的答案, 问题列表)。"""
    problems = []
    clean = {}
    for q in model.QUESTIONS:
        oi = ans.get(q["id"])
        if oi is None:
            problems.append("%s 未作答" % q["id"])
            continue
        if not (0 <= oi < len(q["options"])):
            problems.append("%s 选项下标越界: %s" % (q["id"], oi))
            continue
        clean[q["id"]] = oi
    return clean, problems


# ---------- 统计（纯标准库） ----------
def _rankdata(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def auc_score(scores, labels):
    """Mann–Whitney U 形式计算 AUC（label: 1=已封, 0=未封）；缺一类返回 None。"""
    pos = [scores[i] for i, l in enumerate(labels) if l == 1]
    neg = [scores[i] for i, l in enumerate(labels) if l == 0]
    if not pos or not neg:
        return None
    combined = pos + neg
    ranks = _rankdata(combined)
    r_pos = sum(ranks[:len(pos)])
    u = r_pos - len(pos) * (len(pos) + 1) / 2.0
    return u / (len(pos) * len(neg))


def bootstrap_ci(scores, labels, n_boot=1000, alpha=0.05, seed=20260401):
    """AUC 的 Bootstrap 百分位置信区间。数据太少或单类时返回 None。"""
    if auc_score(scores, labels) is None:
        return None
    rng = random.Random(seed)
    n = len(scores)
    vals = []
    for _ in range(n_boot):
        idx = [rng.randrange(n) for _ in range(n)]
        s = [scores[i] for i in idx]
        l = [labels[i] for i in idx]
        a = auc_score(s, l)
        if a is not None:
            vals.append(a)
    if len(vals) < n_boot // 2:
        return None
    vals.sort()
    lo = vals[int(alpha / 2 * len(vals))]
    hi = vals[min(len(vals) - 1, int((1 - alpha / 2) * len(vals)))]
    return lo, hi


def main():
    ap = argparse.ArgumentParser(
        description="把真实封号案例数据集送入 claude-risk-check 评分模型",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：python scripts/score_from_dataset.py data/pilot.csv --out scored.csv --auc",
    )
    ap.add_argument("csv_path", help="输入 CSV 路径")
    ap.add_argument("--out", help="输出逐条打分 CSV 路径")
    ap.add_argument("--auc", action="store_true", help="计算 AUC 及其 Bootstrap 95%% CI")
    ap.add_argument("--bootstrap", type=int, default=1000, help="Bootstrap 次数，默认 1000")
    ap.add_argument("--allow-partial", action="store_true", help="允许答案不全（默认跳过不完整样本）")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出汇总")
    args = ap.parse_args()

    with open(args.csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        rows = list(reader)

    results, skipped, unlabelled = [], 0, 0
    for row in rows:
        ans, err = parse_answers(row, headers)
        if ans is None:
            skipped += 1
            continue
        clean, problems = validate_answers(ans)
        if problems and not args.allow_partial:
            skipped += 1
            continue
        score, _rows = model.compute(clean)
        lv = model.level_of(score)
        label = parse_label(row.get("label"))
        if label is None:
            unlabelled += 1
        results.append({
            "sample_id": row.get("sample_id") or "",
            "label": label,
            "score": score,
            "levelId": lv["id"],
            "level": lv["name"],
            "answered": len(clean),
        })

    scored = [r["score"] for r in results]
    labels = [r["label"] for r in results]

    summary = {
        "csv": os.path.basename(args.csv_path),
        "rowsInFile": len(rows),
        "scored": len(results),
        "skipped": skipped,
        "unlabelled": unlabelled,
    }
    labelled_pairs = [(s, l) for s, l in zip(scored, labels) if l is not None]
    if labelled_pairs:
        s_arr = [p[0] for p in labelled_pairs]
        l_arr = [p[1] for p in labelled_pairs]
        banned = [s for s, l in labelled_pairs if l == 1]
        survived = [s for s, l in labelled_pairs if l == 0]
        summary["labelled"] = len(labelled_pairs)
        summary["banned"] = {"n": len(banned),
                             "mean": round(sum(banned) / len(banned), 1) if banned else None}
        summary["survived"] = {"n": len(survived),
                               "mean": round(sum(survived) / len(survived), 1) if survived else None}
        buckets = {}
        for s, l in labelled_pairs:
            lv = model.level_of(s)
            b = buckets.setdefault(lv["id"], {"level": lv["name"], "n": 0, "banned": 0})
            b["n"] += 1
            b["banned"] += l
        for b in buckets.values():
            b["ban_rate"] = round(b["banned"] / b["n"], 3) if b["n"] else None
        summary["byLevel"] = buckets
        if args.auc:
            a = auc_score(s_arr, l_arr)
            ci = bootstrap_ci(s_arr, l_arr, n_boot=args.bootstrap)
            summary["auc"] = round(a, 4) if a is not None else None
            summary["auc_ci95"] = [round(ci[0], 4), round(ci[1], 4)] if ci else None

    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["sample_id", "label", "score", "levelId", "level", "answered"])
            w.writeheader()
            for r in results:
                w.writerow(r)

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    print("数据集：%s" % summary["csv"])
    print("读入 %d 行，成功打分 %d 例，跳过 %d 例，无标签 %d 例"
          % (summary["rowsInFile"], summary["scored"], summary["skipped"], summary["unlabelled"]))
    if "banned" in summary:
        print("已封  n=%d  平均分 %s" % (summary["banned"]["n"], summary["banned"]["mean"]))
        print("未封  n=%d  平均分 %s" % (summary["survived"]["n"], summary["survived"]["mean"]))
        print("各等级实际封号率：")
        for k in ("low", "mid", "elevated", "high"):
            b = summary["byLevel"].get(k)
            if b:
                print("  %-8s n=%-5d 封号率 %.1f%%" % (b["level"], b["n"], b["ban_rate"] * 100))
        if args.auc:
            print("AUC = %s" % summary.get("auc"))
            if summary.get("auc_ci95"):
                print("AUC 95%% CI = [%s, %s]（Bootstrap %d 次）"
                      % (summary["auc_ci95"][0], summary["auc_ci95"][1], args.bootstrap))
    if args.out:
        print("逐条结果已写入：%s" % args.out)
    print()
    print("提醒：单点 AUC 不等于效度结论；请按 docs/validation-plan.md 的预注册流程分析。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
