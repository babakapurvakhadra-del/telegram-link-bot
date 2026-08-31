# main.py (FINAL)
import os
import time
import logging
import sqlite3
import re
import requests
import wikipedia
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

# -------- CONFIG --------
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
LOG_CHAT_ID = int(os.getenv("LOG_CHAT_ID", "0"))
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
ADMINS = {ADMIN_ID}
SERPAPI_KEY = os.getenv("SERPAPI_KEY", None)

logging.basicConfig(level=logging.INFO)
start_time = time.time()

# -------- DB (SQLite persisted in container) --------
DB_PATH = "bot.db"
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cur = conn.cursor()

# create tables
cur.execute("""CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    name TEXT,
    username TEXT,
    language TEXT
)""")
cur.execute("""CREATE TABLE IF NOT EXISTS warnings (
    chat_id INTEGER,
    user_id INTEGER,
    count INTEGER,
    PRIMARY KEY (chat_id, user_id)
)""")
cur.execute("""CREATE TABLE IF NOT EXISTS muted (
    chat_id INTEGER,
    user_id INTEGER,
    PRIMARY KEY (chat_id, user_id)
)""")
cur.execute("""CREATE TABLE IF NOT EXISTS allowed_domains (domain TEXT PRIMARY KEY)""")
cur.execute("""CREATE TABLE IF NOT EXISTS blocked_domains (domain TEXT PRIMARY KEY)""")
conn.commit()

# -------- in-memory search cache for choose flow --------
search_cache = {}  # key: (chat_id, user_id) -> list[str]

# -------- helpers & patterns --------
URL_PATTERN = re.compile(r"(https?://\S+|www\.\S+)")

def normalize_domain(netloc: str) -> str:
    if not netloc:
        return ""
    d = netloc.lower()
    if d.startswith("www."):
        d = d[4:]
    return d

def save_user_to_db(user):
    if not user:
        return
    try:
        cur.execute(
            "INSERT OR REPLACE INTO users (user_id, name, username, language) VALUES (?, ?, ?, ?)",
            (user.id, user.full_name, user.username, user.language_code),
        )
        conn.commit()
    except Exception:
        logging.exception("save_user_to_db failed")

def find_user_in_db_by_query(query):
    q = query.strip()
    if q.startswith("@"):
        q = q[1:]
        cur.execute("SELECT user_id, name, username, language FROM users WHERE username = ?", (q,))
        r = cur.fetchone()
        if r:
            return r
    if q.isdigit():
        cur.execute("SELECT user_id, name, username, language FROM users WHERE user_id = ?", (int(q),))
        r = cur.fetchone()
        if r:
            return r
    cur.execute("SELECT user_id, name, username, language FROM users WHERE lower(name) LIKE ?", (f"%{q.lower()}%",))
    r = cur.fetchone()
    if r:
        return r
    return None

def add_allowed_domain(domain):
    domain = normalize_domain(domain)
    cur.execute("INSERT OR IGNORE INTO allowed_domains (domain) VALUES (?)", (domain,))
    conn.commit()

def add_blocked_domain(domain):
    domain = normalize_domain(domain)
    cur.execute("INSERT OR IGNORE INTO blocked_domains (domain) VALUES (?)", (domain,))
    conn.commit()

def list_domains():
    cur.execute("SELECT domain FROM allowed_domains")
    allowed = [r[0] for r in cur.fetchall()]
    cur.execute("SELECT domain FROM blocked_domains")
    blocked = [r[0] for r in cur.fetchall()]
    return allowed, blocked

# warnings/muted DB (per-chat)
def get_warning_count(chat_id:int, user_id:int)->int:
    cur.execute("SELECT count FROM warnings WHERE chat_id=? AND user_id=?", (chat_id, user_id))
    r = cur.fetchone()
    return r[0] if r else 0

def set_warning_count(chat_id:int, user_id:int, count:int):
    cur.execute("REPLACE INTO warnings (chat_id, user_id, count) VALUES (?, ?, ?)", (chat_id, user_id, count))
    conn.commit()

def reset_warnings(chat_id:int, user_id:int):
    cur.execute("DELETE FROM warnings WHERE chat_id=? AND user_id=?", (chat_id, user_id))
    conn.commit()

