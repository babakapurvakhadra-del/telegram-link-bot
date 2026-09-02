import os
import re
import sqlite3
import logging
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SERPAPI_KEY = os.getenv("SERPAPI_KEY")

if not TOKEN:
    print("❌ TOKEN missing")
    exit()

logging.basicConfig(level=logging.INFO)

# ================= DATABASE =================
conn = sqlite3.connect("bot.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("CREATE TABLE IF NOT EXISTS allowed(domain TEXT)")
cursor.execute("CREATE TABLE IF NOT EXISTS blocked(domain TEXT)")
cursor.execute("CREATE TABLE IF NOT EXISTS users(user_id INTEGER, username TEXT)")
conn.commit()

# ================= FLASK =================
app_flask = Flask(__name__)

@app_flask.route("/")
def home():
    return "Bot Running"

@app_flask.route("/health")
def health():
    return "OK"

# ================= UTIL =================
def extract_user(update: Update):
    msg = update.message

    # Reply method (BEST)
    if msg.reply_to_message:
        return msg.reply_to_message.from_user

    args = msg.text.split()

    if len(args) > 1:
        target = args[1]

        # @username
        if target.startswith("@"):
            return target

        # user id
        if target.isdigit():
            return int(target)

    return None

def is_admin(update: Update):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    member = update.get_bot().get_chat_member(chat_id, user_id)
    return member.status in ["administrator", "creator"]

# ================= LINK FILTER =================
def extract_domains(text):
    return re.findall(r"(?:https?://)?(?:www\.)?([a-zA-Z0-9\-]+\.[a-zA-Z]{2,})", text)

async def link_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        msg = update.message
        if not msg or not msg.text:
            return

        domains = extract_domains(msg.text)

        for domain in domains:
            cursor.execute("SELECT 1 FROM allowed WHERE domain=?", (domain,))
            if cursor.fetchone():
                return

            cursor.execute("SELECT 1 FROM blocked WHERE domain=?", (domain,))
            if cursor.fetchone():
                await msg.delete()
                return

            # default suspicious keywords
            if any(x in msg.text.lower() for x in ["free", "earn", "crypto", "scam"]):
                await msg.delete()
                return
    except:
        pass

# ================= COMMANDS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📊 Domains", callback_data="domains")],
        [InlineKeyboardButton("👤 User Panel", callback_data="userpanel")],
        [InlineKeyboardButton("🔍 Search", callback_data="search")]
    ]
    await update.message.reply_text("Admin Panel:", reply_markup=InlineKeyboardMarkup(keyboard))

# ---------- DOMAIN ----------
async def allow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return

    try:
        domain = update.message.text.split()[1]
        cursor.execute("INSERT INTO allowed VALUES(?)", (domain,))
        conn.commit()
        await update.message.reply_text(f"✅ Allowed: {domain}")
    except:
        await update.message.reply_text("Usage: /allow domain.com")

async def block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return

    try:
        domain = update.message.text.split()[1]
        cursor.execute("INSERT INTO blocked VALUES(?)", (domain,))
        conn.commit()
        await update.message.reply_text(f"🚫 Blocked: {domain}")
    except:
        await update.message.reply_text("Usage: /block domain.com")

async def listdomains(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cursor.execute("SELECT domain FROM allowed")
    allowed = [x[0] for x in cursor.fetchall()]

    cursor.execute("SELECT domain FROM blocked")
    blocked = [x[0] for x in cursor.fetchall()]

    await update.message.reply_text(
        f"✅ Allowed:\n{allowed}\n\n🚫 Blocked:\n{blocked}"
    )

# ---------- USER ----------
async def userinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = extract_user(update)

    if isinstance(target, str):
        await update.message.reply_text("❌ Username lookup limited. Use reply.")
        return

    try:
        if isinstance(target, int):
            member = await context.bot.get_chat_member(update.effective_chat.id, target)
        else:
            member = await context.bot.get_chat_member(update.effective_chat.id, target.id)

        user = member.user

        await update.message.reply_text(
            f"👤 User Info\nID: {user.id}\nName: {user.first_name}\nUsername: @{user.username}"
        )
    except:
        await update.message.reply_text("❌ Cannot fetch user")

async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = extract_user(update)

    try:
        user_id = target.id if not isinstance(target, int) else target

        await context.bot.restrict_chat_member(
            chat_id=update.effective_chat.id,
            user_id=user_id,
            permissions={}
        )
        await update.message.reply_text("🔇 Muted")
    except:
        await update.message.reply_text("❌ Failed")

async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = extract_user(update)

    try:
        user_id = target.id if not isinstance(target, int) else target

        await context.bot.restrict_chat_member(
            chat_id=update.effective_chat.id,
            user_id=user_id,
            permissions={"can_send_messages": True}
        )
        await update.message.reply_text("🔊 Unmuted")
    except:
        await update.message.reply_text("❌ Failed")

# ---------- SEARCH ----------
import requests
import wikipedia

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = " ".join(update.message.text.split()[1:])

        # Google search
        url = f"https://serpapi.com/search.json?q={query}&api_key={SERPAPI_KEY}"
        res = requests.get(url).json()

        result = res.get("organic_results", [{}])[0].get("link", "No result")

        # Wikipedia
        try:
            summary = wikipedia.summary(query, sentences=2)
        except:
            summary = "No wiki result"

        await update.message.reply_text(f"{summary}\n\n🔗 {result}")

    except:
        await update.message.reply_text("❌ Search failed")

# ---------- FIND DELETE ----------
async def finddel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyword = update.message.text.split()[1]

    # NOTE: Telegram does NOT allow history scanning
    await update.message.reply_text("⚠️ Telegram API doesn't allow scanning old messages.\nOnly new messages can be filtered.")

# ---------- CALLBACK ----------
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "domains":
        await query.message.reply_text("Use /allow /block /listdomains")

    elif query.data == "userpanel":
        await query.message.reply_text("Reply user then use /mute /unmute /userinfo")

    elif query.data == "search":
        await query.message.reply_text("Use /search query")

# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("allow", allow))
    app.add_handler(CommandHandler("block", block))
    app.add_handler(CommandHandler("listdomains", listdomains))
    app.add_handler(CommandHandler("userinfo", userinfo))
    app.add_handler(CommandHandler("mute", mute))
    app.add_handler(CommandHandler("unmute", unmute))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("finddel", finddel))

    app.add_handler(CallbackQueryHandler(button))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, link_filter))

    app.run_polling()

if __name__ == "__main__":
    main()
