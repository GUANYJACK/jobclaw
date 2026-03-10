[English](./README_EN.md)

```
       __      __    ________
      / /___  / /_  / ____/ /___ __      __
 __  / / __ \/ __ \/ /   / / __ `/ | /| / /
/ /_/ / /_/ / /_/ / /___/ / /_/ /| |/ |/ /
\____/\____/_.___/\____/_/\__,_/ |__/|__/
```

# JobClaw — AI 帮你投简历，你只管躺平

[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](./LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](./CONTRIBUTING.md)

> **一句话说清楚：** JobClaw 是一个开源的 AI 求职 Agent——自动抓岗位、用大模型帮你匹配、一键批量投递，投完还给你发 Telegram/Discord 消息汇报。支持 Boss直聘、LinkedIn、JobsDB 三大平台。  
> 你要做的，就是写好简历，然后等面试通知。

---

## 😩 痛点：求职为什么这么累？

每个找过工作的人都懂：

- **Boss直聘刷到手酸**，一个个点进去看 JD，看完觉得不太行，退出来继续刷
- 好不容易看到一个还行的，点"立即沟通"，想半天打招呼说啥，发完又没下文
- 一天下来投了十几个，回复的寥寥无几，**时间全花在重复劳动上**
- 有些岗位 HR 三个月没上线了，你还在那认真写打招呼语——**投了个寂寞**
- LinkedIn 也要刷，拉勾也要看，JobsDB 也要投，多平台来回切，脑子都乱了
- 投完之后**石沉大海**，哪个回了、哪个没回，全靠记忆

你的时间应该花在**准备面试和提升自己**上，不是当人肉投递机器。

---

## 🦀 JobClaw 帮你做什么？

| 步骤 | 人工操作 | JobClaw |
| --- | --- | --- |
| 🔍 搜岗位 | 多平台来回切，关键词一个个试 | **自动抓取** Boss直聘 + LinkedIn + JobsDB |
| 📖 看 JD | 一个个点开，人肉阅读判断匹不匹配 | **LLM 智能匹配**，打分 + 给出匹配理由 |
| 💬 打招呼 | 想措辞、复制粘贴、一个个发 | **自动生成打招呼语**，支持模板变量 |
| 📤 投简历 | 点「立即沟通」重复 100 遍 | **自动批量投递**高匹配岗位 |
| 🧹 过滤垃圾 | 全靠直觉，经常投到僵尸岗 | **HR 活跃度过滤**，跳过僵尸岗 |
| 📊 跟进状态 | Excel？备忘录？全靠脑子？ | **Telegram / Discord 实时通知** |

**简单说：你配好简历和偏好，JobClaw 帮你 24 小时无休投递。**

---

## ✨ 核心功能

### 🤖 LLM 智能匹配引擎

不是简单的关键词匹配，而是用大模型理解你的背景和岗位要求，给出**匹配分数 + 匹配理由**。

**四种 LLM 认证方式（优先级递减）：**

| 优先级 | 方式 | 费用 | 说明 |
|--------|------|------|------|
| 🥇 | **Claude OAuth** | **免费** | 白嫖 Claude Code 订阅额度，零 API 费用！ |
| 🥈 | **GitHub Copilot** | **免费** | 白嫖 Copilot 订阅额度，零 API 费用！ |
| 🥉 | Anthropic API Key | 按量付费 | 直接调用 Claude API |
| 4️⃣ | OpenAI API Key | 按量付费 | 调用 GPT 系列模型 |

> 💡 **省钱秘籍：** 如果你有 Claude Code 订阅（$20/月）或 GitHub Copilot 订阅（$10/月），JobClaw 可以直接复用你的 OAuth token 调用 LLM，**不额外花一分钱**。Token 过期会自动刷新，完全无感。

### 📮 Boss直聘自动投递（核心卖点）

这不是简单的 API 调用——Boss直聘没有公开投递 API。JobClaw 用 **Playwright 模拟真人浏览器操作**，完整复现投递流程：

1. 打开岗位页面 → 点击"立即沟通"
2. 输入打招呼消息 → 点击发送
3. 等待随机延迟 → 下一个

**防封策略：**

- ⏱️ **随机延迟**：每次投递间隔 3-8 秒（可配置），模拟人类节奏
- 📅 **每日上限**：默认 100 次/天，避免触发风控
- 👻 **僵尸岗过滤**：跳过 HR 超过 N 天未活跃的岗位（默认 7 天）
- 🔄 **防重复投递**：JSON 历史记录，已沟通过的自动跳过
- 🤖 **验证码检测**：遇到验证码自动暂停，发 Telegram 通知你人工处理

**打招呼消息模板：**

```
你好！我对贵公司 $title 岗位很感兴趣，$name，方便聊聊吗？
```

支持变量：`$company`（公司名）、`$title`（岗位名）、`$name`（HR 名字）

### 🌏 JobsDB 自动投递（港澳市场）

针对香港求职市场的 JobsDB 平台，JobClaw 实现了完整的 Quick Apply 自动投递流程：

1. 搜索岗位 → 解析职位列表
2. 打开职位详情 → 点击"Quick Apply / Apply Now"
3. 自动选择已有简历 / 上传 PDF 简历
4. 提交申请 → 记录历史

**反爬策略（针对 JobsDB 强化）：**

- 🕶️ **隐身模式**：移除 `navigator.webdriver` 标识，伪装 `chrome.runtime`
- 🎭 **随机指纹**：每次使用不同的 User-Agent 和视口尺寸
- 📜 **人类模拟滚动**：随机滚动距离 + 随机间隔，触发懒加载
- ⏱️ **随机延迟**：投递间隔 5-12 秒（可配置）
- 📅 **每日上限**：默认 50 次/天
- 🔄 **防重复投递**：历史记录去重
- 🤖 **验证码检测**：检测到验证码自动暂停并通知
- 🔀 **API 降级**：DOM 抓取失败时自动切换到 GraphQL API

### 🍪 Cookie 管理

- `jobclaw login` — 弹出浏览器，交互式登录，cookie 自动保存到 `~/.jobclaw/cookies/`
- `jobclaw login --check` — 检查已保存的 cookie 是否还有效
- **优先级**：`.env` 中配置的 cookie > 持久化文件 > 提示你重新 login
- 支持 Boss直聘 + LinkedIn + JobsDB

### 🔔 通知

投递完成后自动汇报：

- **Telegram Bot** — 配置 `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`
- **Discord Webhook** — 配置 `DISCORD_WEBHOOK_URL`

---

## 🚀 快速开始

### 1. 克隆 & 安装

```bash
git clone https://github.com/VPC-byte/jobclaw.git
cd jobclaw
pip install -e .
```

### 2. 安装浏览器内核

```bash
playwright install chromium
```

### 3. 登录求职平台

```bash
# 登录 Boss直聘（弹出浏览器，手动扫码/登录）
jobclaw login --platform boss

