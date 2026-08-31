import os
import logging
import asyncio
from collections import defaultdict

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

import requests
import wikipedia

# ---------------- CONFIG ----------------
TOKEN = os.getenv("TOKEN")
SERPAPI_KEY = os.getenv("SERPAPI_KEY")

logging.basicConfig(level=logging.INFO)

# Per group warnings
user_warnings = defaultdict(int)

# ---------------- KEEP ALIVE ----------------
from flask import Flask
from threading import Thread

app_flask = Flask(__name__)

@app_flask.route("/")
def home():
    return "Bot is alive", 200

@app_flask.route("/health")
def health():
    return "OK", 200

def run():
    app_flask.run(host="0.0.0.0", port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# ---------------- FUNCTIONS ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔍 Search", callback_data="search")],
        [InlineKeyboardButton("👤 User Info", callback_data="userinfo")],
        [InlineKeyboardButton("🔇 Mute", callback_data="mute"),
         InlineKeyboardButton("🔊 Unmute", callback_data="unmute")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "🤖 Admin Panel\nChoose an option:",
        reply_markup=reply_markup
    )

# ---------------- CALLBACK ----------------

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "search":
        await query.message.reply_text("Send:\n/search your_query")

    elif query.data == "userinfo":
        members = await context.bot.get_chat_administrators(query.message.chat_id)
        text = "Admins:\n"
        for m in members:
            text += f"{m.user.first_name} (@{m.user.username})\n"
        await query.message.reply_text(text)

    elif query.data == "mute":
        await query.message.reply_text("Reply to user with /mute")

    elif query.data == "unmute":
        await query.message.reply_text("Reply to user with /unmute")

# ---------------- SEARCH ----------------

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /search query")
        return

    query = " ".join(context.args)

    # Try Google (SerpAPI)
    try:
        url = "https://serpapi.com/search.json"
        params = {
            "q": query,
            "api_key": SERPAPI_KEY,
            "engine": "google"
        }
        res = requests.get(url, params=params).json()

        if "organic_results" in res:
            result = res["organic_results"][0]
            msg = f"🔎 {result['title']}\n{result['link']}"
            await update.message.reply_text(msg)
            return
    except:
        pass

    # Fallback Wikipedia
    try:
        summary = wikipedia.summary(query, sentences=2)
        await update.message.reply_text(summary)
    except:
        await update.message.reply_text("No result found")

# ---------------- USER ACTIONS ----------------

async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.reply_to_message:
        user_id = update.message.reply_to_message.from_user.id
        chat_id = update.message.chat_id

        await context.bot.restrict_chat_member(
            chat_id,
            user_id,
            permissions={}
        )
        await update.message.reply_text("User muted")

async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.reply_to_message:
        user_id = update.message.reply_to_message.from_user.id
        chat_id = update.message.chat_id

        await context.bot.restrict_chat_member(
            chat_id,
            user_id,
            permissions={"can_send_messages": True}
        )
        await update.message.reply_text("User unmuted")

async def userinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.reply_to_message:
        user = update.message.reply_to_message.from_user
        text = f"""
👤 Name: {user.first_name}
🆔 ID: {user.id}
🔗 Username: @{user.username}
"""
        await update.message.reply_text(text)

# ---------------- ANTI LINK ----------------

async def filter_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()

    if "http" in text or "t.me" in text:
        await update.message.delete()

        key = (update.message.chat_id, update.message.from_user.id)
        user_warnings[key] += 1

        await update.message.chat.send_message(
            f"⚠️ Warning {user_warnings[key]} for {update.message.from_user.first_name}"
        )

# ---------------- ERROR HANDLER ----------------

async def error_handler(update, context):
    print(f"Error: {context.error}")

# ---------------- MAIN ----------------

async def main():
    keep_alive()

    app = ApplicationBuilder().token(TOKEN).build()

    # FIXED webhook properly
    await app.bot.delete_webhook(drop_pending_updates=True)

    # handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("mute", mute))
    app.add_handler(CommandHandler("unmute", unmute))
    app.add_handler(CommandHandler("userinfo", userinfo))

    app.add_handler(CallbackQueryHandler(button_handler))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, filter_links))

    app.add_error_handler(error_handler)

    await app.run_polling()

# ---------------- RUN ----------------

if __name__ == "__main__":
    asyncio.run(main())
