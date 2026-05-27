"""
browser_scrapers.py — Playwright headless browser scrapers.
Runs invisibly in background. No browser window required.
"""

import asyncio
import hashlib
from playwright.async_api import async_playwright, Page
from engine.core import CONFIG, log
import os

SEARCH  = CONFIG["search"]
TITLES  = SEARCH["titles"]
PROFILE = CONFIG["profile"]


def _job_id(url: str, title: str = "", company: str = "") -> str:
    raw = f"{url}{title}{company}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]


async def _safe_get_text(page: Page, selector: str, default: str = "") -> str:
    try:
        el = await page.query_selector(selector)
        return (await el.inner_text()).strip() if el else default
    except Exception:
        return default


# ── Indeed ────────────────────────────────────────────────────
async def scrape_indeed(country: str = "ca") -> list[dict]:
    """
    Scrapes Indeed (Canada or USA).
    country: 'ca' for indeed.ca, 'us' for indeed.com
    """
    base = "https://ca.indeed.com" if country == "ca" else "https://www.indeed.com"
    currency = "CAD" if country == "ca" else "USD"
    jobs = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        for title in TITLES[:4]:
            try:
                url = f"{base}/jobs?q={title.replace(' ', '+')}&sort=date"
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                await asyncio.sleep(2)

                cards = await page.query_selector_all('[data-testid="slider_item"]')
                if not cards:
                    cards = await page.query_selector_all(".job_seen_beacon")

                for card in cards[:15]:
                    try:
                        job_title  = await _safe_get_text(card, "[data-testid='jobTitle'] span")
                        company    = await _safe_get_text(card, "[data-testid='company-name']")
                        location   = await _safe_get_text(card, "[data-testid='text-location']")
                        salary_raw = await _safe_get_text(card, "[data-testid='attribute_snippet_testid']")

                        link_el = await card.query_selector("a[id^='job_']")
                        href    = await link_el.get_attribute("href") if link_el else ""
                        job_url = f"{base}{href}" if href and href.startswith("/") else href

                        # Click for description
                        description = ""
                        if link_el:
                            await link_el.click()
                            await asyncio.sleep(1.5)
                            description = await _safe_get_text(page, "#jobDescriptionText")

                        if job_title and job_url:
                            jobs.append({
                                "id":          _job_id(job_url, job_title, company),
                                "title":       job_title,
                                "company":     company,
                                "location":    location,
                                "region":      country,
                                "source":      f"Indeed_{country.upper()}",
                                "url":         job_url,
                                "salary_raw":  salary_raw,
                                "salary_min":  _extract_salary_min(salary_raw),
                                "salary_max":  0,
                                "currency":    currency,
                                "work_type":   _detect_work_type(location + " " + description),
                                "description": description
                            })
                    except Exception as e:
                        log.debug(f"Indeed card parse error: {e}")
                        continue

                await asyncio.sleep(3)  # polite delay between searches

            except Exception as e:
                log.error(f"Indeed ({country}) scrape error for '{title}': {e}")

        await browser.close()

    log.info(f"Indeed {country.upper()}: {len(jobs)} jobs scraped")
    return jobs


# ── Dice ──────────────────────────────────────────────────────
async def scrape_dice() -> list[dict]:
    """Dice.com — best US tech/security job board."""
    jobs = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page    = await (await browser.new_context()).new_page()

        for title in TITLES[:4]:
            try:
                url = f"https://www.dice.com/jobs?q={title.replace(' ', '%20')}&filters.workplaceTypes=Remote"
                await page.goto(url, wait_until="networkidle", timeout=25000)
                await asyncio.sleep(2)

                cards = await page.query_selector_all("dhi-search-card")
                for card in cards[:20]:
                    try:
                        job_title = await _safe_get_text(card, "a.card-title-link")
                        company   = await _safe_get_text(card, ".card-company")
                        location  = await _safe_get_text(card, ".card-location")
                        link_el   = await card.query_selector("a.card-title-link")
                        href      = await link_el.get_attribute("href") if link_el else ""
                        job_url   = f"https://www.dice.com{href}" if href.startswith("/") else href

                        if job_title and job_url:
                            jobs.append({
                                "id":          _job_id(job_url, job_title, company),
                                "title":       job_title,
                                "company":     company,
                                "location":    location,
                                "region":      "usa",
                                "source":      "Dice",
                                "url":         job_url,
                                "salary_raw":  "",
                                "salary_min":  0,
                                "salary_max":  0,
                                "currency":    "USD",
                                "work_type":   _detect_work_type(location),
                                "description": ""
                            })
                    except Exception:
                        continue

            except Exception as e:
                log.error(f"Dice scrape error for '{title}': {e}")

        await browser.close()

    log.info(f"Dice: {len(jobs)} jobs scraped")
    return jobs


# ── InfoSec Jobs ──────────────────────────────────────────────
async def scrape_infosec_jobs() -> list[dict]:
    """infosec-jobs.com — pure cybersecurity focus, international."""
    jobs = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page    = await (await browser.new_context()).new_page()

        try:
            await page.goto("https://infosec-jobs.com/", wait_until="networkidle", timeout=20000)
            await asyncio.sleep(2)

            cards = await page.query_selector_all(".job-card, .job-listing, article")
            for card in cards[:30]:
                try:
                    job_title = await _safe_get_text(card, "h2, h3, .job-title")
                    company   = await _safe_get_text(card, ".company, .employer")
                    location  = await _safe_get_text(card, ".location, .job-location")
                    link_el   = await card.query_selector("a")
                    href      = await link_el.get_attribute("href") if link_el else ""
                    job_url   = href if href.startswith("http") else f"https://infosec-jobs.com{href}"

                    if job_title:
                        jobs.append({
                            "id":          _job_id(job_url, job_title, company),
                            "title":       job_title,
                            "company":     company,
                            "location":    location,
                            "region":      "both",
                            "source":      "InfoSecJobs",
                            "url":         job_url,
                            "salary_raw":  "",
                            "salary_min":  0,
                            "salary_max":  0,
                            "currency":    "USD",
                            "work_type":   _detect_work_type(location),
                            "description": ""
                        })
                except Exception:
                    continue
        except Exception as e:
            log.error(f"InfoSecJobs scrape error: {e}")

        await browser.close()

    log.info(f"InfoSecJobs: {len(jobs)} jobs scraped")
    return jobs


# ── Helpers ───────────────────────────────────────────────────
def _detect_work_type(text: str) -> str:
    t = text.lower()
    if "remote" in t:
        return "remote"
    if "hybrid" in t:
        return "hybrid"
    return "onsite"


def _extract_salary_min(text: str) -> int:
    import re
    nums = re.findall(r'[\$]?([\d,]+)', text or "")
    if nums:
        try:
            return int(nums[0].replace(",", ""))
        except Exception:
            pass
    return 0
