"""
notifier.py — Sends job notification emails and monitors inbox
for "apply" replies to trigger auto-submission.
Uses your existing Mailcow SMTP at mail.elliotsop.com.
"""

import os
import asyncio
import imaplib
import email
import aiosqlite
import aiosmtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timezone
from engine.core import CONFIG, log, DB_PATH

NOTIFY_CFG = CONFIG["notifications"]
APP_CFG    = CONFIG["application"]
PROFILE    = CONFIG["profile"]
TRIGGER    = NOTIFY_CFG["apply_trigger_word"].lower()


# ── Email Templates ───────────────────────────────────────────
def build_job_email(job: dict, cover_letter: str, analysis: str) -> tuple[str, str]:
    """Returns (subject, html_body)."""
    score    = job.get("score", 0)
    score_bar = "█" * (score // 10) + "░" * (10 - score // 10)
    salary   = job.get("salary_raw") or "Not disclosed"
    work_type = (job.get("work_type") or "Unknown").title()
    region   = "🇺🇸 USA" if job.get("region") == "usa" else "🇨🇦 Canada" if job.get("region") == "ca" else "🌐 Remote"

    subject  = f"[{score}/100] {job['title']} @ {job.get('company', 'Unknown')} — Reply APPLY to submit"

    html = f"""
<!DOCTYPE html>
<html>
<head>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #0d1117; color: #e6edf3; margin: 0; padding: 20px; }}
  .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 24px; max-width: 680px; margin: 0 auto; }}
  .score {{ font-size: 32px; font-weight: bold; color: {'#3fb950' if score >= 80 else '#d29922' if score >= 65 else '#f85149'}; }}
  .score-bar {{ font-family: monospace; color: #58a6ff; font-size: 14px; letter-spacing: 2px; }}
  .tag {{ display: inline-block; background: #1f6feb33; border: 1px solid #1f6feb; border-radius: 4px; padding: 2px 8px; font-size: 12px; margin: 2px; }}
  .section {{ margin-top: 20px; padding-top: 16px; border-top: 1px solid #30363d; }}
  .apply-btn {{ background: #238636; color: white; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: bold; display: inline-block; margin-top: 16px; }}
  .cover-letter {{ background: #0d1117; border-left: 3px solid #58a6ff; padding: 16px; margin-top: 12px; white-space: pre-wrap; font-size: 14px; line-height: 1.6; }}
  h1 {{ font-size: 20px; margin: 0 0 4px 0; }}
  h2 {{ font-size: 14px; font-weight: normal; color: #8b949e; margin: 0; }}
  .meta {{ color: #8b949e; font-size: 13px; margin-top: 12px; }}
</style>
</head>
<body>
<div class="card">
  <div style="display:flex; justify-content:space-between; align-items:flex-start;">
    <div>
      <h1>{job['title']}</h1>
      <h2>{job.get('company', 'Unknown Company')}</h2>
    </div>
    <div style="text-align:right;">
      <div class="score">{score}/100</div>
      <div class="score-bar">{score_bar}</div>
    </div>
  </div>

  <div class="meta">
    <span class="tag">{region}</span>
    <span class="tag">{work_type}</span>
    <span class="tag">💰 {salary}</span>
    <span class="tag">📡 {job.get('source', 'Unknown')}</span>
  </div>

  <div class="section">
    <strong>📊 Match Analysis</strong>
    <div style="margin-top:8px; white-space:pre-line; font-size:14px; line-height:1.7;">
{analysis}
    </div>
  </div>

  <div class="section">
    <strong>📝 Cover Letter (auto-generated, tailored)</strong>
    <div class="cover-letter">{cover_letter}</div>
  </div>

  <div class="section">
    <a href="{job.get('url', '#')}" class="apply-btn">🔗 View Full Job Posting</a>
    <br><br>
    <strong style="color:#f85149;">⚡ Reply to this email with the word "{TRIGGER.upper()}" to auto-submit your application.</strong>
    <br>
    <span style="font-size:12px; color:#8b949e;">Job ID: {job['id']} | Expires in {APP_CFG['reply_timeout_hours']}h</span>
  </div>
</div>
</body>
</html>
"""
    return subject, html


# ── Send Email ────────────────────────────────────────────────
async def send_notification(job: dict, cover_letter: str, analysis: str):
    subject, html = build_job_email(job, cover_letter, analysis)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = NOTIFY_CFG["from_address"]
    msg["To"]      = NOTIFY_CFG["to_address"]
    msg["X-Job-ID"] = job["id"]  # used to match reply

    msg.attach(MIMEText(html, "html"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=NOTIFY_CFG["smtp_host"],
            port=NOTIFY_CFG["smtp_port"],
            username=os.getenv("SMTP_USER"),
            password=os.getenv("SMTP_PASS"),
            start_tls=True
        )
        log.info(f"Notification sent: {job['title']} @ {job.get('company')}")

        # Mark as notified in DB
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE jobs SET status='notified', notified_at=? WHERE id=?",
                (datetime.now(timezone.utc).isoformat(), job["id"])
            )
            await db.commit()
    except Exception as e:
        log.error(f"Failed to send notification: {e}")


# ── Send Digest ───────────────────────────────────────────────
async def send_digest(jobs: list[dict]):
    """Send a batch summary email for multiple jobs."""
    if not jobs:
        return

    rows = ""
    for job in jobs:
        score = job.get("score", 0)
        color = "#3fb950" if score >= 80 else "#d29922" if score >= 65 else "#e6edf3"
        rows += f"""
        <tr>
          <td style="padding:8px; border-bottom:1px solid #30363d;">
            <a href="{job.get('url','#')}" style="color:#58a6ff;">{job['title']}</a>
          </td>
          <td style="padding:8px; border-bottom:1px solid #30363d; color:#8b949e;">{job.get('company','')}</td>
          <td style="padding:8px; border-bottom:1px solid #30363d; color:{color}; font-weight:bold;">{score}/100</td>
          <td style="padding:8px; border-bottom:1px solid #30363d; color:#8b949e;">{job.get('source','')}</td>
        </tr>"""

    html = f"""
<!DOCTYPE html><html><body style="background:#0d1117;color:#e6edf3;font-family:Arial,sans-serif;padding:20px;">
<div style="max-width:700px;margin:0 auto;background:#161b22;border:1px solid #30363d;border-radius:8px;padding:24px;">
  <h2>🎯 JobHunter Digest — {len(jobs)} New Matches</h2>
  <table style="width:100%;border-collapse:collapse;">
    <thead><tr style="color:#8b949e;font-size:12px;">
      <th style="text-align:left;padding:8px;">Title</th>
      <th style="text-align:left;padding:8px;">Company</th>
      <th style="text-align:left;padding:8px;">Score</th>
      <th style="text-align:left;padding:8px;">Source</th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table>
  <p style="color:#8b949e;font-size:12px;margin-top:16px;">
    High-score jobs (85+) get individual emails with cover letters and reply-to-apply.
  </p>
</div>
</body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[JobHunter] {len(jobs)} New Cybersecurity Matches"
    msg["From"]    = NOTIFY_CFG["from_address"]
    msg["To"]      = NOTIFY_CFG["to_address"]
    msg.attach(MIMEText(html, "html"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=NOTIFY_CFG["smtp_host"],
            port=NOTIFY_CFG["smtp_port"],
            username=os.getenv("SMTP_USER"),
            password=os.getenv("SMTP_PASS"),
            start_tls=True
        )
        log.info(f"Digest sent: {len(jobs)} jobs")
    except Exception as e:
        log.error(f"Digest send failed: {e}")


# ── IMAP Reply Monitor ─────────────────────────────────────────
def check_for_apply_replies() -> list[str]:
    """
    Checks IMAP inbox for replies containing TRIGGER word.
    Returns list of job IDs to apply to.
    Runs synchronously — called from scheduler.
    """
    imap_host = NOTIFY_CFG["smtp_host"]
    user      = os.getenv("SMTP_USER")
    password  = os.getenv("SMTP_PASS")
    job_ids   = []

    try:
        mail = imaplib.IMAP4_SSL(imap_host)
        mail.login(user, password)
        mail.select("INBOX")

        # Search for unseen replies to our notifications
        _, messages = mail.search(None, '(UNSEEN SUBJECT "Re:")')
        for num in messages[0].split():
            _, data = mail.fetch(num, "(RFC822)")
            raw    = data[0][1]
            msg    = email.message_from_bytes(raw)

            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                        break
            else:
                body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")

            # Check first line for trigger word
            first_line = body.strip().split("\n")[0].strip().lower()
            if TRIGGER in first_line:
                # Extract job ID from original email headers (via References/In-Reply-To)
                # Simpler: search subject for job title patterns
                subject = msg.get("Subject", "")
                log.info(f"Apply reply received for: {subject}")

                # Mark as read
                mail.store(num, "+FLAGS", "\\Seen")

                # Extract job ID from subject if present
                # Format: [85/100] Title @ Company — Reply APPLY ...
                import re
                match = re.search(r'\[(\d+)/100\]', subject)
                if match:
                    # Query DB by recent notified jobs
                    job_ids.append(subject)  # pass full subject; main.py handles lookup

        mail.logout()
    except Exception as e:
        log.error(f"IMAP check failed: {e}")

    return job_ids
