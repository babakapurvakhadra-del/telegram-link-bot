import logging
import os

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ---------------- LOGGING ----------------

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - message",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

# ---------------- START ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text(
            "👋 Bot is active.\nI delete links only (no ban, no kick)."
        )

# ---------------- HELP ----------------

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text(
            "/start - start bot\n/help - help"
        )

# ---------------- LINK CHECK ----------------

def has_link(text: str) -> bool:
    text = text.lower()
    return (
        "http://" in text or
        "https://" in text or
        "www." in text or
        "t.me/" in text or
        ".com" in text
    )

# ---------------- DELETE LOGIC ----------------

async def delete_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.message:
            text = update.message.text or update.message.caption or ""

            if has_link(text):
                await update.message.delete()

    except Exception as e:
        logger.error(f"Delete error: {e}")

# ---------------- MAIN ----------------

def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")

    if not token:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN")

    app = Application.builder().token(token).build()

    # commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))

    # IMPORTANT FIX: catch all message types
    app.add_handler(MessageHandler(filters.ALL, delete_links))

    logger.info("Bot started successfully")
    app.run_polling()

if __name__ == "__main__":
    main()
