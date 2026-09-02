import os
import re
import sqlite3
import logging
from flask import Flask
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# ================= DATABASE =================
conn = sqlite3.connect("bot.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("CREATE TABLE IF NOT EXISTS blocked(domain TEXT)")
cursor.execute("CREATE TABLE IF NOT EXISTS allowed(domain TEXT)")
conn.commit()

# ================= FLASK =================
app_flask = Flask(__name__)

@app_flask.route("/")
def home():
    return "Bot running"

@app_flask.route("/health")
def health():
    return "OK"

# ================= LOGGING =================
logging.basicConfig(level=logging.INFO)

# ================= ADMIN CHECK =================
async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    member = await context.bot.get_chat_member(
        update.effective_chat.id,
        update.effective_user.id
    )
    return member.status in ["administrator", "creator"]

# ================= DOMAIN FUNCTIONS =================
def get_blocked():
    return [x[0] for x in cursor.execute("SELECT domain FROM blocked").fetchall()]

def get_allowed():
    return [x[0] for x in cursor.execute("SELECT domain FROM allowed").fetchall()]

# ================= COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Admin Panel Ready")

async def block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    if not context.args:
        await update.message.reply_text("Usage: /block domain.com")
        return

    domain = context.args[0].replace("www.", "")
    cursor.execute("INSERT INTO blocked VALUES (?)", (domain,))
    conn.commit()

    await update.message.reply_text(f"🚫 Blocked: {domain}")

async def allow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    if not context.args:
        return

    domain = context.args[0].replace("www.", "")
    cursor.execute("INSERT INTO allowed VALUES (?)", (domain,))
    conn.commit()

    await update.message.reply_text(f"✅ Allowed: {domain}")

async def listdomains(update: Update, context: ContextTypes.DEFAULT_TYPE):
    blocked = get_blocked()
    allowed = get_allowed()

    await update.message.reply_text(
        f"🚫 Blocked:\n{blocked}\n\n✅ Allowed:\n{allowed}"
    )

# ================= LINK FILTER =================
async def filter_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if not text:
        return

    urls = re.findall(r"(https?://\S+|www\.\S+)", text)

    if not urls:
        return

    blocked = get_blocked()
    allowed = get_allowed()

    for url in urls:
        domain = re.sub(r"https?://", "", url).split("/")[0].replace("www.", "")

        if domain in blocked and domain not in allowed:
            try:
                await update.message.delete()
            except:
                pass
            return

# ================= USER COMMANDS =================
async def userinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to user for info")
        return

    user = update.message.reply_to_message.from_user

    await update.message.reply_text(
        f"👤 User Info\nID: {user.id}\nName: {user.full_name}\nUsername: @{user.username}"
    )

async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to user")
        return

    user = update.message.reply_to_message.from_user

    await context.bot.restrict_chat_member(
        update.effective_chat.id,
        user.id,
        permissions={}
    )

    await update.message.reply_text("🔇 Muted")

async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to user")
        return

    user = update.message.reply_to_message.from_user

    await context.bot.restrict_chat_member(
        update.effective_chat.id,
        user.id,
        permissions={
            "can_send_messages": True,
            "can_send_media_messages": True
        }
    )

    await update.message.reply_text("🔊 Unmuted")

# ================= FIND & DELETE =================
async def finddel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    await update.message.reply_text("⚠️ Telegram does not allow scanning old messages automatically.\nOnly new messages can be filtered.")

# ================= ERROR HANDLER =================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print(f"Error: {context.error}")

# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_error_handler(error_handler)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("block", block))
    app.add_handler(CommandHandler("allow", allow))
    app.add_handler(CommandHandler("listdomains", listdomains))
    app.add_handler(CommandHandler("userinfo", userinfo))
    app.add_handler(CommandHandler("mute", mute))
    app.add_handler(CommandHandler("unmute", unmute))
    app.add_handler(CommandHandler("finddel", finddel))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, filter_links))

    app.run_polling()

if __name__ == "__main__":
    main()
