# Job Hunt Bot — Data Engineer
Auto-apply to LinkedIn, Naukri, Workday, Greenhouse, Lever

## Setup (one time)

### 1. Install Python libraries
```bash
pip install -r requirements.txt
```

### 2. Edit your profile
Open `config/profile.py` and fill in:
- Your name, email, phone, city
- LinkedIn password & Naukri password
- Path to your resume PDF

### 3. Add your resume
Put your resume PDF inside the `resume/` folder.
Update the path in `config/profile.py`:
```python
"resume_path": "resume/Your_Name_Data_Engineer.pdf"
```

---

## Running the Bot

### Test first (no browser, no login needed)
```bash
python main.py --test
```
Shows which jobs would be applied to based on your skills.

### Run LinkedIn only
```bash
python main.py --linkedin
```

### Run Naukri only
```bash
python main.py --naukri
```

### Run company career sites (Workday, Greenhouse, Lever)
Add URLs to `careers_bot.py` → `CAREER_URLS` list, then:
```bash
python main.py --careers
```

### Run everything
```bash
python main.py
```

### Run without visible browser (background mode)
```bash
python main.py --headless
```

### View today's application summary
```bash
python main.py --summary
```

---

## Career Sites Supported

| Platform  | Companies                              | Status     |
|-----------|----------------------------------------|------------|
| Workday   | Google, Microsoft, Apple, Salesforce  | ✅ Full auto |
| Greenhouse| Airbnb, Dropbox, many startups        | ✅ Full auto |
| Lever     | Many tech companies                    | ✅ Full auto |
| Naukri    | All Naukri listings                   | ✅ Full auto |
| LinkedIn  | LinkedIn Easy Apply jobs              | ✅ Full auto |
| Generic   | Any other career page                 | ⚠️ Fills form, you submit |

---

## Tracker

All applications are saved to `logs/job_applications.csv`.
Open in Excel / Google Sheets to track status.

Columns: Date | Company | Role | Portal | URL | Status | Match% | Skills | Follow Up Date

---

## Tips

- Run every morning — most jobs are posted between 9–11 AM
- Set `MIN_MATCH_SCORE = 25` in `config/profile.py` to apply more broadly
- Add more keywords to `SEARCH_KEYWORDS` for better coverage
- LinkedIn sometimes asks for CAPTCHA — just solve it manually and the bot continues
