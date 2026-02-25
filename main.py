"""
Entry point — starts the Userbot, the Bot, and the APScheduler.

Required environment variables (set in Railway or .env locally):
  API_ID          – Telegram API ID  (my.telegram.org)
  API_HASH        – Telegram API Hash
  BOT_TOKEN       – Bot token from @BotFather
  SESSION_STRING  – Pyrogram session string (run setup_session.py once)
  ADMIN_ID        – Your Telegram user ID (integer)
  TARGET_CHANNEL  – Channel/chat ID where videos are forwarded (e.g. -100123456)

Optional:
  MIN_DURATION    – Minimum video length in seconds (default: 300 = 5 min)
  DATA_DIR        – Folder for SQLite file (default: /data for Railway)
"""

import asyncio
import logging
import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pyrogram import Client

from db import get_setting, init_db
from handlers import register_handlers
from scanner import daily_job

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _require(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return val


async def main() -> None:
    # ── Config ───────────────────────────────────────────────────────────────
    api_id         = int(_require("API_ID"))
    api_hash       = _require("API_HASH")
    bot_token      = _require("BOT_TOKEN")
    session_string = _require("SESSION_STRING")
    admin_id       = int(_require("ADMIN_ID"))
    target_channel = _require("TARGET_CHANNEL")
    min_duration   = int(os.environ.get("MIN_DURATION", "300"))
    data_dir       = os.environ.get("DATA_DIR", "/data")

    # ── DB ───────────────────────────────────────────────────────────────────
    await init_db(data_dir)

    # Load saved schedule (or fall back to noon UTC)
    send_hour   = int(await get_setting(data_dir, "send_hour",   "12"))
    send_minute = int(await get_setting(data_dir, "send_minute", "0"))

    # ── Clients ──────────────────────────────────────────────────────────────
    userbot = Client(
        name="userbot",
        api_id=api_id,
        api_hash=api_hash,
        session_string=session_string,
        workdir=data_dir,
    )

    bot = Client(
        name="bot",
        api_id=api_id,
        api_hash=api_hash,
        bot_token=bot_token,
        workdir=data_dir,
    )

    # ── Scheduler ────────────────────────────────────────────────────────────
    scheduler = AsyncIOScheduler(timezone="UTC")

    async with userbot, bot:
        # Register all command handlers
        register_handlers(
            bot=bot,
            userbot=userbot,
            scheduler=scheduler,
            admin_id=admin_id,
            target_channel=target_channel,
            min_duration=min_duration,
            data_dir=data_dir,
        )

        # Daily job
        scheduler.add_job(
            daily_job,
            trigger="cron",
            hour=send_hour,
            minute=send_minute,
            id="daily_send",
            replace_existing=True,
            kwargs=dict(
                userbot=userbot,
                bot=bot,
                target_channel=target_channel,
                min_duration=min_duration,
                admin_id=admin_id,
                data_dir=data_dir,
            ),
        )

        scheduler.start()
        logger.info(
            "Bot started. Daily job at %02d:%02d UTC. Admin: %s",
            send_hour, send_minute, admin_id,
        )

        # Notify admin that the bot is online
        try:
            await bot.send_message(
                admin_id,
                f"🟢 הבוט עלה!\n"
                f"⏰ שליחה יומית: {send_hour:02d}:{send_minute:02d} UTC\n"
                f"הקלד /status לפרטים נוספים.",
            )
        except Exception as e:
            logger.warning("Could not send startup message: %s", e)

        # Keep running forever
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
