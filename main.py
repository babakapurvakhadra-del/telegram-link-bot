import logging
import os
import re
import time
from collections import defaultdict

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from keep_alive import keep_alive
import wikipedia

# ======================
# CONFIG
# ======================

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

LOG_CHAT_ID = int(os.getenv("LOG_CHAT_ID", "0"))
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
ADMINS = {ADMIN_ID}

logging.basicConfig(level=logging.INFO)

start_time = time.time()

# ======================
# STORAGE
# ======================

user_warnings = defaultdict(int)
muted_users = set()

allowed_domains = set(["youtube.com", "youtu.be", "t.me", "telegram.me"])
blocked_domains = set()

known_users = {}

# ======================
# PATTERN
# ======================

URL_PATTERN = re.compile(r"(https?://[^\s]+|www\.[^\s]+)")

# ======================
# ERROR HANDLER
# ======================

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print("BOT ERROR:", context.error)

# ======================
# KEEP ALIVE
# ======================

def start_server():
    keep_alive()

# ======================
# DETECTION
# ======================

def is_suspicious(text: str) -> bool:
    if not text:
        return False

    text = text.lower()
    urls = URL_PATTERN.findall(text)

    for url in urls:
        url_low = url.lower()

        if any(domain in url_low for domain in allowed_domains):
            continue

        if any(domain in url_low for domain in blocked_domains):
            return True

        if url.startswith("http"):
            return True

    return False

# ======================
# LOGGING
# ======================

async def log_private(context, text):
    if LOG_CHAT_ID:
        await context.bot.send_message(chat_id=LOG_CHAT_ID, text=text)

# ======================
# NEW MEMBER
# ======================

async def new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for user in update.message.new_chat_members:
        known_users[user.id] = user

        text = (
            "👤 NEW MEMBER\n"
            f"Name: {user.full_name}\n"
            f"Username: @{user.username if user.username else 'No username'}\n"
            f"User ID: {user.id}\n"
            f"Language: {user.language_code}"
        )

        await log_private(context, text)

# ======================
# USER INFO
# ======================

async def userinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a user")
        return

    user = update.message.reply_to_message.from_user

    text = (
        "📌 USER INFO\n"
        f"Name: {user.full_name}\n"
        f"Username: @{user.username if user.username else 'No username'}\n"
        f"User ID: {user.id}\n"
        f"Language: {user.language_code}"
    )

    await log_private(context, text)

# ======================
# WARNINGS
# ======================

async def warnings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(f"Warnings: {user_warnings[user_id]}")

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.reply_to_message:
        user_id = update.message.reply_to_message.from_user.id
        user_warnings[user_id] = 0
        await update.message.reply_text("Warnings reset")

# ======================
# MUTE / UNMUTE
# ======================

async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.reply_to_message:
        user_id = update.message.reply_to_message.from_user.id
        muted_users.add(user_id)
        await update.message.reply_text("User muted")

async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.reply_to_message:
        user_id = update.message.reply_to_message.from_user.id
        muted_users.discard(user_id)
        await update.message.reply_text("User unmuted")

# ======================
# LINK CONTROL
# ======================

async def allow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /allow domain.com")
        return

    domain = context.args[0]
    allowed_domains.add(domain)
    await update.message.reply_text(f"Allowed: {domain}")

async def block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /block domain.com")
        return

    domain = context.args[0]
    blocked_domains.add(domain)
    await update.message.reply_text(f"Blocked: {domain}")

# ======================
# SEARCH
# ======================

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)

    if not query:
        await update.message.reply_text("Usage: /search topic")
        return

    try:
        result = wikipedia.summary(query, sentences=2)
        await update.message.reply_text(result)
    except:
        await update.message.reply_text("No result found")

# ======================
# STATUS
# ======================

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uptime = int(time.time() - start_time)
    await update.message.reply_text(f"Bot uptime: {uptime} sec")

# ======================
# MESSAGE HANDLER
# ======================

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if not update.message or not update.message.text:
        return

    text = update.message.text

    known_users[user.id] = user

    if user.id in muted_users:
        try:
            await update.message.delete()
        except:
            pass
        return

    if user.id in ADMINS:
        return

    if is_suspicious(text):
        user_warnings[user.id] += 1

        try:
            await update.message.delete()
        except:
            pass

        await log_private(context, f"🚨 Deleted message from {user.full_name}")

# ======================
# MAIN FUNCTION
# ======================

def main():
    start_server()

    app = ApplicationBuilder().token(TOKEN).build()

    # ✅ ERROR HANDLER (IMPORTANT)
    app.add_error_handler(error_handler)

    # COMMANDS
    app.add_handler(CommandHandler("userinfo", userinfo))
    app.add_handler(CommandHandler("warnings", warnings))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("mute", mute))
    app.add_handler(CommandHandler("unmute", unmute))
    app.add_handler(CommandHandler("allow", allow))
    app.add_handler(CommandHandler("block", block))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("status", status))

    # EVENTS
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_member))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

    print("Bot started successfully")

    app.run_polling(drop_pending_updates=True)

# ======================
# START
# ======================

if __name__ == "__main__":
    main()
