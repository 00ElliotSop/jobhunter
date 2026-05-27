"""
scorer.py — Scores and ranks jobs against your profile config.
No AI calls here — pure keyword/heuristic scoring for speed.
Claude API is called only for top matches (cover letter + explanation).
"""

import re
import json
from engine.core import CONFIG, log

WEIGHTS = CONFIG["scoring"]
SEARCH  = CONFIG["search"]


def score_job(job: dict) -> tuple[int, dict]:
    """
    Returns (total_score 0-100, breakdown dict).
    job dict keys: title, description, salary_min, salary_max,
                   currency, work_type, location, company
    """
    breakdown = {}
    total = 0

    # 1. Title match
    title_score = _score_title(job.get("title", ""))
    breakdown["title_match"] = title_score
    total += title_score

    # 2. Required keyword hits in description
    kw_score = _score_keywords(job.get("description", ""))
    breakdown["keyword_hits"] = kw_score
    total += kw_score

    # 3. Blocklist — hard zero if any blocked keyword found
    if _is_blocked(job.get("title", ""), job.get("description", "")):
        breakdown["blocked"] = True
        return 0, breakdown

    # 4. Salary
    sal_score = _score_salary(job)
    breakdown["salary"] = sal_score
    total += sal_score

    # 5. Remote/hybrid
    work_score = _score_work_type(job.get("work_type", ""), job.get("description", ""))
    breakdown["work_type"] = work_score
    total += work_score

    # 6. Certs mentioned
    cert_score = _score_certs(job.get("description", ""))
    breakdown["cert_mentioned"] = cert_score
    total += cert_score

    # Cap at 100
    total = min(total, 100)
    breakdown["total"] = total
    return total, breakdown


def _score_title(title: str) -> int:
    title_lower = title.lower()
    max_w = WEIGHTS["title_match"]
    target_titles = [t.lower() for t in SEARCH["titles"]]

    # Exact match
    for i, t in enumerate(target_titles):
        if t in title_lower:
            # Earlier in priority list = higher score
            priority_bonus = max(0, 5 - i)
            return max_w + priority_bonus

    # Partial match on key words
    security_words = ["security", "pentest", "penetration", "red team", "offensive",
                      "vulnerability", "exploit", "infosec", "cyber"]
    hits = sum(1 for w in security_words if w in title_lower)
    if hits >= 2:
        return int(max_w * 0.7)
    if hits == 1:
        return int(max_w * 0.4)
    return 0


def _score_keywords(description: str) -> int:
    desc_lower = description.lower()
    required = [k.lower() for k in SEARCH["required_keywords"]]
    hits = sum(1 for k in required if k in desc_lower)
    max_w = WEIGHTS["required_keyword_hits"]

    if hits == 0:
        return 0
    ratio = min(hits / max(len(required) * 0.3, 1), 1.0)  # 30% hit rate = full score
    return int(max_w * ratio)


def _is_blocked(title: str, description: str) -> bool:
    combined = (title + " " + description).lower()
    blocked = [k.lower() for k in SEARCH["blocked_keywords"]]
    return any(k in combined for k in blocked)


def _score_salary(job: dict) -> int:
    max_w = WEIGHTS["salary_disclosed"]
    currency = (job.get("currency") or "").upper()
    sal_min = job.get("salary_min") or 0

    if not sal_min:
        return 0  # no salary disclosed

    # Check against minimums
    if currency == "CAD":
        min_target = SEARCH["salary"]["min_cad"]
    else:
        min_target = SEARCH["salary"]["min_usd"]

    if sal_min >= min_target:
        return max_w
    if sal_min >= min_target * 0.85:
        return int(max_w * 0.5)
    return 0


def _score_work_type(work_type: str, description: str) -> int:
    max_w = WEIGHTS["remote_work"]
    combined = (work_type + " " + description).lower()

    prefs = SEARCH["work_type"]
    for i, pref in enumerate(prefs):
        if pref.lower() in combined:
            # First preference = full score, descending
            return max_w if i == 0 else int(max_w * (1 - i * 0.3))
    return 0


def _score_certs(description: str) -> int:
    max_w = WEIGHTS["cert_mentioned"]
    certs = ["oscp", "ceh", "gpen", "gwapt", "ejpt", "pnpt", "crtp",
             "cissp", "security+", "cism", "ccnp", "cpts"]
    desc_lower = description.lower()
    hits = sum(1 for c in certs if c in desc_lower)
    if hits >= 2:
        return max_w
    if hits == 1:
        return int(max_w * 0.6)
    return 0


def filter_and_rank(jobs: list[dict]) -> list[dict]:
    """Score all jobs, filter below threshold, sort by score."""
    save_threshold = CONFIG["scoring"]["save_threshold"]
    scored = []
    for job in jobs:
        score, breakdown = score_job(job)
        if score >= save_threshold:
            job["score"] = score
            job["score_breakdown"] = json.dumps(breakdown)
            scored.append(job)

    scored.sort(key=lambda j: j["score"], reverse=True)
    log.info(f"Scored {len(jobs)} jobs → {len(scored)} above threshold ({save_threshold})")
    return scored
