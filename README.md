# Claude 账号风控自检 · Claude Account Risk Self-Check

[中文](#中文) | [English](#english)

一个帮助用户自查 Claude 使用环境中「风控风险」的小工具：回答 16 道题，按 8 个维度加权打分，给出风险等级与**需要调整的方面**清单。

> **免责声明**：Anthropic 并未公开「满足某几条即封号」的官方规则。本工具基于社区大量封号案例与 Anthropic 公开 Safeguards 文档归纳，**仅供自查参考，不代表对封号结果的预测，也不构成规避平台规则的保证**。请在符合服务条款与当地法规的前提下使用 Claude。

---

## 中文

### 这是什么

国内用户使用 Claude（尤其 Claude Code）时，账号被风控/封禁往往不是因为违规，而是网络环境、使用行为、账号年龄等细节踩到了敏感线。本工具把公开资料中被反复印证的触发点整理成一份**可打分的自检问卷**，帮你在出问题前定位并调整。

### 两个产物

| 文件 | 说明 |
| --- | --- |
| [`index.html`](./index.html) | 单文件网页自检页，零依赖，双击浏览器打开即用；含分数圆环、维度分布条、待调整清单 |
| [`claude_risk_check.py`](./claude_risk_check.py) | 命令行版本，与网页版共用同一套评分模型；支持 `--json`（机器可读结果）、`--no-color` |

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

克隆或下载本仓库后，直接双击 `index.html` 即可。

**方式二：命令行**

```bash
# 需要 Python 3.8+
python claude_risk_check.py          # 交互式作答
python claude_risk_check.py --json   # 额外输出 JSON 结果
python claude_risk_check.py --no-color
```

作答时输入选项数字；`b` 返回上一题，`q` 退出。

**方式三：Windows 一键安装**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

脚本会：定位 Python → 复制工具到 `%USERPROFILE%\.claude-risk-check\` → 在 `%USERPROFILE%\.local\bin\` 注册全局命令 `claude-risk-check` → 自检并打印用法。可用参数：

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

网页版与 CLI 使用完全相同的模型，同一组答案得到相同的分数。

### 目录结构

```
claude-risk-check/
├── index.html            # 网页版自检页（单文件）
├── claude_risk_check.py  # CLI 自检（与网页版同模型）
└── scripts/
    └── install.ps1       # Windows 一键安装脚本
```

---

## English

### What it is

A self-check tool for the "risk-control" exposure of your Claude account setup. It asks 16 questions across 8 weighted dimensions and reports a risk level plus a prioritized list of **things to adjust**.

> **Disclaimer**: Anthropic does not publish an official rule such as "meet these N conditions and you get banned." This tool is a summary of widely reported ban cases from the community and Anthropic's public Safeguards documentation. It is **for self-check reference only** — it does not predict bans and does not guarantee evasion of platform rules. Use Claude in compliance with the Terms of Service and local laws.

### Two deliverables

| File | Description |
| --- | --- |
| [`index.html`](./index.html) | Single-file web self-check page, zero dependencies — just open it in a browser. Includes a score gauge, per-dimension bars, and an action list |
| [`claude_risk_check.py`](./claude_risk_check.py) | CLI version sharing the exact same scoring model; supports `--json` (machine-readable) and `--no-color` |

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

Clone or download this repo, then open `index.html` in your browser.

**Option 2: CLI**

```bash
# Requires Python 3.8+
python claude_risk_check.py          # interactive quiz
python claude_risk_check.py --json   # also emit a JSON result
python claude_risk_check.py --no-color
```

Type the option number to answer; `b` goes back, `q` quits.

**Option 3: One-click install on Windows**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

The script locates Python, copies the tool to `%USERPROFILE%\.claude-risk-check\`, registers a global `claude-risk-check` command in `%USERPROFILE%\.local\bin\`, self-verifies, and prints usage. Parameters:

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

The web page and the CLI use the identical model — the same answers always yield the same score.

### Repository layout

```
claude-risk-check/
├── index.html            # Web self-check page (single file)
├── claude_risk_check.py  # CLI self-check (same model as the web page)
└── scripts/
    └── install.ps1       # Windows one-click installer
```

---

## License

MIT — see [LICENSE](./LICENSE).
