import logging
import os

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text("Bot active")

def has_link(text: str) -> bool:
    return any(x in text.lower() for x in ["http", "www.", "t.me/"])

async def delete_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        msg = update.message
        if not msg:
            return

        text = msg.text or msg.caption or ""
        if has_link(text):
            await msg.delete()

    except Exception as e:
        logger.error(e)

def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")

    if not token:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.ALL, delete_links))

    logger.info("Bot started")
    app.run_polling()

if __name__ == "__main__":
    main()
