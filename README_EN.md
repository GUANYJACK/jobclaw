[中文](./README.md)

```
       __      __    ________
      / /___  / /_  / ____/ /___ __      __
 __  / / __ \/ __ \/ /   / / __ `/ | /| / /
/ /_/ / /_/ / /_/ / /___/ / /_/ /| |/ |/ /
\____/\____/_.___/\____/_/\__,_/ |__/|__/
```

# JobClaw — Stop Applying Manually. Let AI Do the Grunt Work.

[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](./LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](./CONTRIBUTING.md)

> **TL;DR:** JobClaw is an open-source AI job hunting agent. It scrapes job listings from LinkedIn, Boss直聘, and JobsDB, matches them against your profile using LLMs, auto-applies to the best fits, and notifies you of results via Telegram or Discord.  
> You write the resume. JobClaw does the rest.

---

## 😩 The Problem

Job hunting is a grind. Everyone knows it:

- You scroll through **LinkedIn** for hours, tweaking keywords, opening tabs
- You read each JD manually to decide if it's worth applying
- You click "Easy Apply" dozens of times a day — same info, over and over
- Half the postings are ghost jobs where the recruiter hasn't logged in for months
- You lose track of what you applied to, what ghosted you, what's pending

Your time is better spent **preparing for interviews and building skills** — not being a human apply-bot.

---

## 🦀 What JobClaw Does

| Step | Manual | JobClaw |
| --- | --- | --- |
| 🔍 Find jobs | Jump between platforms, try different keywords | **Auto-scrape** LinkedIn + Boss直聘 + JobsDB |
| 📖 Evaluate fit | Read each JD, gut-feel it | **LLM-powered matching** with scores + explanations |
| 💬 Craft messages | Write custom intros for each role | **Auto-generated greetings** with template variables |
| 📤 Apply | Click "Apply" 100 times | **Auto-apply** to high-match roles |
| 🧹 Filter junk | Pure intuition, often wasted on ghost jobs | **Recruiter activity filter** — skip inactive postings |
| 📊 Track status | Spreadsheet? Sticky notes? Memory? | **Real-time Telegram / Discord notifications** |

**Set up your profile once. Let JobClaw work 24/7.**

---

## ✨ Key Features

### 🤖 LLM-Powered Matching Engine

Not simple keyword matching — JobClaw uses large language models to understand your background and job requirements, producing **match scores with explanations**.

**Three authentication methods (in priority order):**

| Priority | Method | Cost | Notes |
|----------|--------|------|-------|
| 🥇 | **Claude OAuth** | **Free** | Piggyback on your Claude Code subscription — zero API cost! |
| 🥈 | Anthropic API Key | Pay-per-use | Direct Claude API calls |
| 🥉 | OpenAI API Key | Pay-per-use | GPT model family |

> 💡 **Cost-saving tip:** If you have a Claude Code subscription ($20/month), JobClaw can reuse your OAuth token to call Claude — **no additional API cost whatsoever**. Tokens auto-refresh before expiry. Completely seamless.

### 📮 Boss直聘 Auto-Apply (China Market)

Boss直聘 has no public application API. JobClaw uses **Playwright browser automation** to simulate the full human interaction flow:

1. Open job page → Click "Start Chat"
2. Type greeting message → Send
3. Random delay → Next job

**Anti-detection measures:**

- ⏱️ **Random delays**: 3-8 seconds between actions (configurable)
- 📅 **Daily cap**: Default 100 applications/day to avoid rate limits
- 👻 **Ghost job filter**: Skip postings where HR hasn't been active for N days (default: 7)
- 🔄 **Dedup**: JSON history prevents re-applying to the same job
- 🤖 **CAPTCHA detection**: Auto-pauses and sends Telegram alert for manual intervention

**Greeting template:**

```
Hi! I'm very interested in the $title role at $company, $name. Would love to chat!
```

Variables: `$company`, `$title` (job title), `$name` (recruiter name)

### 🌏 JobsDB Auto-Apply (Hong Kong / APAC Market)

Full Quick Apply automation for the JobsDB platform:

1. Search jobs → Parse listing cards
2. Open job detail → Click "Quick Apply / Apply Now"
3. Auto-select existing resume or upload PDF
4. Submit application → Record history

**Enhanced anti-detection measures:**

- 🕶️ **Stealth mode**: Removes `navigator.webdriver` flag, spoofs `chrome.runtime`
- 🎭 **Random fingerprint**: Different User-Agent and viewport size each session
- 📜 **Human-like scrolling**: Randomized scroll distance + delay intervals
- ⏱️ **Random delays**: 5-12 seconds between applications (configurable)
- 📅 **Daily cap**: Default 50 applications/day
- 🔄 **Dedup**: History-based duplicate prevention
- 🤖 **CAPTCHA detection**: Auto-pauses and notifies on CAPTCHA
- 🔀 **API fallback**: Switches to GraphQL API when DOM scraping fails

### 🍪 Cookie Management

- `jobclaw login` — Opens browser for interactive login, cookies auto-saved to `~/.jobclaw/cookies/`
- `jobclaw login --check` — Verify saved cookies are still valid
- **Priority**: `.env` config > persisted files > prompt to re-login
- Supports Boss直聘 + LinkedIn + JobsDB

### 🔔 Notifications

Auto-report after each run:

- **Telegram Bot** — Set `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`
- **Discord Webhook** — Set `DISCORD_WEBHOOK_URL`

---

## 🚀 Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/VPC-byte/jobclaw.git
cd jobclaw
pip install -e .
```

