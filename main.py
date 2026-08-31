import os
import time
import logging
import sqlite3
import wikipedia

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)

from keep_alive import keep_alive

# ===== CONFIG =====
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
LOG_CHAT_ID = int(os.getenv("LOG_CHAT_ID"))
ADMIN_ID = int(os.getenv("ADMIN_ID"))

logging.basicConfig(level=logging.INFO)

# ===== DATABASE =====
conn = sqlite3.connect("bot.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    name TEXT,
    username TEXT,
    language TEXT
)
""")

conn.commit()

# ===== MEMORY =====
search_cache = {}  # {(chat_id, user_id): results}

# ===== HELPERS =====
def save_user(user):
    cursor.execute(
        "INSERT OR REPLACE INTO users VALUES (?, ?, ?, ?)",
        (user.id, user.full_name, user.username, user.language_code)
    )
    conn.commit()

async def log(context, text):
    await context.bot.send_message(LOG_CHAT_ID, text)

# ===== AUTO SAVE USERS =====
async def track_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.from_user:
        save_user(update.message.from_user)

# ===== USER FIND =====
def find_user(query):
    cursor.execute("SELECT * FROM users")
    users = cursor.fetchall()

    query = query.lower()

    for u in users:
        uid, name, username, lang = u

        if str(uid) == query:
            return u

        if username and ("@" + username).lower() == query:
            return u

        if name and query in name.lower():
            return u

    return None

# ===== USERINFO =====
async def userinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        query = " ".join(context.args)
        user = find_user(query)
    elif update.message.reply_to_message:
        u = update.message.reply_to_message.from_user
        save_user(u)
        user = (u.id, u.full_name, u.username, u.language_code)
    else:
        await update.message.reply_text("Reply or give username")
        return

    if not user:
        await update.message.reply_text("User not found")
        return

    text = f"📌 USER INFO\nName: {user[1]}\nUsername: @{user[2]}\nID: {user[0]}\nLang: {user[3]}"
    await log(context, text)
    await update.message.reply_text("Sent to log")

# ===== SEARCH USER =====
async def searchuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    user = find_user(query)

    if not user:
        await update.message.reply_text("User not found")
        return

    await update.message.reply_text(f"Found: {user[1]} (@{user[2]})")

# ===== SEARCH =====
async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)

    try:
        results = wikipedia.search(query, results=5)

        if not results:
            await update.message.reply_text("No results")
            return

        key = (update.effective_chat.id, update.effective_user.id)
        search_cache[key] = results

        msg = "🔎 Results:\n"
        for i, r in enumerate(results, 1):
            msg += f"{i}. {r}\n"

        msg += "\nUse: /choose 1"
        await update.message.reply_text(msg)

    except:
        await update.message.reply_text("Search failed, try different word")

# ===== CHOOSE =====
async def choose(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = (update.effective_chat.id, update.effective_user.id)

    if key not in search_cache:
        await update.message.reply_text("Search first")
        return

    try:
        index = int(context.args[0]) - 1
        title = search_cache[key][index]

        summary = wikipedia.summary(title, sentences=5)

        await update.message.reply_text(f"📖 {title}\n\n{summary}")

    except:
        await update.message.reply_text("Invalid choice")

# ===== PANEL =====
async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("User Info", callback_data="x")],
        [InlineKeyboardButton("Search", callback_data="x")],
        [InlineKeyboardButton("Health", callback_data="x")]
    ]
    await update.message.reply_text("Admin Panel", reply_markup=InlineKeyboardMarkup(keyboard))

# ===== HEALTH =====
start_time = time.time()

async def health(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uptime = int(time.time() - start_time)
    await update.message.reply_text(f"Bot running\nUptime: {uptime}s")

# ===== ERROR =====
async def error_handler(update, context):
    print(context.error)

# ===== MAIN =====
def main():
    keep_alive()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_error_handler(error_handler)

    app.add_handler(MessageHandler(filters.ALL, track_users))

    app.add_handler(CommandHandler("userinfo", userinfo))
    app.add_handler(CommandHandler("searchuser", searchuser))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("choose", choose))
    app.add_handler(CommandHandler("panel", panel))
    app.add_handler(CommandHandler("health", health))

    print("Bot started")
    app.run_polling()

if __name__ == "__main__":
    main()
