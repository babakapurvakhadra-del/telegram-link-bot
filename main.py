import logging
import os
import re
from collections import defaultdict
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

LOG_CHAT_ID = 6609362058
ADMINS = {6609362058}

logging.basicConfig(level=logging.INFO)

# ======================
# PATTERNS
# ======================

URL_PATTERN = re.compile(r"(https?://[^\s]+|www\.[^\s]+)")

SAFE_DOMAINS = [
    "youtube.com",
    "youtu.be",
    "t.me",
    "telegram.me"
]

SUSPICIOUS_KEYWORDS = [
    "free money",
    "click here",
    "earn $",
    "bitcoin giveaway",
    "instant reward",
    "claim now",
    "urgent win"
]

SUSPICIOUS_DOMAINS = [
    "bit.ly",
    "tinyurl",
    "shorturl",
    "airdrop",
    "claim",
    "earn",
    "gift"
]

# ======================
# USER TRACKING
# ======================

user_warnings = defaultdict(int)

# ======================
# DETECTION
# ======================

def is_suspicious(text: str) -> bool:
    text = text.lower()

    # keyword check
    for word in SUSPICIOUS_KEYWORDS:
        if word in text:
            return True

    urls = URL_PATTERN.findall(text)

    for url in urls:
        url_low = url.lower()

        # ✅ allow safe links
        if any(domain in url_low for domain in SAFE_DOMAINS):
            continue

        # ❌ block known bad domains
        if any(domain in url_low for domain in SUSPICIOUS_DOMAINS):
            return True

        # ❌ unknown external links = suspicious
        if "http" in url_low or "www" in url_low:
            return True

    return False

# ======================
# LOGGING (FIXED)
# ======================

async def log_to_private(update: Update, reason: str, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.message.text

    log_text = (
        "🚨 BLOCKED MESSAGE\n"
        f"User: {user.full_name}\n"
        f"Username: @{user.username}\n"
        f"Reason: {reason}\n"
        f"Message: {msg}"
    )

    await context.bot.send_message(
        chat_id=LOG_CHAT_ID,
        text=log_text
    )

# ======================
# START
# ======================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot active")

# ======================
# HANDLER
# ======================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    # admin bypass
    if user_id in ADMINS:
        return

    if is_suspicious(text):

        user_warnings[user_id] += 1
        count = user_warnings[user_id]

        if count == 1:
            await update.message.reply_text("⚠️ Warning: suspicious message detected.")
            await log_to_private(update, "1st warning", context)

        elif count == 2:
            try:
                await update.message.delete()
            except:
                pass
            await log_to_private(update, "2nd warning - deleted", context)

        else:
            try:
                await update.message.delete()
            except:
                pass
            await log_to_private(update, "3rd warning - banned level", context)

# ======================
# ERROR HANDLER
# ======================

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logging.error(f"Bot error: {context.error}")

# ======================
# MAIN
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
