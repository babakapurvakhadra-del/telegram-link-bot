import os
import logging
import requests
import wikipedia
from collections import defaultdict
from flask import Flask
from threading import Thread

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    CallbackQueryHandler,
    filters
)

# ================== CONFIG ==================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SERPAPI_KEY = os.getenv("SERPAPI_KEY")

if not TOKEN:
    print("❌ TOKEN missing")
    exit(1)

logging.basicConfig(level=logging.INFO)

# ================== KEEP ALIVE ==================
app_flask = Flask(__name__)

@app_flask.route("/")
def home():
    return "Bot is alive", 200

@app_flask.route("/health")
def health():
    return "OK", 200

def run_flask():
    app_flask.run(host="0.0.0.0", port=8080)

def keep_alive():
    t = Thread(target=run_flask)
    t.start()

# ================== DATA ==================
user_warnings = defaultdict(int)

# ================== COMMANDS ==================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔍 Search", callback_data="search")],
        [InlineKeyboardButton("👤 User Info", callback_data="userinfo")],
        [InlineKeyboardButton("🔇 Mute", callback_data="mute"),
         InlineKeyboardButton("🔊 Unmute", callback_data="unmute")],
        [InlineKeyboardButton("❤️ Health", callback_data="health")]
    ]
    await update.message.reply_text(
        "✅ Bot Active\nSelect command:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def health_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Bot is healthy")

# ================== SEARCH ==================

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)

    if not query:
        await update.message.reply_text("❌ Usage: /search keyword")
        return

    # Google (SerpAPI)
    try:
        url = "https://serpapi.com/search"
        params = {
            "q": query,
            "api_key": SERPAPI_KEY
        }
        res = requests.get(url, params=params).json()

        if "organic_results" in res:
            result = res["organic_results"][0]
            msg = f"🔎 {result['title']}\n{result['link']}"
            await update.message.reply_text(msg)
            return
    except:
        pass

    # Wikipedia fallback
    try:
        summary = wikipedia.summary(query, sentences=2)
        await update.message.reply_text(f"📚 {summary}")
    except:
        await update.message.reply_text("❌ No results found")

# ================== USER INFO ==================

async def userinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.reply_to_message:
        user = update.message.reply_to_message.from_user
        msg = f"👤 {user.first_name}\n🆔 {user.id}"
        await update.message.reply_text(msg)
    else:
        await update.message.reply_text("❌ Reply to a user")

# ================== MUTE ==================

async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.reply_to_message:
        user_id = update.message.reply_to_message.from_user.id
        await update.chat.restrict_member(user_id, permissions={})
        await update.message.reply_text("🔇 Muted")
    else:
        await update.message.reply_text("❌ Reply to user")

async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.reply_to_message:
        user_id = update.message.reply_to_message.from_user.id
        await update.chat.restrict_member(
            user_id,
            permissions={
                "can_send_messages": True
            }
        )
        await update.message.reply_text("🔊 Unmuted")
    else:
        await update.message.reply_text("❌ Reply to user")

# ================== LINK FILTER ==================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id

    if "http" in text:
        await update.message.delete()
        user_warnings[(chat_id, user_id)] += 1

        await update.message.chat.send_message(
            f"⚠️ Link removed\nWarnings: {user_warnings[(chat_id, user_id)]}"
        )

# ================== INLINE BUTTON HANDLER ==================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "health":
        await query.message.reply_text("✅ Bot is healthy")

    elif query.data == "search":
        await query.message.reply_text("Use: /search keyword")

    elif query.data == "userinfo":
        await query.message.reply_text("Reply to user → /userinfo")

    elif query.data == "mute":
        await query.message.reply_text("Reply to user → /mute")

    elif query.data == "unmute":
        await query.message.reply_text("Reply to user → /unmute")

# ================== MAIN ==================

def main():
    keep_alive()

    app = ApplicationBuilder().token(TOKEN).build()

    # commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("health", health_cmd))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("userinfo", userinfo))
    app.add_handler(CommandHandler("mute", mute))
    app.add_handler(CommandHandler("unmute", unmute))

    # messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # buttons
    app.add_handler(CallbackQueryHandler(button_handler))

    print("✅ Bot started")
    app.run_polling()

if __name__ == "__main__":
    main()