### 2. Install Browser Runtime

```bash
playwright install chromium
```

### 3. Log in to Job Platforms

```bash
# Log in to LinkedIn (opens browser for manual login)
jobclaw login --platform linkedin

# Log in to Boss直聘
jobclaw login --platform boss

# Log in to JobsDB
jobclaw login --platform jobsdb

# Log in to all platforms at once
jobclaw login --platform all

# Check if saved cookies are still valid
jobclaw login --platform linkedin --check
```

### 4. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your settings (see [Configuration](#%EF%B8%8F-configuration) below).

### 5. Set Up Your Profile

```bash
cp profiles/example.yaml profiles/me.yaml
```

Edit `profiles/me.yaml` — your skills, salary expectations, preferred locations, etc.

### 6. Launch!

```bash
# Full pipeline: scrape → match → apply → notify
jobclaw run --profile profiles/me.yaml --query "AI Engineer"
```

Grab a coffee and wait for notifications ☕

---

## 🔧 CLI Reference

### `jobclaw login` — Platform Authentication

```bash
# Log in to LinkedIn
jobclaw login --platform linkedin

# Log in to Boss直聘
jobclaw login --platform boss

# Log in to JobsDB
jobclaw login --platform jobsdb

# Log in to all platforms
jobclaw login --platform all

# Set login timeout (minutes)
jobclaw login --platform linkedin --timeout 5

# Check cookie validity (no browser popup)
jobclaw login --platform linkedin --check
```

### `jobclaw scrape` — Scrape Only (No Applications)

```bash
# Scrape LinkedIn jobs
jobclaw scrape --platform linkedin --query "AI Engineer" --limit 20

# Scrape Boss直聘
jobclaw scrape --platform boss --query "后端工程师" --limit 20

# Scrape JobsDB (Hong Kong market)
jobclaw scrape --platform jobsdb --query "Python Developer" --limit 20

# Scrape all platforms
jobclaw scrape --platform all --query "Python Developer" --limit 30
```

> 💡 Use `scrape` first to check listing quality before running the full pipeline.

### `jobclaw run` — Full Pipeline

```bash
# Basic usage
jobclaw run --profile profiles/me.yaml --query "AI Engineer"

# Specific platform + limit
jobclaw run --platform linkedin --profile profiles/me.yaml --query "ML Engineer" --limit 20

# All platforms
jobclaw run --platform all --profile profiles/me.yaml --query "Backend Developer" --limit 50
```

### `jobclaw validate-profile` — Validate Profile YAML

```bash
jobclaw validate-profile --profile profiles/me.yaml
```

