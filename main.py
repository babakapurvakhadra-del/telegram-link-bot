import logging
import os
from threading import Thread
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------- KEEP ALIVE SERVER (FOR RENDER WEB SERVICE) ----------------
def run_server():
    port = int(os.environ.get("PORT", 10000))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot is running")

    server = HTTPServer(("0.0.0.0", port), Handler)
    server.serve_forever()

# ---------------- BOT ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot active")

def has_link(text: str) -> bool:
    return any(x in text.lower() for x in ["http", "www.", "t.me"])

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

    # start web server (important for Render Web Service)
    Thread(target=run_server, daemon=True).start()

    # start telegram bot
    app.run_polling()

if __name__ == "__main__":
    main()
