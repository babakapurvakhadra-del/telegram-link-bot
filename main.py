import logging
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# ---------------- LOGGING ----------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------- KEEP ALIVE SERVER (RENDER NEEDS THIS) ----------------
def run_server():
    port = int(os.environ.get("PORT", 10000))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot is running")

    HTTPServer(("0.0.0.0", port), Handler).serve_forever()


# ---------------- START COMMAND ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_message:
        await update.effective_message.reply_text("Bot is active ✅")


# ---------------- LINK DETECTOR ----------------
def has_link(text: str) -> bool:
    if not text:
        return False

    text = text.lower()

    return any(
        x in text for x in [
            "http://",
            "https://",
            "www.",
            "t.me/"
        ]
    )


# ---------------- DELETE LINKS ----------------
async def delete_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        msg = update.effective_message
        if not msg:
            return

        text = msg.text or msg.caption or ""

        if has_link(text):
            await msg.delete()
            logger.info("Deleted suspicious link message")

    except Exception as e:
        logger.error(f"Delete error: {e}")


# ---------------- MAIN ----------------
def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")

    if not token:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN")

    app = Application.builder().token(token).build()

    # handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT | filters.CAPTION, delete_links))

    logger.info("Bot started successfully")

    # keep alive server for Render
    Thread(target=run_server, daemon=True).start()

    # start bot (IMPORTANT FIX FOR RENDER)
    app.run_polling(drop_pending_updates=True, stop_signals=None)


if __name__ == "__main__":
    main()
