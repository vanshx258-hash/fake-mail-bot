import sqlite3
import logging
import random
import string
import re
import os
import threading
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, CallbackQueryHandler, ConversationHandler
)
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# ================== CONFIG ==================
BOT_TOKEN = os.getenv("BOT_TOKEN", "9259442048:AAEZd8_NvInXdUlPw3YHuSck-Cmo0Ofi7Gc")
API_ID = int(os.getenv("API_ID", "38746329"))
API_HASH = os.getenv("API_HASH", "dc6d3dd0de462ed07952a64c3253c437")
TARGET_BOT = "fakemailbot"

owner1_str = os.getenv("OWNER_ID_1", "7729056358")
owner2_str = os.getenv("OWNER_ID_2", "8808192812")
BASE_OWNERS = [int(o) for o in [owner1_str, owner2_str] if o.isdigit()]

(ASK_PHONE, ASK_OTP, ASK_2FA, ASK_SAVE_MAIL, ASK_GROUP_LINK) = range(5)

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ================== FLASK ==================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

# ================== DATABASE ==================
DB_PATH = "fake_mail.db"

def init_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, phone TEXT, session_string TEXT, is_banned INTEGER DEFAULT 0)")
    c.execute("CREATE TABLE IF NOT EXISTS saved_mails (id INTEGER PRIMARY KEY AUTOINCREMENT, email_address TEXT UNIQUE)")
    c.execute("CREATE TABLE IF NOT EXISTS user_mails (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, email_address TEXT UNIQUE)")
    c.execute("CREATE TABLE IF NOT EXISTS transfers (transfer_id TEXT PRIMARY KEY, email_address TEXT, from_user INTEGER, to_user INTEGER)")
    c.execute("CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS owners (user_id INTEGER PRIMARY KEY)")
    
    try: c.execute("ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0")
    except sqlite3.OperationalError: pass 

    for owner in BASE_OWNERS:
        c.execute("INSERT OR IGNORE INTO owners (user_id) VALUES (?)", (owner,))
    
    # Aapki backup emails
    backup_emails = ["rokjbvq@hi2.in", "jjeznz@telegmail.com", "hzmmyg@hi2.in", "yxnldyc@hi2.in"]
    for email in backup_emails:
        try: c.execute("INSERT INTO saved_mails (email_address) VALUES (?)", (email,))
        except sqlite3.IntegrityError: pass

    conn.commit()
    conn.close()

init_db()

def db_exec(query, params=()):
    conn = sqlite3.connect(DB_PATH, timeout=10)
    c = conn.cursor()
    try:
        c.execute(query, params)
        conn.commit()
        res = c.fetchall()
    finally:
        conn.close()
    return res

def get_config(key, default=None):
    res = db_exec("SELECT value FROM config WHERE key=?", (key,))
    return res[0][0] if res else default

def get_all_owners():
    res = db_exec("SELECT user_id FROM owners")
    return [row[0] for row in res] if res else []

active_userbots = {}
temp_clients = {}
EMAIL_REGEX = re.compile(r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})')

def find_user_by_email(text):
    match = EMAIL_REGEX.search(text)
    if match:
        email = match.group(1)
        res = db_exec("SELECT user_id FROM user_mails WHERE email_address=?", (email,))
        if res: return res[0][0]
    res = db_exec("SELECT user_id FROM user_mails ORDER BY id DESC LIMIT 1")
    return res[0][0] if res else None

