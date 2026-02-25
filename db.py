"""
Database layer — SQLite via aiosqlite for async operations.
Tables: channels, settings, sent_videos
"""

import aiosqlite
import os
from pathlib import Path


def db_path(data_dir: str) -> str:
    return os.path.join(data_dir, "bot.db")


async def init_db(data_dir: str) -> None:
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(db_path(data_dir)) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS channels (
                channel_id   TEXT PRIMARY KEY,
                channel_name TEXT NOT NULL,
                active       INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sent_videos (
                message_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                sent_date  TEXT NOT NULL,
                PRIMARY KEY (message_id, channel_id)
            );
        """)
        await db.commit()


# ── Channels ────────────────────────────────────────────────────────────────

async def add_channel(data_dir: str, channel_id: str, channel_name: str) -> None:
    async with aiosqlite.connect(db_path(data_dir)) as db:
        await db.execute(
            "INSERT OR REPLACE INTO channels (channel_id, channel_name, active) VALUES (?, ?, 1)",
            (str(channel_id), channel_name),
        )
        await db.commit()


async def remove_channel(data_dir: str, channel_id: str) -> bool:
    async with aiosqlite.connect(db_path(data_dir)) as db:
        cur = await db.execute(
            "UPDATE channels SET active=0 WHERE channel_id=? AND active=1",
            (str(channel_id),),
        )
        await db.commit()
        return cur.rowcount > 0


async def get_channels(data_dir: str) -> list[tuple[str, str]]:
    async with aiosqlite.connect(db_path(data_dir)) as db:
        async with db.execute(
            "SELECT channel_id, channel_name FROM channels WHERE active=1"
        ) as cur:
            return await cur.fetchall()


# ── Settings ─────────────────────────────────────────────────────────────────

async def get_setting(data_dir: str, key: str, default: str | None = None) -> str | None:
    async with aiosqlite.connect(db_path(data_dir)) as db:
        async with db.execute("SELECT value FROM settings WHERE key=?", (key,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else default


async def set_setting(data_dir: str, key: str, value: str) -> None:
    async with aiosqlite.connect(db_path(data_dir)) as db:
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, str(value)),
        )
        await db.commit()


# ── Sent-videos dedup ────────────────────────────────────────────────────────

async def was_sent_today(data_dir: str, message_id: str, channel_id: str) -> bool:
    from datetime import date
    today = str(date.today())
    async with aiosqlite.connect(db_path(data_dir)) as db:
        async with db.execute(
            "SELECT 1 FROM sent_videos WHERE message_id=? AND channel_id=? AND sent_date=?",
            (str(message_id), str(channel_id), today),
        ) as cur:
            return await cur.fetchone() is not None


async def mark_as_sent(data_dir: str, message_id: str, channel_id: str) -> None:
    from datetime import date
    today = str(date.today())
    async with aiosqlite.connect(db_path(data_dir)) as db:
        await db.execute(
            "INSERT OR IGNORE INTO sent_videos (message_id, channel_id, sent_date) VALUES (?, ?, ?)",
            (str(message_id), str(channel_id), today),
        )
        await db.commit()
