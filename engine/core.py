"""
core.py — Database, config loader, logging setup
"""

import os
import yaml
import logging
import aiosqlite
from pathlib import Path
from dotenv import load_dotenv
from rich.logging import RichHandler

load_dotenv()

# ── Logging ──────────────────────────────────────────────────
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(message)s",
    handlers=[
        RichHandler(rich_tracebacks=True),
        logging.FileHandler("logs/jobhunter.log")
    ]
)
log = logging.getLogger("jobhunter")

# ── Config ───────────────────────────────────────────────────
def load_config(path="config/config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)

CONFIG = load_config()

# ── Database ─────────────────────────────────────────────────
DB_PATH = os.getenv("DB_PATH", "./data/jobhunter.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    company         TEXT,
    location        TEXT,
    region          TEXT,
    source          TEXT,
    url             TEXT UNIQUE,
    salary_raw      TEXT,
    salary_min      INTEGER,
    salary_max      INTEGER,
    currency        TEXT,
    work_type       TEXT,
    description     TEXT,
    required_kws    TEXT,
    score           INTEGER DEFAULT 0,
    score_breakdown TEXT,
    cover_letter    TEXT,
    status          TEXT DEFAULT 'new',
    notified_at     TEXT,
    applied_at      TEXT,
    reply_received  INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS scrape_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT,
    started_at  TEXT,
    finished_at TEXT,
    jobs_found  INTEGER DEFAULT 0,
    jobs_new    INTEGER DEFAULT 0,
    error       TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs(score DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at DESC);
"""

async def init_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()
    log.info(f"Database ready at {DB_PATH}")

async def get_db():
    return await aiosqlite.connect(DB_PATH)