# 登录 LinkedIn
jobclaw login --platform linkedin

# 登录 JobsDB
jobclaw login --platform jobsdb

# 登录 GitHub Copilot（设备码认证）
jobclaw login --platform copilot

# 一次性登录所有平台
jobclaw login --platform all

# 检查 cookie 是否有效
jobclaw login --platform boss --check
```

### 4. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，根据需要填写（详见下方[配置说明](#-配置说明)）。

### 5. 填写求职画像

**方式一：AI 引导（推荐）**

```bash
jobclaw init-profile
```

回答 13 个简单问题，AI 自动帮你生成标准画像文件。

**方式二：手动编辑**

```bash
cp profiles/example.yaml profiles/me.yaml
```

编辑 `profiles/me.yaml`——你的技能、期望薪资、偏好城市等。

### 6. 开跑！

```bash
# 完整流程：抓取 → 匹配 → 投递 → 通知
jobclaw run --profile profiles/me.yaml --query "Python 工程师"
```

跑起来之后去喝杯咖啡，等 Telegram 通知就行 ☕

---

## 🔧 CLI 命令全集

### `jobclaw login` — 登录平台

```bash
# 登录 Boss直聘
jobclaw login --platform boss

# 登录 LinkedIn
jobclaw login --platform linkedin

# 登录 JobsDB
jobclaw login --platform jobsdb

# 登录 GitHub Copilot（设备码认证，无需浏览器）
jobclaw login --platform copilot

# 登录所有支持的平台
jobclaw login --platform all

# 设置登录超时（分钟）
jobclaw login --platform boss --timeout 5

# 检查 cookie 有效性（不弹浏览器）
jobclaw login --platform boss --check
```

### `jobclaw scrape` — 只抓取，不投递

```bash
# 抓取 Boss直聘上的岗位
jobclaw scrape --platform boss --query "后端工程师" --limit 20

# 抓取 LinkedIn
jobclaw scrape --platform linkedin --query "AI Engineer" --limit 10

# 抓取 JobsDB（香港市场）
jobclaw scrape --platform jobsdb --query "Python Developer" --limit 20

# 全平台抓取
jobclaw scrape --platform all --query "Python 开发" --limit 30
```

> 💡 先用 `scrape` 看看抓到的岗位质量，再决定要不要跑完整流程。

### `jobclaw run` — 完整流程

```bash
# 基础用法
jobclaw run --profile profiles/me.yaml --query "AI 工程师"

# 指定平台 + 限制数量
jobclaw run --platform boss --profile profiles/me.yaml --query "大模型工程师" --limit 20

