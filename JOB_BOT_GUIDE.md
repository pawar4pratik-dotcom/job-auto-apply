# 🤖 Job Auto Apply Bot: Migration & Feature Guide

This guide documents the upgrades applied to the active codebase, details the design systems implemented, and outlines how to migrate the bot and its context to another conversation or workspace.

---

## 🎯 Active Files Modified

All modifications were applied to the **live active project files** in the workspace directory, **NOT** legacy/old versions:
1. **Frontend UI**: [templates/dashboard_react.html](templates/dashboard_react.html)
   - Modified `JobPipelineTab` using Babel React JSX to render a sleek, glassmorphic 5-column Kanban Board with HTML5 drag-and-drop.
   - Added a purple toggle button to switch between the Kanban View and the searchable List View.
   - Implemented score-coloured left border strips on job cards (Green: $\ge 75\%$, Amber: $55-74\%$, Coral/Red: $< 55\%$).
   - Embedded portal badges (LinkedIn, Naukri, Indeed) and quick link icons (`↗`).
2. **Backend API**: [routes/data_routes.py](routes/data_routes.py)
   - Wired up `/api/applications/status` (POST) to handle drag-and-drop status changes, calling `tracker.update_status()`.
   - Implemented `/api/kanban` to serve status aggregates.
3. **Configuration**: [config/profile.py](config/profile.py)
   - Added `github_username` to the core user profile to support GitHub enrichment.
4. **Security & Vcs**: [.gitignore](.gitignore)
   - Hardened repository tracking to prevent leaking local database cache, logs, session data, and secret keys.

---

## ⚙️ Implemented Processes & Upgrades

| Dimension | Previous State (Legacy) | New Active State (Current Bot) | Key Benefit |
|---|---|---|---|
| **UI Aesthetics & Layout** | Basic HTML portal with standard text layouts. | Sleek glassmorphic Dark Theme with Kanban drag-and-drop and instant List-view toggles. | High visual appeal; drag-and-drop job status updates. |
| **Match Engine** | Simple keyword density calculations. | Multi-vector explaining grading cards with colour-coded match levels (Green, Amber, Coral). | Instant visibility of score match reasons. |
| **Application Tracking** | Manual checks and OTP intercept. | FSM-validated Kanban updates + AI-driven IMAP email checking (`email_monitor.py`). | Prevents illegal state transitions (e.g. Reject $\to$ Offer); auto-tracks incoming emails. |
| **Candidate Profiling** | Static profile properties. | Dynamic GitHub-enriched skill parsing (pulls public repos). | Auto-appends active tech stack to profile score. |

---

## 🔄 How to Move this Bot to a New Conversation

If you need to start a new chat session or carry this project to another machine/workspace, follow these steps to ensure the new AI assistant has full context immediately:

### Step 1: Copy/Package the Project Folder
Copy or compress the entire project directory:
`C:\Users\Pratik\Downloads\job auto apply`
*(Note: `.gitignore` protects your personal database, credentials, and secrets from being committed/copied to public areas).*

### Step 2: Initialize in the New Conversation
When starting the new conversation, send a prompt pointing the AI assistant to this guide:
> "Hello! I am resuming work on my Job Auto Apply Bot project. Please read `JOB_BOT_GUIDE.md` first to understand the active code files, architecture, and features we implemented."

### Step 3: Run Setup and Launch
To start the bot and open the glassmorphic dashboard:
1. Run `pip install -r requirements.txt` (if moving to a new machine).
2. Launch the Flask server:
   ```bash
   python app.py
   ```
3. Open `http://localhost:5006` in your browser.
4. If the page doesn't show the Kanban Columns in the **Pipeline** tab, perform a hard refresh:
   - **Chrome/Firefox**: Press `Ctrl + Shift + R` or `Cmd + Shift + R`
   - **Safari**: Press `Cmd + Option + E` then reload.

---

## 🔒 Email & LinkedIn Data Extraction Process
- **LinkedIn / Naukri Scraping**: The scrapers in `scrapers/` automatically launch a selenium browser instance (configured in `browser.py`), navigate to job posts, and parse the job descriptions.
- **Match Engine**: Computes compatibility score based on skills, experience, and GitHub repo details.
- **Outreach Engine**: When a match is found and applied, `outreach_engine.py` generates custom-tailored outreach emails to HR/Recruiters (retrieved from job listings or search pages) and sends them to bypass spam firewalls.
