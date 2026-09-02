import os
import re
import sqlite3
import logging
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SERPAPI = os.getenv("SERPAPI_KEY")

if not TOKEN:
    print("❌ TOKEN missing")
    exit()

# ================= DATABASE =================
conn = sqlite3.connect("bot.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("CREATE TABLE IF NOT EXISTS blocked(domain TEXT)")
cursor.execute("CREATE TABLE IF NOT EXISTS allowed(domain TEXT)")
conn.commit()

# ================= FLASK =================
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot Running"

@app.route("/health")
def health():
    return "OK"

# ================= HELPERS =================
async def is_admin(update: Update):
    member = await update.effective_chat.get_member(update.effective_user.id)
    return member.status in ["administrator", "creator"]

def extract_domain(text):
    urls = re.findall(r'(https?://\S+|www\.\S+|\S+\.\S+)', text)
    domains = []
    for url in urls:
        d = url.replace("http://", "").replace("https://", "").split("/")[0]
        d = d.replace("www.", "")
        domains.append(d.lower())
    return domains

def get_blocked():
    cursor.execute("SELECT domain FROM blocked")
    return [i[0] for i in cursor.fetchall()]

def get_allowed():
    cursor.execute("SELECT domain FROM allowed")
    return [i[0] for i in cursor.fetchall()]

# ================= COMMANDS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = [
        [InlineKeyboardButton("📛 Block", callback_data="block")],
        [InlineKeyboardButton("✅ Allow", callback_data="allow")],
        [InlineKeyboardButton("📜 Domains", callback_data="list")],
        [InlineKeyboardButton("🔍 Search", callback_data="search")]
    ]
    await update.message.reply_text(
        "Admin Panel:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# ---------- DOMAIN ----------
async def block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return

    if not context.args:
        await update.message.reply_text("Usage: /block domain.com")
        return

    d = context.args[0].replace("www.", "").lower()
    cursor.execute("INSERT INTO blocked VALUES (?)", (d,))
    conn.commit()

    await update.message.reply_text(f"🚫 Blocked: {d}")

async def allow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return

    if not context.args:
        await update.message.reply_text("Usage: /allow domain.com")
        return

    d = context.args[0].replace("www.", "").lower()
    cursor.execute("INSERT INTO allowed VALUES (?)", (d,))
    conn.commit()

    await update.message.reply_text(f"✅ Allowed: {d}")

async def listdomains(update: Update, context: ContextTypes.DEFAULT_TYPE):
    b = get_blocked()
    a = get_allowed()

    await update.message.reply_text(
        f"📛 Blocked:\n{b}\n\n✅ Allowed:\n{a}"
    )

# ---------- USER ACTION ----------
async def get_target(update: Update):
    if update.message.reply_to_message:
        return update.message.reply_to_message.from_user
    return None

async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return

    user = await get_target(update)
    if not user:
        await update.message.reply_text("Reply to user")
        return

    await update.effective_chat.restrict_member(
        user.id,
        permissions={}
    )
    await update.message.reply_text(f"🔇 Muted {user.first_name}")

async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return

    user = await get_target(update)
    if not user:
        await update.message.reply_text("Reply to user")
        return

    await update.effective_chat.restrict_member(
        user.id,
        permissions={"can_send_messages": True}
    )
    await update.message.reply_text(f"🔊 Unmuted {user.first_name}")

async def userinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await get_target(update)

    if not user:
        await update.message.reply_text("Reply to user for info")
        return

    await update.message.reply_text(
        f"👤 User Info\nID: {user.id}\nName: {user.first_name}\nUsername: @{user.username}"
    )

# ---------- SEARCH ----------
import requests

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Usage: /search query")

    q = " ".join(context.args)

    url = f"https://serpapi.com/search.json?q={q}&api_key={SERPAPI}"
    res = requests.get(url).json()

    try:
        r = res["organic_results"][0]
        msg = f"{r['title']}\n{r['link']}"
    except:
        msg = "No result"

    await update.message.reply_text(msg)

# ================= LINK FILTER =================
async def filter_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if not text: return

    domains = extract_domain(text)

    blocked = get_blocked()
    allowed = get_allowed()

    for d in domains:
        if d in allowed:
            return

        if d in blocked:
            try:
                await update.message.delete()
                await update.message.reply_text(f"❌ Blocked link: {d}")
            except:
                pass
            return

# ================= MAIN =================
def main():
    app_bot = ApplicationBuilder().token(TOKEN).build()

    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("block", block))
    app_bot.add_handler(CommandHandler("allow", allow))
    app_bot.add_handler(CommandHandler("listdomains", listdomains))

    app_bot.add_handler(CommandHandler("mute", mute))
    app_bot.add_handler(CommandHandler("unmute", unmute))
    app_bot.add_handler(CommandHandler("userinfo", userinfo))

    app_bot.add_handler(CommandHandler("search", search))

    app_bot.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), filter_links))

    app_bot.run_polling()

if __name__ == "__main__":
    main()
