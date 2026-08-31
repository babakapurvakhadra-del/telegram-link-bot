import os
import logging
import sqlite3
import requests
import wikipedia
from flask import Flask
from functools import wraps

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# ================= CONFIG =================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SERPAPI_KEY = os.getenv("SERPAPI_KEY")

if not TOKEN:
    raise Exception("❌ TELEGRAM_BOT_TOKEN missing")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ================= DATABASE =================
conn = sqlite3.connect("bot.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""CREATE TABLE IF NOT EXISTS muted_users(
    chat_id INTEGER,
    user_id INTEGER
)""")

cur.execute("""CREATE TABLE IF NOT EXISTS blocked_domains(
    domain TEXT
)""")

conn.commit()

# ================= FLASK =================
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is alive"

@app.route("/health")
def health():
    return {"status": "ok"}

# ================= HELPERS =================
def safe(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            return await func(update, context)
        except Exception as e:
            logger.error(f"Error: {e}")
    return wrapper


def resolve_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Works for:
    - reply
    - username
    - user_id
    """
    msg = update.message

    if msg.reply_to_message:
        return msg.reply_to_message.from_user

    if context.args:
        arg = context.args[0]

        if arg.startswith("@"):
            for u in msg.chat.get_administrators():
                if u.user.username == arg[1:]:
                    return u.user

        try:
            return msg.chat.get_member(int(arg)).user
        except:
            pass

    return msg.from_user


# ================= INLINE PANEL =================
def admin_panel():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👤 User Info", callback_data="userinfo"),
            InlineKeyboardButton("🔇 Mute", callback_data="mute"),
        ],
        [
            InlineKeyboardButton("🔊 Unmute", callback_data="unmute"),
            InlineKeyboardButton("🌐 Allow Domain", callback_data="allow"),
        ],
        [
            InlineKeyboardButton("🚫 Block Domain", callback_data="block"),
            InlineKeyboardButton("📋 List Domains", callback_data="list"),
        ],
        [
            InlineKeyboardButton("🔍 Search", callback_data="search"),
            InlineKeyboardButton("🆔 Get ID", callback_data="id"),
        ]
    ])


# ================= COMMANDS =================
@safe
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Admin Panel",
        reply_markup=admin_panel()
    )


@safe
async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = resolve_user(update, context)

    cur.execute("INSERT INTO muted_users VALUES (?,?)",
                (update.effective_chat.id, user.id))
    conn.commit()

    await update.message.reply_text(f"🔇 Muted {user.full_name}")


@safe
async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = resolve_user(update, context)

    cur.execute("DELETE FROM muted_users WHERE chat_id=? AND user_id=?",
                (update.effective_chat.id, user.id))
    conn.commit()

    await update.message.reply_text(f"🔊 Unmuted {user.full_name}")


@safe
async def userinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = resolve_user(update, context)

    text = f"""
👤 User Info
ID: {user.id}
Name: {user.full_name}
Username: @{user.username if user.username else 'N/A'}
"""

    await update.message.reply_text(text)


@safe
async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = " ".join(context.args)

    if SERPAPI_KEY:
        url = "https://serpapi.com/search"
        res = requests.get(url, params={
            "q": q,
            "api_key": SERPAPI_KEY
        }).json()

        if "organic_results" in res:
            top = res["organic_results"][0]
            await update.message.reply_text(top.get("title", "") + "\n" + top.get("link", ""))
            return

    # fallback wikipedia
    try:
        await update.message.reply_text(wikipedia.summary(q, sentences=2))
    except:
        await update.message.reply_text("No results found")


# ================= CALLBACK HANDLER =================
@safe
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "userinfo":
        await query.message.reply_text("Reply with /userinfo @user or reply message")

    elif data == "mute":
        await query.message.reply_text("Reply with /mute @user")

    elif data == "unmute":
        await query.message.reply_text("Reply with /unmute @user")

    elif data == "search":
        await query.message.reply_text("Use /search query")


# ================= MAIN =================
def main():
    app_bot = ApplicationBuilder().token(TOKEN).build()

    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("mute", mute))
    app_bot.add_handler(CommandHandler("unmute", unmute))
    app_bot.add_handler(CommandHandler("userinfo", userinfo))
    app_bot.add_handler(CommandHandler("search", search))

    app_bot.add_handler(CallbackQueryHandler(button_handler))

    app_bot.run_polling()

# Flask + bot run
if __name__ == "__main__":
    from threading import Thread

    Thread(target=lambda: app.run(host="0.0.0.0", port=8080)).start()
    main()
