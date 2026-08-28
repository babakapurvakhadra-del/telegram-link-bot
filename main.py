import logging
import os
import re
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ======================
# CONFIG
# ======================

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

LOG_CHAT_ID = 6609362058  # your private log chat ID
ADMINS = {6609362058}     # your admin user ID

logging.basicConfig(level=logging.INFO)

# ======================
# URL DETECTION
# ======================
URL_PATTERN = re.compile(r"(https?://[^\s]+|www\.[^\s]+)")

# ======================
# SAFE DOMAINS (ALLOWED)
# ======================
SAFE_DOMAINS = [
    "youtube.com",
    "youtu.be",
    "t.me",
    "telegram.me"
]

# ======================
# SUSPICIOUS DOMAINS (BLOCKED)
# ======================
SUSPICIOUS_DOMAINS = [
    "bit.ly",
    "tinyurl",
    "shorturl",
    "free",
    "claim",
    "airdrop",
    "earn",
    "gift",
    "spam",
]

# ======================
# SUSPICIOUS KEYWORDS
# ======================
SUSPICIOUS_KEYWORDS = [
    "free money",
    "click here",
    "earn $",
    "bitcoin giveaway",
    "instant reward",
    "claim now",
    "urgent win",
]


# ======================
# DETECTION LOGIC
# ======================

def is_suspicious(text: str) -> bool:
    text = text.lower()

    # 1. keyword check
    for word in SUSPICIOUS_KEYWORDS:
        if word in text:
            return True

    # 2. URL check
    urls = URL_PATTERN.findall(text)

    for url in urls:
        url_low = url.lower()

        # ✔ SAFE LINKS (allow)
        if any(domain in url_low for domain in SAFE_DOMAINS):
            continue

        # ❌ BLOCK suspicious domains
        if any(bad in url_low for bad in SUSPICIOUS_DOMAINS):
            return True

        # ❌ unknown external links (treat as risky)
        if url.startswith("http"):
            return True

    return False


# ======================
# PRIVATE LOGS
# ======================

async def log_to_private(update: Update, reason: str):
    user = update.effective_user
    msg = update.message.text

    log_text = (
        "🚨 MESSAGE BLOCKED\n"
        f"User: {user.full_name}\n"
        f"Username: @{user.username}\n"
        f"Reason: {reason}\n"
        f"Message: {msg}"
    )

    await update.get_bot().send_message(
        chat_id=LOG_CHAT_ID,
        text=log_text
    )


# ======================
# COMMANDS
# ======================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot active")


# ======================
# MESSAGE HANDLER
# ======================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    # 👑 ADMIN bypass
    if user_id in ADMINS:
        return

    # 🚨 detect spam/suspicious
    if is_suspicious(text):
        try:
            await update.message.delete()
        except:
            pass

        await log_to_private(update, "Suspicious link or spam detected")
        return


# ======================
# ERROR HANDLER
# ======================

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logging.error(f"Bot error: {context.error}")


# ======================
# MAIN RUN
# ======================

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    print("Bot started successfully")

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
