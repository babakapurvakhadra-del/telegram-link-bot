import os
import json
import logging
import requests
import wikipedia

from collections import defaultdict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ================== CONFIG ==================
TOKEN = os.getenv("BOT_TOKEN")
SERPAPI_KEY = os.getenv("SERPAPI_KEY")

logging.basicConfig(level=logging.INFO)

# ================== DATABASE ==================
DB_FILE = "data.json"

def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f:
            return json.load(f)
    return {"warnings": {}, "blocked_domains": []}

def save_db():
    with open(DB_FILE, "w") as f:
        json.dump(db, f)

db = load_db()

def get_warning(chat_id, user_id):
    return db["warnings"].get(f"{chat_id}_{user_id}", 0)

def add_warning(chat_id, user_id):
    key = f"{chat_id}_{user_id}"
    db["warnings"][key] = db["warnings"].get(key, 0) + 1
    save_db()
    return db["warnings"][key]

# ================== INLINE PANEL ==================
def main_menu():
    keyboard = [
        [
            InlineKeyboardButton("🔍 Search", callback_data="search"),
            InlineKeyboardButton("👤 User Info", callback_data="userinfo"),
        ],
        [
            InlineKeyboardButton("🔇 Mute", callback_data="mute"),
            InlineKeyboardButton("🔊 Unmute", callback_data="unmute"),
        ],
        [
            InlineKeyboardButton("🌐 Domains", callback_data="domains"),
            InlineKeyboardButton("❤️ Health", callback_data="health"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)

# ================== COMMANDS ==================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Bot Ready\nUse buttons below:",
        reply_markup=main_menu()
    )

async def health(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Bot is running perfectly")

# ================== SEARCH ==================
async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /search keyword")
        return

    query = " ".join(context.args)

    # Google search (SerpAPI)
    try:
        url = "https://serpapi.com/search"
        params = {
            "q": query,
            "api_key": SERPAPI_KEY,
            "engine": "google"
        }
        res = requests.get(url, params=params).json()

        if "organic_results" in res:
            result = res["organic_results"][0]
            await update.message.reply_text(
                f"🔍 {result['title']}\n{result['link']}"
            )
            return
    except:
        pass

    # Wikipedia fallback
    try:
        summary = wikipedia.summary(query, sentences=2)
        await update.message.reply_text(summary)
    except:
        await update.message.reply_text("❌ No results found")

# ================== USER INFO ==================
async def userinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a user")
        return

    user = update.message.reply_to_message.from_user
    await update.message.reply_text(
        f"👤 Name: {user.first_name}\nID: {user.id}"
    )

# ================== MUTE ==================
async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to user to mute")
        return

    user_id = update.message.reply_to_message.from_user.id
    await context.bot.restrict_chat_member(
        update.effective_chat.id,
        user_id,
        permissions={}
    )
    await update.message.reply_text("🔇 User muted")

async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to user to unmute")
        return

    user_id = update.message.reply_to_message.from_user.id
    await context.bot.restrict_chat_member(
        update.effective_chat.id,
        user_id,
        permissions={
            "can_send_messages": True
        }
    )
    await update.message.reply_text("🔊 User unmuted")

# ================== LINK FILTER ==================
async def filter_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if "http" in text:
        await update.message.delete()

        user = update.message.from_user
        chat_id = update.effective_chat.id

        count = add_warning(chat_id, user.id)

        await context.bot.send_message(
            chat_id,
            f"⚠️ {user.first_name} warning {count}/3"
        )

# ================== CALLBACK ==================
async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "health":
        await query.edit_message_text("✅ Bot is healthy")

    elif query.data == "search":
        await query.edit_message_text("Use /search keyword")

    elif query.data == "userinfo":
        await query.edit_message_text("Reply to user then use /userinfo")

    elif query.data == "mute":
        await query.edit_message_text("Reply to user then use /mute")

    elif query.data == "unmute":
        await query.edit_message_text("Reply to user then use /unmute")

    elif query.data == "domains":
        await query.edit_message_text("Domain system active")

# ================== ERROR ==================
async def error_handler(update, context):
    print("ERROR:", context.error)

# ================== MAIN ==================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("health", health))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("userinfo", userinfo))
    app.add_handler(CommandHandler("mute", mute))
    app.add_handler(CommandHandler("unmute", unmute))

    # Buttons
    app.add_handler(CallbackQueryHandler(button_click))

    # Messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, filter_links))

    # Error
    app.add_error_handler(error_handler)

    print("Bot started")

    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
