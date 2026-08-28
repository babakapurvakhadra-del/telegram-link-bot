import logging
import os
from threading import Thread
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ---------------- LOGGING ----------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------- KEEP ALIVE SERVER (RENDER FIX) ----------------
def run_server():
    port = int(os.environ.get("PORT", 10000))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot is running")

    server = HTTPServer(("0.0.0.0", port), Handler)
    server.serve_forever()

# ---------------- COMMAND: START ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_message:
        await update.effective_message.reply_text("Bot active")

# ---------------- LINK CHECK ----------------
def has_link(text: str) -> bool:
    if not text:
        return False

    text = text.lower()

    return any(
        x in text for x in [
            "http://",
            "https://",
            "www.",
            "t.me/",
            ".com"
        ]
    )

# ---------------- DELETE LOGIC ----------------
async def delete_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        msg = update.effective_message
        if not msg:
            return

        text = msg.text or msg.caption or ""

        if has_link(text):
            await msg.delete()
            logger.info("Deleted a link message")

    except Exception as e:
        logger.error(f"Error deleting message: {e}")

# ---------------- MAIN ----------------
def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")

    if not token:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN")

    app = Application.builder().token(token).build()

    # commands
    app.add_handler(CommandHandler("start", start))

    # only text/caption messages (clean + safe)
    app.add_handler(MessageHandler(filters.TEXT | filters.CAPTION, delete_links))

    logger.info("Bot started successfully")

    # start web server for Render
    Thread(target=run_server, daemon=True).start()

    # start telegram bot
    app.run_polling()

if __name__ == "__main__":
    main()
