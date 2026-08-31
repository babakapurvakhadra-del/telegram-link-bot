import logging
import os
import re
import time
from collections import defaultdict

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    CallbackQueryHandler,
    filters,
)

import wikipedia
from keep_alive import keep_alive

# ======================
# CONFIG
# ======================

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
LOG_CHAT_ID = int(os.getenv("LOG_CHAT_ID"))
ADMIN_ID = int(os.getenv("ADMIN_ID"))

ADMINS = {ADMIN_ID}

logging.basicConfig(level=logging.INFO)
start_time = time.time()

# ======================
# STORAGE
# ======================

user_warnings = defaultdict(int)
muted_users = set()
known_users = {}
search_cache = {}

# ======================
# PATTERN
# ======================

URL_PATTERN = re.compile(r"(https?://\S+|www\.\S+)")

# ======================
# LOG
# ======================

async def log_private(context, text):
    await context.bot.send_message(chat_id=LOG_CHAT_ID, text=text)

# ======================
# USER SAVE
# ======================

def save_user(user):
    known_users[user.id] = {
        "name": user.full_name,
        "username": user.username,
        "language": user.language_code,
    }

# ======================
# FIND USER
# ======================

def find_user(query):
    query = str(query).lower()

    for uid, data in known_users.items():
        if (
            query == str(uid)
            or (data["username"] and query == data["username"].lower())
            or query in data["name"].lower()
        ):
            return uid, data

    return None, None

# ======================
# NEW MEMBER
# ======================

async def new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for user in update.message.new_chat_members:
        save_user(user)

        text = (
            f"👤 NEW MEMBER\n"
            f"Name: {user.full_name}\n"
            f"Username: @{user.username if user.username else 'None'}\n"
            f"User ID: {user.id}\n"
            f"Language: {user.language_code}"
        )

        await log_private(context, text)

# ======================
# USER INFO
# ======================

async def userinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = None

    if update.message.reply_to_message:
        user = update.message.reply_to_message.from_user
        target = (user.id, known_users.get(user.id))

    elif context.args:
        uid, data = find_user(" ".join(context.args))
        target = (uid, data)

    if not target or not target[0]:
        await update.message.reply_text("User not found")
        return

    uid, data = target

    text = (
        f"📌 USER INFO\n"
        f"Name: {data['name']}\n"
        f"Username: @{data['username'] if data['username'] else 'None'}\n"
        f"User ID: {uid}\n"
        f"Language: {data['language']}"
    )

    await log_private(context, text)
    await update.message.reply_text("User info sent to private log")

# ======================
# SEARCH USER
# ======================

async def searchuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Usage: /searchuser name")

    uid, data = find_user(" ".join(context.args))

    if not uid:
        return await update.message.reply_text("User not found")

    text = (
        f"👤 FOUND USER\n"
        f"Name: {data['name']}\n"
        f"Username: @{data['username'] if data['username'] else 'None'}\n"
        f"User ID: {uid}"
    )

    await update.message.reply_text(text)

# ======================
# MUTE / UNMUTE
# ======================

async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = None

    if update.message.reply_to_message:
        uid = update.message.reply_to_message.from_user.id
    elif context.args:
        uid, _ = find_user(" ".join(context.args))

    if not uid:
        return await update.message.reply_text("User not found")

    muted_users.add(uid)
    await update.message.reply_text("User muted")

async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = None

    if update.message.reply_to_message:
        uid = update.message.reply_to_message.from_user.id
    elif context.args:
        uid, _ = find_user(" ".join(context.args))

    if not uid:
        return await update.message.reply_text("User not found")

    muted_users.discard(uid)
    await update.message.reply_text("User unmuted")

# ======================
# SEARCH (ADVANCED)
# ======================

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)

    try:
        results = wikipedia.search(query)

        if not results:
            return await update.message.reply_text("No results found")

        search_cache[update.effective_user.id] = results[:5]

        msg = "🔎 Multiple results:\n"
        for i, r in enumerate(results[:5], 1):
            msg += f"{i}. {r}\n"

        msg += "\nUse: /choose 1"
        await update.message.reply_text(msg)

    except Exception as e:
        await update.message.reply_text("Search error")

async def choose(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        index = int(context.args[0]) - 1
        results = search_cache.get(update.effective_user.id)

        if not results:
            return await update.message.reply_text("Search expired")

        title = results[index]
        summary = wikipedia.summary(title, sentences=5)

        await update.message.reply_text(f"📖 {title}\n\n{summary}")

    except:
        await update.message.reply_text("Invalid choice")

# ======================
# PANEL
# ======================

async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Status", callback_data="status")],
        [InlineKeyboardButton("Warnings", callback_data="warnings")],
    ]

    await update.message.reply_text(
        "Admin Panel",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "status":
        uptime = int(time.time() - start_time)
        await query.edit_message_text(f"Uptime: {uptime}s")

# ======================
# HANDLE MESSAGE
# ======================

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user)

    text = update.message.text

    if user.id in muted_users:
        await update.message.delete()
        return

    if URL_PATTERN.search(text):
        await update.message.delete()
        await log_private(context, f"🚨 Link removed: {text}")

# ======================
# MAIN
# ======================

def main():
    keep_alive()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("userinfo", userinfo))
    app.add_handler(CommandHandler("searchuser", searchuser))
    app.add_handler(CommandHandler("mute", mute))
    app.add_handler(CommandHandler("unmute", unmute))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("choose", choose))
    app.add_handler(CommandHandler("panel", panel))

    app.add_handler(CallbackQueryHandler(button_handler))

    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_member))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
