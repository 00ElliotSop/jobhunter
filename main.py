"""
main.py — JobHunter orchestrator.
Runs the full pipeline: scrape → score → deduplicate → notify → apply.

Usage:
  python main.py run       # run one full cycle now
  python main.py daemon    # run on schedule (recommended for VPS)
  python main.py stats     # print DB stats
  python main.py check-replies  # manually check for apply replies
"""

import asyncio
import click
import aiosqlite
import schedule
import time
from datetime import datetime, timezone
from rich.console import Console
from rich.table import Table

from engine.core import init_db, get_db, CONFIG, log, DB_PATH
from engine.scorer import filter_and_rank
from engine.claude_ai import generate_cover_letter, analyze_job_fit
from scrapers.api_scrapers import scrape_usajobs, scrape_adzuna, scrape_remoteok
from scrapers.browser_scrapers import scrape_indeed, scrape_dice, scrape_infosec_jobs
from notifier.notifier import send_notification, send_digest, check_for_apply_replies

console = Console()
NOTIFY_THRESHOLD  = CONFIG["scoring"]["notify_threshold"]
INSTANT_THRESHOLD = CONFIG["notifications"]["instant_alert_threshold"]


# ── Core Pipeline ─────────────────────────────────────────────
async def run_scrape_cycle():
    """One full scrape → score → save → notify cycle."""
    start = datetime.now(timezone.utc)
    log.info("=" * 60)
    log.info(f"Scrape cycle started at {start.strftime('%Y-%m-%d %H:%M UTC')}")

    # 1. Collect from all enabled sources
    all_jobs = []

    import aiohttp
    async with aiohttp.ClientSession() as session:
        # API scrapers (parallel)
        api_results = await asyncio.gather(
            scrape_usajobs(session),
            scrape_adzuna(session, "ca"),
            scrape_adzuna(session, "us"),
            scrape_remoteok(session),
            return_exceptions=True
        )
        for result in api_results:
            if isinstance(result, list):
                all_jobs.extend(result)
            else:
                log.error(f"API scraper failed: {result}")

    # Browser scrapers (sequential to avoid resource issues)
    try:
        all_jobs.extend(await scrape_indeed("ca"))
        all_jobs.extend(await scrape_indeed("us"))
        all_jobs.extend(await scrape_dice())
        all_jobs.extend(await scrape_infosec_jobs())
    except Exception as e:
        log.error(f"Browser scraper error: {e}")

    log.info(f"Total raw jobs collected: {len(all_jobs)}")

    # 2. Score and filter
    scored_jobs = filter_and_rank(all_jobs)

    # 3. Deduplicate against DB and save new jobs
    new_jobs = []
    async with aiosqlite.connect(DB_PATH) as db:
        for job in scored_jobs:
            # Check if already exists
            async with db.execute("SELECT id FROM jobs WHERE id=? OR url=?",
                                  (job["id"], job.get("url", ""))) as cursor:
                existing = await cursor.fetchone()

            if not existing:
                await db.execute("""
                    INSERT INTO jobs
                    (id, title, company, location, region, source, url,
                     salary_raw, salary_min, salary_max, currency, work_type,
                     description, score, score_breakdown, status)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    job["id"], job["title"], job.get("company"), job.get("location"),
                    job.get("region"), job.get("source"), job.get("url"),
                    job.get("salary_raw"), job.get("salary_min", 0), job.get("salary_max", 0),
                    job.get("currency", "USD"), job.get("work_type"), job.get("description"),
                    job["score"], job.get("score_breakdown"), "new"
                ))
                new_jobs.append(job)

        await db.commit()

    log.info(f"New jobs saved: {len(new_jobs)}")

    # 4. Notify for jobs above threshold
    notify_jobs = [j for j in new_jobs if j["score"] >= NOTIFY_THRESHOLD]
    instant_jobs = [j for j in new_jobs if j["score"] >= INSTANT_THRESHOLD]

    # Generate cover letters + analysis for instant alerts (top matches)
    for job in instant_jobs:
        cover_letter = await generate_cover_letter(job)
        analysis     = await analyze_job_fit(job)

        # Save cover letter to DB
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE jobs SET cover_letter=? WHERE id=?",
                             (cover_letter, job["id"]))
            await db.commit()

        job["cover_letter"] = cover_letter
        await send_notification(job, cover_letter, analysis)

    # Send digest for remaining notify-threshold jobs
    digest_jobs = [j for j in notify_jobs if j not in instant_jobs]
    if digest_jobs:
        await send_digest(digest_jobs)

    # 5. Log run stats
    elapsed = (datetime.now(timezone.utc) - start).seconds
    log.info(f"Cycle complete in {elapsed}s | "
             f"Collected: {len(all_jobs)} | "
             f"Scored: {len(scored_jobs)} | "
             f"New: {len(new_jobs)} | "
             f"Notified: {len(notify_jobs)}")


async def check_and_process_replies():
    """Check inbox for apply replies and mark jobs accordingly."""
    reply_subjects = check_for_apply_replies()

    if not reply_subjects:
        return

    async with aiosqlite.connect(DB_PATH) as db:
        for subject in reply_subjects:
            # Find matching job by title in subject
            async with db.execute(
                "SELECT id, title, company, url FROM jobs WHERE status='notified' ORDER BY notified_at DESC LIMIT 20"
            ) as cursor:
                recent = await cursor.fetchall()

            for row in recent:
                job_id, title, company, url = row
                if title.lower() in subject.lower() or (company and company.lower() in subject.lower()):
                    await db.execute(
                        "UPDATE jobs SET status='apply_requested', reply_received=1 WHERE id=?",
                        (job_id,)
                    )
                    log.info(f"Apply requested for: {title} @ {company}")
                    log.info(f"Manual action needed: Open {url} and submit application")
                    # TODO: Playwright auto-submit can be wired here per-site
                    break

        await db.commit()


# ── CLI ───────────────────────────────────────────────────────
@click.group()
def cli():
    pass


@cli.command()
def run():
    """Run one full scrape and notify cycle."""
    asyncio.run(_run_with_init())


async def _run_with_init():
    await init_db()
    await run_scrape_cycle()
    await check_and_process_replies()


@cli.command()
def daemon():
    """Run on schedule (for VPS deployment). Ctrl+C to stop."""
    asyncio.run(init_db())
    interval = CONFIG["scheduler"]["scrape_interval_minutes"]

    log.info(f"Daemon started. Scraping every {interval} minutes.")
    log.info("Press Ctrl+C to stop.")

    # Run immediately on start
    asyncio.run(run_scrape_cycle())

    # Schedule recurring runs
    schedule.every(interval).minutes.do(lambda: asyncio.run(run_scrape_cycle()))
    schedule.every(15).minutes.do(lambda: asyncio.run(check_and_process_replies()))

    while True:
        schedule.run_pending()
        time.sleep(30)


@cli.command()
def stats():
    """Print database statistics."""
    asyncio.run(_print_stats())


async def _print_stats():
    await init_db()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM jobs") as c:
            total = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM jobs WHERE status='new'") as c:
            new = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM jobs WHERE status='notified'") as c:
            notified = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM jobs WHERE status='applied'") as c:
            applied = (await c.fetchone())[0]
        async with db.execute(
            "SELECT title, company, score, source, status FROM jobs ORDER BY score DESC LIMIT 20"
        ) as c:
            top = await c.fetchall()

    table = Table(title="Top 20 Jobs by Score", style="bold blue")
    table.add_column("Title", style="white", max_width=35)
    table.add_column("Company", style="cyan", max_width=20)
    table.add_column("Score", style="green", justify="right")
    table.add_column("Source", style="yellow")
    table.add_column("Status", style="magenta")

    for row in top:
        score_color = "green" if row[2] >= 80 else "yellow" if row[2] >= 65 else "white"
        table.add_row(row[0][:35], (row[1] or "")[:20], f"[{score_color}]{row[2]}[/]", row[3], row[4])

    console.print(f"\n[bold]Total jobs:[/] {total}  [bold]New:[/] {new}  "
                  f"[bold]Notified:[/] {notified}  [bold]Applied:[/] {applied}\n")
    console.print(table)


@cli.command(name="check-replies")
def check_replies():
    """Manually check inbox for apply replies."""
    asyncio.run(_check_replies())


async def _check_replies():
    await init_db()
    await check_and_process_replies()


if __name__ == "__main__":
    cli()
