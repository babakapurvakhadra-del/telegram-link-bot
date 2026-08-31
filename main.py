import os
import logging
import sqlite3
import requests
from flask import Flask
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ================= LOGGING =================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ================= ENV =================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SERPAPI_KEY = os.getenv("SERPAPI_KEY")

if not TOKEN:
    print("❌ TOKEN missing")
    exit(1)

# ================= DB =================
conn = sqlite3.connect("bot.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    name TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS muted (
    user_id INTEGER PRIMARY KEY
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS domains (
    domain TEXT PRIMARY KEY,
    status TEXT
)
""")

conn.commit()

# ================= FLASK =================
app_web = Flask(__name__)

@app_web.route("/")
def home():
    return "Bot Running"

@app_web.route("/health")
def health():
    return {"status": "ok"}

# ================= HELPERS =================
def is_admin(user_id: int, chat_member) -> bool:
    return chat_member.status in ["administrator", "creator"]

async def get_chat_member(update, context, user_id):
    try:
        return await context.bot.get_chat_member(update.effective_chat.id, user_id)
    except:
        return None

def extract_user_id(text: str):
    if not text:
        return None

    text = text.strip()

    if text.startswith("@"):
        return text[1:]

    if "tg://user?id=" in text:
        return text.split("tg://user?id=")[-1]

    if text.isdigit():
        return int(text)

    return text

# ================= START PANEL =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("👤 User Info", callback_data="userinfo")],
        [InlineKeyboardButton("🔇 Mute", callback_data="mute")],
        [InlineKeyboardButton("🔊 Unmute", callback_data="unmute")],
        [InlineKeyboardButton("🌐 Domains", callback_data="domains")],
        [InlineKeyboardButton("🔍 Search", callback_data="search")],
    ]
    await update.message.reply_text(
        "🤖 Safe Group Protector Panel",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

# ================= USER INFO (FIXED) =================
async def userinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = " ".join(context.args) if context.args else None

        if update.message.reply_to_message:
            user = update.message.reply_to_message.from_user
        else:
            uid = extract_user_id(query)
            if not uid:
                await update.message.reply_text("Reply or give username/id")
                return

            user = await context.bot.get_chat(uid)

        msg = f"""
👤 User Info
ID: {user.id}
Name: {user.full_name}
Username: @{user.username if user.username else 'N/A'}
"""
        await update.message.reply_text(msg)

    except Exception as e:
        logger.error(e)
        await update.message.reply_text("User not found")

# ================= MUTE =================
async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not context.args and not update.message.reply_to_message:
            await update.message.reply_text("Usage: /mute @user or reply")
            return

        user = update.message.reply_to_message.from_user if update.message.reply_to_message else await context.bot.get_chat(extract_user_id(" ".join(context.args)))

        cur.execute("INSERT OR IGNORE INTO muted VALUES (?)", (user.id,))
        conn.commit()

        await update.message.reply_text(f"🔇 Muted {user.full_name}")

    except Exception as e:
        logger.error(e)

# ================= UNMUTE =================
async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.message.reply_to_message.from_user if update.message.reply_to_message else await context.bot.get_chat(extract_user_id(" ".join(context.args)))

        cur.execute("DELETE FROM muted WHERE user_id=?", (user.id,))
        conn.commit()

        await update.message.reply_text(f"🔊 Unmuted {user.full_name}")

    except Exception as e:
        logger.error(e)

# ================= DOMAIN CONTROL =================
async def allow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    domain = " ".join(context.args)
    cur.execute("INSERT OR REPLACE INTO domains VALUES (?,?)", (domain, "allowed"))
    conn.commit()
    await update.message.reply_text(f"✅ Allowed {domain}")

async def block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    domain = " ".join(context.args)
    cur.execute("INSERT OR REPLACE INTO domains VALUES (?,?)", (domain, "blocked"))
    conn.commit()
    await update.message.reply_text(f"⛔ Blocked {domain}")

async def listdomains(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = cur.execute("SELECT * FROM domains").fetchall()
    text = "\n".join([f"{d[0]} - {d[1]}" for d in rows]) or "No domains"
    await update.message.reply_text(text)

# ================= SEARCH (SERPAPI) =================
async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = " ".join(context.args)
    if not q:
        await update.message.reply_text("Usage: /search query")
        return

    if not SERPAPI_KEY:
        await update.message.reply_text("SerpAPI key missing")
        return

    url = f"https://serpapi.com/search.json?q={q}&api_key={SERPAPI_KEY}"
    r = requests.get(url).json()

    results = r.get("organic_results", [])[:3]
    msg = "\n\n".join([f"{x.get('title')}\n{x.get('link')}" for x in results])

    await update.message.reply_text(msg or "No results")

# ================= WIKIPEDIA =================
async def wiki(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = " ".join(context.args)
    if not q:
        await update.message.reply_text("Usage: /wiki query")
        return

    r = requests.get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{q}")
    data = r.json()

    await update.message.reply_text(data.get("extract", "Not found"))

# ================= CALLBACK BUTTONS =================
async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "userinfo":
        await query.message.reply_text("Use /userinfo @user")
    elif data == "mute":
        await query.message.reply_text("Use /mute @user")
    elif data == "unmute":
        await query.message.reply_text("Use /unmute @user")
    elif data == "domains":
        await query.message.reply_text("Use /allow /block /listdomains")
    elif data == "search":
        await query.message.reply_text("Use /search query")

# ================= ERROR SAFE =================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Error: %s", context.error)

# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("userinfo", userinfo))
    app.add_handler(CommandHandler("mute", mute))
    app.add_handler(CommandHandler("unmute", unmute))
    app.add_handler(CommandHandler("allow", allow))
    app.add_handler(CommandHandler("block", block))
    app.add_handler(CommandHandler("listdomains", listdomains))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("wiki", wiki))
    app.add_handler(CallbackQueryHandler(buttons))

    app.add_error_handler(error_handler)

    print("Bot running...")
    app.run_polling()

# ================= RUN =================
if __name__ == "__main__":
    from threading import Thread

    Thread(target=lambda: app_web.run(host="0.0.0.0", port=8080)).start()
    main()
