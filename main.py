import os
import re
import sqlite3
import logging
import requests
import wikipedia
from flask import Flask
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
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
SERP_API = os.getenv("SERPAPI_KEY")

if not TOKEN:
    print("❌ TOKEN missing")
    exit()

logging.basicConfig(level=logging.INFO)

# ================= DB =================
conn = sqlite3.connect("bot.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("CREATE TABLE IF NOT EXISTS blocked(domain TEXT)")
cur.execute("CREATE TABLE IF NOT EXISTS allowed(domain TEXT)")
cur.execute("CREATE TABLE IF NOT EXISTS users(user_id INTEGER, username TEXT, name TEXT)")
conn.commit()

# ================= FLASK =================
app_flask = Flask(__name__)

@app_flask.route("/")
def home():
    return "Bot Running"

@app_flask.route("/health")
def health():
    return "OK"

# ================= HELPERS =================
async def is_admin(update: Update):
    member = await update.effective_chat.get_member(update.effective_user.id)
    return member.status in ["administrator", "creator"]

def extract_domain(text):
    urls = re.findall(r"(https?://[^\s]+|www\.[^\s]+)", text)
    domains = []
    for u in urls:
        d = re.sub(r"https?://", "", u)
        d = d.split("/")[0]
        domains.append(d.lower())
    return domains

def save_user(user):
    cur.execute("INSERT INTO users VALUES (?, ?, ?)", (
        user.id,
        user.username or "",
        user.first_name or ""
    ))
    conn.commit()

def find_user(query):
    if query.startswith("@"):
        cur.execute("SELECT * FROM users WHERE username=?", (query[1:],))
    else:
        cur.execute("SELECT * FROM users WHERE name LIKE ?", (f"%{query}%",))
    return cur.fetchone()

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔍 Search", callback_data="search")],
        [InlineKeyboardButton("👤 User Info", callback_data="userinfo")],
        [InlineKeyboardButton("🔇 Mute", callback_data="mute"),
         InlineKeyboardButton("🔊 Unmute", callback_data="unmute")],
        [InlineKeyboardButton("🚫 Block Domain", callback_data="block"),
         InlineKeyboardButton("✅ Allow Domain", callback_data="allow")],
    ]
    await update.message.reply_text(
        "Admin Panel:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ================= DOMAIN =================
async def block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return
    domain = context.args[0]
    cur.execute("INSERT INTO blocked VALUES (?)", (domain,))
    conn.commit()
    await update.message.reply_text(f"🚫 Blocked: {domain}")

async def allow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return
    domain = context.args[0]
    cur.execute("INSERT INTO allowed VALUES (?)", (domain,))
    conn.commit()
    await update.message.reply_text(f"✅ Allowed: {domain}")

async def listdomains(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cur.execute("SELECT domain FROM blocked")
    b = [i[0] for i in cur.fetchall()]
    cur.execute("SELECT domain FROM allowed")
    a = [i[0] for i in cur.fetchall()]
    await update.message.reply_text(f"Blocked:\n{b}\nAllowed:\n{a}")

# ================= FILTER =================
async def filter_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    domains = extract_domain(update.message.text)
    if not domains:
        return

    cur.execute("SELECT domain FROM blocked")
    blocked = [i[0] for i in cur.fetchall()]

    cur.execute("SELECT domain FROM allowed")
    allowed = [i[0] for i in cur.fetchall()]

    for d in domains:
        if d in blocked and d not in allowed:
            try:
                await update.message.delete()
                await update.message.reply_text(f"⚠️ Blocked link: {d}")
            except:
                pass

# ================= USER =================
async def userinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.reply_to_message:
        user = update.message.reply_to_message.from_user
    elif context.args:
        result = find_user(context.args[0])
        if not result:
            await update.message.reply_text("User not found")
            return
        user_id, username, name = result
        await update.message.reply_text(
            f"👤 {name}\nID: {user_id}\nUsername: @{username}"
        )
        return
    else:
        await update.message.reply_text("Reply to user or give name")
        return

    await update.message.reply_text(
        f"👤 {user.first_name}\nID: {user.id}\nUsername: @{user.username}"
    )

async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to user")
        return
    user = update.message.reply_to_message.from_user
    await update.effective_chat.restrict_member(user.id, permissions={})
    await update.message.reply_text("Muted")

async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to user")
        return
    user = update.message.reply_to_message.from_user
    await update.effective_chat.restrict_member(user.id, permissions=None)
    await update.message.reply_text("Unmuted")

# ================= SEARCH =================
async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    url = f"https://serpapi.com/search.json?q={query}&api_key={SERP_API}"
    res = requests.get(url).json()

    try:
        r = res["organic_results"][0]
        await update.message.reply_text(f"{r['title']}\n{r['link']}")
    except:
        await update.message.reply_text("No result")

# ================= MESSAGE SAVE =================
async def save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        save_user(update.message.from_user)

# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("block", block))
    app.add_handler(CommandHandler("allow", allow))
    app.add_handler(CommandHandler("listdomains", listdomains))
    app.add_handler(CommandHandler("userinfo", userinfo))
    app.add_handler(CommandHandler("mute", mute))
    app.add_handler(CommandHandler("unmute", unmute))
    app.add_handler(CommandHandler("search", search))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, filter_links))
    app.add_handler(MessageHandler(filters.ALL, save))

    print("✅ Bot Running")
    app.run_polling()

if __name__ == "__main__":
    main()
