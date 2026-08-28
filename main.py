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

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - message",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text("👋 Bot active. I delete links only.")

def has_link(text: str) -> bool:
    text = text.lower()
    return (
        "http://" in text or
        "https://" in text or
        "t.me/" in text or
        "www." in text
    )

async def delete_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.message and update.message.text:
            if has_link(update.message.text):
                await update.message.delete()
    except Exception as e:
        logger.error(e)

def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")

    if not token:
        raise RuntimeError("Missing token")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.ALL, delete_links))

    app.run_polling()

if __name__ == "__main__":
    main()
