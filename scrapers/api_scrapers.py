"""
api_scrapers.py — Scrapers for job boards with free APIs.
These are reliable, no bot-detection, no login needed.
"""

import os
import hashlib
import aiohttp
from engine.core import CONFIG, log

SEARCH = CONFIG["search"]
TITLES = SEARCH["titles"]


def _job_id(url: str, title: str, company: str) -> str:
    """Generate a stable unique ID for a job posting."""
    raw = f"{url}{title}{company}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]


# ── USAJobs (US Federal) ──────────────────────────────────────
async def scrape_usajobs(session: aiohttp.ClientSession) -> list[dict]:
    """
    Official US Federal Jobs API.
    Register free at: https://developer.usajobs.gov/
    """
    api_key = os.getenv("USAJOBS_API_KEY", "")
    email   = os.getenv("USAJOBS_EMAIL", "")
    if not api_key:
        log.warning("USAJobs: No API key set. Skipping.")
        return []

    jobs = []
    headers = {
        "Authorization-Key": api_key,
        "User-Agent": email,
        "Host": "data.usajobs.gov"
    }

    for title in TITLES[:5]:  # top 5 priority titles
        try:
            params = {
                "PositionTitle": title,
                "ResultsPerPage": 25,
                "Fields": "min"
            }
            async with session.get(
                "https://data.usajobs.gov/api/search",
                headers=headers, params=params, timeout=aiohttp.ClientTimeout(total=15)
            ) as r:
                if r.status != 200:
                    continue
                data = await r.json()
                items = data.get("SearchResult", {}).get("SearchResultItems", [])
                for item in items:
                    pos = item.get("MatchedObjectDescriptor", {})
                    url = pos.get("ApplyURI", [""])[0] or pos.get("PositionURI", "")
                    sal = pos.get("PositionRemuneration", [{}])[0]
                    jobs.append({
                        "id":         _job_id(url, pos.get("PositionTitle", ""), pos.get("OrganizationName", "")),
                        "title":      pos.get("PositionTitle", ""),
                        "company":    pos.get("OrganizationName", ""),
                        "location":   pos.get("PositionLocationDisplay", ""),
                        "region":     "usa",
                        "source":     "USAJobs",
                        "url":        url,
                        "salary_raw": f"{sal.get('MinimumRange', '')} - {sal.get('MaximumRange', '')} {sal.get('RateIntervalCode', '')}",
                        "salary_min": _parse_salary(sal.get("MinimumRange")),
                        "salary_max": _parse_salary(sal.get("MaximumRange")),
                        "currency":   "USD",
                        "work_type":  pos.get("PositionSchedule", [{}])[0].get("Name", ""),
                        "description": pos.get("UserArea", {}).get("Details", {}).get("JobSummary", "")
                    })
        except Exception as e:
            log.error(f"USAJobs error for '{title}': {e}")

    log.info(f"USAJobs: {len(jobs)} jobs fetched")
    return jobs


# ── Adzuna (CA + US) ──────────────────────────────────────────
async def scrape_adzuna(session: aiohttp.ClientSession, country: str = "ca") -> list[dict]:
    """
    Adzuna free API — 250 calls/day free tier.
    Register at: https://developer.adzuna.com/
    country: 'ca' for Canada, 'us' for USA
    """
    app_id  = os.getenv("ADZUNA_APP_ID", "")
    app_key = os.getenv("ADZUNA_API_KEY", "")
    if not app_id or not app_key:
        log.warning("Adzuna: No API credentials set. Skipping.")
        return []

    currency = "CAD" if country == "ca" else "USD"
    min_sal  = SEARCH["salary"]["min_cad"] if country == "ca" else SEARCH["salary"]["min_usd"]
    jobs     = []

    for title in TITLES[:4]:
        try:
            params = {
                "app_id":    app_id,
                "app_key":   app_key,
                "results_per_page": 20,
                "what":      title,
                "content-type": "application/json"
            }
            url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/1"
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status != 200:
                    continue
                data = await r.json()
                for item in data.get("results", []):
                    redirect_url = item.get("redirect_url", "")
                    company = item.get("company", {}).get("display_name", "")
                    jobs.append({
                        "id":         _job_id(redirect_url, item.get("title", ""), company),
                        "title":      item.get("title", ""),
                        "company":    company,
                        "location":   item.get("location", {}).get("display_name", ""),
                        "region":     country,
                        "source":     f"Adzuna_{country.upper()}",
                        "url":        redirect_url,
                        "salary_raw": str(item.get("salary_min", "")),
                        "salary_min": int(item.get("salary_min") or 0),
                        "salary_max": int(item.get("salary_max") or 0),
                        "currency":   currency,
                        "work_type":  item.get("contract_type", ""),
                        "description": item.get("description", "")
                    })
        except Exception as e:
            log.error(f"Adzuna ({country}) error for '{title}': {e}")

    log.info(f"Adzuna {country.upper()}: {len(jobs)} jobs fetched")
    return jobs


# ── RemoteOK (Remote only) ────────────────────────────────────
async def scrape_remoteok(session: aiohttp.ClientSession) -> list[dict]:
    """No key needed. Returns remote-only jobs."""
    try:
        headers = {"User-Agent": "JobHunter/1.0 (github.com/yourprofile/jobhunter)"}
        async with session.get(
            "https://remoteok.com/api",
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=15)
        ) as r:
            if r.status != 200:
                return []
            data = await r.json()

        security_tags = {"security", "cybersecurity", "pentest", "infosec",
                         "hacking", "red-team", "vulnerability"}
        jobs = []
        for item in data[1:]:  # first item is metadata
            tags = set(item.get("tags") or [])
            title = (item.get("position") or "").lower()

            has_security = bool(tags & security_tags) or any(
                t in title for t in ["security", "pentest", "red team", "cyber"]
            )
            if not has_security:
                continue

            url = f"https://remoteok.com/remote-jobs/{item.get('id', '')}"
            jobs.append({
                "id":          _job_id(url, item.get("position", ""), item.get("company", "")),
                "title":       item.get("position", ""),
                "company":     item.get("company", ""),
                "location":    "Remote",
                "region":      "remote",
                "source":      "RemoteOK",
                "url":         url,
                "salary_raw":  item.get("salary", ""),
                "salary_min":  0,
                "salary_max":  0,
                "currency":    "USD",
                "work_type":   "remote",
                "description": item.get("description", "")
            })

        log.info(f"RemoteOK: {len(jobs)} security jobs fetched")
        return jobs
    except Exception as e:
        log.error(f"RemoteOK error: {e}")
        return []


# ── Helpers ───────────────────────────────────────────────────
def _parse_salary(val) -> int:
    try:
        return int(float(str(val).replace(",", "").strip()))
    except Exception:
        return 0
