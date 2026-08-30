import logging
import os
import re
import time
from collections import defaultdict

from telegram import Update, ChatMemberUpdated
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
    ChatMemberHandler
)

from keep_alive import keep_alive
import wikipedia

# ======================
# CONFIG
# ======================

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

LOG_CHAT_ID = 6609362058
ADMINS = {6609362058}

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
# PATTERNS
# ======================

URL_PATTERN = re.compile(r"(https?://[^\s]+|www\.[^\s]+)")

# ======================
# DETECTION
# ======================

def is_suspicious(text: str) -> bool:
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
# PRIVATE LOG
# ======================

async def log_private(context, text):
    try:
        await context.bot.send_message(chat_id=LOG_CHAT_ID, text=text)
    except Exception as e:
        logging.error(f"Log error: {e}")

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
# BOT ADDED TRACK
# ======================

async def bot_added(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result: ChatMemberUpdated = update.my_chat_member

    if result.new_chat_member.status in ("member", "administrator"):
        chat = result.chat
        user = result.from_user

        text = (
            "🤖 BOT ADDED\n"
            f"Group: {chat.title}\n"
            f"Group ID: {chat.id}\n"
            f"Added by: {user.full_name}\n"
            f"User ID: {user.id}"
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
# FIND USER (FROM MEMORY)
# ======================

async def finduser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /finduser name")
        return

    query = " ".join(context.args).lower()

    results = []
    for user in known_users.values():
        if query in (user.full_name or "").lower() or query in (user.username or "").lower():
            results.append(f"{user.full_name} (@{user.username}) - {user.id}")

    if results:
        await log_private(context, "🔍 USER SEARCH\n" + "\n".join(results[:10]))
    else:
        await update.message.reply_text("No user found")

# ======================
# WARNINGS
# ======================

async def warnings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(f"Warnings: {user_warnings[user_id]}")

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        return

    user_id = update.message.reply_to_message.from_user.id
    user_warnings[user_id] = 0
    await update.message.reply_text("Reset done")

# ======================
# MUTE / UNMUTE
# ======================

async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        return

    user_id = update.message.reply_to_message.from_user.id
    muted_users.add(user_id)
    await update.message.reply_text("User muted")

async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        return

    user_id = update.message.reply_to_message.from_user.id
    muted_users.discard(user_id)
    await update.message.reply_text("User unmuted")

# ======================
# LINK CONTROL SAFE
# ======================

async def allow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /allow domain.com")
        return

    domain = context.args[0].lower()
    allowed_domains.add(domain)
    await update.message.reply_text(f"Allowed: {domain}")

async def block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /block domain.com")
        return

    domain = context.args[0].lower()
    blocked_domains.add(domain)
    await update.message.reply_text(f"Blocked: {domain}")

# ======================
# SEARCH (SAFE)
# ======================

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /search topic")
        return

    query = " ".join(context.args)

    try:
        result = wikipedia.summary(query, sentences=2)
        await update.message.reply_text(result)
    except wikipedia.exceptions.DisambiguationError:
        await update.message.reply_text("Too many results, be specific")
    except wikipedia.exceptions.PageError:
        await update.message.reply_text("No result found")
    except Exception:
        await update.message.reply_text("Error occurred")

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
    user = update.effective_user
    text = update.message.text

    known_users[user.id] = user

    if user.id in muted_users:
        await update.message.delete()
        return

    if user.id in ADMINS:
        return

    if is_suspicious(text):
        user_warnings[user.id] += 1

        try:
            await update.message.delete()
        except:
            pass

        await log_private(context, f"🚨 Deleted\nUser: {user.full_name}\nMessage: {text}")

# ======================
# MAIN
# ======================

def main():
    keep_alive()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("userinfo", userinfo))
    app.add_handler(CommandHandler("finduser", finduser))
    app.add_handler(CommandHandler("warnings", warnings))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("mute", mute))
    app.add_handler(CommandHandler("unmute", unmute))
    app.add_handler(CommandHandler("allow", allow))
    app.add_handler(CommandHandler("block", block))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("status", status))

    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_member))
    app.add_handler(ChatMemberHandler(bot_added, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

    print("Bot started")

    app.run_polling()

if __name__ == "__main__":
    main()
