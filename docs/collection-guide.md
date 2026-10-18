# 采集指南 · Data Collection Guide

> 配套阅读：[validation-plan.md](./validation-plan.md)（方案、偏差控制、验收标准）、[pre-registration.md](./pre-registration.md)（预注册冻结）
> 适用阶段：**P1 试点采集**、**P2 正式采集**

## 0. 一句话

每个样本 = 一次账号实例在**封号前 / 观察期末**的环境快照 + 最终结局标签。
不含任何可识别个人身份的信息（PII）。

## 1. 四步上手

1. 复制模板 [collection-template.csv](./collection-template.csv) → 另存为 `data/pilot.csv`
   （`data/` 已写入 `.gitignore`，含真实案例的原始数据绝不公开）
2. **删掉模板里的 `EXAMPLE-000-PLEASE-DELETE` 示例行**
3. 按 §2 / §3 逐条填写
4. 填完立刻跑管线（§6）——先确认数据能被正确解析，再继续累积样本

## 2. 字段说明

| 字段 | 必填 | 取值 | 说明 |
| --- | --- | --- | --- |
| `sample_id` | ✅ | `sha256(线索)[:16]` | **不可逆哈希**，仅用于去重；不得含邮箱 / 手机号 / 账号 ID |
| `label` | ✅ | `banned` / `survived` | 结局标签 |
| `label_confidence` | ✅ | `confirmed` / `reported` | `confirmed` = 有官方邮件或截图佐证；`reported` = 仅用户自述 |
| `ban_time` | banned 必填 | ISO 8601 UTC | 封禁时间；`survived` 留空，改填观察截止时间 |
| `observation_window_days` | survived 必填 | 整数 | 观察窗口天数；**≥ 30，建议 ≥ 60** |
| `snapshot_point` | ✅ | `pre_ban` / `during_window` | 作答对应的时点；**必须是封号前 / 窗口内**，不能是事后回忆 |
| `channel` | ✅ | `github_issue` / `reddit` / `form` / `self_report` | 来源渠道 |
| `captured_at` | ✅ | ISO 8601 UTC | 本次采集时间 |
| `q1` … `q16` | ✅ | 选项下标（**0 起**） | 见 §3；缺任何一题即视为不完整样本 |

## 3. 答案怎么填

与 [questions.json](./../questions.json) 的 `qid` 与**选项下标**直接对应，保证与工具评分模型零转换：

- **方式 A（推荐，表格友好）**：`q1` … `q16` 各占一列，单元格填选项下标（0 起）
- **方式 B**：单列 `answers`，内容为 JSON 对象 `{"q1":2,"q2":1,...}`

两种方式**二选一**即可，`score_from_dataset.py` 会自动识别（优先 `answers` 列）。选项下标的含义就是 `questions.json` 里每题 `options` 数组的顺序。

## 4. 三题可借助自动探测

以下三题带有自动探测标记，可先用工具探测、再由填写者确认：

| 题目 | 探测项 |
| --- | --- |
| `q1` | `ip_type` |
| `q3` | `ip_region` |
| `q11` | `env_consistency` |

但**采集时一律以「封号前 / 观察期内」的状态为准**；探测不到就手工填，不要用当前状态替代。

## 5. 五条硬性约束（违反则该样本不合格）

1. **时点**：`snapshot_point` 必须是 `pre_ban` / `during_window`。问"封号前那周"的具体状态，不要问"你平时是不是…"
2. **观察窗口**：`survived` 的窗口 ≥ 30 天（建议 ≥ 60）。窗口太短时"还没封"只等于"还没轮到"，会把暂未封的用户误标为阴性、稀释区分度
3. **对照组**：必须主动招募长期未封样本。只收事故案例会因选择偏差把 AUC 抬高
4. **完整性**：答案缺项默认被脚本跳过（`--allow-partial` 可纳入，但**主分析不用**不完整样本）
5. **匿名**：`sample_id` 不可逆；不收集邮箱、卡号、手机号、具体 IP

## 6. 采集后立刻跑管线

```powershell
# 1) 打分：逐条送入评分模型，输出分组统计与快速 AUC
python scripts/score_from_dataset.py data/pilot.csv --out data/pilot_scored.csv --auc

# 2) 主分析：AUC + Bootstrap CI、DeLong、阈值 18/40/65、维度重要性、亚组
python analysis/auc.py data/pilot.csv

# 3) 校准：分箱可靠性、Brier / Brier Skill Score、Murphy 分解、单调性
python analysis/calibration.py data/pilot.csv
```

- 第 1 条用于**快速体检**：看 `scored / skipped` 是否合理，跳过率过高说明表单或采集流程有问题
- 第 2、3 条是正式分析脚本，**预注册后只跑一次**（见 [pre-registration.md](./pre-registration.md)）
- **试点阶段（~50 例）跑这三条的目的是暴露偏差、修正管线，不是出正式结论**

## 7. 采集进度记账

| 阶段 | 目标 | banned | survived | 备注 |
| --- | --- | --- | --- | --- |
| P1 试点 | ~50 例 | | | 验证管线 + 暴露偏差 |
| P2 正式 | ≥ 200 / ≥ 200 | | | 功效下限 53+53，取 200 为压窄 CI 并支撑亚组分析 |

## 8. 伦理红线

- **匿名化**：`sample_id` 不可逆，不含 PII
- **知情同意**：说明用途，允许随时撤回并删除
- **最小化**：只收评估必需字段
- **边界**：不提供规避平台规则的任何建议，不协助违反 ToS 的行为
- **存储**：原始逐条数据只留在本地 / 私有仓库，公开仅出**聚合统计**
