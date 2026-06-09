# 🎯 JobHunter — Automated Cybersecurity Job Pipeline

**Free, self-hosted, VPS-deployable job hunter.**
Scrapes 10+ job boards, scores matches against your profile, sends email alerts with tailored cover letters, and lets you apply by replying "apply" to an email.

Built for cybersecurity professionals. Open-source and configurable for any field.

---

## What It Does

1. **Scrapes** LinkedIn, Indeed (CA + US), Dice, USAJobs, Adzuna, RemoteOK, InfoSecJobs and more every 90 minutes
2. **Scores** each job 0–100 against your target roles, keywords, salary, and work type
3. **Filters** out non-cybersecurity roles automatically
4. **Emails you** the top matches with a tailored cover letter already written
5. **Reply "apply"** to any email → system marks it for submission
6. Runs 24/7 on your VPS as a background process

---

## Step-by-Step Setup

### Step 1 — SSH into your VPS

```bash
ssh root@your-vps-ip
```

### Step 2 — Clone the repo

```bash
cd /root
git clone https://github.com/00ElliotSop/jobhunter
cd jobhunter
```

### Step 3 — Install Python dependencies

```bash
# Install pip if needed
apt-get install python3-pip python3-venv -y

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install packages
pip install -r requirements.txt

# Install Playwright browser (Chromium only, ~170MB)
playwright install chromium
playwright install-deps chromium
```

### Step 4 — Get your free API keys

**Claude API** (for cover letters and analysis):
1. Go to https://console.anthropic.com
2. Sign up → go to "API Keys" → "Create Key"
3. Copy the key (starts with `sk-ant-`)
4. Set a monthly spend limit under "Billing" → "Usage Limits" (recommend $20/month cap)

**USAJobs API** (US federal jobs, free):
1. Go to https://developer.usajobs.gov/APIRequest/Index
2. Fill out the form with your name and email
3. You'll get an API key by email within minutes

**Adzuna API** (free tier = 250 calls/day):
1. Go to https://developer.adzuna.com
2. Create account → "Create App"
3. Copy your App ID and API Key

### Step 5 — Configure your environment

```bash
cp .env.example .env
nano .env
```

Fill in every value. The only required ones to start:
- `ANTHROPIC_API_KEY` — from Step 4
- `SMTP_USER` and `SMTP_PASS` — your Mailcow credentials
- `NOTIFY_EMAIL` — where you want alerts sent

### Step 6 — Configure your job targets

```bash
nano config/config.yaml
```

Key sections to edit:
- `profile.email` — your email
- `search.titles` — job titles (already set for cybersecurity)
- `search.blocked_keywords` — add roles you never want
- `notifications.to_address` — your notification email
- `sources` — toggle any job board on/off with `enabled: true/false`

### Step 7 — Add your resume

```bash
# Upload your resume PDF to the data folder
mkdir -p data
# Use scp from your local machine:
# scp resume.pdf root@your-vps-ip:/root/jobhunter/data/resume.pdf
```

### Step 8 — Test run (single cycle)

```bash
mkdir -p logs
python main.py run
```

You should see:
- Scrapers running (each logs job counts)
- Scoring output
- Email sent if matches found

Check your inbox. If you get a notification email, everything works.

### Step 9 — Check your stats

```bash
python main.py stats
```

Shows a table of top jobs by score with status.

### Step 10 — Deploy as daemon (runs forever)

```bash
# Make sure PM2 is installed (it already is on your VPS)
pm2 start pm2.config.js
pm2 save
pm2 startup   # auto-start on VPS reboot
```

Monitor it:
```bash
pm2 logs jobhunter     # live logs
pm2 status             # process health
pm2 restart jobhunter  # restart if needed
pm2 stop jobhunter     # pause it
```

---

## How the Email Reply-to-Apply Works

1. System finds a job scoring 85+ → emails you with subject like:
   `[87/100] Penetration Tester @ CrowdStrike — Reply APPLY to submit`

2. Email contains: match analysis, salary, work type, cover letter

3. You reply with just the word **apply** (first line of your reply)

4. System checks inbox every 15 minutes → marks job as apply-requested

5. View the job link in the email → paste the cover letter → submit

> **Note:** Full Playwright auto-submission (system clicks submit for you) is in the roadmap. Current version handles the application prep and tracking; you do the final submit. This avoids ToS violations on most platforms.

---

## Adding a New Job Site

Open `config/config.yaml` and add under `sources`:

```yaml
- name: "MyNewSite"
  type: "scraper"        # api | scraper | aggregator_scraper
  enabled: true
  url: "https://example.com/jobs"
  region: "both"         # canada | usa | remote | both
  requires_login: false
  notes: "Optional description"
```

Then create a matching scraper function in `scrapers/browser_scrapers.py` and import it in `main.py`. The pattern is consistent across all scrapers.

---

## Adjusting Your Job Targets

Everything is in `config/config.yaml`. Common adjustments:

**Add a new target title:**
```yaml
search:
  titles:
    - "Cloud Security Engineer"    # add here
```

**Block a keyword:**
```yaml
search:
  blocked_keywords:
    - "junior"   # add to block junior roles
```

**Change minimum score for notifications:**
```yaml
scoring:
  notify_threshold: 70   # default 65
```

**Change scrape frequency:**
```yaml
scheduler:
  scrape_interval_minutes: 60   # default 90
```

---

## Costs

| Service | Cost |
|---------|------|
| Claude API (cover letters + scoring) | ~$5–15/month at 30–50 apps/day |
| USAJobs API | Free |
| Adzuna API | Free (250 calls/day) |
| RemoteOK API | Free |
| Your existing VPS | Already paying |
| **Total new cost** | **~$5–15/month** |

Set a hard cap at https://console.anthropic.com → Billing → Usage Limits.

---

## Architecture

```
jobhunter/
├── main.py                    # Orchestrator + CLI
├── pm2.config.js              # VPS deployment config
├── requirements.txt
├── config/
│   └── config.yaml            # ← Edit this to control everything
├── engine/
│   ├── core.py                # DB, config loader, logging
│   ├── scorer.py              # Keyword scoring engine
│   └── claude_ai.py           # Cover letter + analysis
├── scrapers/
│   ├── api_scrapers.py        # USAJobs, Adzuna, RemoteOK
│   └── browser_scrapers.py    # Indeed, Dice, InfoSecJobs
├── notifier/
│   └── notifier.py            # Email send + IMAP reply monitor
├── data/
│   ├── resume.pdf             # Your resume (gitignored)
│   └── jobhunter.db           # SQLite database (gitignored)
└── logs/                      # Log files (gitignored)
```

---

## Sharing / Using for Other Fields

This repo is designed to be field-agnostic via config. To use for a different career:

1. Fork the repo
2. Edit `config/config.yaml`:
   - Change `search.titles` to your target roles
   - Change `search.required_keywords` to field-specific terms
   - Change `search.blocked_keywords` accordingly
3. Update `engine/claude_ai.py` → `PROFILE_SUMMARY` with your background
4. Done — scrapers and notifier work identically

---

## Roadmap

- [ ] LinkedIn Easy Apply auto-submission via Playwright
- [ ] Greenhouse/Lever ATS auto-fill
- [ ] Web dashboard (React) for tracking applications
- [ ] Clearance Jobs integration
- [ ] Glassdoor rating integration for company scoring
- [ ] Slack/Discord push notifications as alternative to email

---

## License

MIT. Fork it, build on it, share it.
