import os
import logging
import sqlite3
import requests
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ----------------- SAFE TOKEN LOAD -----------------
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SERPAPI_KEY = os.getenv("SERPAPI_KEY")

if not TOKEN:
    raise Exception("❌ TELEGRAM_BOT_TOKEN missing in environment variables")

# ----------------- LOGGING -----------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ----------------- DB (NO RESET) -----------------
conn = sqlite3.connect("bot.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS banned_domains (
    domain TEXT PRIMARY KEY
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS muted_users (
    user_id INTEGER PRIMARY KEY
)
""")

conn.commit()

# ----------------- FLASK HEALTH -----------------
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running"

@app.route("/health")
def health():
    return {"status": "ok"}

# ----------------- HELPERS -----------------
def save_user(user):
    cursor.execute(
        "INSERT OR REPLACE INTO users VALUES (?, ?, ?)",
        (user.id, user.username, user.first_name),
    )
    conn.commit()


def get_user_from_anywhere(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Resolve user from reply, username, id, mention"""
    msg = update.message

    # 1. reply
    if msg.reply_to_message:
        return msg.reply_to_message.from_user

    # 2. argument
    if context.args:
        arg = context.args[0]

        if arg.startswith("@"):
            return arg[1:]  # username

        if arg.isdigit():
            return int(arg)

    return msg.from_user


# ----------------- INLINE ADMIN PANEL -----------------
def admin_panel():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔇 Mute", callback_data="mute"),
            InlineKeyboardButton("🔊 Unmute", callback_data="unmute"),
        ],
        [
            InlineKeyboardButton("🚫 Block Domain", callback_data="block"),
            InlineKeyboardButton("✅ Allow Domain", callback_data="allow"),
        ],
        [
            InlineKeyboardButton("👤 User Info", callback_data="userinfo"),
            InlineKeyboardButton("🔎 Search User", callback_data="searchuser"),
        ],
        [
            InlineKeyboardButton("📊 Moderation", callback_data="moderate"),
        ]
    ])


# ----------------- COMMANDS -----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Bot Started ✅",
        reply_markup=admin_panel()
    )


# ----------------- MUTE / UNMUTE -----------------
async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user_from_anywhere(update, context)

    try:
        await context.bot.restrict_chat_member(
            update.effective_chat.id,
            user.id,
            permissions={"can_send_messages": False},
        )
        cursor.execute("INSERT OR REPLACE INTO muted_users VALUES (?)", (user.id,))
        conn.commit()

        await update.message.reply_text(f"🔇 Muted {user.id}")

    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user_from_anywhere(update, context)

    try:
        await context.bot.restrict_chat_member(
            update.effective_chat.id,
            user.id,
            permissions={"can_send_messages": True},
        )

        cursor.execute("DELETE FROM muted_users WHERE user_id=?", (user.id,))
        conn.commit()

        await update.message.reply_text(f"🔊 Unmuted {user.id}")

    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


# ----------------- USER INFO (FOR ANY USER) -----------------
async def userinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user_from_anywhere(update, context)

    try:
        member = await context.bot.get_chat_member(
            update.effective_chat.id,
            user.id
        )

        text = f"""
👤 User Info
ID: {user.id}
Name: {user.first_name}
Username: @{user.username}
Status: {member.status}
"""
        await update.message.reply_text(text)

    except Exception as e:
        await update.message.reply_text(f"User info error: {e}")


# ----------------- SERPAPI GOOGLE SEARCH -----------------
async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)

    if not query:
        return await update.message.reply_text("Send query")

    url = "https://serpapi.com/search"
    params = {
        "q": query,
        "api_key": SERPAPI_KEY
    }

    res = requests.get(url, params=params).json()

    try:
        results = res.get("organic_results", [])[:3]
        text = "\n\n".join([r["title"] + "\n" + r.get("link", "") for r in results])
        await update.message.reply_text(text)
    except:
        await update.message.reply_text("No results")


# ----------------- CALLBACK HANDLER -----------------
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    action = q.data

    if action == "mute":
        await q.message.reply_text("Reply or use /mute @user")

    elif action == "unmute":
        await q.message.reply_text("Reply or use /unmute @user")

    elif action == "userinfo":
        await q.message.reply_text("Reply or /userinfo @user")

    elif action == "moderate":
        await q.message.reply_text("Moderation panel ready")


# ----------------- BOT SETUP -----------------
def main():
    app_bot = ApplicationBuilder().token(TOKEN).build()

    # commands (BotFather style menu)
    app_bot.bot.set_my_commands([
        BotCommand("start", "Start bot"),
        BotCommand("mute", "Mute user"),
        BotCommand("unmute", "Unmute user"),
        BotCommand("userinfo", "User info"),
        BotCommand("search", "Google search"),
    ])

    # handlers
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("mute", mute))
    app_bot.add_handler(CommandHandler("unmute", unmute))
    app_bot.add_handler(CommandHandler("userinfo", userinfo))
    app_bot.add_handler(CommandHandler("search", search))

    app_bot.add_handler(CallbackQueryHandler(button_handler))

    # start bot
    app_bot.run_polling(drop_pending_updates=True)


# ----------------- RUN -----------------
if __name__ == "__main__":
    main()
