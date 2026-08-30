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
# CONFIG (SAFE)
# ======================

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

LOG_CHAT_ID = os.getenv("LOG_CHAT_ID")
ADMIN_ID = os.getenv("ADMIN_ID")

if not TOKEN:
    raise ValueError("Missing TELEGRAM_BOT_TOKEN")

if not LOG_CHAT_ID:
    raise ValueError("Missing LOG_CHAT_ID")

if not ADMIN_ID:
    raise ValueError("Missing ADMIN_ID")

LOG_CHAT_ID = int(LOG_CHAT_ID)
ADMIN_ID = int(ADMIN_ID)

ADMINS = {ADMIN_ID}

logging.basicConfig(level=logging.INFO)

start_time = time.time()

# ======================
# STORAGE (FIXED SCOPING)
# ======================

# FIXED: per chat + per user warnings
user_warnings = defaultdict(int)

muted_users = set()

allowed_domains = {"youtube.com", "youtu.be", "t.me", "telegram.me"}
blocked_domains = set()

known_users = {}

URL_PATTERN = re.compile(r"(https?://[^\s]+|www\.[^\s]+)")

# ======================
# LOG FUNCTION (SAFE)
# ======================

async def log_private(context, text):
    try:
        await context.bot.send_message(chat_id=LOG_CHAT_ID, text=text)
    except Exception as e:
        logging.error(f"LOG ERROR: {e}")

# ======================
# LINK DETECTION
# ======================

def is_suspicious(text: str):
    if not text:
        return False

    text = text.lower()
    urls = URL_PATTERN.findall(text)

    for url in urls:
        if any(domain in url for domain in allowed_domains):
            continue

        if any(domain in url for domain in blocked_domains):
            return True

        return True

    return False

# ======================
# NEW MEMBER TRACKING
# ======================

async def new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    chat = update.effective_chat

    for user in update.message.new_chat_members:
        known_users[user.id] = user

        await log_private(
            context,
            f"👤 NEW MEMBER\n"
            f"Name: {user.full_name}\n"
            f"Username: @{user.username if user.username else 'No username'}\n"
            f"User ID: {user.id}\n"
            f"Language: {user.language_code}"
        )

        # BOT DETECTED IN GROUP (SAFE CHECK)
        if user.is_bot:
            await log_private(
                context,
                f"🤖 BOT ADDED / JOINED\n"
                f"Group: {chat.title}\n"
                f"Group ID: {chat.id}\n"
                f"Bot: @{user.username}"
            )

# ======================
# USER INFO
# ======================

async def userinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a user")
        return

    user = update.message.reply_to_message.from_user

    await log_private(
        context,
        f"📌 USER INFO\n"
        f"Name: {user.full_name}\n"
        f"Username: @{user.username if user.username else 'No username'}\n"
        f"User ID: {user.id}\n"
        f"Language: {user.language_code}"
    )

# ======================
# WARNINGS (FIXED SCOPING)
# ======================

async def warnings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    await update.message.reply_text(
        f"Warnings: {user_warnings[(chat_id, user_id)]}"
    )

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        return

    chat_id = update.effective_chat.id
    user_id = update.message.reply_to_message.from_user.id

    user_warnings[(chat_id, user_id)] = 0
    await update.message.reply_text("Reset done")

# ======================
# MUTE / UNMUTE
# ======================

async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        return

    muted_users.add(update.message.reply_to_message.from_user.id)
    await update.message.reply_text("User muted")

async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        return

    muted_users.discard(update.message.reply_to_message.from_user.id)
    await update.message.reply_text("User unmuted")

# ======================
# LINK CONTROL (SAFE)
# ======================

async def allow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /allow domain.com")
        return

    allowed_domains.add(context.args[0].lower())
    await update.message.reply_text("Allowed added")

async def block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /block domain.com")
        return

    blocked_domains.add(context.args[0].lower())
    await update.message.reply_text("Blocked added")

# ======================
# SEARCH (SAFE)
# ======================

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)

    if not query:
        await update.message.reply_text("Usage: /search topic")
        return

    try:
        wikipedia.set_lang("en")
        result = wikipedia.summary(query, sentences=2)
        await update.message.reply_text(result)
    except Exception:
        await update.message.reply_text("No result found")

# ======================
# STATUS
# ======================

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uptime = int(time.time() - start_time)
    await update.message.reply_text(f"Uptime: {uptime} sec")

# ======================
# MESSAGE HANDLER
# ======================

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user = update.effective_user
    chat_id = update.effective_chat.id
    text = update.message.text

    known_users[user.id] = user

    if user.id in muted_users:
        await update.message.delete()
        return

    if user.id in ADMINS:
        return

    if is_suspicious(text):
        user_warnings[(chat_id, user.id)] += 1

        try:
            await update.message.delete()
        except:
            pass

        await log_private(context, f"🚨 Deleted Message: {text}")

# ======================
# ERROR HANDLER (FIXED)
# ======================

async def error_handler(update, context):
    logging.error(f"ERROR: {context.error}")

# ======================
# KEEP ALIVE
# ======================

from keep_alive import keep_alive

# ======================
# MAIN
# ======================

def main():
    keep_alive()

    app = ApplicationBuilder().token(TOKEN).build()

    # FIX: prevent webhook conflict
    app.bot.delete_webhook(drop_pending_updates=True)

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

    # MESSAGES
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

    # ERROR HANDLER
    app.add_error_handler(error_handler)

    print("Bot started successfully")

    app.run_polling()

if __name__ == "__main__":
    main()