# ================== USERBOT (OTP SENDER) ==================
async def start_userbot(user_id, session_str):
    if user_id in active_userbots:
        try: await active_userbots[user_id].disconnect()
        except: pass

    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    await client.connect()
    active_userbots[user_id] = client
    logger.info(f"✅ Userbot connected for user {user_id}")

    @client.on(events.NewMessage(incoming=True))
    async def otp_listener(event):
        try:
            if not event.is_private: return
            sender = await event.get_sender()
            if not sender: return
            
            uname = (getattr(sender, "username", "") or "").lower()
            if uname != TARGET_BOT.lower(): return

            full_text = event.message.message or ""
            if not full_text: return

            logger.info("🎯 Target bot message detected!")
            target_user_id = find_user_by_email(full_text)

            if target_user_id:
                try:
                    from telegram import Bot
                    bot = Bot(BOT_TOKEN)
                    # OTP direct user ko bhejo (bina heading)
                    await bot.send_message(chat_id=target_user_id, text=full_text)
                    logger.info(f"✅ OTP sent to user {target_user_id}")
                    await bot.close()
                except Exception as e:
                    logger.error(f"User send failed: {e}")
        except Exception as e:
            logger.error(f"otp_listener error: {e}", exc_info=True)

# ================== BOT COMMANDS ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    res = db_exec("SELECT user_id FROM users WHERE user_id=?", (user.id,))
    if not res:
        db_exec("INSERT INTO users (user_id) VALUES (?)", (user.id,))
    
    text = "Welcome to @FakeMailss_Bot!\nSend /generate to get your fakemail address."
    await update.message.reply_text(text)
    return ConversationHandler.END

async def generate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    res = db_exec("SELECT phone FROM users WHERE user_id=?", (user_id,))
    if not res or not res[0][0]:
        kb = [[KeyboardButton("Share Contact", request_contact=True)]]
        return await update.message.reply_text("Share contact first:", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True, one_time_keyboard=True))
        
    kb = [
        [InlineKeyboardButton("@hi2.in", callback_data="domain_hi2")],
        [InlineKeyboardButton("@telegmail.com", callback_data="domain_tg")]
    ]
    await update.message.reply_text("Select domain:", reply_markup=InlineKeyboardMarkup(kb))

async def domain_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    domain = "hi2.in" if query.data == "domain_hi2" else "telegmail.com"

    saved = db_exec("SELECT id, email_address FROM saved_mails LIMIT 1")
    if saved:
        mail_id, email_address = saved[0]
        db_exec("DELETE FROM saved_mails WHERE id=?", (mail_id,))
    else:
        random_str = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
        email_address = f"{random_str}@{domain}"

    db_exec("INSERT INTO user_mails (user_id, email_address) VALUES (?,?)", (user_id, email_address))
    await query.edit_message_text(f"Your new fakemail address is {email_address}\nSend /id to see list.")

async def id_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    mails = db_exec("SELECT id, email_address FROM user_mails WHERE user_id=?", (user_id,))
    if not mails: return await update.message.reply_text("No emails generated.")
    text = "Your Emails:\n"
    for i, m in enumerate(mails, 1): text += f"{i}. {m[1]} | /delete_{m[0]}\n"
    await update.message.reply_text(text)

async def contact_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact = update.message.contact
    if contact:
        db_exec("UPDATE users SET phone=? WHERE user_id=?", (contact.phone_number, update.effective_user.id))
        await update.message.reply_text("Number Saved! Now /generate")

# ================== OWNER / ADMAIL ==================
async def ask_add_mail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in get_all_owners(): return ConversationHandler.END
    await update.message.reply_text("Send emails (comma separated or new lines) to add 20 at once:")
    return ASK_SAVE_MAIL

async def save_mail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_text = update.message.text.strip()
    # Comma ya newline se split karo
    emails = re.split(r'[,\n]+', raw_text)
    added = 0
    for email in emails:
        email = email.strip()
        if not email: continue
        try:
            db_exec("INSERT INTO saved_mails (email_address) VALUES (?)", (email,))
            added += 1
        except sqlite3.IntegrityError:
            pass # Pehle se hai
    await update.message.reply_text(f"✅ {added} emails added successfully!")
    return ConversationHandler.END

async def cancel_conv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Canceled.")
    return ConversationHandler.END

async def set_group_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in get_all_owners(): return ConversationHandler.END
    await update.message.reply_text("Send group link/username:")
    return ASK_GROUP_LINK