# 全平台
jobclaw run --platform all --profile profiles/me.yaml --query "后端开发" --limit 50
```

### `jobclaw init-profile` — AI 引导生成求职画像

```bash
# 交互式问答，AI 生成画像
jobclaw init-profile

# 指定输出路径
jobclaw init-profile -o profiles/custom.yaml
```

回答 13 个问题（名字、技能、期望薪资等），AI 自动生成标准 YAML 画像文件。内置校验和纠错机制，确保生成内容合法。

### `jobclaw validate-profile` — 校验画像文件

```bash
jobclaw validate-profile --profile profiles/me.yaml
```

确认你的 YAML 格式没问题再跑，避免跑到一半报错。

---

## ⚙️ 配置说明

### `.env` 环境变量

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| **核心运行时** | | | |
| `JOBCLAW_ENV` | 否 | `development` | 运行环境 |
| `JOBCLAW_LOG_LEVEL` | 否 | `INFO` | 日志级别 |
| `JOBCLAW_HEADLESS` | 否 | `true` | 浏览器是否无头模式（调试时设 `false` 看操作过程） |
| `JOBCLAW_MAX_JOBS` | 否 | `30` | 单次最大处理岗位数 |
| `JOBCLAW_REQUEST_TIMEOUT` | 否 | `30` | 网络请求超时（秒） |
| **LLM 配置** | | | |
| `CLAUDE_CREDENTIALS_PATH` | 否 | 自动检测 | Claude OAuth 凭证路径（默认 `~/.claude/.credentials.json`） |
| `CLAUDE_MODEL` | 否 | `claude-sonnet-4-6` | Claude OAuth 使用的模型 |
| `ANTHROPIC_API_KEY` | 否 | - | Anthropic API Key |
| `OPENAI_API_KEY` | 否 | - | OpenAI API Key |
| `JOBCLAW_LLM_MODEL` | 否 | `gpt-4o-mini` | OpenAI 使用的模型 |
| **GitHub Copilot** | | | |
| `COPILOT_MODEL` | 否 | `gpt-4o` | Copilot Chat 使用的模型 |
| **平台 Cookie** | | | |
| `BOSS_COOKIE` | 否 | - | Boss直聘 cookie（优先于持久化文件） |
| `LINKEDIN_COOKIE` | 否 | - | LinkedIn cookie |
| `JOBSDB_COOKIE` | 否 | - | JobsDB cookie（优先于持久化文件） |
| **Boss直聘专属** | | | |
| `BOSS_GREETING` | 否 | - | 打招呼模板，支持 `$company` `$title` `$name` 变量 |
| `BOSS_APPLY_DELAY_MIN` | 否 | `3.0` | 投递间隔最小秒数 |
| `BOSS_APPLY_DELAY_MAX` | 否 | `8.0` | 投递间隔最大秒数 |
| `BOSS_DAILY_LIMIT` | 否 | `100` | 每日投递上限（1-150） |
| `BOSS_SKIP_INACTIVE_DAYS` | 否 | `7` | 跳过 HR 多少天未活跃的岗位 |
| **JobsDB 专属** | | | |
| `JOBSDB_RESUME_PATH` | 否 | - | 简历 PDF 路径，用于 JobsDB 自动上传 |
| `JOBSDB_APPLY_DELAY_MIN` | 否 | `5.0` | 投递间隔最小秒数 |
| `JOBSDB_APPLY_DELAY_MAX` | 否 | `12.0` | 投递间隔最大秒数 |
| `JOBSDB_DAILY_LIMIT` | 否 | `50` | 每日投递上限（1-100） |
| **通知** | | | |
| `TELEGRAM_BOT_TOKEN` | 否 | - | Telegram Bot Token |
| `TELEGRAM_CHAT_ID` | 否 | - | Telegram Chat ID |
| `DISCORD_WEBHOOK_URL` | 否 | - | Discord Webhook URL |
| **网络** | | | |
| `HTTP_PROXY` | 否 | - | HTTP 代理 |
| `HTTPS_PROXY` | 否 | - | HTTPS 代理 |

> 🆓 **零成本 LLM 方案：**
> - **Claude OAuth：** 安装 Claude Code CLI（`npm i -g @anthropic-ai/claude-code`）并登录，JobClaw 自动检测 OAuth token。
> - **GitHub Copilot：** 运行 `jobclaw login --platform copilot`，用 GitHub 账号授权，直接使用 Copilot 订阅额度。
> 两种方式都**无需 API Key，零额外费用**。

### `profiles/me.yaml` 求职画像

```yaml
name: "张三"
email: "zhangsan@example.com"
years_experience: 3

summary: >
  全栈开发，擅长 AI/ML 应用、云基础设施和 DevOps。
  目前在找 AI Agent 相关的岗位。

