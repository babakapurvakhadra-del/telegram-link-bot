# main.py
import os
import time
import logging
import sqlite3
import wikipedia
import re
from urllib.parse import urlparse

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from keep_alive import keep_alive

# ===== CONFIG =====
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
LOG_CHAT_ID = int(os.getenv("LOG_CHAT_ID"))
ADMIN_ID = int(os.getenv("ADMIN_ID"))

ADMINS = {ADMIN_ID}
logging.basicConfig(level=logging.INFO)
start_time = time.time()

# ===== DB (persistent) =====
DB_PATH = "bot.db"
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cur = conn.cursor()

# tables
cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    name TEXT,
    username TEXT,
    language TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS warnings (
    chat_id INTEGER,
    user_id INTEGER,
    count INTEGER,
    PRIMARY KEY (chat_id, user_id)
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS muted (
    chat_id INTEGER,
    user_id INTEGER,
    PRIMARY KEY (chat_id, user_id)
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS allowed_domains (
    domain TEXT PRIMARY KEY
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS blocked_domains (
    domain TEXT PRIMARY KEY
)
""")

conn.commit()

# ===== In-memory session storage =====
# search_cache key = (chat_id, user_id) -> list of titles
search_cache = {}

# url detection regex
URL_PATTERN = re.compile(r"(https?://\S+|www\.\S+)")

# ===== Helpers =====
def save_user_to_db(user):
    if not user:
        return
    cur.execute(
        "INSERT OR REPLACE INTO users (user_id, name, username, language) VALUES (?, ?, ?, ?)",
        (user.id, user.full_name, user.username, user.language_code),
    )
    conn.commit()

def find_user_in_db_by_query(query):
    q = query.strip()
    # id
    if q.isdigit():
        cur.execute("SELECT user_id, name, username, language FROM users WHERE user_id = ?", (int(q),))
        r = cur.fetchone()
        if r:
            return r
    # @username
    if q.startswith("@"):
        username = q[1:]
        cur.execute("SELECT user_id, name, username, language FROM users WHERE username = ?", (username,))
        r = cur.fetchone()
        if r:
            return r
    # partial name
    cur.execute("SELECT user_id, name, username, language FROM users WHERE lower(name) LIKE ?", (f"%{q.lower()}%",))
    r = cur.fetchone()
    if r:
        return r
    return None

async def send_private_log(context: ContextTypes.DEFAULT_TYPE, text: str):
    try:
        await context.bot.send_message(chat_id=LOG_CHAT_ID, text=text)
    except Exception as e:
        logging.error("Failed to send private log: %s", e)

# domain helpers
def normalize_domain(netloc: str) -> str:
    if not netloc:
        return ""
    d = netloc.lower()
    if d.startswith("www."):
        d = d[4:]
    return d

def is_domain_allowed(domain: str) -> bool:
    cur.execute("SELECT 1 FROM allowed_domains WHERE domain = ?", (domain,))
    return cur.fetchone() is not None

def is_domain_blocked(domain: str) -> bool:
    cur.execute("SELECT 1 FROM blocked_domains WHERE domain = ?", (domain,))
    return cur.fetchone() is not None

def add_allowed_domain(domain: str):
    cur.execute("INSERT OR IGNORE INTO allowed_domains (domain) VALUES (?)", (domain,))
    conn.commit()

def add_blocked_domain(domain: str):
    cur.execute("INSERT OR IGNORE INTO blocked_domains (domain) VALUES (?)", (domain,))
    conn.commit()

def list_domains():
    cur.execute("SELECT domain FROM allowed_domains")
    allowed = [r[0] for r in cur.fetchall()]
    cur.execute("SELECT domain FROM blocked_domains")
    blocked = [r[0] for r in cur.fetchall()]
    return allowed, blocked

# warnings / mute DB helpers
def get_warning_count(chat_id: int, user_id: int):
    cur.execute("SELECT count FROM warnings WHERE chat_id=? AND user_id=?", (chat_id, user_id))
    row = cur.fetchone()
    return row[0] if row else 0

def set_warning_count(chat_id: int, user_id: int, count: int):
    cur.execute("REPLACE INTO warnings (chat_id, user_id, count) VALUES (?, ?, ?)", (chat_id, user_id, count))
    conn.commit()

def reset_warnings(chat_id: int, user_id: int):
    cur.execute("DELETE FROM warnings WHERE chat_id=? AND user_id=?", (chat_id, user_id))
    conn.commit()

def mute_db(chat_id: int, user_id: int):
    cur.execute("REPLACE INTO muted (chat_id, user_id) VALUES (?, ?)", (chat_id, user_id))
    conn.commit()

def unmute_db(chat_id: int, user_id: int):
    cur.execute("DELETE FROM muted WHERE chat_id=? AND user_id=?", (chat_id, user_id))
    conn.commit()

def is_muted_db(chat_id: int, user_id: int):
    cur.execute("SELECT 1 FROM muted WHERE chat_id=? AND user_id=?", (chat_id, user_id))
    return cur.fetchone() is not None

# ===== Track and new members =====
async def track_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user:
        save_user_to_db(update.effective_user)

async def new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for user in update.message.new_chat_members:
        save_user_to_db(user)
        text = (
            f"👤 NEW MEMBER\n"
            f"Name: {user.full_name}\n"
            f"Username: @{user.username if user.username else 'None'}\n"
            f"User ID: {user.id}\n"
            f"Language: {user.language_code}"
        )
        await send_private_log(context, text)

# ===== Commands: userinfo / searchuser =====
async def userinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
        save_user_to_db(target)
        row = (target.id, target.full_name, target.username, target.language_code)
    elif context.args:
        q = " ".join(context.args)
        row = find_user_in_db_by_query(q)
    else:
        await update.message.reply_text("Reply to a user or use /userinfo @username or /userinfo <id> or /userinfo <partial name>")
        return

    if not row:
        await update.message.reply_text("User not found in DB. They must interact once or be replied-to so bot can save them.")
        return

    user_id, name, username, lang = row
    text = f"📌 USER INFO\nName: {name}\nUsername: @{username if username else 'None'}\nUser ID: {user_id}\nLanguage: {lang}"
    await send_private_log(context, text)
    await update.message.reply_text("User info sent to private log")

async def searchuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /searchuser <name|@username|id>")
        return
    q = " ".join(context.args)
    row = find_user_in_db_by_query(q)
    if not row:
        await update.message.reply_text("User not found in DB.")
        return
    user_id, name, username, _ = row
    await update.message.reply_text(f"Found: {name} (@{username if username else 'None'}) — ID: {user_id}")

# ===== Domain commands: allow / block / listdomains =====
async def allow_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caller = update.effective_user.id
    if caller not in ADMINS:
        await update.message.reply_text("Only admin can change allowed domains.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /allow <domain>  (example: /allow youtube.com)")
        return
    domain = context.args[0].lower().strip()
    domain = domain.replace("http://", "").replace("https://", "").split("/")[0]
    if domain.startswith("www."):
        domain = domain[4:]
    add_allowed_domain(domain)
    await update.message.reply_text(f"Allowed domain: {domain}")

async def block_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caller = update.effective_user.id
    if caller not in ADMINS:
        await update.message.reply_text("Only admin can block domains.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /block <domain>  (example: /block scam.com)")
        return
    domain = context.args[0].lower().strip()
    domain = domain.replace("http://", "").replace("https://", "").split("/")[0]
    if domain.startswith("www."):
        domain = domain[4:]
    add_blocked_domain(domain)
    await update.message.reply_text(f"Blocked domain: {domain}")

async def listdomains_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    allowed, blocked = list_domains()
    msg = "Allowed domains:\n" + (", ".join(allowed) if allowed else "— none —")
    msg += "\n\nBlocked domains:\n" + (", ".join(blocked) if blocked else "— none —")
    await update.message.reply_text(msg)

# ===== SEARCH + CHOOSE (per chat+user) =====
async def search_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args).strip()
    if not query:
        await update.message.reply_text("Usage: /search <query>")
        return
    try:
        results = wikipedia.search(query, results=7)
    except Exception as e:
        logging.exception("wikipedia.search failed")
        await update.message.reply_text("Search error (Wikipedia may be temporarily unavailable).")
        return
    if not results:
        await update.message.reply_text("No results found.")
        return
    key = (update.effective_chat.id, update.effective_user.id)
    search_cache[key] = results
    msg = "🔎 Multiple results:\n\n"
    for i, r in enumerate(results[:7], 1):
        msg += f"{i}. {r}\n"
    msg += "\nChoose with: /choose <number>"
    await update.message.reply_text(msg)

async def choose_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = (update.effective_chat.id, update.effective_user.id)
    if key not in search_cache:
        await update.message.reply_text("No active search found for you in this chat. Use /search first.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /choose <number>")
        return
    try:
        idx = int(context.args[0]) - 1
        results = search_cache[key]
        if idx < 0 or idx >= len(results):
            await update.message.reply_text("Invalid choice number.")
            return
        title = results[idx]
        try:
            summary = wikipedia.summary(title, sentences=6)
            await update.message.reply_text(f"📖 {title}\n\n{summary}")
        except wikipedia.DisambiguationError as ex:
            options = ex.options[:7]
            msg = f"⚠️ Disambiguation for '{title}':\n"
            for i, o in enumerate(options, 1):
                msg += f"{i}. {o}\n"
            msg += "\nTry /search with a more specific query."
            await update.message.reply_text(msg)
        except Exception:
            await update.message.reply_text(f"Could not fetch details for {title}.")
    except ValueError:
        await update.message.reply_text("Invalid number. Use /choose 1")

# ===== Moderation flow (moderate button panel) =====
async def moderate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a user's message and then run /moderate")
        return
    caller_id = update.effective_user.id
    if caller_id not in ADMINS:
        await update.message.reply_text("Only admin can use moderation buttons.")
        return
    target = update.message.reply_to_message.from_user
    chat_id = update.effective_chat.id
    target_id = target.id
    keyboard = [
        [
            InlineKeyboardButton("Mute", callback_data=f"mod:mute:{chat_id}:{target_id}"),
            InlineKeyboardButton("Unmute", callback_data=f"mod:unmute:{chat_id}:{target_id}")
        ],
        [
            InlineKeyboardButton("Warn +1", callback_data=f"mod:warn:{chat_id}:{target_id}"),
            InlineKeyboardButton("Reset", callback_data=f"mod:reset:{chat_id}:{target_id}")
        ],
        [
            InlineKeyboardButton("Userinfo (log)", callback_data=f"mod:userinfo:{target_id}")
        ]
    ]
    await update.message.reply_text(
        f"Moderation for {target.full_name} (@{target.username if target.username else 'none'})",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    caller_id = query.from_user.id
    if caller_id not in ADMINS:
        await query.edit_message_text("Only admin may use these buttons.")
        return
    parts = data.split(":")
    if parts[0] != "mod":
        await query.edit_message_text("Unknown action")
        return
    action = parts[1]
    if action in ("mute", "unmute", "warn", "reset"):
        if len(parts) < 4:
            await query.edit_message_text("Bad callback payload.")
            return
        chat_id = int(parts[2]); target_id = int(parts[3])
        if action == "mute":
            mute_db(chat_id, target_id)
            await query.edit_message_text("User muted (DB).")
            await send_private_log(context, f"🔇 Muted {target_id} in {chat_id} by {caller_id}")
        elif action == "unmute":
            unmute_db(chat_id, target_id)
            await query.edit_message_text("User unmuted (DB).")
            await send_private_log(context, f"🔊 Unmuted {target_id} in {chat_id} by {caller_id}")
        elif action == "warn":
            cur_count = get_warning_count(chat_id, target_id)
            cur_count += 1
            set_warning_count(chat_id, target_id, cur_count)
            await query.edit_message_text(f"Warning added. Count = {cur_count}")
            await send_private_log(context, f"⚠️ Warning for {target_id} in {chat_id}. Now {cur_count}")
        elif action == "reset":
            reset_warnings(chat_id, target_id)
            await query.edit_message_text("Warnings reset.")
            await send_private_log(context, f"🔁 Warnings reset for {target_id} in {chat_id}")
    elif action == "userinfo":
        if len(parts) < 3:
            await query.edit_message_text("Bad payload")
            return
        tid = int(parts[2])
        cur.execute("SELECT user_id, name, username, language FROM users WHERE user_id=?", (tid,))
        r = cur.fetchone()
        if not r:
            await query.edit_message_text("User not in DB.")
            return
        user_id, name, username, lang = r
        text = f"📌 USER INFO\nName: {name}\nUsername: @{username if username else 'None'}\nID: {user_id}\nLang: {lang}"
        await send_private_log(context, text)
        await query.edit_message_text("User info sent to private log")
    else:
        await query.edit_message_text("Unknown moderation action")

# ===== Menu / postmenu =====
async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Health", callback_data="menu:health")],
        [InlineKeyboardButton("Search help", callback_data="menu:search")],
        [InlineKeyboardButton("Moderate (reply)", callback_data="menu:moderate_help")],
        [InlineKeyboardButton("Panel (admin)", callback_data="menu:panel")],
        [InlineKeyboardButton("Allowed/Blocked", callback_data="menu:domains")],
    ]
    await update.message.reply_text("Bot menu (pin this message for bottom access):", reply_markup=InlineKeyboardMarkup(keyboard))

async def menu_cb_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = (q.data or "").split(":")
    if len(data) < 2:
        await q.edit_message_text("Unknown menu action")
        return
    action = data[1]
    if action == "health":
        uptime = int(time.time() - start_time)
        await q.edit_message_text(f"Bot is alive — uptime {uptime}s")
    elif action == "search":
        await q.edit_message_text("Use /search <query> then /choose <number> to pick.")
    elif action == "moderate_help":
        await q.edit_message_text("To moderate: reply to a user's message and run /moderate — moderation buttons will appear.")
    elif action == "panel":
        await q.edit_message_text("Admin panel is /panel (admin only).")
    elif action == "domains":
        allowed, blocked = list_domains()
        msg = "Allowed domains:\n" + (", ".join(allowed) if allowed else "— none —")
        msg += "\n\nBlocked domains:\n" + (", ".join(blocked) if blocked else "— none —")
        await q.edit_message_text(msg)
    else:
        await q.edit_message_text("Unknown menu action")

async def panel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caller = update.effective_user.id
    if caller not in ADMINS:
        await update.message.reply_text("Only admin can open the panel.")
        return
    keyboard = [
        [InlineKeyboardButton("Health", callback_data="menu:health")],
        [InlineKeyboardButton("Search help", callback_data="menu:search")],
        [InlineKeyboardButton("Moderate (reply)", callback_data="menu:moderate_help")],
        [InlineKeyboardButton("Domains", callback_data="menu:domains")],
    ]
    await update.message.reply_text("Admin panel:", reply_markup=InlineKeyboardMarkup(keyboard))

async def postmenu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caller = update.effective_user.id
    if caller not in ADMINS:
        await update.message.reply_text("Only admin can post & pin the menu.")
        return
    keyboard = [
        [InlineKeyboardButton("Health", callback_data="menu:health")],
        [InlineKeyboardButton("Search help", callback_data="menu:search")],
        [InlineKeyboardButton("Moderate (reply)", callback_data="menu:moderate_help")],
        [InlineKeyboardButton("Domains", callback_data="menu:domains")],
    ]
    msg = await update.message.reply_text("Bot quick menu (pin this message):", reply_markup=InlineKeyboardMarkup(keyboard))
    try:
        await context.bot.pin_chat_message(chat_id=update.effective_chat.id, message_id=msg.message_id, disable_notification=True)
        await update.message.reply_text("Menu posted and pinned.")
    except Exception as e:
        logging.warning("Pin failed: %s", e)
        await update.message.reply_text("Menu posted but could not pin (bot needs pin permission).")

# ===== Health command =====
async def health_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uptime = int(time.time() - start_time)
    await update.message.reply_text(f"✅ Bot healthy — uptime {uptime}s")

# ===== Link detection + deletion handler =====
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Save user
    if update.effective_user:
        save_user_to_db(update.effective_user)

    chat_id = update.effective_chat.id
    user = update.effective_user
    text = update.message.text or ""

    # if user muted -> delete message
    if is_muted_db(chat_id, user.id):
        try:
            await update.message.delete()
        except:
            pass
        return

    # check for URL(s)
    urls = URL_PATTERN.findall(text)
    if not urls:
        return

    for url in urls:
        # obtain domain
        try:
            parsed = urlparse(url if url.startswith("http") else "http://" + url)
            domain = normalize_domain(parsed.netloc)
        except:
            domain = ""
        # if domain explicitly allowed -> skip
        if domain and is_domain_allowed(domain):
            return  # allowed link, ignore further checks
        # if domain explicitly blocked -> delete
        if domain and is_domain_blocked(domain):
            try:
                await update.message.delete()
            except:
                pass
            await send_private_log(context, f"🚨 BLOCKED LINK deleted from {user.full_name} ({user.id}) in chat {chat_id} — {url}")
            return
        # otherwise treat any external http(s) link as suspicious -> delete (you can relax this if you want)
        if url.startswith("http"):
            try:
                await update.message.delete()
            except:
                pass
            await send_private_log(context, f"🚨 External link removed from {user.full_name} ({user.id}) in chat {chat_id} — {url}")
            return

# ===== Error handler =====
async def error_handler(update, context):
    logging.error("Bot error: %s", context.error)

# ===== Main boot =====
def main():
    keep_alive()
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_error_handler(error_handler)

    # Track users and new members
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_member))
    # track messages (text only) and run link detection
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    # Save any user that sends any message or updates (just track with a light handler)
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, track_users))

    # commands
    app.add_handler(CommandHandler("userinfo", userinfo))
    app.add_handler(CommandHandler("searchuser", searchuser))
    app.add_handler(CommandHandler("search", search_cmd))
    app.add_handler(CommandHandler("choose", choose_cmd))
    app.add_handler(CommandHandler("moderate", moderate_cmd))
    app.add_handler(CommandHandler("menu", menu_cmd))
    app.add_handler(CommandHandler("panel", panel_cmd))
    app.add_handler(CommandHandler("postmenu", postmenu_cmd))
    app.add_handler(CommandHandler("health", health_cmd))

    # domain commands
    app.add_handler(CommandHandler("allow", allow_cmd))
    app.add_handler(CommandHandler("block", block_cmd))
    app.add_handler(CommandHandler("listdomains", listdomains_cmd))

    # callbacks
    app.add_handler(CallbackQueryHandler(callback_query_handler, pattern=r"^mod:"))
    app.add_handler(CallbackQueryHandler(menu_cb_handler, pattern=r"^menu:"))

    print("Bot started")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