async def save_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db_exec("INSERT OR REPLACE INTO config (key, value) VALUES (?,?)", ("target_group", update.message.text.strip()))
    await update.message.reply_text("Group set!")
    return ConversationHandler.END

async def owner_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in get_all_owners(): return
    mails = db_exec("SELECT email_address FROM saved_mails")
    grp = get_config("target_group", "Not Set")
    text = f"👑 OWNER PANEL\nGroup: {grp}\nTotal Mails: {len(mails)}\n\n"
    await update.message.reply_text(text)

# ================== USERBOT LOGIN ==================
async def add_acc_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in get_all_owners(): return ConversationHandler.END
    await update.message.reply_text("Enter Phone Number (+91...):")
    return ASK_PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    uid = update.effective_user.id
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.connect()
    try:
        sent = await client.send_code_request(phone)
        temp_clients[uid] = {'client': client, 'hash': sent.phone_code_hash, 'phone': phone}
        await update.message.reply_text("Enter OTP (1 2 3 4 5):")
        return ASK_OTP
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")
        return ConversationHandler.END

async def get_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    otp = update.message.text.strip().replace(" ", "").replace("-", "")
    try:
        await temp_clients[uid]['client'].sign_in(phone=temp_clients[uid]['phone'], code=otp, phone_code_hash=temp_clients[uid]['hash'])
        session = temp_clients[uid]['client'].session.save()
        db_exec("INSERT OR REPLACE INTO users (user_id, phone, session_string) VALUES (?,?,?)", (uid, temp_clients[uid]['phone'], session))
        await start_userbot(uid, session)
        await update.message.reply_text("✅ Userbot Active! OTPs will be delivered.")
        return ConversationHandler.END
    except Exception as e:
        if "Two-step" in str(e):
            await update.message.reply_text("Enter 2FA Password:")
            return ASK_2FA
        await update.message.reply_text(f"Login Failed: {e}")
        return ConversationHandler.END

async def get_2fa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    try:
        await temp_clients[uid]['client'].sign_in(password=update.message.text.strip())
        session = temp_clients[uid]['client'].session.save()
        db_exec("INSERT OR REPLACE INTO users (user_id, phone, session_string) VALUES (?,?,?)", (uid, temp_clients[uid]['phone'], session))
        await start_userbot(uid, session)
        await update.message.reply_text("✅ Userbot Active via 2FA!")
    except Exception as e:
        await update.message.reply_text(f"Failed: {e}")
    return ConversationHandler.END

# ================== MAIN ==================
def main():
    threading.Thread(target=run_flask, daemon=True).start()
    app_bot = Application.builder().token(BOT_TOKEN).build()

    login_conv = ConversationHandler(
        entry_points=[CommandHandler("phone", add_acc_start)],
        states={ASK_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)], ASK_OTP: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_otp)], ASK_2FA: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_2fa)]}, fallbacks=[]
    )
    mail_conv = ConversationHandler(
        entry_points=[CommandHandler("addmail", ask_add_mail)],
        states={ASK_SAVE_MAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_mail)]}, fallbacks=[CommandHandler("cancel", cancel_conv)]
    )
    group_conv = ConversationHandler(
        entry_points=[CommandHandler("setgroup", set_group_cmd)],
        states={ASK_GROUP_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_group)]}, fallbacks=[]
    )

    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("generate", generate_cmd))
    app_bot.add_handler(CommandHandler("id", id_cmd))
    app_bot.add_handler(CommandHandler("owner", owner_panel))
    app_bot.add_handler(login_conv)
    app_bot.add_handler(mail_conv)
    app_bot.add_handler(group_conv)
    app_bot.add_handler(MessageHandler(filters.CONTACT, contact_handler))
    app_bot.add_handler(CallbackQueryHandler(domain_selected, pattern="^domain_"))

    logger.info("Bot started!")
    app_bot.run_polling(allowed_updates=Update.ALL_TYPES, close_loop=False)

if __name__ == "__main__":
    main()
