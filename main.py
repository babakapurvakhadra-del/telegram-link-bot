import logging
import os
import re
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

LOG_CHAT_ID = 6609362058

# 👑 Admin user IDs
ADMINS = {6609362058}

logging.basicConfig(level=logging.INFO)

# 🔥 URL detection (important improvement)
URL_PATTERN = re.compile(r"(https?://\S+|www\.\S+)")

# 🚨 suspicious keywords
SUSPICIOUS_KEYWORDS = [
    "free money",
    "click here",
    "earn $",
    "bitcoin giveaway",
    "airdrop",
    "claim now"
]

# ✅ allowed safe domains
SAFE_DOMAINS = [
    "youtube.com",
    "youtu.be",
    "t.me",
    "telegram.me"
]


def is_safe_link(text: str) -> bool:
    text = text.lower()

    for domain in SAFE_DOMAINS:
        if domain in text:
            return True

    return False


def is_suspicious(text: str) -> bool:
    text = text.lower()

    # keyword check
    for word in SUSPICIOUS_KEYWORDS:
        if word in text:
            return True

    # URL check
    urls = URL_PATTERN.findall(text)

    for url in urls:
        if not is_safe_link(url):
            return True

    return False


async def log_to_private(update: Update, reason: str):
    user = update.effective_user
    msg = update.message.text

    log_text = (
        f"🚨 LINK BLOCKED\n"
        f"User: {user.full_name}\n"
        f"Username: @{user.username}\n"
        f"Reason: {reason}\n"
        f"Message: {msg}"
    )

    await update.get_bot().send_message(chat_id=LOG_CHAT_ID, text=log_text)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot active")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    # 👑 admin bypass
    if user_id in ADMINS:
        return

    # 🚨 suspicious detection
    if is_suspicious(text):
        await update.message.delete()
        await log_to_private(update, "Suspicious content detected")
        return


def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot started successfully")

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
