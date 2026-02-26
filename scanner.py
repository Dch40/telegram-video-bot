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


async def daily_job(
    userbot: Client,
    bot: Client,
    target_channel: str,
    min_duration: int,
    admin_id: int,
    data_dir: str,
) -> None:
    """Scan all channels, pick the best video, copy it to target_channel."""
    logger.info("Daily job started.")

    try:
        channels = await get_channels(data_dir)
        if not channels:
            await bot.send_message(admin_id, "⚠️ אין ערוצים ברשימה. הוסף עם /addchannel.")
            return

        cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)

        best_message: Message | None = None
        best_channel_id: str | None = None
        best_score: float = -1.0
        scan_errors: list[str] = []
        videos_checked = 0

        for channel_id, channel_name in channels:
            logger.info("Scanning: %s (%s)", channel_name, channel_id)
            try:
                async for msg in userbot.get_chat_history(channel_id, limit=SCAN_LIMIT):
                    msg_time = msg.date
                    if msg_time.tzinfo is None:
                        msg_time = msg_time.replace(tzinfo=timezone.utc)
                    if msg_time < cutoff:
                        break

                    video = msg.video
                    if not video or (video.duration or 0) < min_duration:
                        continue
                    if await was_sent_today(data_dir, str(msg.id), str(channel_id)):
                        continue

                    videos_checked += 1
                    score = _score(video.duration, msg.views or 0)
                    if score > best_score:
                        best_score = score
                        best_message = msg
                        best_channel_id = str(channel_id)

            except Exception as exc:
                logger.warning("Could not scan %s: %s", channel_name, exc)
                scan_errors.append(f"• {channel_name}: `{exc}`")

        # ── No winner found — report why ─────────────────────────────────────
        if best_message is None:
            if scan_errors:
                err_text = "\n".join(scan_errors[:5])
                await bot.send_message(
                    admin_id,
                    f"❌ **שגיאות גישה לערוצים** ({len(scan_errors)}/{len(channels)}):\n\n"
                    f"{err_text}\n\n"
                    f"💡 הפתרון: הפעל מחדש את הבוט כדי לסנכרן את הרשאות הגישה.",
                )
            else:
                await bot.send_message(
                    admin_id,
                    f"⚠️ לא נמצאו סרטונים מעל {min_duration // 60} דקות "
                    f"ב-{LOOKBACK_HOURS} השעות האחרונות.\n"
                    f"(סרוקו {len(channels)} ערוצים)",
                )
            return

        # ── Send the winner ───────────────────────────────────────────────────
        await userbot.copy_message(
            chat_id=target_channel,
            from_chat_id=best_channel_id,
            message_id=best_message.id,
        )
        await mark_as_sent(data_dir, str(best_message.id), best_channel_id)

        dur_min = int(best_message.video.duration) // 60
        dur_sec = int(best_message.video.duration) % 60
        views   = best_message.views or "N/A"

        await bot.send_message(
            admin_id,
            f"✅ סרטון נשלח!\n"
            f"📺 ערוץ: `{best_channel_id}`\n"
            f"⏱ אורך: {dur_min}:{dur_sec:02d}\n"
            f"👁 צפיות: {views}\n"
            f"🔍 מתוך {videos_checked} סרטונים שנמצאו",
        )
        if scan_errors:
            await bot.send_message(
                admin_id,
                f"⚠️ {len(scan_errors)} ערוצים לא היו נגישים:\n" + "\n".join(scan_errors[:5]),
            )
        logger.info("Video sent from %s (msg %s).", best_channel_id, best_message.id)

    except Exception as exc:
        logger.error("daily_job error: %s", exc, exc_info=True)
        try:
            await bot.send_message(admin_id, f"❌ שגיאה בשליחה היומית:\n`{exc}`")
        except Exception:
            pass
