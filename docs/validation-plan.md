# 真实封号案例验证计划 · Validation Plan against Real Ban Cases

[中文](#中文) | [English abstract](#english-abstract)

> 本文档回答一个问题：**claude-risk-check 的分数，在真实「已封 / 未封」案例上到底有没有区分力？**
> 这是一个回溯性（retrospective）效度验证方案，不是产品功能。执行它需要真实标注数据，工具自身给不出。

---

## 中文

### 0. 目标与非目标

**目标**

1. 量化 `claude-risk-check` 的 0–100 分与真实封号结果之间的**区分度**（discrimination）；
2. 检验等级阈值（18 / 40 / 65）的**校准度**（calibration）与错误代价；
3. 用真实数据**重估 8 个维度的权重**，或证伪当前权重。

**非目标（明确划掉）**

- 不是"预测下一秒会不会被封"——模型只描述环境画像，不做时序预测；
- 不做因果推断（"改了就一定不会被封"不在此列）；
- 不产出任何"如何规避平台规则"的操作指南；
- 不收集、不存储任何可识别个人身份的信息（PII）。

### 1. 待检验假设

| 编号 | 假设 | 预期 |
| --- | --- | --- |
| H1 | 已封案例的分数显著高于未封案例 | 主检验 |
| H2 | 分数与"实际封号率"单调正相关 | 校准检验 |
| H3 | 高权重维度（网络 25 / 行为 20 / 账号年龄 15）在实际样本中更具区分力 | 权重检验 |
| H0 | 分数与封号结果**无关**（零假设） | 需被拒绝，否则工具无效 |

若不能拒绝 H0（AUC 置信区间覆盖 0.5），必须**如实报告工具无效**，而不是修改口径。

### 2. 数据需求

**样本标签**

- `label = banned`：在观察窗口内被 Anthropic 封禁；
- `label = survived`：在**足够长的观察窗口**内（≥ 30 天，建议 ≥ 60 天）始终未封。
  > 关键：未封样本必须有足够长的窗口，否则"还没封"只等于"还没轮到"，会把大量暂未封的用户误标为阴性，稀释区分度。

**每例样本字段（schema）**

```jsonc
{
  "sample_id": "sha256(线索)[:16]",   // 不可逆哈希，用于去重，不含 PII
  "label": "banned | survived",
  "label_confidence": "confirmed | reported",
  // confirmed = 有官方邮件/截图佐证；reported = 仅用户自述
  "ban_time": "2026-03-15T00:00:00Z",  // 或 survived 的观察截止时间
  "observation_window_days": 60,
  "channel": "github_issue | reddit | form | self_report",
  "captured_at": "2026-04-01T00:00:00Z",
  // 关键：环境快照必须是「封号前 / 观察期末」的状态，而非事后回忆
  "snapshot_point": "pre_ban | during_window",
  "answers": { "q1": 2, "q2": 1, "q3": 0, "...": 0 }  // 直接对应 questions.json 的 qid + 选项序号
}
```

`answers` 直接复用 [questions.json](./../questions.json) 的 `qid` 与选项下标，保证与工具的评分模型**零转换**对接。

### 3. 数据来源与偏差控制

| 来源 | 优点 | 主要偏差 | 对策 |
| --- | --- | --- | --- |
| 社区案例帖（Reddit / V2EX / 知乎 / 公众号长文） | 量大、有叙事细节 | 只有"出事的"才发帖（选择偏差极端） | 仅作补充，**不作为主样本** |
| 结构化匿名问卷（GitHub Issue 模板 / 在线表单） | 字段可控、可对齐 | 自述偏差、回忆偏差 | 强制填"封号前"快照 + 时间锚点 |
| 工具内"匿名上报"（结果页按钮） | 样本自然分布 | 上报率低、可能被滥用 | 与 `label_confidence` 交叉校验 |

**四条必须控制的偏差**

1. **选择偏差**：主动招募"长期未封"的对照，否则样本里全是事故案例，AUC 会被虚高；
2. **回忆偏差**：问"封号前那周"的具体状态，不问"你平时是不是……"；
3. **观察窗口偏倚**：见 §2；
4. **标注噪声**：区分 `confirmed / reported`，所有主分析用 `confirmed` 子集跑一遍做敏感性分析。

### 4. 样本量估算

主指标为 ROC-AUC，采用 Hanley–McNeil 单样本 AUC 检验：

```
n_per_group = ( z_{α/2} · √(V0) + z_β · √(V1) )² / (AUC_1 − 0.5)²
```

- `α = 0.05`（双侧）、`power = 0.80`；
- 备择 `AUC_1` 取 **0.65**（"中等区分力"，低于此的工具不值得继续投入）；
- `V0 / V1` 为 AUC 在 H0 / H1 下的方差，需按实际正负样本比例计算。

**落地要求**：不要直接抄本文的估算。请写一个 `scripts/power_auc.py`（或调用 `statsmodels` / `pROC`）按最终正负比例**实算**，把结果写回本节。
粗估（供预算参考，非结论）：每组约 200 例时，AUC≈0.65 的 95% CI 半宽约 ±0.07，可稳定拒绝 H0。**总样本目标：≥ 200 banned + ≥ 200 survived。**

### 5. 分析方案

**主分析（预注册，只做一次）**

1. **ROC-AUC**（分数 → label）+ Bootstrap（≥ 1000 次）95% CI；
2. **DeLong 检验**：AUC 是否显著 > 0.5；
3. 阈值 **18 / 40 / 65** 处的 Precision / Recall / 各段的实际封号率。

**次分析**

- **校准**：把分数分箱（0–17 / 18–39 / 40–64 / 65–100），对比"预测等级"与"实际封号率"，画 reliability diagram，算 Brier score；
- **单调性**：分数 vs 封号率的 Spearman ρ；
- **维度重要性**：各维度单独 AUC；逻辑回归系数 / 置换重要性（需注意维度间共线性，报告 VIF）；
- **亚组**：新号（<2 周 / 2 周–1 月）vs 老号、支持区 vs 其他区；
- **随机基准**：AUC = 0.5 的对比线必须在图上画出。

**预注册（防止 p-hacking）**

- 采集**开始前**锁定：主指标、阈值、排除标准、分析脚本；
- 只跑一次正式分析；任何事后探索必须显式标注为 `探索性`；
- 分析代码与脱敏数据开源，保证可复现。

### 6. 数据伦理与合规

- **匿名化**：`sample_id` 不可逆；不收集邮箱、卡号、手机号、具体 IP；
- **知情同意**：明确用途、可随时撤回并删除；
- **最小化**：只收评估必需的字段；
- **边界**：不提供规避建议、不协助违反 ToS 的行为；
- **存储**：原始逐条数据只保存在私有仓库 / 本地（`data/` 入 `.gitignore`），仅公开**聚合统计**。

### 7. 执行阶段与交付物

| 阶段 | 内容 | 交付物 |
| --- | --- | --- |
| P0 准备 | 问卷字段、schema、采集表、预注册文档、功效脚本 | `docs/validation-plan.md`、`scripts/power_auc.py` |
| P1 试点 | 采集 ~50 例，跑通评分→分析全链路，暴露偏差 | 试点报告 + 管线修正 |
| P2 正式采集 | 达到 §4 目标样本量 | 脱敏数据集（私有） |
| P3 分析 | 按 §5 执行 | `analysis/` 脚本 + 结果报告 |
| P4 复盘 | 依据结果修订条目 / 权重，或宣布无效 | 修订后的 `questions.json` |

**与现有仓库的衔接**

```
claude-risk-check/
├── scripts/
│   ├── power_auc.py            # 样本量核算（新增）
│   └── score_from_dataset.py   # CSV → 复用 claude_risk_check.compute 打分（新增）
├── analysis/
│   ├── auc.py                  # 主分析
│   └── calibration.py          # 校准
└── data/                       # 原始数据（.gitignore，不公开）
```

`score_from_dataset.py` 必须**直接 import `claude_risk_check.compute`**，不得重写评分逻辑——否则验证的就不是被测工具了。

### 8. 风险与失败预案

| 风险 | 预案 |
| --- | --- |
| 样本量不足 | 降级为描述性统计，明确标注"未达检验功效" |
| 标注噪声大 | 仅保留 `confirmed` 重跑；报告两版差异 |
| **AUC ≈ 0.5（工具无区分力）** | **如实公开**，停止宣称其预警价值，或回炉重设条目 |
| 合规/舆论风险 | 拒绝任何"规避指南"类诉求，文档中显式声明边界 |

### 9. 验收标准（怎样才算"验证过了"）

至少满足：

1. 样本量达标且 `banned/survived` 两类都不少于 100；
2. 主分析 AUC 的 95% CI **下界 > 0.5**（否则视为无效）；
3. 校准曲线非系统性高估 / 低估（Brier score 与基线比较有改善）；
4. 全流程脚本可一键复现。

> **一句话**：这个计划能做到"用真实案例检验工具是否有用"；做不到的是"保证工具一定有用"——那取决于数据，不取决于计划。

---

## English abstract

A retrospective validation plan for testing whether `claude-risk-check`'s 0–100 score actually discriminates real banned vs. survived cases. It specifies: labelled sample schema (with `confirmed`/`reported` label confidence and a mandatory pre-ban snapshot), bias controls (selection, recall, observation-window, label noise), a Hanley–McNeil sample-size calculation, a pre-registered analysis (ROC-AUC with bootstrap CI, DeLong test, threshold precision/recall, calibration/Brier, per-dimension importance), ethics (anonymisation, consent, no evasion guidance, private raw data), a phased rollout, and explicit acceptance criteria — including the obligation to publish a negative result if AUC's CI covers 0.5. It cannot prove the tool works; it can only measure whether it does.
