"""
Telegram command handlers (admin-only).

Commands:
  /start          – help menu
  /addchannel     – add a channel to the scan list
  /removechannel  – remove a channel from the scan list
  /listchannels   – show all active channels
  /settime HH:MM  – change the daily send time (UTC)
  /sendnow        – trigger the daily job immediately
  /status         – show bot state and next run time
  /search <name>  – search Telegram for channels by name
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pyrogram import Client, filters
from pyrogram.types import Message

from db import (
    add_channel,
    get_channels,
    get_setting,
    remove_channel,
    set_setting,
)
from scanner import daily_job

logger = logging.getLogger(__name__)

HELP_TEXT = (
    "📋 **פקודות זמינות:**\n\n"
    "/mychannels — רשימת כל הערוצים בחשבונך (לבחירת ID)\n"
    "/addchannel `@username` או `ID` — הוסף ערוץ לסריקה\n"
    "/removechannel `@username` או `ID` — הסר ערוץ\n"
    "/listchannels — ערוצים שמוגדרים לסריקה\n"
    "/settime `HH:MM` — שנה שעת שליחה יומית (UTC)\n"
    "/sendnow — שלח את הסרטון הטוב ביותר עכשיו\n"
    "/status — סטטוס הבוט\n"
    "/search `שם ערוץ` — חפש ערוץ בטלגרם"
)


def register_handlers(
    bot: Client,
    userbot: Client,
    scheduler: AsyncIOScheduler,
    admin_id: int,
    target_channel: str,
    min_duration: int,
    data_dir: str,
) -> None:

    # Helper: build a filter that accepts only the admin in private chat
    admin_filter = filters.private & filters.user(admin_id)

    # ── /start ───────────────────────────────────────────────────────────────

    @bot.on_message(filters.command("start") & admin_filter)
    async def cmd_start(_: Client, msg: Message) -> None:
        await msg.reply(f"👋 ברוך הבא!\n\n{HELP_TEXT}")

    # ── helpers ──────────────────────────────────────────────────────────────

    async def _resolve_chat(identifier: str):
        """
        Find a chat the userbot has access to.
        1. For @username  → join (public) or get_chat (already member)
        2. For numeric ID → search dialogs directly (bypasses peer cache issues)
        """
        identifier = identifier.strip()

        # Numeric ID path — search dialogs to get the access_hash
        if identifier.lstrip("-").isdigit():
            target_id = int(identifier)
            # Strip Telegram's -100 prefix to get the raw channel id
            raw_id = abs(target_id)
            if str(raw_id).startswith("100"):
                raw_id = int(str(raw_id)[3:])

            async for dialog in userbot.get_dialogs():
                did = dialog.chat.id
                if did == target_id or abs(did) == raw_id:
                    return dialog.chat

            raise ValueError(
                "הערוץ לא נמצא בחשבונך. ודא שהחשבון שיצר את ה-Session String מנוי לערוץ זה."
            )

        # Username path — try join first, fallback to get_chat
        try:
            return await userbot.join_chat(identifier)
        except Exception:
            return await userbot.get_chat(identifier)

    # ── /addchannel ──────────────────────────────────────────────────────────

    @bot.on_message(filters.command("addchannel") & admin_filter)
    async def cmd_add_channel(_: Client, msg: Message) -> None:
        parts = msg.text.split(maxsplit=1)
        if len(parts) < 2:
            await msg.reply(
                "שימוש:\n"
                "• ערוץ ציבורי: `/addchannel @username`\n"
                "• ערוץ פרטי: `/addchannel -1001234567890`\n\n"
                "לרשימת ערוצים זמינים: /mychannels"
            )
            return

        identifier = parts[1].strip()
        await msg.reply("🔍 מחפש ערוץ...")
        try:
            chat = await _resolve_chat(identifier)
            await add_channel(data_dir, str(chat.id), chat.title or identifier)
            await msg.reply(f"✅ ערוץ נוסף: **{chat.title}** (`{chat.id}`)")
        except Exception as exc:
            await msg.reply(
                f"❌ לא הצלחתי למצוא את הערוץ.\n\n"
                f"נסה `/mychannels` לרשימת כל הערוצים שהחשבון שלך מנוי אליהם.\n\n"
                f"`{exc}`"
            )

    # ── /removechannel ───────────────────────────────────────────────────────

    @bot.on_message(filters.command("removechannel") & admin_filter)
    async def cmd_remove_channel(_: Client, msg: Message) -> None:
        parts = msg.text.split(maxsplit=1)
        if len(parts) < 2:
            await msg.reply("שימוש: `/removechannel @username` או `channel_id`")
            return

        identifier = parts[1].strip()
        try:
            chat = await userbot.get_chat(identifier)
            removed = await remove_channel(data_dir, str(chat.id))
            if removed:
                await msg.reply(f"✅ ערוץ הוסר: **{chat.title}**")
            else:
                await msg.reply(f"⚠️ הערוץ לא נמצא ברשימה.")
        except Exception as exc:
            await msg.reply(f"❌ שגיאה: `{exc}`")

    # ── /mychannels ──────────────────────────────────────────────────────────

    @bot.on_message(filters.command("mychannels") & admin_filter)
    async def cmd_my_channels(_: Client, msg: Message) -> None:
        await msg.reply("⏳ טוען רשימת ערוצים מהחשבון שלך...")
        lines = []
        try:
            async for dialog in userbot.get_dialogs():
                chat = dialog.chat
                # Show only channels and supergroups
                if str(chat.type) not in ("ChatType.CHANNEL", "ChatType.SUPERGROUP"):
                    continue
                username = f"@{chat.username}" if chat.username else "פרטי"
                lines.append(f"• **{chat.title}** — `{chat.id}` ({username})")
                if len(lines) >= 50:
                    break

            if not lines:
                await msg.reply("לא נמצאו ערוצים בחשבון.")
                return

            # Split into chunks of 30 to avoid message size limit
            chunk = lines[:30]
            await msg.reply(
                f"📋 **ערוצים בחשבון ({len(lines)} נמצאו):**\n\n" + "\n".join(chunk)
            )
            if len(lines) > 30:
                await msg.reply("\n".join(lines[30:]))

        except Exception as exc:
            await msg.reply(f"❌ שגיאה: `{exc}`")

    # ── /listchannels ────────────────────────────────────────────────────────

    @bot.on_message(filters.command("listchannels") & admin_filter)
    async def cmd_list_channels(_: Client, msg: Message) -> None:
        channels = await get_channels(data_dir)
        if not channels:
            await msg.reply("📭 אין ערוצים ברשימה. הוסף עם /addchannel.")
            return

        lines = [f"{i}. **{name}** (`{cid}`)"
                 for i, (cid, name) in enumerate(channels, 1)]
        await msg.reply("📋 **ערוצים פעילים:**\n\n" + "\n".join(lines))

    # ── /settime ─────────────────────────────────────────────────────────────

    @bot.on_message(filters.command("settime") & admin_filter)
    async def cmd_set_time(_: Client, msg: Message) -> None:
        parts = msg.text.split(maxsplit=1)
        if len(parts) < 2:
            await msg.reply("שימוש: `/settime HH:MM`  (זמן UTC)\nדוגמה: `/settime 18:30`")
            return

        time_str = parts[1].strip()
        try:
            h, m = time_str.split(":")
            hour, minute = int(h), int(m)
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError
        except ValueError:
            await msg.reply("❌ פורמט שגוי. השתמש ב-`HH:MM` (לדוגמה: `18:30`).")
            return

        await set_setting(data_dir, "send_hour", str(hour))
        await set_setting(data_dir, "send_minute", str(minute))

        # Update the live scheduler job
        scheduler.reschedule_job(
            "daily_send",
            trigger="cron",
            hour=hour,
            minute=minute,
        )

        await msg.reply(
            f"⏰ שעת שליחה עודכנה: **{hour:02d}:{minute:02d} UTC**\n"
            f"(ישראל = UTC+2 בחורף, UTC+3 בקיץ)"
        )

    # ── /sendnow ─────────────────────────────────────────────────────────────

    @bot.on_message(filters.command("sendnow") & admin_filter)
    async def cmd_send_now(_: Client, msg: Message) -> None:
        await msg.reply("🔍 סורק ערוצים...")
        await daily_job(
            userbot=userbot,
            bot=bot,
            target_channel=target_channel,
            min_duration=min_duration,
            admin_id=admin_id,
            data_dir=data_dir,
        )

    # ── /status ──────────────────────────────────────────────────────────────

    @bot.on_message(filters.command("status") & admin_filter)
    async def cmd_status(_: Client, msg: Message) -> None:
        channels = await get_channels(data_dir)
        send_hour   = await get_setting(data_dir, "send_hour",   "12")
        send_minute = await get_setting(data_dir, "send_minute", "00")

        job = scheduler.get_job("daily_send")
        next_run = str(job.next_run_time) if job else "לא מתוזמן"

        await msg.reply(
            f"📊 **סטטוס בוט**\n\n"
            f"✅ פעיל\n"
            f"📺 ערוצים פעילים: **{len(channels)}**\n"
            f"⏰ שעת שליחה: **{int(send_hour):02d}:{int(send_minute):02d} UTC**\n"
            f"🕐 ריצה הבאה: `{next_run}`\n"
            f"🎬 מינימום אורך וידאו: {min_duration // 60} דקות"
        )

    # ── /search ──────────────────────────────────────────────────────────────

    @bot.on_message(filters.command("search") & admin_filter)
    async def cmd_search(_: Client, msg: Message) -> None:
        parts = msg.text.split(maxsplit=1)
        if len(parts) < 2:
            await msg.reply("שימוש: `/search שם הערוץ`")
            return

        query = parts[1].strip()
        await msg.reply(f"🔍 מחפש: **{query}**...")

        try:
            # Use Telegram's built-in contact/channel search
            from pyrogram.raw import functions as raw_functions

            result = await userbot.invoke(
                raw_functions.contacts.Search(q=query, limit=15)
            )

            chats = {c.id: c for c in result.chats}
            if not chats:
                await msg.reply("לא נמצאו ערוצים.")
                return

            lines = []
            for chat in chats.values():
                title = getattr(chat, "title", None) or "ללא שם"
                username = getattr(chat, "username", None)
                mention = f"@{username}" if username else f"`{chat.id}`"
                lines.append(f"• **{title}** — {mention}")

            await msg.reply(
                f"🔍 תוצאות עבור \"{query}\":\n\n" + "\n".join(lines[:10])
            )

        except Exception as exc:
            logger.error("Search error: %s", exc)
            await msg.reply(f"❌ שגיאה בחיפוש: `{exc}`")

    # ── Catch-all for unknown commands ───────────────────────────────────────

    @bot.on_message(filters.command([]) & admin_filter)
    async def cmd_unknown(_: Client, msg: Message) -> None:
        if msg.text and msg.text.startswith("/"):
            await msg.reply(f"❓ פקודה לא מוכרת.\n\n{HELP_TEXT}")
