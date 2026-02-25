"""
Channel scanner — finds the best video across all active channels.

Scoring formula:  score = duration_seconds × √(views + 1)
This gives roughly equal weight to length and popularity.
"""

import logging
import math
from datetime import datetime, timedelta, timezone

from pyrogram import Client
from pyrogram.types import Message

from db import get_channels, mark_as_sent, was_sent_today

logger = logging.getLogger(__name__)

LOOKBACK_HOURS = 24   # How far back to search each scan
SCAN_LIMIT     = 100  # Max messages to check per channel


def _score(duration_seconds: int, views: int) -> float:
    return duration_seconds * math.sqrt(views + 1)


async def scan_channels(
    userbot: Client,
    data_dir: str,
    min_duration: int = 300,
) -> tuple[Message | None, str | None]:
    """
    Scan all active channels and return (best_message, channel_id).
    Returns (None, None) when nothing qualifies.
    """
    channels = await get_channels(data_dir)
    if not channels:
        logger.info("No channels in list.")
        return None, None

    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)

    best_message: Message | None = None
    best_channel_id: str | None = None
    best_score: float = -1.0

    for channel_id, channel_name in channels:
        logger.info("Scanning: %s (%s)", channel_name, channel_id)
        try:
            async for msg in userbot.get_chat_history(channel_id, limit=SCAN_LIMIT):
                # Stop if we've gone past the lookback window
                msg_time = msg.date
                if msg_time.tzinfo is None:
                    msg_time = msg_time.replace(tzinfo=timezone.utc)
                if msg_time < cutoff:
                    break

                video = msg.video
                if not video:
                    continue
                if (video.duration or 0) < min_duration:
                    continue

                # Skip if already sent today (dedup)
                if await was_sent_today(data_dir, str(msg.id), str(channel_id)):
                    continue

                score = _score(video.duration, msg.views or 0)
                if score > best_score:
                    best_score = score
                    best_message = msg
                    best_channel_id = str(channel_id)

        except Exception as exc:
            logger.warning("Could not scan %s: %s", channel_name, exc)

    return best_message, best_channel_id


async def daily_job(
    userbot: Client,
    bot: Client,
    target_channel: str,
    min_duration: int,
    admin_id: int,
    data_dir: str,
) -> None:
    """Scan, pick the winner, copy it to target_channel, notify admin."""
    logger.info("Daily job started.")

    try:
        best_msg, best_channel_id = await scan_channels(userbot, data_dir, min_duration)

        if best_msg is None:
            await bot.send_message(
                admin_id,
                "⚠️ לא נמצאו סרטונים מעל "
                f"{min_duration // 60} דקות ב-24 השעות האחרונות.",
            )
            return

        # Copy WITHOUT forward attribution (userbot must have post rights in target)
        await userbot.copy_message(
            chat_id=target_channel,
            from_chat_id=best_channel_id,
            message_id=best_msg.id,
        )

        await mark_as_sent(data_dir, str(best_msg.id), best_channel_id)

        dur_min = best_msg.video.duration // 60
        dur_sec = best_msg.video.duration % 60
        views   = best_msg.views or "N/A"

        await bot.send_message(
            admin_id,
            f"✅ סרטון נשלח!\n"
            f"📺 ערוץ: `{best_channel_id}`\n"
            f"⏱ אורך: {dur_min}:{dur_sec:02d}\n"
            f"👁 צפיות: {views}",
        )
        logger.info("Video sent from %s (msg %s).", best_channel_id, best_msg.id)

    except Exception as exc:
        logger.error("daily_job error: %s", exc, exc_info=True)
        try:
            await bot.send_message(admin_id, f"❌ שגיאה בשליחה היומית:\n`{exc}`")
        except Exception:
            pass
