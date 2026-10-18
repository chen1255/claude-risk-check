# Claude 账号风控自检 · Claude Account Risk Self-Check

[中文](#中文) | [English](#english)

一个帮助用户自查 Claude 使用环境中「风控风险」的小工具：回答 16 道题，按 8 个维度加权打分，给出风险等级与**需要调整的方面**清单。

提供三种使用方式：**网页版**（含自动环境探测、场景沙盒、历史记录）与 **命令行版**（可输出 JSON），二者共用同一套评分模型与同一份数据源。

> **免责声明**：Anthropic 并未公开「满足某几条即封号」的官方规则。本工具基于社区大量封号案例与 Anthropic 公开 Safeguards 文档归纳，**仅供自查参考，不代表对封号结果的预测，也不构成规避平台规则的保证**。请在符合服务条款与当地法规的前提下使用 Claude。

---

## 中文

### 这是什么

国内用户使用 Claude（尤其 Claude Code）时，账号被风控/封禁往往不是因为违规，而是网络环境、使用行为、账号年龄等细节踩到了敏感线。本工具把公开资料中被反复印证的触发点整理成一份**可打分的自检问卷**，帮你在出问题前定位并调整。

### 文件清单

| 文件 | 说明 |
| --- | --- |
| [`index.html`](./index.html) | 网页自检页：分数圆环、维度分布条、待调整清单、自动探测、场景沙盒、历史记录 |
| [`questions.js`](./questions.js) | 网页数据文件（由 `questions.json` 生成），**须与 `index.html` 放在同一目录** |
| [`questions.json`](./questions.json) | **唯一数据源**：维度/权重/题目/选项/建议/来源/置信度/探测配置 |
| [`claude_risk_check.py`](./claude_risk_check.py) | 命令行版本，读取 `questions.json`；支持 `--auto`、`--json`、`--no-color` |
| [`probe.py`](./probe.py) | 环境探测（出口 IP 类型/地区、语言时区）的纯逻辑与 I/O，供 CLI 使用 |
| [`scripts/build_questions.py`](./scripts/build_questions.py) | 由 `questions.json` 生成 `questions.js`，并校验数据合法性 |
| [`scripts/install.ps1`](./scripts/install.ps1) | Windows 一键安装脚本 |
| [`tests/`](./tests) | 单元测试（数据一致性、评分边界、探测逻辑、编码） |

> 网页版**不再是单文件、零依赖**：浏览器在 `file://` 下无法用 `fetch` 读取本地 JSON（会被同源策略拦截），因此数据以 `<script src="questions.js">` 的形式外链加载。请保持这两个文件在同一目录。

### 8 个维度与权重

| 维度 | 权重 | 自查要点 |
| --- | --- | --- |
| 网络环境 | 25 | IP 是否为住宅 IP、出口地区是否稳定与受支持 |
| 使用行为模式 | 20 | 是否 24h 高负载、是否跑自动化/批量调用、用量强度 |
| 账号年龄与养号 | 15 | 账号注册时长、是否新号立即充值、是否频繁打满限额 |
| 账号共享 | 15 | 是否一人一号、是否存在异地/多人多地登录 |
| 环境指纹 | 10 | 系统语言/时区与出口地区是否自洽、换号是否清理残留 |
| 接入通道 | 5 | 新号阶段是否过早使用 CLI / 第三方客户端 |
| 支付与订阅 | 5 | 支付方式与退款渠道 |
| 邮箱与验证 | 5 | 注册邮箱类型、验证手机号地区 |

### 快速开始

**方式一：网页版（最简单）**

克隆或下载本仓库后，双击 `index.html` 即可（`questions.js` 需在同一目录）。

- **自动探测我的环境**：读取本机时区与浏览器语言，并尝试通过公开 API 获取出口 IP 的地区/ASN，给出 q1/q3/q11 的建议选项（仅作建议，可手动修改）。
- **场景沙盒**：一键切换「理想画像 / 普通海外用户 / 高危画像」预设，即时对比调整前后的分数。
- **历史记录**：每次生成报告自动存入浏览器 localStorage，可对比多次结果的变化。

> 以 `file://` 直接打开时，出口 IP 探测可能因同源策略失效（其余功能不受影响）。如需完整探测能力，可将其放到本地 HTTP 服务器或用 GitHub Pages 打开。

**方式二：命令行**

```bash
# 需要 Python 3.8+
python claude_risk_check.py             # 交互式作答
python claude_risk_check.py --auto      # 先自动探测出口 IP / 语言时区，再作答
python claude_risk_check.py --json      # 额外输出 JSON 结果
python claude_risk_check.py --no-color
```

作答时输入选项数字；`b` 返回上一题，`q` 退出。

**方式三：Windows 一键安装**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

脚本会：定位 Python → 复制全部运行文件到 `%USERPROFILE%\.claude-risk-check\` → 在 `%USERPROFILE%\.local\bin\` 注册全局命令 `claude-risk-check` → 自检并打印用法。可用参数：

| 参数 | 说明 |
| --- | --- |
| `-InstallDir` | 安装目录，默认 `%USERPROFILE%\.claude-risk-check` |
| `-BinDir` | launcher 输出目录，默认 `%USERPROFILE%\.local\bin` |
| `-Python` | 指定 Python 解释器完整路径 |
| `-NoLauncher` | 只复制文件，不注册全局命令 |
| `-Open` | 安装完成后用默认浏览器打开自检页 |

> 若要在任意终端直接敲 `claude-risk-check`，请确认 `%USERPROFILE%\.local\bin` 已在 PATH 中。

### 评分模型

- 每个维度取其问题的**平均风险值**（0 ~ 1）；
- 总分 = Σ（维度权重 × 维度平均风险），范围 0 ~ 100；
- 等级：`< 18` 低风险 · `18 ~ 40` 中等风险 · `40 ~ 65` 较高风险 · `≥ 65` 高风险。

网页版与 CLI 使用完全相同的模型与数据源，同一组答案得到相同的分数（取整已在两端统一为「四舍五入」，避免 Python 银行家舍入造成的偏差）。

### 标准来源与置信度

问卷条目在 `questions.json` 中均标注来源与置信度，常见来源：

- **Anthropic 官方文档**（Supported Countries / Usage Policy / Safeguards）——置信度 `high`
- **社区封号案例整理**（多篇高阅读量「Claude 封号避坑」长文）——置信度 `medium`
- **经验归纳 / 启发式推断**（无公开出处）——置信度 `low`

自动探测支持的**启发式关键字与支持国家列表**集中在 `questions.json` 的 `probe` 段，网页与 CLI 共用同一份，避免两端漂移。

### 测试与 CI

```bash
python scripts/build_questions.py --check      # 校验 questions.js 与数据源一致
python -m unittest discover -s tests -t . -v   # 运行全部测试
```

测试覆盖：数据源合法性、`questions.js` 与 `questions.json` 的一致性、评分阈值边界（18/40/65）、取整一致性、非法输入、探测分类逻辑、JSON 合法性。CI 在 Ubuntu 与 Windows、Python 3.9 与 3.12 上运行。

### 能验证到什么程度（重要）

| 能自动化验证 ✅ | 无法验证 ❌ |
| --- | --- |
| 两端一致性、可复现性、边界/阈值、JSON 合法性、编码 | 对**真实封号概率**的效度 |

原因：① 没有 ground truth——Anthropic 从不公开规则与真实标注；② 本工具本身的条目来自社区归纳，是「输入」而非「真值」；③ 自陈问卷存在偏差。若想提升效度，只能做**回溯性验证**：收集真实「已封 / 未封」案例打标签，看分数能否分离（例如 AUC）。这需要真实数据，本工具本身给不出。

### 目录结构

```
claude-risk-check/
├── index.html              # 网页自检页（外链 questions.js）
├── questions.js            # 生成的网页数据文件（勿手改）
├── questions.json          # 唯一数据源
├── claude_risk_check.py    # CLI 自检
├── probe.py                # 环境探测（CLI）
├── scripts/
│   ├── build_questions.py  # questions.json → questions.js
│   └── install.ps1         # Windows 一键安装
├── tests/                  # 单元测试
└── .github/workflows/ci.yml
```

---

## English

### What it is

A self-check tool for the "risk-control" exposure of your Claude account setup. It asks 16 questions across 8 weighted dimensions and reports a risk level plus a prioritized list of **things to adjust**. Three ways to use it: a **web page** (with environment detection, a scenario sandbox, and history) and a **CLI** with JSON output — both share the same scoring model and the same data source.

> **Disclaimer**: Anthropic does not publish an official rule such as "meet these N conditions and you get banned." This tool is a summary of widely reported ban cases from the community and Anthropic's public Safeguards documentation. It is **for self-check reference only** — it does not predict bans and does not guarantee evasion of platform rules. Use Claude in compliance with the Terms of Service and local laws.

### Files

| File | Description |
| --- | --- |
| [`index.html`](./index.html) | Web self-check page: gauge, per-dimension bars, action list, auto-detection, sandbox, history |
| [`questions.js`](./questions.js) | Web data file (generated from `questions.json`); **must sit next to `index.html`** |
| [`questions.json`](./questions.json) | **Single source of truth**: dimensions/weights/questions/options/advice/sources/confidence/probe config |
| [`claude_risk_check.py`](./claude_risk_check.py) | CLI reading `questions.json`; supports `--auto`, `--json`, `--no-color` |
| [`probe.py`](./probe.py) | Environment probing (exit-IP type/region, locale/timezone) used by the CLI |
| [`scripts/build_questions.py`](./scripts/build_questions.py) | Generates `questions.js` from `questions.json` and validates it |
| [`scripts/install.ps1`](./scripts/install.ps1) | Windows one-click installer |
| [`tests/`](./tests) | Unit tests (data parity, scoring boundaries, probe logic, encoding) |

> The web page is **no longer a single file**: under `file://` a browser cannot `fetch` a local JSON (blocked by same-origin policy), so data is loaded via `<script src="questions.js">`. Keep both files in the same directory.

### The 8 dimensions and weights

| Dimension | Weight | What to check |
| --- | --- | --- |
| Network environment | 25 | Residential vs. datacenter IP; stable and supported exit region |
| Usage behavior | 20 | 24/7 load, automation / bulk calls, usage intensity |
| Account age & warm-up | 15 | Account age, immediate top-up on a new account, hitting limits repeatedly |
| Account sharing | 15 | One-person-one-account; multi-location / multi-user logins |
| Environment fingerprint | 10 | Language/timezone consistency with exit region; cleaning residue before switching accounts |
| Access channel | 5 | Using CLI / third-party clients too early on a new account |
| Payment & subscription | 5 | Payment method and refund channel |
| Email & verification | 5 | Sign-up email type; phone number region |

### Quick start

**Option 1: Web page (easiest)**

Clone or download the repo, then open `index.html` (keep `questions.js` beside it).

- **Detect my environment**: reads your timezone / browser language and tries public APIs for the exit IP region and ASN, then pre-fills q1/q3/q11 (suggestions only — editable).
- **Scenario sandbox**: switch between "ideal / typical / high-risk" presets to compare scores before vs. after adjustments.
- **History**: each report is saved in browser localStorage so you can compare runs.

> Opened directly via `file://`, exit-IP detection may fail due to same-origin policy (everything else still works). For full detection, serve it over local HTTP or GitHub Pages.

**Option 2: CLI**

```bash
# Requires Python 3.8+
python claude_risk_check.py             # interactive quiz
python claude_risk_check.py --auto      # probe exit IP / locale first, then quiz
python claude_risk_check.py --json      # also emit a JSON result
python claude_risk_check.py --no-color
```

Type the option number to answer; `b` goes back, `q` quits.

**Option 3: One-click install on Windows**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

The script locates Python, copies all runtime files to `%USERPROFILE%\.claude-risk-check\`, registers a global `claude-risk-check` command in `%USERPROFILE%\.local\bin\`, self-verifies, and prints usage. Parameters:

| Parameter | Description |
| --- | --- |
| `-InstallDir` | Install directory, default `%USERPROFILE%\.claude-risk-check` |
| `-BinDir` | Launcher output directory, default `%USERPROFILE%\.local\bin` |
| `-Python` | Full path to a Python interpreter |
| `-NoLauncher` | Copy files only; do not register the global command |
| `-Open` | Open the web self-check page in your browser after install |

> To run `claude-risk-check` from any terminal, make sure `%USERPROFILE%\.local\bin` is on your PATH.

### Scoring model

- Each dimension takes the **average risk** of its questions (0 – 1);
- Total = Σ (dimension weight × dimension average risk), ranging 0 – 100;
- Levels: `< 18` Low · `18 – 40` Moderate · `40 – 65` Elevated · `≥ 65` High.

The web page and the CLI use the identical model and data source — the same answers always yield the same score (rounding is unified to "half-up" on both sides to avoid Python's banker's rounding).

### Sources & confidence

Every item in `questions.json` carries a source and a confidence level:

- **Anthropic official docs** (Supported Countries / Usage Policy / Safeguards) — `high`
- **Community ban-case write-ups** (widely read "avoiding Claude bans" posts) — `medium`
- **Experience-based / heuristic** (no public source) — `low`

The heuristic keywords and supported-country list used by detection live in the `probe` section of `questions.json`, shared by the web page and the CLI to prevent drift.

### Tests & CI

```bash
python scripts/build_questions.py --check      # verify questions.js matches the source
python -m unittest discover -s tests -t . -v   # run all tests
```

Coverage: data validity, `questions.js`/`questions.json` parity, score thresholds (18/40/65), rounding consistency, invalid input, probe classification, JSON validity. CI runs on Ubuntu and Windows with Python 3.9 and 3.12.

### What can and cannot be verified (important)

| Auto-verifiable ✅ | Not verifiable ❌ |
| --- | --- |
| Two-sided consistency, reproducibility, boundaries/thresholds, JSON validity, encoding | The **validity** against real ban probability |

Reasons: (1) no ground truth — Anthropic never publishes its rules or labels; (2) the items themselves come from community summaries — an input, not truth; (3) self-reported questionnaires are biased. Improving validity would require **retrospective validation**: collecting real banned/not-banned cases with labels and checking whether the score separates them (e.g. AUC). That needs real data the tool itself cannot produce.

### Repository layout

```
claude-risk-check/
├── index.html              # web self-check page (loads questions.js)
├── questions.js            # generated web data file (do not edit)
├── questions.json          # single source of truth
├── claude_risk_check.py    # CLI self-check
├── probe.py                # environment probing (CLI)
├── scripts/
│   ├── build_questions.py  # questions.json → questions.js
│   └── install.ps1         # Windows one-click installer
├── tests/                  # unit tests
└── .github/workflows/ci.yml
```

---

## License

MIT — see [LICENSE](./LICENSE).
