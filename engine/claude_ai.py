"""
claude_ai.py — Cover letter generation and job analysis via Claude API.
Only called for jobs that score above notify_threshold.
"""

import os
import anthropic
from engine.core import CONFIG, log

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
MODEL  = CONFIG["application"]["claude_model"]
MAX_WORDS = CONFIG["application"]["cover_letter_max_words"]

# ── Load profile for context ─────────────────────────────────
PROFILE = CONFIG["profile"]
SEARCH  = CONFIG["search"]

PROFILE_SUMMARY = f"""
Candidate: {PROFILE['name']}
Location: {PROFILE['location']}
Work Authorization: Canadian citizen, TN visa eligible for US roles (obtainable at border with offer letter)
Target Roles: {', '.join(SEARCH['titles'][:5])}
Core Skills: Penetration testing, offensive security, red team operations, vulnerability assessment, web/network exploitation
Certifications: OSCP (in progress), prior CRTP attempt, PEN-200 completed
Background: BSc Criminology (attacker psychology lens), BA/compliance experience, founder of ElliotSop Security (offensive security firm)
Notable: Top 2% TryHackMe, active GovCon positioning (SAM.gov registered), hands-on lab experience with AD environments
"""


async def generate_cover_letter(job: dict) -> str:
    """Generate a tailored cover letter for a specific job."""
    prompt = f"""
You are writing a cover letter for {PROFILE['name']}, an offensive security professional.

CANDIDATE PROFILE:
{PROFILE_SUMMARY}

JOB DETAILS:
Title: {job['title']}
Company: {job.get('company', 'the company')}
Location: {job.get('location', 'N/A')}
Description excerpt:
{job.get('description', '')[:2000]}

INSTRUCTIONS:
- Write a compelling, direct cover letter under {MAX_WORDS} words
- Open with a hook — NOT "I am writing to apply for..."
- Reference 2-3 specific things from the job description
- Highlight OSCP progress and hands-on offensive security background
- Mention TN visa eligibility naturally if it's a US role
- Close with a confident, specific call to action
- Tone: sharp, confident, professional — not generic or AI-sounding
- Do NOT use phrases like "I am passionate about" or "synergy"
- Output ONLY the cover letter body, no subject line, no metadata
"""

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}]
        )
        letter = response.content[0].text.strip()
        log.info(f"Cover letter generated for: {job['title']} @ {job.get('company', 'Unknown')}")
        return letter
    except Exception as e:
        log.error(f"Cover letter generation failed: {e}")
        return ""


async def analyze_job_fit(job: dict) -> str:
    """
    Returns a 3-bullet fit analysis for the notification email.
    Tells you WHY this job matched and what to know before applying.
    """
    prompt = f"""
Analyze this job posting for {PROFILE['name']}, an offensive security professional with OSCP in progress, 
penetration testing focus, and GovCon positioning.

JOB:
Title: {job['title']}
Company: {job.get('company', 'Unknown')}
Score: {job.get('score', 0)}/100
Description: {job.get('description', '')[:1500]}

Give exactly 3 bullet points:
1. WHY this matches (specific skills/requirements that align)
2. ONE potential gap or concern (be honest)  
3. ONE thing to emphasize in the application

Keep each bullet under 20 words. No preamble. Output bullets only.
"""

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text.strip()
    except Exception as e:
        log.error(f"Job analysis failed: {e}")
        return "• Strong keyword match\n• Review JD for clearance requirements\n• Lead with OSCP progress"
