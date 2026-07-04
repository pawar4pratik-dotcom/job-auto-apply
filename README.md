# 🤖 Job Auto Apply Bot

> AI-powered job application automation for **LinkedIn**, **Naukri**, and **Workday** portals — with a live Kanban dashboard, SQLite tracking, and GitHub-enriched AI scoring.

![Status](https://img.shields.io/badge/status-active-22c55e?style=flat-square)
![Python](https://img.shields.io/badge/python-3.11+-3b82f6?style=flat-square&logo=python)
![Flask](https://img.shields.io/badge/flask-dashboard-6b7280?style=flat-square)

---

## ✨ Features

| Feature | Description |
|---|---|
| 🔍 **Multi-portal automation** | LinkedIn Easy Apply, Naukri Quick Apply, Workday forms |
| 🧠 **2-stage AI scoring** | Keyword match + Gemini AI suitability score |
| 🗄️ **SQLite backend** | WAL-mode DB with auto CSV sync — no file lock crashes |
| 📊 **Live Kanban dashboard** | Drag-and-drop board with FSM state tracking |
| 📧 **Email progression monitor** | Auto-detects interview/rejection emails via IMAP |
| 🐙 **GitHub enrichment** | Pulls repo skills to boost AI match accuracy |
| ⚡ **Self-learning Q&A** | Bot learns answers to form questions over time |

---

## 🏗️ Architecture

```
job-auto-apply-bot/
├── app.py                  # Flask dashboard entry point (port 5006)
├── linkedin_bot.py         # LinkedIn Easy Apply automation
├── naukri_bot.py           # Naukri Quick Apply automation
├── careers_bot.py          # Workday / corporate careers bot
├── filter.py               # 2-stage AI job matching engine
├── tracker.py              # Dual-write CSV + SQLite tracker
├── email_monitor.py        # IMAP inbox progression monitor
├── core/
│   ├── database.py         # SQLite backend (WAL mode)
│   ├── github_enricher.py  # GitHub API skill extractor
│   ├── outreach_engine.py  # HR email outreach engine
│   ├── semantic_qa.py      # Semantic Q&A memory store
│   └── notifier.py         # Telegram / email alerts
├── routes/                 # Flask API blueprints
├── static/js/kanban.js     # Drag-and-drop Kanban board
├── templates/dashboard.html
└── config/
    └── profile.py          # Candidate profile & thresholds
```

---

## 🚀 Quick Start

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure credentials
```bash
# Create config/secrets.py (never committed)
cp config/secrets.example.py config/secrets.py
# Fill in: LinkedIn, Naukri, Gmail App Password, Gemini API Key
```

### 3. Set your profile
Edit `config/profile.py`:
```python
PROFILE = {
    'first_name': 'Your Name',
    'email': 'you@gmail.com',
    'github_username': 'your-github',  # Enables GitHub skill enrichment
    ...
}
MY_SKILLS = ['Python', 'AWS', 'PySpark', 'Snowflake', ...]
```

### 4. Launch the dashboard
```bash
python app.py
# Open http://localhost:5006
```

---

## 🧠 AI Scoring Engine

Every job goes through 2 stages before the bot applies:

1. **Stage A — Title match**: Fast keyword scoring against `ROLE_ALIASES`
2. **Stage B — Skill scan**: Keyword overlap between JD and `MY_SKILLS`
3. **Stage C (optional) — Gemini AI**: Full suitability score with reasoning + GitHub context

| Score | Decision |
|---|---|
| ≥ 75% | ✅ Auto Apply |
| 55–74% | ⏳ Review Queue |
| < 55% | ❌ Skip |

---

## 📊 Dashboard

Open `http://localhost:5006` to access:
- **Command Center** — Start/stop bots, live logs
- **Pipeline (Kanban)** — Drag-and-drop application tracking
- **Q&A Resolver** — Manage the bot's form-filling memory bank
- **Analytics** — Funnel charts, score distributions
- **HR Outreach** — Cold email campaign manager

---

## 🔒 Safety Features
- All new modules wrapped in `try/except` — CSV is always the fallback
- SQLite uses WAL mode — no read/write lock conflicts
- Secrets never leave `config/secrets.py` (gitignored)
- Bot rate-limits all API calls to avoid quota exhaustion

---

## 📋 Tech Stack
`Python 3.11` · `Flask` · `Selenium` · `SQLite` · `Google Gemini API` · `IMAP` · `GitHub API`
