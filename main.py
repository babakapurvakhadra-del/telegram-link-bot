import os
import logging
import requests
import wikipedia
from flask import Flask
from threading import Thread

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ---------------- CONFIG ----------------
TOKEN = os.getenv("TOKEN")
SERP_API_KEY = os.getenv("SERPAPI_KEY")

logging.basicConfig(level=logging.INFO)

# ---------------- KEEP ALIVE ----------------
app_web = Flask(__name__)

@app_web.route("/")
def home():
    return "Bot is alive", 200

@app_web.route("/health")
def health():
    return "OK", 200

def run_web():
    app_web.run(host="0.0.0.0", port=8080)

def keep_alive():
    t = Thread(target=run_web)
    t.start()

# ---------------- COMMANDS ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔍 Search", callback_data="search")],
        [InlineKeyboardButton("👤 User Info", callback_data="userinfo")],
        [InlineKeyboardButton("🛡 Domains", callback_data="domains")],
        [InlineKeyboardButton("❤️ Health", callback_data="health")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "🤖 *Admin Panel*\nClick buttons below:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def health_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Bot is running perfectly")

# ---------------- SEARCH ----------------

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /search keyword")
        return

    query = " ".join(context.args)

    # Google search via SERP API
    try:
        url = f"https://serpapi.com/search.json?q={query}&api_key={SERP_API_KEY}"
        res = requests.get(url).json()

        if "organic_results" in res:
            first = res["organic_results"][0]
            msg = f"🔎 *Google Result*\n{first['title']}\n{first['link']}"
            await update.message.reply_text(msg, parse_mode="Markdown")
            return
    except:
        pass

    # Wikipedia fallback
    try:
        summary = wikipedia.summary(query, sentences=2)
        await update.message.reply_text(f"📚 {summary}")
    except:
        await update.message.reply_text("❌ No result found")

# ---------------- USER INFO ----------------

async def userinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.reply_to_message.from_user if update.message.reply_to_message else update.message.from_user

    text = f"""
👤 Name: {user.first_name}
🆔 ID: {user.id}
🔗 Username: @{user.username if user.username else "N/A"}
"""
    await update.message.reply_text(text)

# ---------------- LINK FILTER ----------------

BLOCKED = ["http", "https", ".com"]

async def filter_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()

    if any(word in text for word in BLOCKED):
        try:
            await update.message.delete()
        except:
            pass

# ---------------- MAIN ----------------

def main():
    if not TOKEN:
        print("❌ TOKEN missing")
        return

    keep_alive()

    app = ApplicationBuilder().token(TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("health", health_cmd))
    app.add_handler(CommandHandler("userinfo", userinfo))

    # Message filter
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), filter_links))

    print("✅ Bot started...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
