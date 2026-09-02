import os
import re
import sqlite3
import logging
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# ================= CONFIG =================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# ================= LOGGING =================
logging.basicConfig(level=logging.INFO)

# ================= DB =================
conn = sqlite3.connect("bot.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("CREATE TABLE IF NOT EXISTS blocked(domain TEXT)")
cur.execute("CREATE TABLE IF NOT EXISTS allowed(domain TEXT)")
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
async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        member = await context.bot.get_chat_member(
            update.effective_chat.id,
            update.effective_user.id
        )
        return member.status in ["administrator", "creator"]
    except:
        return False

def extract_domain(text):
    urls = re.findall(r'(https?://\S+|www\.\S+|\b[\w.-]+\.[a-z]{2,}\b)', text)
    return urls

def is_blocked(domain):
    cur.execute("SELECT 1 FROM blocked WHERE domain=?", (domain,))
    return cur.fetchone() is not None

def is_allowed(domain):
    cur.execute("SELECT 1 FROM allowed WHERE domain=?", (domain,))
    return cur.fetchone() is not None

# ================= COMMANDS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📛 Block", callback_data="block")],
        [InlineKeyboardButton("✅ Allow", callback_data="allow")],
        [InlineKeyboardButton("📋 Domains", callback_data="list")],
    ]
    await update.message.reply_text("Admin Panel Ready", reply_markup=InlineKeyboardMarkup(keyboard))

async def block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    if not context.args:
        await update.message.reply_text("Usage: /block domain")
        return

    domain = context.args[0].replace("www.", "")
    cur.execute("INSERT INTO blocked VALUES (?)", (domain,))
    conn.commit()
    await update.message.reply_text(f"🚫 Blocked: {domain}")

async def allow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    if not context.args:
        await update.message.reply_text("Usage: /allow domain")
        return

    domain = context.args[0].replace("www.", "")
    cur.execute("INSERT INTO allowed VALUES (?)", (domain,))
    conn.commit()
    await update.message.reply_text(f"✅ Allowed: {domain}")

async def listdomains(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cur.execute("SELECT domain FROM blocked")
    blocked = [x[0] for x in cur.fetchall()]

    cur.execute("SELECT domain FROM allowed")
    allowed = [x[0] for x in cur.fetchall()]

    await update.message.reply_text(
        f"🚫 Blocked:\n{blocked}\n\n✅ Allowed:\n{allowed}"
    )

# ================= USER ACTIONS =================

async def userinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = None

    # reply method
    if update.message.reply_to_message:
        user = update.message.reply_to_message.from_user

    # username method
    elif context.args:
        username = context.args[0].replace("@", "")
        try:
            user = await context.bot.get_chat(username)
        except:
            pass

    if not user:
        await update.message.reply_text("Reply to user or give username")
        return

    text = f"""
👤 User Info
ID: {user.id}
Name: {user.full_name}
Username: @{user.username if user.username else "N/A"}
"""
    await context.bot.send_message(chat_id=ADMIN_ID, text=text)
    await update.message.reply_text("Sent to admin log")

async def getid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.reply_to_message:
        user = update.message.reply_to_message.from_user
        await update.message.reply_text(f"User ID: {user.id}")

async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to user")
        return

    user_id = update.message.reply_to_message.from_user.id

    await context.bot.restrict_chat_member(
        update.effective_chat.id,
        user_id,
        permissions={}
    )

    await update.message.reply_text("🔇 Muted")

async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to user")
        return

    user_id = update.message.reply_to_message.from_user.id

    await context.bot.restrict_chat_member(
        update.effective_chat.id,
        user_id,
        permissions={"can_send_messages": True}
    )

    await update.message.reply_text("🔊 Unmuted")

# ================= AUTO LINK BLOCK =================

async def filter_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if not text:
        return

    domains = extract_domain(text)

    for d in domains:
        d = d.replace("http://", "").replace("https://", "").replace("www.", "").split("/")[0]

        if is_allowed(d):
            return

        if is_blocked(d):
            try:
                await update.message.delete()
                await update.message.chat.send_message("🚫 Link blocked")
            except:
                pass

# ================= FIND & DELETE =================

async def finddel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    await update.message.reply_text("⚠️ Telegram does not allow scanning old messages.\nOnly new messages can be deleted.")

# ================= CALLBACK =================

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "list":
        cur.execute("SELECT domain FROM blocked")
        blocked = [x[0] for x in cur.fetchall()]
        await query.edit_message_text(f"Blocked:\n{blocked}")

# ================= MAIN =================

def main():
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("block", block))
    application.add_handler(CommandHandler("allow", allow))
    application.add_handler(CommandHandler("listdomains", listdomains))
    application.add_handler(CommandHandler("userinfo", userinfo))
    application.add_handler(CommandHandler("getid", getid))
    application.add_handler(CommandHandler("mute", mute))
    application.add_handler(CommandHandler("unmute", unmute))
    application.add_handler(CommandHandler("finddel", finddel))

    application.add_handler(CallbackQueryHandler(button))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, filter_links))

    application.run_polling()

if __name__ == "__main__":
    main()
