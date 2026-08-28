import os
import logging
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# ---------------- LOGGING ----------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------- FLASK APP ----------------
app_web = Flask(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN")

# ---------------- BOT ----------------
app = Application.builder().token(TOKEN).build()

# start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot active")

# link detection
def has_link(text: str) -> bool:
    if not text:
        return False
    text = text.lower()
    return any(x in text for x in ["http://", "https://", "www.", "t.me/"])

# delete messages
async def delete_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg:
        return

    text = msg.text or msg.caption or ""

    if has_link(text):
        await msg.delete()
        logger.info("Deleted link")

# handlers
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT | filters.CAPTION, delete_links))

# ---------------- WEBHOOK ROUTE ----------------
@app_web.post("/")
async def webhook():
    update = Update.de_json(request.get_json(force=True), app.bot)
    await app.process_update(update)
    return "ok"

@app_web.get("/")
def home():
    return "Bot is running"

# ---------------- RUN ----------------
if __name__ == "__main__":
    import asyncio

    async def run():
        await app.initialize()
        await app.start()

        port = int(os.environ.get("PORT", 10000))
        app_web.run(host="0.0.0.0", port=port)

    asyncio.run(run())