skills:
  - Python
  - TypeScript
  - LLM/Agent 开发
  - Kubernetes
  - Docker
  - AWS/GCP

desired_roles:
  - AI Agent 开发工程师
  - 大模型应用工程师
  - 后端开发（AI 方向）

preferences:
  locations:
    - "深圳"
    - "remote"
  salary_min: 25000
  salary_max: 50000
  work_schedule: "双休"
  industries:
    - AI
    - Web3
    - Cloud
  deal_breakers:
    - "996"
    - "大小周"
    - "无社保"
```

---

## 🏗️ 架构

```text
+---------------------+
|   Profile Loader    |  你的简历 / 求职画像 (YAML)
+----------+----------+
           |
           v
+---------------------+      +----------------------+
|   Scraper Layer     |----->| Unified Job Objects  |
| Boss直聘 / LinkedIn |      | (Pydantic 标准化)     |
| / JobsDB            |      +----------+-----------+
           |                            |
           v                            v
+---------------------+      +----------------------+
|   LLM Matcher       |----->| 匹配分数 + 匹配理由   |
| Claude OAuth/API/   |      | (SSE streaming)      |
| OpenAI              |      +----------+-----------+
+----------+----------+                 |
           |                            v
+---------------------+      +----------------------+
|  Auto Applier       |----->| 投递状态              |
| Boss直聘 / LinkedIn |      | 已投 / 失败 / 跳过    |
| / JobsDB            |      +----------+-----------+
           |                            |
           +------------+---------------+
                        v
              +--------------------+
              | Notification Layer |
              | Telegram / Discord |
              +--------------------+
```

## 📂 项目结构

```text
jobclaw/
  applier/                 # 自动投递
    base.py                #   投递器基类
    boss.py                #   Boss直聘投递（打招呼 + 防封策略）
    linkedin.py            #   LinkedIn Easy Apply
    jobsdb.py              #   JobsDB Quick Apply（反爬 + 自动选简历）
    captcha.py             #   验证码检测 + 通知
    history.py             #   投递历史记录（防重复）
  auth/                    # 登录认证
    browser_login.py       #   Playwright 交互式浏览器登录
    cookie_manager.py      #   Cookie 持久化管理
    claude_auth.py         #   Claude OAuth 凭证读取
    token_refresh.py       #   OAuth token 自动刷新
  matcher/                 # LLM 匹配引擎
    llm_matcher.py         #   多 provider 匹配打分
  models/                  # Claude API 客户端
    claude_api.py          #   Claude API 封装
    streaming.py           #   SSE streaming + retry/backoff
  notifier/                # 通知
    telegram.py            #   Telegram Bot 通知
    discord.py             #   Discord Webhook 通知
  profile/                 # 画像加载
    loader.py              #   YAML 画像解析
  scraper/                 # 爬虫
    base.py                #   爬虫基类
    boss.py                #   Boss直聘抓取
    linkedin.py            #   LinkedIn 抓取
    jobsdb.py              #   JobsDB 抓取（反爬 + API 降级）
  cli.py                   # CLI 入口（Click）
  config.py                # 配置管理（pydantic-settings）
  domain.py                # 数据模型（Pydantic）
profiles/
  example.yaml             # 画像模板
docs/
  architecture.md          # 架构设计文档
tests/
  test_models.py           # 测试
```

## 📋 支持平台

| 平台 | 抓取 | 投递 | 说明 |
| --- | --- | --- | --- |
| **Boss直聘** (zhipin.com) | ✅ | ✅ | Playwright 模拟打招呼 |
| **LinkedIn** | ✅ | ✅ | Easy Apply 自动投递 |
| **JobsDB** (jobsdb.com) | ✅ | ✅ | Quick Apply + 自动选简历（港澳市场） |
| 拉勾 (Lagou) | 🔜 | 🔜 | 适配器开发中 |
| 前程无忧 (51Job) | 🔜 | 🔜 | 适配器开发中 |

---

## 🤝 参与贡献

欢迎 PR！特别欢迎：

- 🔌 **新平台适配器**（拉勾、前程无忧、猎聘……）
- 🧠 **更好的匹配策略**（prompt 调优、多维度评分）
- 🔒 **稳定性改进**（反爬对抗、断点续跑）
- 📢 **新通知渠道**（微信、飞书、钉钉）

```bash
pip install -e .[dev]
pytest -q
```

提 PR 前请跑测试、加类型标注、更新相关文档。

## ⚠️ 合规声明

自动化操作求职平台可能受到平台条款和当地法律的限制。请在合法合规、个人授权范围内使用本项目。作者不对滥用行为承担责任。

## 📜 许可证

MIT License — 详见 [LICENSE](./LICENSE)。
