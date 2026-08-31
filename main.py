import os
import logging
import sqlite3
import requests
import wikipedia
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

# ================= CONFIG =================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SERPAPI_KEY = os.getenv("SERPAPI_KEY")

logging.basicConfig(level=logging.INFO)

# ================= DB =================
conn = sqlite3.connect("bot.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("CREATE TABLE IF NOT EXISTS domains (domain TEXT, type TEXT)")
cursor.execute("CREATE TABLE IF NOT EXISTS mutes (user_id INTEGER)")
conn.commit()

# ================= FLASK =================
app_flask = Flask(__name__)

@app_flask.route("/")
def home():
    return "Bot running"

@app_flask.route("/health")
def health():
    return "OK"

# ================= HELPERS =================
def is_admin(update: Update):
    try:
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        admins = update.get_bot().get_chat_administrators(chat_id)
        return any(admin.user.id == user_id for admin in admins)
    except:
        return False

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔍 Search", callback_data="search")],
        [InlineKeyboardButton("👤 User Info", callback_data="userinfo")],
        [InlineKeyboardButton("🔇 Mute", callback_data="mute")],
        [InlineKeyboardButton("🔊 Unmute", callback_data="unmute")],
        [InlineKeyboardButton("🌐 Domains", callback_data="domains")]
    ]
    await update.message.reply_text(
        "⚙ Admin Panel",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ================= CALLBACK =================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "search":
        await query.message.reply_text("Use:\n/search keyword")

    elif data == "userinfo":
        await query.message.reply_text("Reply to user:\n/userinfo")

    elif data == "mute":
        await query.message.reply_text("Reply to user:\n/mute")

    elif data == "unmute":
        await query.message.reply_text("Reply to user:\n/unmute")

    elif data == "domains":
        await query.message.reply_text(
            "/allow domain.com\n/block domain.com\n/listdomains"
        )

# ================= SEARCH =================
async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = " ".join(context.args)
        if not query:
            await update.message.reply_text("Give keyword")
            return

        url = "https://serpapi.com/search.json"
        params = {
            "q": query,
            "api_key": SERPAPI_KEY
        }

        res = requests.get(url, params=params).json()
        results = res.get("organic_results", [])[:3]

        text = "🔎 Results:\n"
        for r in results:
            text += f"\n{r['title']}\n{r['link']}\n"

        await update.message.reply_text(text)

    except Exception as e:
        await update.message.reply_text("Search error")

# ================= WIKI =================
async def wiki(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = " ".join(context.args)
        summary = wikipedia.summary(query, sentences=2)
        await update.message.reply_text(summary)
    except:
        await update.message.reply_text("Wiki not found")

# ================= USER INFO =================
async def userinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to user")
        return

    user = update.message.reply_to_message.from_user
    await update.message.reply_text(
        f"👤 {user.full_name}\nID: {user.id}\nUsername: @{user.username}"
    )

# ================= MUTE =================
async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to user")
        return

    user_id = update.message.reply_to_message.from_user.id
    cursor.execute("INSERT INTO mutes VALUES (?)", (user_id,))
    conn.commit()

    await update.message.reply_text("Muted")

async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to user")
        return

    user_id = update.message.reply_to_message.from_user.id
    cursor.execute("DELETE FROM mutes WHERE user_id=?", (user_id,))
    conn.commit()

    await update.message.reply_text("Unmuted")

# ================= DOMAIN =================
async def allow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    domain = context.args[0]
    cursor.execute("INSERT INTO domains VALUES (?,?)", (domain, "allow"))
    conn.commit()
    await update.message.reply_text("Allowed")

async def block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    domain = context.args[0]
    cursor.execute("INSERT INTO domains VALUES (?,?)", (domain, "block"))
    conn.commit()
    await update.message.reply_text("Blocked")

async def listdomains(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cursor.execute("SELECT * FROM domains")
    rows = cursor.fetchall()

    text = "Domains:\n"
    for r in rows:
        text += f"{r[0]} ({r[1]})\n"

    await update.message.reply_text(text)

# ================= FILTER =================
async def message_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.message.from_user.id

        cursor.execute("SELECT user_id FROM mutes WHERE user_id=?", (user_id,))
        if cursor.fetchone():
            await update.message.delete()
            return

        text = update.message.text or ""

        cursor.execute("SELECT domain FROM domains WHERE type='block'")
        blocked = [d[0] for d in cursor.fetchall()]

        for domain in blocked:
            if domain in text:
                await update.message.delete()
                return

    except:
        pass

# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("wiki", wiki))
    app.add_handler(CommandHandler("userinfo", userinfo))
    app.add_handler(CommandHandler("mute", mute))
    app.add_handler(CommandHandler("unmute", unmute))
    app.add_handler(CommandHandler("allow", allow))
    app.add_handler(CommandHandler("block", block))
    app.add_handler(CommandHandler("listdomains", listdomains))

    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_filter))

    app.run_polling()

if __name__ == "__main__":
    main()
