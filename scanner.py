"""
Channel scanner — finds the top videos across all active channels.

For each channel: collect all qualifying videos from the last 24 hours,
sort by views descending, and forward up to VIDEOS_PER_CHANNEL.
"""

import logging
from datetime import datetime, timedelta, timezone

from pyrogram import Client
from pyrogram.types import Message

from db import get_channels, mark_as_sent, was_sent_today

logger = logging.getLogger(__name__)

LOOKBACK_HOURS     = 24   # How far back to search each scan
SCAN_LIMIT         = 100  # Max messages to check per channel
VIDEOS_PER_CHANNEL = 3    # Max videos to send per channel per run


async def daily_job(
    userbot: Client,
    bot: Client,
    target_channel: str,
    min_duration: int,
    admin_id: int,
    data_dir: str,
) -> None:
    """For every channel send up to VIDEOS_PER_CHANNEL top-viewed videos."""
    logger.info("Daily job started.")

    try:
        channels = await get_channels(data_dir)
        if not channels:
            await bot.send_message(admin_id, "⚠️ אין ערוצים ברשימה. הוסף עם /addchannel.")
            return

        cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)

        total_sent  = 0
        scan_errors: list[str] = []

        for channel_id, channel_name in channels:
            logger.info("Scanning: %s (%s)", channel_name, channel_id)
            candidates: list[Message] = []

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

                    candidates.append(msg)

            except Exception as exc:
                logger.warning("Could not scan %s: %s", channel_name, exc)
                scan_errors.append(f"• {channel_name}: `{exc}`")
                continue

            if not candidates:
                continue

            # Sort by views descending and take the top N
            candidates.sort(key=lambda m: m.views or 0, reverse=True)
            top = candidates[:VIDEOS_PER_CHANNEL]

            for msg in top:
                try:
                    await userbot.copy_message(
                        chat_id=target_channel,
                        from_chat_id=str(channel_id),
                        message_id=msg.id,
                    )
                    await mark_as_sent(data_dir, str(msg.id), str(channel_id))
                    total_sent += 1
                    logger.info(
                        "Sent video from %s (msg_id=%s, views=%s).",
                        channel_name, msg.id, msg.views,
                    )
                except Exception as exc:
                    logger.warning(
                        "Failed to copy msg %s from %s: %s", msg.id, channel_name, exc
                    )

        # ── Summary report ────────────────────────────────────────────────────
        if total_sent == 0:
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

        await bot.send_message(
            admin_id,
            f"✅ נשלחו **{total_sent}** סרטונים מ-{len(channels)} ערוצים\n"
            f"(עד {VIDEOS_PER_CHANNEL} סרטונים עם הכי הרבה צפיות מכל ערוץ)",
        )
        if scan_errors:
            await bot.send_message(
                admin_id,
                f"⚠️ {len(scan_errors)} ערוצים לא היו נגישים:\n" + "\n".join(scan_errors[:5]),
            )
        logger.info("Daily job done. Sent %d videos total.", total_sent)

    except Exception as exc:
        logger.error("daily_job error: %s", exc, exc_info=True)
        try:
            await bot.send_message(admin_id, f"❌ שגיאה בשליחה היומית:\n`{exc}`")
        except Exception:
            pass
