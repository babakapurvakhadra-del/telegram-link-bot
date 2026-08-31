import logging
import os
import re
import time
import sqlite3
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
LOG_CHAT_ID = int(os.getenv("LOG_CHAT_ID"))
ADMINS = {int(os.getenv("ADMIN_ID"))}

logging.basicConfig(level=logging.INFO)
start_time = time.time()

# ======================
# DATABASE
# ======================

conn = sqlite3.connect("bot.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    name TEXT,
    username TEXT,
    language TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS warnings (
    user_id INTEGER PRIMARY KEY,
    count INTEGER
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS muted (
    user_id INTEGER PRIMARY KEY
)
""")

conn.commit()

# ======================
# MEMORY
# ======================

allowed_domains = {"youtube.com", "youtu.be", "t.me"}
blocked_domains = set()

URL_PATTERN = re.compile(r"(https?://[^\s]+|www\.[^\s]+)")

# ======================
# HELPERS
# ======================

def save_user(user):
    cur.execute(
        "INSERT OR REPLACE INTO users VALUES (?, ?, ?, ?)",
        (user.id, user.full_name, user.username, user.language_code),
    )
    conn.commit()

def get_warnings(user_id):
    cur.execute("SELECT count FROM warnings WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    return row[0] if row else 0

def add_warning(user_id):
    count = get_warnings(user_id) + 1
    cur.execute("INSERT OR REPLACE INTO warnings VALUES (?, ?)", (user_id, count))
    conn.commit()
    return count

def reset_warning(user_id):
    cur.execute("DELETE FROM warnings WHERE user_id=?", (user_id,))
    conn.commit()

def is_muted(user_id):
    cur.execute("SELECT 1 FROM muted WHERE user_id=?", (user_id,))
    return cur.fetchone() is not None

def mute_user(user_id):
    cur.execute("INSERT OR REPLACE INTO muted VALUES (?)", (user_id,))
    conn.commit()

def unmute_user(user_id):
    cur.execute("DELETE FROM muted WHERE user_id=?", (user_id,))
    conn.commit()

async def log_private(context, text):
    await context.bot.send_message(chat_id=LOG_CHAT_ID, text=text)

# ======================
# DETECTION
# ======================

def is_suspicious(text: str):
    urls = URL_PATTERN.findall(text.lower())

    for url in urls:
        if any(d in url for d in allowed_domains):
            continue
        if any(d in url for d in blocked_domains):
            return True
        if url.startswith("http"):
            return True

    return False

# ======================
# COMMANDS
# ======================

async def userinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message

    if msg.reply_to_message:
        user = msg.reply_to_message.from_user
    else:
        user = msg.from_user

    save_user(user)

    text = (
        f"📌 USER INFO\n"
        f"Name: {user.full_name}\n"
        f"Username: @{user.username if user.username else 'None'}\n"
        f"User ID: {user.id}\n"
        f"Language: {user.language_code}"
    )

    await log_private(context, text)
    await msg.reply_text("User info sent to private log")

async def searchuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)

    cur.execute("SELECT * FROM users WHERE name LIKE ? OR username LIKE ?", (f"%{query}%", f"%{query}%"))
    rows = cur.fetchall()

    if not rows:
        await update.message.reply_text("User not found")
        return

    text = "🔍 USERS FOUND:\n\n"
    for r in rows[:5]:
        text += f"{r[1]} (@{r[2]}) | ID: {r[0]}\n"

    await log_private(context, text)
    await update.message.reply_text("Result sent to private log")

async def warnings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(f"Warnings: {get_warnings(user_id)}")

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        return
    uid = update.message.reply_to_message.from_user.id
    reset_warning(uid)
    await update.message.reply_text("Reset done")

async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        return
    uid = update.message.reply_to_message.from_user.id
    mute_user(uid)
    await update.message.reply_text("Muted")

async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        return
    uid = update.message.reply_to_message.from_user.id
    unmute_user(uid)
    await update.message.reply_text("Unmuted")

async def allow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /allow domain.com")
        return
    allowed_domains.add(context.args[0])
    await update.message.reply_text("Allowed")

async def block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /block domain.com")
        return
    blocked_domains.add(context.args[0])
    await update.message.reply_text("Blocked")

# ✅ FIXED SEARCH
async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)

    if not query:
        await update.message.reply_text("Usage: /search topic")
        return

    try:
        results = wikipedia.search(query)

        if not results:
            await update.message.reply_text("No results found")
            return

        if len(results) > 1:
            text = "🔎 Multiple results:\n\n"
            for i, r in enumerate(results[:5], 1):
                text += f"{i}. {r}\n"
            await update.message.reply_text(text)
            return

        page = wikipedia.page(results[0])
        summary = wikipedia.summary(page.title, sentences=2)
        await update.message.reply_text(summary)

    except:
        await update.message.reply_text("Search failed")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uptime = int(time.time() - start_time)
    await update.message.reply_text(f"Uptime: {uptime} sec")

async def health_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Bot is healthy")

# ======================
# EVENTS
# ======================

async def new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for user in update.message.new_chat_members:
        save_user(user)
        await log_private(context, f"New Member: {user.full_name} | {user.id}")

async def bot_added(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    await log_private(context, f"Bot added in {chat.title} by {user.full_name}")

# ======================
# MESSAGE HANDLER
# ======================

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text or ""

    save_user(user)

    if is_muted(user.id):
        await update.message.delete()
        return

    if user.id in ADMINS:
        return

    if is_suspicious(text):
        add_warning(user.id)
        await update.message.delete()
        await log_private(context, f"Deleted: {text}")

# ======================
# ERROR HANDLER
# ======================

async def error_handler(update, context):
    print(context.error)

# ======================
# MAIN
# ======================

def main():
    keep_alive()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_error_handler(error_handler)

    app.add_handler(CommandHandler("userinfo", userinfo))
    app.add_handler(CommandHandler("searchuser", searchuser))
    app.add_handler(CommandHandler("warnings", warnings))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("mute", mute))
    app.add_handler(CommandHandler("unmute", unmute))
    app.add_handler(CommandHandler("allow", allow))
    app.add_handler(CommandHandler("block", block))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("health", health_cmd))

    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_member))
    app.add_handler(MessageHandler(filters.ALL, handle))

    print("Bot started")
    app.run_polling()

if __name__ == "__main__":
    main()
