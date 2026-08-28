import logging
import os
import re
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# 🔴 PUT YOUR PRIVATE LOG CHAT ID HERE (your Telegram ID or channel ID)
LOG_CHAT_ID = 6609362058  # example: 123456789

logging.basicConfig(level=logging.INFO)

# ---------- SUSPICIOUS LINK PATTERN ----------
SUSPICIOUS_PATTERNS = [
    r"bit\.ly",
    r"tinyurl",
    r"t\.me\/\+",
    r"free\s*money",
    r"crypto\s*giveaway",
    r"earn\s*money\s*fast",
]

def is_suspicious(text: str) -> bool:
    text = text.lower()
    return any(re.search(pattern, text) for pattern in SUSPICIOUS_PATTERNS)


# ---------- START COMMAND ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot active and monitoring links ✅")


# ---------- MAIN MESSAGE HANDLER ----------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    user = update.effective_user

    if not message or not message.text:
        return

    text = message.text

    # Get admin list
    chat_admins = await context.bot.get_chat_administrators(update.effective_chat.id)
    admin_ids = [admin.user.id for admin in chat_admins]

    # If admin → ignore completely
    if user.id in admin_ids:
        return

    # Check links
    if is_suspicious(text):
        await message.delete()

        log_text = (
            f"🚨 Suspicious Link Removed\n"
            f"User: {user.full_name}\n"
            f"Username: @{user.username}\n"
            f"Message: {text}"
        )

        # Send log if enabled
        if LOG_CHAT_ID:
            try:
                await context.bot.send_message(LOG_CHAT_ID, log_text)
            except Exception as e:
                logging.error(f"Log failed: {e}")


# ---------- MAIN ----------
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot started successfully")

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