Catch YAML errors before running the pipeline.

---

## ⚙️ Configuration

### `.env` Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| **Core** | | | |
| `JOBCLAW_ENV` | No | `development` | Runtime environment |
| `JOBCLAW_LOG_LEVEL` | No | `INFO` | Log level |
| `JOBCLAW_HEADLESS` | No | `true` | Headless browser mode (set `false` to watch) |
| `JOBCLAW_MAX_JOBS` | No | `30` | Max jobs to process per run |
| `JOBCLAW_REQUEST_TIMEOUT` | No | `30` | Request timeout in seconds |
| **LLM** | | | |
| `CLAUDE_CREDENTIALS_PATH` | No | Auto-detect | Claude OAuth credentials (default: `~/.claude/.credentials.json`) |
| `CLAUDE_MODEL` | No | `claude-sonnet-4-6` | Model for Claude OAuth |
| `ANTHROPIC_API_KEY` | No | - | Anthropic API key |
| `OPENAI_API_KEY` | No | - | OpenAI API key |
| `JOBCLAW_LLM_MODEL` | No | `gpt-4o-mini` | Model for OpenAI |
| **Platform Cookies** | | | |
| `BOSS_COOKIE` | No | - | Boss直聘 cookie (overrides saved file) |
| `LINKEDIN_COOKIE` | No | - | LinkedIn cookie |
| `JOBSDB_COOKIE` | No | - | JobsDB cookie (overrides saved file) |
| **Boss直聘 Settings** | | | |
| `BOSS_GREETING` | No | - | Greeting template (`$company` `$title` `$name`) |
| `BOSS_APPLY_DELAY_MIN` | No | `3.0` | Min seconds between applications |
| `BOSS_APPLY_DELAY_MAX` | No | `8.0` | Max seconds between applications |
| `BOSS_DAILY_LIMIT` | No | `100` | Daily application cap (1-150) |
| `BOSS_SKIP_INACTIVE_DAYS` | No | `7` | Skip jobs where HR inactive for N days |
| **JobsDB Settings** | | | |
| `JOBSDB_RESUME_PATH` | No | - | Path to resume PDF for auto-upload |
| `JOBSDB_APPLY_DELAY_MIN` | No | `5.0` | Min seconds between applications |
| `JOBSDB_APPLY_DELAY_MAX` | No | `12.0` | Max seconds between applications |
| `JOBSDB_DAILY_LIMIT` | No | `50` | Daily application cap (1-100) |
| **Notifications** | | | |
| `TELEGRAM_BOT_TOKEN` | No | - | Telegram Bot token |
| `TELEGRAM_CHAT_ID` | No | - | Telegram Chat ID |
| `DISCORD_WEBHOOK_URL` | No | - | Discord Webhook URL |
| **Network** | | | |
| `HTTP_PROXY` | No | - | HTTP proxy |
| `HTTPS_PROXY` | No | - | HTTPS proxy |

> 🆓 **Claude OAuth (Zero-Cost LLM):** Install Claude Code CLI (`npm i -g @anthropic-ai/claude-code`), log in with your subscription, and JobClaw auto-detects `~/.claude/.credentials.json`. **No API key needed, no extra cost.** Token auto-refreshes before expiry.

### `profiles/me.yaml` — Job Seeker Profile

```yaml
name: "Jane Doe"
email: "jane@example.com"
years_experience: 3

summary: >
  Full-stack developer with experience in AI/ML applications,
  cloud infrastructure, and DevOps. Looking for AI Agent roles.

skills:
  - Python
  - TypeScript
  - LLM/Agent Development
  - Kubernetes
  - Docker
  - AWS/GCP

desired_roles:
  - AI Agent Developer
  - LLM Application Engineer
  - MLOps Engineer
  - Backend Developer (AI)

preferences:
  locations:
    - "San Francisco"
    - "remote"
  salary_min: 120000   # Annual, USD
  salary_max: 200000
  work_schedule: "flexible"
  industries:
    - AI
    - Web3
    - Cloud
  deal_breakers:
    - "no remote option"
    - "contract only"
```

