import os
import logging
from collections import defaultdict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    CallbackQueryHandler,
    filters
)

# =========================
# 🔧 ENV VARIABLES
# =========================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
LOG_CHAT_ID = int(os.getenv("LOG_CHAT_ID", "0"))

# =========================
# 🧠 MEMORY STORAGE
# =========================
user_warnings = defaultdict(int)  # (chat_id, user_id)

# =========================
# ⚙️ LOGGING
# =========================
logging.basicConfig(level=logging.INFO)

# =========================
# 🚀 KEEP ALIVE (FLASK)
# =========================
from flask import Flask
from threading import Thread

app_flask = Flask(__name__)

@app_flask.route("/")
def home():
    return "Bot is alive", 200

@app_flask.route("/health")
def health():
    return "OK", 200

def run():
    app_flask.run(host="0.0.0.0", port=8080)

def keep_alive():
    t = Thread(target=run)
    t.daemon = True
    t.start()

# =========================
# 🔍 SEARCH COMMAND (WORKING BASIC)
# =========================
async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Usage: /search keyword")
        return

    query = " ".join(context.args)
    await update.message.reply_text(f"🔍 Searching for: {query}")

# =========================
# 🛡️ LINK FILTER
# =========================
async def filter_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        return

    text = message.text.lower()
    chat_id = message.chat_id
    user_id = message.from_user.id

    if "http" in text or "t.me" in text:
        try:
            await message.delete()

            key = (chat_id, user_id)
            user_warnings[key] += 1

            await context.bot.send_message(
                chat_id,
                f"⚠️ {message.from_user.first_name} link removed!\nWarnings: {user_warnings[key]}"
            )

        except Exception as e:
            print("Delete error:", e)

# =========================
# 👮 ADMIN PANEL (INLINE)
# =========================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    keyboard = [
        [InlineKeyboardButton("🔍 Search", callback_data="search")],
        [InlineKeyboardButton("📊 Health", callback_data="health")],
        [InlineKeyboardButton("ℹ️ Info", callback_data="info")]
    ]

    await update.message.reply_text(
        "👮 Admin Panel",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# =========================
# 🔘 BUTTON HANDLER
# =========================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "search":
        await query.edit_message_text("Use: /search keyword")

    elif query.data == "health":
        await query.edit_message_text("✅ Bot is running")

    elif query.data == "info":
        await query.edit_message_text("🤖 Anti-link bot active")

# =========================
# ⚠️ ERROR HANDLER
# =========================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print(f"Error: {context.error}")

# =========================
# 🚀 MAIN FUNCTION (FIXED)
# =========================
def main():
    keep_alive()

    app = ApplicationBuilder().token(TOKEN).build()

    # Handlers
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, filter_links))

    app.add_error_handler(error_handler)

    print("Bot started...")

    # ✅ CORRECT METHOD (NO async mistakes)
    app.run_polling(drop_pending_updates=True)

# =========================
# ▶️ START
# =========================
if __name__ == "__main__":
    main()
