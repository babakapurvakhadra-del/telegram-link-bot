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

SAFE_DOMAINS = ["youtube.com", "youtu.be", "t.me", "telegram.me"]

SUSPICIOUS_DOMAINS = ["bit.ly", "tinyurl", "shorturl", "free", "claim", "airdrop"]

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
# USER TRACKING (STEP 2 CORE)
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

    # url check
    urls = URL_PATTERN.findall(text)

    for url in urls:
        url_low = url.lower()

        if any(domain in url_low for domain in SAFE_DOMAINS):
            continue

        if any(bad in url_low for bad in SUSPICIOUS_DOMAINS):
            return True

        if url.startswith("http"):
            return True

    return False


# ======================
# LOGGING
# ======================

async def log_to_private(update: Update, reason: str):
    user = update.effective_user
    msg = update.message.text

    text = (
        "🚨 BLOCKED MESSAGE\n"
        f"User: {user.full_name}\n"
        f"Username: @{user.username}\n"
        f"Reason: {reason}\n"
        f"Message: {msg}"
    )

    await update.get_bot().send_message(LOG_CHAT_ID, text)


# ======================
# COMMANDS
# ======================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot active")


# ======================
# MAIN LOGIC (STEP 2)
# ======================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id in ADMINS:
        return

    text = update.message.text

    if is_suspicious(text):

        user_warnings[user_id] += 1
        count = user_warnings[user_id]

        # 1st warning
        if count == 1:
            await update.message.reply_text("⚠️ Warning: suspicious message detected.")
            await log_to_private(update, "1st warning")

        # 2nd delete
        elif count == 2:
            try:
                await update.message.delete()
            except:
                pass
            await log_to_private(update, "2nd warning - deleted")

        # 3rd strict delete
        else:
            try:
                await update.message.delete()
            except:
                pass
            await log_to_private(update, "3rd+ warning - repeated spam")

        return


# ======================
# ERROR HANDLER
# ======================

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logging.error(f"Error: {context.error}")


# ======================
# RUN
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
