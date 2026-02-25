"""
Run this script ONCE on your local machine to generate a SESSION_STRING.
The session string lets the bot act as your Telegram account (userbot).

Usage:
    pip install pyrogram TgCrypto
    python setup_session.py

Then copy the printed string into your Railway environment variables.
"""

from pyrogram import Client

print("=" * 60)
print("  Telegram Userbot — Session String Generator")
print("=" * 60)
print()
print("Get your API_ID and API_HASH from: https://my.telegram.org")
print()

api_id   = int(input("API_ID   : ").strip())
api_hash = input("API_HASH : ").strip()

print()
print("Telegram will now send you a login code via SMS or the app...")
print()

with Client("_tmp_session", api_id=api_id, api_hash=api_hash) as app:
    session_string = app.export_session_string()

print()
print("=" * 60)
print("  YOUR SESSION STRING (copy everything below):")
print("=" * 60)
print()
print(session_string)
print()
print("=" * 60)
print("Save this as the SESSION_STRING environment variable in Railway.")
print("Keep it secret — it gives full access to your Telegram account!")
print("=" * 60)