def mute_db(chat_id:int, user_id:int):
    cur.execute("REPLACE INTO muted (chat_id, user_id) VALUES (?, ?)", (chat_id, user_id))
    conn.commit()

def unmute_db(chat_id:int, user_id:int):
    cur.execute("DELETE FROM muted WHERE chat_id=? AND user_id=?", (chat_id, user_id))
    conn.commit()

def is_muted_db(chat_id:int, user_id:int)->bool:
    cur.execute("SELECT 1 FROM muted WHERE chat_id=? AND user_id=?", (chat_id, user_id))
    return cur.fetchone() is not None

def muted_list_for_chat(chat_id:int):
    cur.execute("SELECT user_id FROM muted WHERE chat_id=?", (chat_id,))
    return [r[0] for r in cur.fetchall()]

# private log sender
async def send_private_log(context: ContextTypes.DEFAULT_TYPE, text: str):
    try:
        if LOG_CHAT_ID == 0:
            logging.warning("LOG_CHAT_ID not set - private logs disabled")
            return
        await context.bot.send_message(chat_id=LOG_CHAT_ID, text=text)
    except Exception:
        logging.exception("send_private_log failed")

# robust target resolver
async def parse_target_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Returns (target_id:int, display:str) or (None, None).
    Order:
     1) reply -> replied user
     2) tg://user?id=123
     3) numeric id -> attempt get_chat_member if in chat
     4) @username -> try DB -> get_chat (public username) -> then get_chat_member(chat_id, id) to confirm presence in current chat
     5) plain name -> DB search
    Note: Telegram API doesn't allow searching all chat members by name; DB or reply is the reliable way.
    """
    # (1) reply
    if update.message and update.message.reply_to_message:
        u = update.message.reply_to_message.from_user
        return u.id, f"{u.full_name} (@{u.username if u.username else 'none'})"

    # (2) args given
    if context.args:
        raw = " ".join(context.args).strip()

        if raw.startswith("tg://user?id="):
            try:
                uid = int(raw.split("=",1)[1])
                return uid, f"id:{uid}"
            except:
                return None, None

        if raw.isdigit():
            uid = int(raw)
            # try to validate presence in chat
            try:
                if update.effective_chat:
                    await context.bot.get_chat_member(update.effective_chat.id, uid)
                    return uid, f"id:{uid}"
                return uid, f"id:{uid}"
            except Exception:
                # not member or API blocked, still return id
                return uid, f"id:{uid}"

        if raw.startswith("@"):
            db_res = find_user_in_db_by_query(raw)
            if db_res:
                return db_res[0], f"{db_res[1]} (@{db_res[2] if db_res[2] else 'none'})"
            # fallback to get_chat (public username)
            try:
                chat = await context.bot.get_chat(raw)
                # Validate if they are member in this chat
                uid = chat.id
                if update.effective_chat:
                    try:
                        await context.bot.get_chat_member(update.effective_chat.id, uid)
                        return uid, f"{getattr(chat,'full_name', raw)} (@{getattr(chat,'username', None)})"
                    except Exception:
                        # user exists but may not be member of this chat
                        return uid, f"{getattr(chat,'full_name', raw)} (@{getattr(chat,'username', None)})"
                return uid, f"{getattr(chat,'full_name', raw)} (@{getattr(chat,'username', None)})"
            except Exception:
                return None, None

        # plain name -> DB search
        db_res = find_user_in_db_by_query(raw)
        if db_res:
            return db_res[0], f"{db_res[1]} (@{db_res[2] if db_res[2] else 'none'})"

    return None, None

# track users helper
async def track_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user:
        save_user_to_db(update.effective_user)

# new member handler
async def new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for user in update.message.new_chat_members:
        save_user_to_db(user)
        txt = (
            f"👤 NEW MEMBER\n"
            f"Name: {user.full_name}\n"
            f"Username: @{user.username if user.username else 'None'}\n"
            f"User ID: {user.id}\n"
            f"Language: {user.language_code}"
        )
        await send_private_log(context, txt)

# userinfo
async def userinfo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # reply => info of replied user
    if update.message and update.message.reply_to_message:
        tgt = update.message.reply_to_message.from_user
        save_user_to_db(tgt)
        row = (tgt.id, tgt.full_name, tgt.username, tgt.language_code)
    elif context.args:
        q = " ".join(context.args)
        row = find_user_in_db_by_query(q)
        # fallback: @username => get_chat
        if not row and q.startswith("@"):
            try:
                chat = await context.bot.get_chat(q)
                row = (chat.id, getattr(chat, "full_name", q), getattr(chat, "username", None), getattr(chat, "language_code", None))
            except Exception:
                row = None
    else:
        await update.message.reply_text("Usage: reply to user or /userinfo <@username|id|partial name>")
        return

    if not row:
        await update.message.reply_text("User not found in DB or via Telegram API.")
        return

    uid, name, username, lang = row
    text = f"📌 USER INFO\nName: {name}\nUsername: @{username if username else 'None'}\nUser ID: {uid}\nLanguage: {lang}"
    await send_private_log(context, text)
    await update.message.reply_text("User info sent to private log")

# searchuser quick DB lookup
async def searchuser_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /searchuser <@username|id|partial name>")
        return
    q = " ".join(context.args)
    row = find_user_in_db_by_query(q)
    if not row:
        await update.message.reply_text("User not found in DB.")
        return
    user_id, name, username, lang = row
    await update.message.reply_text(f"Found: {name} (@{username if username else 'None'}) — ID: {user_id}")

# getid command — returns user id for member in same chat (best-effort)
async def getid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # if reply
    if update.message and update.message.reply_to_message:
        u = update.message.reply_to_message.from_user
        await update.message.reply_text(f"User ID: {u.id}")
        return
    if not context.args:
        await update.message.reply_text("Usage: reply to user or /getid <@username|id|tg://user?id=...>")
        return
    target_id, desc = await parse_target_id(update, context)
    if not target_id:
        await update.message.reply_text("Could not resolve user. Use reply, @username, tg://user?id or numeric id.")
        return
    await update.message.reply_text(f"Resolved: {desc} — ID: {target_id}")

# SEARCH /choose — Wiki -> DDG -> SerpAPI fallback
async def search_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args).strip()
    if not query:
        await update.message.reply_text("Usage: /search <query>")
        return

    results = []
    # try Wikipedia
    try:
        results = wikipedia.search(query, results=8)
    except Exception:
        logging.exception("wikipedia.search failed")

    # DuckDuckGo fallback
    if not results:
        try:
            r = requests.get("https://api.duckduckgo.com/", params={"q": query, "format": "json", "no_html": 1, "no_redirect": 1}, timeout=6)
            if r.status_code == 200:
                data = r.json()
                if data.get("Heading"):
                    results = [data.get("Heading")]
                else:
                    related = data.get("RelatedTopics", [])
                    titles = []
                    for it in related:
                        if isinstance(it, dict):
                            t = it.get("Text")
                            if t:
                                titles.append(t.split(" - ")[0])
                            if len(titles) >= 8:
                                break
                    results = titles
        except Exception:
            logging.exception("DDG fallback failed")

    # SerpAPI fallback (if key provided)
    if not results and SERPAPI_KEY:
        try:
            r = requests.get("https://serpapi.com/search.json", params={"q": query, "engine": "google", "api_key": SERPAPI_KEY, "num": 8}, timeout=6)
            if r.status_code == 200:
                data = r.json()
                organic = data.get("organic_results", []) or data.get("organic", [])
                titles = []
                for o in organic:
                    title = o.get("title") or o.get("snippet") or o.get("link")
                    if title:
                        titles.append(title)
                    if len(titles) >= 8:
                        break
                results = titles
        except Exception:
            logging.exception("SerpAPI fallback failed")

    if not results:
        await update.message.reply_text("No results found.")
        return

    key = (update.effective_chat.id, update.effective_user.id)
    search_cache[key] = results

    msg = "🔎 Multiple results:\n\n"
    for i, r in enumerate(results[:8], 1):
        msg += f"{i}. {r}\n"
    msg += "\nChoose one with: /choose <number>"
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
        # try wikipedia summary
        try:
            summary = wikipedia.summary(title, sentences=10)
            await update.message.reply_text(f"📖 {title}\n\n{summary}")
            return
        except wikipedia.DisambiguationError as ex:
            options = ex.options[:7]
            msg = f"⚠️ Disambiguation for '{title}':\n"
            for i, o in enumerate(options, 1):
                msg += f"{i}. {o}\n"
            msg += "\nTry /search with a more specific query or re-run /search and /choose."
            await update.message.reply_text(msg)
            return
        except Exception:
            logging.exception("wikipedia.summary failed")
        # fallback: wiki API extract
        try:
            r = requests.get("https://en.wikipedia.org/w/api.php",
                             params={"action": "query", "prop": "extracts", "exintro": True, "explaintext": True, "titles": title, "format": "json", "redirects": 1}, timeout=6)
            if r.status_code == 200:
                data = r.json()
                pages = data.get("query", {}).get("pages", {})
                if pages:
                    page = next(iter(pages.values()))
                    extract = page.get("extract", "No extract available.")
                    await update.message.reply_text(f"📖 {title}\n\n{extract}")
                    return
        except Exception:
            logging.exception("wiki API fallback failed")
        # final fallback ddg
        try:
            r = requests.get("https://api.duckduckgo.com/", params={"q": title, "format": "json", "no_html": 1, "no_redirect": 1}, timeout=6)
            if r.status_code == 200:
                data = r.json()
                if data.get("AbstractText"):
                    await update.message.reply_text(f"📖 {title}\n\n{data.get('AbstractText')}")
                    return
        except Exception:
            logging.exception("DDG title fallback failed")
        await update.message.reply_text(f"Could not fetch details for {title}.")
    except ValueError:
        await update.message.reply_text("Invalid number. Use /choose 1")

# allow/block/listdomains
async def allow_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMINS:
        await update.message.reply_text("Only admin can change allowed domains.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /allow <domain>")
        return
    add_allowed_domain(context.args[0])
    await update.message.reply_text(f"Allowed: {context.args[0]}")

async def block_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMINS:
        await update.message.reply_text("Only admin can block domains.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /block <domain>")
        return
    add_blocked_domain(context.args[0])
    await update.message.reply_text(f"Blocked: {context.args[0]}")

async def listdomains_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    allowed, blocked = list_domains()
    await update.message.reply_text("Allowed:\n" + (", ".join(allowed) if allowed else "— none —") + "\n\nBlocked:\n" + (", ".join(blocked) if blocked else "— none —"))

# mute/unmute/mutelist with robust resolution
async def mute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMINS:
        await update.message.reply_text("Only admin can mute.")
        return
    target_id, desc = await parse_target_id(update, context)
    if not target_id:
        await update.message.reply_text("Could not determine user. Use reply / @username / tg://user?id / numeric id / name (DB).")
        return
    chat_id = update.effective_chat.id
    # optionally confirm presence using get_chat_member
    try:
        await context.bot.get_chat_member(chat_id, target_id)
    except Exception:
        # still allow muting by DB (best-effort) but inform admin
        await update.message.reply_text("User resolved but may not be a current chat member (muted in DB).")
    mute_db(chat_id, target_id)
    await update.message.reply_text(f"Muted {desc}")
    await send_private_log(context, f"🔇 Muted {desc} id:{target_id} in {chat_id} by {update.effective_user.id}")

async def unmute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMINS:
        await update.message.reply_text("Only admin can unmute.")
        return
    target_id, desc = await parse_target_id(update, context)
    if not target_id:
        await update.message.reply_text("Could not determine user.")
        return
    chat_id = update.effective_chat.id
    unmute_db(chat_id, target_id)
    await update.message.reply_text(f"Unmuted {desc}")
    await send_private_log(context, f"🔊 Unmuted {desc} id:{target_id} in {chat_id} by {update.effective_user.id}")

async def mutelist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    uids = muted_list_for_chat(chat_id)
    if not uids:
        await update.message.reply_text("No muted users.")
        return
    lines = []
    for uid in uids:
        cur.execute("SELECT name, username FROM users WHERE user_id=?", (uid,))
        r = cur.fetchone()
        if r:
            name, username = r
            lines.append(f"{name} (@{username}) — {uid}" if username else f"{name} — {uid}")
        else:
            lines.append(str(uid))
    await update.message.reply_text("Muted users:\n" + "\n".join(lines))

# message handlers for muting & link deletion
async def handle_all_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.effective_chat:
        return
    save_user_to_db(update.effective_user)
    uid = update.effective_user.id
    chat_id = update.effective_chat.id
    if update.message and update.message.new_chat_members:
        return
    if is_muted_db(chat_id, uid):
        try:
            if update.message:
                await update.message.delete()
        except Exception:
            pass
        return

async def handle_text_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return
    text = update.message.text or ""
    urls = URL_PATTERN.findall(text)
    if not urls:
        return
    for raw_url in urls:
        parsed = urlparse(raw_url if raw_url.startswith("http") else "http://" + raw_url)
        domain = normalize_domain(parsed.netloc)
        cur.execute("SELECT 1 FROM allowed_domains WHERE domain=?", (domain,))
        if cur.fetchone():
            return
        cur.execute("SELECT 1 FROM blocked_domains WHERE domain=?", (domain,))
        if cur.fetchone():
            try:
                await update.message.delete()
            except:
                pass
            await send_private_log(context, f"🚨 BLOCKED LINK deleted: {raw_url} by {update.effective_user.full_name} ({update.effective_user.id}) in chat {update.effective_chat.id}")
            return
        if raw_url.startswith("http"):
            try:
                await update.message.delete()
            except:
                pass
            await send_private_log(context, f"🚨 External link removed: {raw_url} from {update.effective_user.full_name} ({update.effective_user.id}) in chat {update.effective_chat.id}")
            return

# moderation reply-panel & postpanel
async def moderate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMINS:
        await update.message.reply_text("Only admin can moderate.")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a user's message then run /moderate")
        return
    target = update.message.reply_to_message.from_user
    chat_id = update.effective_chat.id
    keyboard = [
        [InlineKeyboardButton("Mute", callback_data=f"mod:mute:{chat_id}:{target.id}"),
         InlineKeyboardButton("Unmute", callback_data=f"mod:unmute:{chat_id}:{target.id}")],
        [InlineKeyboardButton("Warn +1", callback_data=f"mod:warn:{chat_id}:{target.id}"),
         InlineKeyboardButton("Reset", callback_data=f"mod:reset:{chat_id}:{target.id}")],
        [InlineKeyboardButton("Userinfo (log)", callback_data=f"mod:userinfo:{target.id}")]
    ]
    await update.message.reply_text(f"Moderation for {target.full_name}", reply_markup=InlineKeyboardMarkup(keyboard))

# postpanel: admin replies to a user and posts persistent panel (pin by admin if desired)
async def postpanel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMINS:
        await update.message.reply_text("Admin only.")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a user's message then run /postpanel")
        return
    target = update.message.reply_to_message.from_user
    chat_id = update.effective_chat.id
    keyboard = [
        [InlineKeyboardButton("Mute", callback_data=f"mod:mute:{chat_id}:{target.id}"),
         InlineKeyboardButton("Unmute", callback_data=f"mod:unmute:{chat_id}:{target.id}")],
        [InlineKeyboardButton("Warn +1", callback_data=f"mod:warn:{chat_id}:{target.id}"),
         InlineKeyboardButton("Reset", callback_data=f"mod:reset:{chat_id}:{target.id}")],
        [InlineKeyboardButton("Userinfo (log)", callback_data=f"mod:userinfo:{target.id}")]
    ]
    await update.message.reply_text(f"Admin Panel — {target.full_name}", reply_markup=InlineKeyboardMarkup(keyboard))

# callback handler for mod actions
async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    caller = q.from_user.id
    if caller not in ADMINS:
        await q.edit_message_text("Only admin may use these buttons.")
        return
    parts = data.split(":")
    if parts[0] != "mod":
        await q.edit_message_text("Unknown action")
        return
    action = parts[1]
    if action in ("mute","unmute","warn","reset"):
        chat_id = int(parts[2]); target_id = int(parts[3])
        if action == "mute":
            mute_db(chat_id, target_id); await q.edit_message_text("User muted (DB)."); await send_private_log(context, f"🔇 Muted {target_id} in {chat_id} by {caller}")
        elif action == "unmute":
            unmute_db(chat_id, target_id); await q.edit_message_text("User unmuted (DB)."); await send_private_log(context, f"🔊 Unmuted {target_id} in {chat_id} by {caller}")
        elif action == "warn":
            cnt = get_warning_count(chat_id, target_id) + 1; set_warning_count(chat_id, target_id, cnt)
            await q.edit_message_text(f"Warning added. Count = {cnt}"); await send_private_log(context, f"⚠️ Warning for {target_id} in {chat_id}. Now {cnt}")
        elif action == "reset":
            reset_warnings(chat_id, target_id); await q.edit_message_text("Warnings reset."); await send_private_log(context, f"🔁 Warnings reset for {target_id} in {chat_id}")
    elif action == "userinfo":
        tid = int(parts[2])
        cur.execute("SELECT user_id, name, username, language FROM users WHERE user_id=?", (tid,))
        r = cur.fetchone()
        if not r:
            await q.edit_message_text("User not in DB.")
            return
        user_id, name, username, lang = r
        text = f"📌 USER INFO\nName: {name}\nUsername: @{username if username else 'None'}\nID: {user_id}\nLang: {lang}"
        await send_private_log(context, text)
        await q.edit_message_text("User info sent to private log")
    else:
        await q.edit_message_text("Unknown moderation action")

# quick menu/panel
async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("Health", callback_data="menu:health")],
        [InlineKeyboardButton("Search help", callback_data="menu:search")],
        [InlineKeyboardButton("Moderate (reply)", callback_data="menu:moderate_help")],
        [InlineKeyboardButton("Domains", callback_data="menu:domains")],
    ]
    await update.message.reply_text("Quick menu (pin this message for bottom accessibility):", reply_markup=InlineKeyboardMarkup(kb))

async def menu_cb_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    parts = (q.data or "").split(":")
    if len(parts) < 2:
        await q.edit_message_text("Unknown action"); return
    a = parts[1]
    if a == "health":
        await q.edit_message_text(f"Bot alive. Uptime {int(time.time()-start_time)}s")
    elif a == "search":
        await q.edit_message_text("Use /search <query>. Then /choose <number>.")
    elif a == "moderate_help":
        await q.edit_message_text("Reply to a user's message, then run /moderate or /postpanel")
    elif a == "domains":
        allowed, blocked = list_domains(); await q.edit_message_text("Allowed: "+(", ".join(allowed) if allowed else "— none —")+"\nBlocked: "+(", ".join(blocked) if blocked else "— none —"))
    else:
        await q.edit_message_text("Unknown menu action")

# health command
async def health_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"✅ Bot healthy — uptime {int(time.time() - start_time)}s")

# error handler
async def error_handler(update, context):
    logging.error("Bot error: %s", context.error)

# ----- main -----
def main():
    keep_alive()
    app = ApplicationBuilder().token(TOKEN).build()

    async def on_startup(application):
        try:
            await application.bot.delete_webhook(drop_pending_updates=True)
        except Exception:
            logging.exception("delete_webhook failed")

    app.add_error_handler(error_handler)

    # handlers
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_member))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_all_messages), 0)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_links), 1)
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, track_users), 2)

    # commands
    app.add_handler(CommandHandler("userinfo", userinfo_cmd))
    app.add_handler(CommandHandler("searchuser", searchuser_cmd))
    app.add_handler(CommandHandler("getid", getid_cmd))
    app.add_handler(CommandHandler("search", search_cmd))
    app.add_handler(CommandHandler("choose", choose_cmd))
    app.add_handler(CommandHandler("moderate", moderate_cmd))
    app.add_handler(CommandHandler("postpanel", postpanel_cmd))
    app.add_handler(CommandHandler("menu", menu_cmd))
    app.add_handler(CommandHandler("panel", menu_cmd))
    app.add_handler(CommandHandler("health", health_cmd))

    app.add_handler(CommandHandler("allow", allow_cmd))
    app.add_handler(CommandHandler("block", block_cmd))
    app.add_handler(CommandHandler("listdomains", listdomains_cmd))

    app.add_handler(CommandHandler("mute", mute_cmd))
    app.add_handler(CommandHandler("unmute", unmute_cmd))
    app.add_handler(CommandHandler("mutelist", mutelist_cmd))

    # callbacks
    app.add_handler(CallbackQueryHandler(callback_query_handler, pattern=r"^mod:"))
    app.add_handler(CallbackQueryHandler(menu_cb_handler, pattern=r"^menu:"))

    print("Bot started")
    app.run_polling(drop_pending_updates=True, post_init=on_startup)

if __name__ == "__main__":
    main()
