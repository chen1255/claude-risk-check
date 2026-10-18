# 预注册 · Pre-registration

[中文](#中文) | [English abstract](#english-abstract)

> 本文档在**正式采集开始前**冻结：被测模型、分析脚本、主指标、阈值、排除标准与样本量目标。
> 目的是防止事后调参（p-hacking）——**只跑一次**正式分析，任何事后的探索都必须显式标注为「探索性」。
> 配套阅读：[validation-plan.md](./validation-plan.md)（方案总纲）、[collection-guide.md](./collection-guide.md)（采集指南）。

---

## 中文

### 0. 冻结声明

本预注册由 [validation-plan.md](./validation-plan.md) §5 要求。**冻结物一经确定，正式采集期间不得修改**；确需修改时，必须在 §7 偏离登记表逐条登记，并说明修改发生在何时、是否已看过数据。

| 项目 | 冻结值 | 说明 |
| --- | --- | --- |
| 冻结日期 | `__________` | 正式采集开始日（待填） |
| 冻结人 | `__________` | 负责登记偏离者（待填） |
| 被测模型 | `questions.json` **version 1.0.0** | 任一题 / 权重 / 阈值改动即宣告冻结失效，须重走本流程 |
| 打分管线 | `scripts/score_from_dataset.py` @ `212864c` | 分数一律经 `claude_risk_check.compute`，不得重写 |
| 主分析脚本 | `analysis/auc.py` @ `212864c` | AUC / DeLong / 阈值 / 分段 / 维度 / 亚组 |
| 校准脚本 | `analysis/calibration.py` @ `212864c` | reliability / Brier / Murphy / Spearman |
| 功效脚本 | `scripts/power_auc.py` @ `212864c` | 样本量核算依据 |

> `212864c` 指提交 `212864c9899d5a3d319e60a40e44ea98e4382329`；脚本一经冻结，正式分析须在该提交（或其后仅含注释/文档改动的提交）上运行，并在结果报告中写明实际所用 commit。

### 1. 被测对象

- **模型**：`questions.json` version 1.0.0（8 维度 / 16 题加权问卷，输出 0–100 分）；
- **等级阈值**：`low ≤ 18`、`mid ≤ 40`、`elevated ≤ 65`、`high ≤ 101`（即切点 **18 / 40 / 65**）；
- **维度权重**：network 25 / behavior 20 / accountAge 15 / sharing 15 / fingerprint 10 / channel 5 / payment 5 / identity 5；
- **能力边界**：模型只描述环境画像，**不做时序预测**，也不做因果推断（见 validation-plan §0）。

### 2. 样本与标签规则

| 规则 | 冻结值 |
| --- | --- |
| 结局标签 | `banned` / `survived` |
| 标签置信 | `confirmed`（有官方邮件/截图佐证）/ `reported`（仅自述） |
| 主分析人群 | **`confirmed` 全量**；`reported` 仅用于敏感性分析，**不进主分析** |
| `survived` 观察窗口 | **≥ 30 天，建议 ≥ 60**；< 30 天者排除 |
| 快照时点 | 必须 `pre_ban` / `during_window`；事后回忆作答者排除 |
| 完整度 | 答案缺项默认排除（`--allow-partial` 仅供试点排查用，**不进主分析**） |
| `sample_id` | 不可逆哈希，仅去重；含 PII 者排除 |

### 3. 主分析（预注册，只做一次）

**主指标**：ROC-AUC（分数 → `label`）。

1. **AUC + Bootstrap 95% CI**（`--bootstrap ≥ 1000`，默认 1000）；
2. **DeLong 检验**：AUC 是否显著 > 0.5，**双侧 α = 0.05**；
3. **判据（预先声明）**：AUC 的 95% CI **下界 > 0.5** 才算通过（与 validation-plan §9 一致）。

**阈值分析**（切点 **18 / 40 / 65** 固定，不可事后挑选）：报告每个切点处的 Precision / Recall / 特异度，以及四个分数段（0–17 / 18–39 / 40–64 / 65–100）的实际封号率。

**命令**（冻结，不得增删参数）：

```powershell
python scripts/score_from_dataset.py data/final.csv --out data/final_scored.csv --auc
python analysis/auc.py data/final.csv --bootstrap 1000 --out data/final_auc.json
```

### 4. 次分析（同批报告，但非主判据）

- **校准**：分数分箱 0–17 / 18–39 / 40–64 / 65–100，对比「平均预测风险（分数/100）」vs「实际封号率」；Brier score、与常数基线比较的 Brier Skill Score、Murphy 分解；
- **单调性**：分数 vs 标签的 Spearman ρ（正态近似 p 值）；
- **维度重要性**：各维度单独 AUC + 置换重要性（200 次，seed `20260401`）；
- **共线性**：维度相关矩阵的 VIF（奇异时如实报告，不强行出数）；
- **亚组**：新号（<2 周 / 2 周–1 月）vs 老号；支持区 vs 其他区；
- **随机基准**：所有图上须画出 AUC = 0.5 对比线。

**命令**：

```powershell
python analysis/calibration.py data/final.csv --out data/final_calib.json
```

### 5. 样本量目标

主指标为 AUC，用 Hanley–McNeil 方差 + 正态近似（`scripts/power_auc.py`）。α = 0.05、power = 0.80、两组 1:1：

| 预期 AUC | 每组 n | 合计 |
| --- | --- | --- |
| 0.55 | 518 | 1036 |
| 0.60 | 125 | 250 |
| **0.65** | **53** | **106** |
| 0.70 | 28 | 56 |

- **功效下限**：若真实区分力 AUC ≈ 0.65，则 **53 + 53** 即达标；
- **正式采集目标**：**≥ 200 `banned` + ≥ 200 `survived`**（把 95% CI 半宽压到约 ±0.054，并支撑 §4 亚组与 `confirmed` 敏感性分析）；
- **达标下限（验收）**：两类**各不少于 100**（validation-plan §9）。未达标时降级为描述性统计，并明确标注「未达检验功效」。

### 6. 结果公开承诺

- **负结果同样公开**：若 AUC 的 95% CI 覆盖 0.5，将**如实报告工具无区分力**，停止宣称预警价值，或按 validation-plan §8 回炉重设条目——**不得通过修改口径、挑选阈值、删样本使结果变好**；
- **可复现**：分析代码开源；脱敏数据集与分析输出一并公开，保证他人可复算；
- **原始数据**：逐条原始数据只留在本地 / 私有仓库（`data/` 在 `.gitignore`），公开仅出**聚合统计**。

### 7. 偏离登记表

任何偏离预注册的改动（改参数、改人群、改切点、加分析）都必须登记；正式分析**只跑一次**，事后探索一律标注「探索性」。

| 日期 | 偏离内容 | 是否已看过数据 | 理由 | 登记人 |
| --- | --- | --- | --- | --- |
| | | | | |

> 空表即表示「零偏离」：正式分析完全按本预注册执行。

---

## English abstract

A pre-registration for the claude-risk-check validation. It freezes, before data collection starts: the exact model (`questions.json` version 1.0.0) and analysis scripts (commit `212864c`), the primary endpoint (ROC-AUC with bootstrap 95% CI and DeLong test, two-sided α=0.05, pass iff CI lower bound > 0.5), the three thresholds (18/40/65), secondary analyses (calibration/Brier, Spearman monotonicity, per-dimension importance, VIF, subgroups), inclusion/exclusion rules (`confirmed` labels only, ≥30-day survival window, mandatory pre-ban snapshot), a sample-size target of ≥200 per group (power floor 53+53), a commitment to publish negative results, and a deviation log. Formal analysis is run exactly once; any later exploration must be labelled exploratory.
