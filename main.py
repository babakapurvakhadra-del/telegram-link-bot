import os
import re
import sqlite3
import logging
import requests
import wikipedia

from flask import Flask
from threading import Thread

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters, CallbackQueryHandler
)

# ---------------- CONFIG ----------------
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SERPAPI_KEY = os.getenv("SERPAPI_KEY")

logging.basicConfig(level=logging.INFO)

# ---------------- DATABASE ----------------
conn = sqlite3.connect("bot.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("CREATE TABLE IF NOT EXISTS blocked(domain TEXT)")
cur.execute("CREATE TABLE IF NOT EXISTS allowed(domain TEXT)")
conn.commit()

# ---------------- FLASK ----------------
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot Running"

@app.route("/health")
def health():
    return "OK"

def run_flask():
    app.run(host="0.0.0.0", port=8080)

# ---------------- HELPERS ----------------

async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        member = await context.bot.get_chat_member(
            update.effective_chat.id,
            update.effective_user.id
        )
        return member.status in ["administrator", "creator"]
    except:
        return False


def get_target_user(update: Update):
    if update.message.reply_to_message:
        return update.message.reply_to_message.from_user
    return None


def extract_domain(text):
    urls = re.findall(r"(https?://[^\s]+)", text)
    domains = [u.split("/")[2] for u in urls]
    return domains


# ---------------- DOMAIN CONTROL ----------------

async def allow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    try:
        domain = context.args[0]
        cur.execute("INSERT INTO allowed VALUES(?)", (domain,))
        conn.commit()
        await update.message.reply_text(f"✅ Allowed: {domain}")
    except:
        await update.message.reply_text("Usage: /allow domain.com")


async def block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    try:
        domain = context.args[0]
        cur.execute("INSERT INTO blocked VALUES(?)", (domain,))
        conn.commit()
        await update.message.reply_text(f"🚫 Blocked: {domain}")
    except:
        await update.message.reply_text("Usage: /block domain.com")


async def listdomains(update: Update, context: ContextTypes.DEFAULT_TYPE):
    blocked = cur.execute("SELECT domain FROM blocked").fetchall()
    allowed = cur.execute("SELECT domain FROM allowed").fetchall()

    msg = "📛 Blocked:\n"
    msg += "\n".join([d[0] for d in blocked]) or "None"

    msg += "\n\n✅ Allowed:\n"
    msg += "\n".join([d[0] for d in allowed]) or "None"

    await update.message.reply_text(msg)


# ---------------- AUTO LINK FILTER ----------------

async def filter_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.text:
        return

    domains = extract_domain(update.message.text)
    blocked = [d[0] for d in cur.execute("SELECT domain FROM blocked").fetchall()]
    allowed = [d[0] for d in cur.execute("SELECT domain FROM allowed").fetchall()]

    for d in domains:
        if d in blocked and d not in allowed:
            try:
                await update.message.delete()
                await update.message.reply_text(f"🚫 Blocked link removed: {d}")
            except:
                pass


# ---------------- USER COMMANDS ----------------

async def userinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_target_user(update)

    if not user:
        await update.message.reply_text("Reply to user for info")
        return

    await update.message.reply_text(
        f"👤 User Info\n"
        f"ID: {user.id}\n"
        f"Name: {user.first_name}\n"
        f"Username: @{user.username}"
    )


async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    user = get_target_user(update)
    if not user:
        await update.message.reply_text("Reply to user to mute")
        return

    try:
        await context.bot.restrict_chat_member(
            update.effective_chat.id,
            user.id,
            permissions={}
        )
        await update.message.reply_text("🔇 Muted")
    except Exception as e:
        await update.message.reply_text(str(e))


async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    user = get_target_user(update)
    if not user:
        await update.message.reply_text("Reply to user to unmute")
        return

    try:
        await context.bot.restrict_chat_member(
            update.effective_chat.id,
            user.id,
            permissions={
                "can_send_messages": True
            }
        )
        await update.message.reply_text("🔊 Unmuted")
    except Exception as e:
        await update.message.reply_text(str(e))


# ---------------- SEARCH ----------------

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = " ".join(context.args)
        url = f"https://serpapi.com/search.json?q={query}&api_key={SERPAPI_KEY}"
        res = requests.get(url).json()

        results = res.get("organic_results", [])[:3]
        msg = "\n\n".join([r["title"] + "\n" + r["link"] for r in results])

        await update.message.reply_text(msg or "No results")
    except:
        await update.message.reply_text("Search error")


async def wiki(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = " ".join(context.args)
        summary = wikipedia.summary(query, sentences=2)
        await update.message.reply_text(summary)
    except:
        await update.message.reply_text("No wiki result")


# ---------------- ADMIN PANEL ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔍 Search", callback_data="search")],
        [InlineKeyboardButton("📛 Domains", callback_data="domains")],
        [InlineKeyboardButton("👤 User Info", callback_data="userinfo")],
    ]
    await update.message.reply_text(
        "Admin Panel:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def panel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "domains":
        await query.message.reply_text("Use /allow /block /listdomains")

    elif query.data == "search":
        await query.message.reply_text("Use /search keyword")

    elif query.data == "userinfo":
        await query.message.reply_text("Reply to user then /userinfo")


# ---------------- ERROR HANDLER ----------------

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logging.error(msg="Exception:", exc_info=context.error)


# ---------------- MAIN ----------------

def main():
    Thread(target=run_flask).start()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("allow", allow))
    app.add_handler(CommandHandler("block", block))
    app.add_handler(CommandHandler("listdomains", listdomains))

    app.add_handler(CommandHandler("userinfo", userinfo))
    app.add_handler(CommandHandler("mute", mute))
    app.add_handler(CommandHandler("unmute", unmute))

    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("wiki", wiki))

    app.add_handler(CallbackQueryHandler(panel_handler))

    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), filter_links))

    app.add_error_handler(error_handler)

    app.run_polling()


if __name__ == "__main__":
    main()