---

## 🏗️ Architecture

```text
+---------------------+
|   Profile Loader    |  Your resume / preferences (YAML)
+----------+----------+
           |
           v
+---------------------+      +----------------------+
|   Scraper Layer     |----->| Unified Job Objects  |
| LinkedIn / Boss直聘 |      | (Pydantic Models)    |
| / JobsDB            |      +----------+-----------+
           |                            |
           v                            v
+---------------------+      +----------------------+
|   LLM Matcher       |----->| Match Score + Reason |
| Claude OAuth/API/   |      | (SSE streaming)      |
| OpenAI              |      +----------+-----------+
+----------+----------+                 |
           |                            v
+---------------------+      +----------------------+
|  Auto Applier       |----->| Application Status   |
| LinkedIn / Boss直聘 |      | Applied / Failed /   |
| / JobsDB            |      | Skipped              |
           |                 +----------+-----------+
           +------------+---------------+
                        v
              +--------------------+
              | Notification Layer |
              | Telegram / Discord |
              +--------------------+
```

## 📂 Project Structure

```text
jobclaw/
  applier/                 # Auto-application engines
    base.py                #   Applier base class
    boss.py                #   Boss直聘 (greeting + anti-detection)
    linkedin.py            #   LinkedIn Easy Apply
    jobsdb.py              #   JobsDB Quick Apply (anti-detection + auto resume)
    captcha.py             #   CAPTCHA detection + notification
    history.py             #   Application history (dedup)
  auth/                    # Authentication
    browser_login.py       #   Playwright interactive browser login
    cookie_manager.py      #   Cookie persistence manager
    claude_auth.py         #   Claude OAuth credential reader
    token_refresh.py       #   OAuth token auto-refresh
  matcher/                 # LLM matching engine
    llm_matcher.py         #   Multi-provider match scoring
  models/                  # Claude API client
    claude_api.py          #   Claude API wrapper
    streaming.py           #   SSE streaming + retry/backoff
  notifier/                # Notifications
    telegram.py            #   Telegram Bot notifications
    discord.py             #   Discord Webhook notifications
  profile/                 # Profile loading
    loader.py              #   YAML profile parser
  scraper/                 # Job scrapers
    base.py                #   Scraper base class
    boss.py                #   Boss直聘 scraper
    linkedin.py            #   LinkedIn scraper
    jobsdb.py              #   JobsDB scraper (anti-detection + API fallback)
  cli.py                   # CLI entry point (Click)
  config.py                # Configuration (pydantic-settings)
  domain.py                # Data models (Pydantic)
profiles/
  example.yaml             # Profile template
docs/
  architecture.md          # Architecture docs
tests/
  test_models.py           # Tests
```

## 📋 Platform Support

| Platform | Scraping | Applying | Notes |
| --- | --- | --- | --- |
| **LinkedIn** | ✅ | ✅ | Easy Apply automation |
| **Boss直聘** (zhipin.com) | ✅ | ✅ | Playwright-simulated greeting |
| **JobsDB** (jobsdb.com) | ✅ | ✅ | Quick Apply + auto resume (HK/APAC market) |
| Lagou (拉勾) | 🔜 | 🔜 | Adapter in development |
| 51Job (前程无忧) | 🔜 | 🔜 | Adapter in development |

---

## 🤝 Contributing

PRs welcome! Especially:

- 🔌 **New platform adapters** (Indeed, Glassdoor, Lagou, JobStreet…)
- 🧠 **Better matching strategies** (prompt tuning, multi-dimensional scoring)
- 🔒 **Reliability improvements** (anti-detection, checkpoint/resume)
- 📢 **New notification channels** (Slack, WeChat, email)

```bash
pip install -e .[dev]
pytest -q
```

Please run tests, add type hints, and update docs before submitting.

## ⚠️ Disclaimer

Automated interaction with job platforms may be subject to their terms of service and local regulations. Use this tool responsibly, within your authorized scope. The authors are not liable for misuse.

## 📜 License

MIT License — see [LICENSE](./LICENSE).
