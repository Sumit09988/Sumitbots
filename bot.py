import os
import asyncio
import json
import requests
import random
import string
from datetime import datetime, time, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import firebase_admin
from firebase_admin import credentials, db

# ============ CONFIG ============
TOKEN = "8785204698:AAFtQfVU2vA1Vhi6wbvQOzw6HSNFsOhUBk4"
FORCE_CHANNEL = "https://t.me/SUMITNETW0RK"
FORCE_CHANNEL_USERNAME = "@SUMITNETW0RK"
ADMIN_IDS = [7515864015]
FIREBASE_CRED = os.getenv("FIREBASE_CREDENTIALS")
FIREBASE_DB_URL = os.getenv("FIREBASE_DB_URL", "https://your-db.firebaseio.com/")
SMS_API_URL = os.getenv("SMS_API_URL", "https://api.textlocal.in/send/")
SMS_API_KEY = os.getenv("SMS_API_KEY", "your_api_key")
DAILY_CREDITS = 50
REFER_BONUS = 10
GIFT_CODE_LENGTH = 12

# ============ FIREBASE INIT (Main) ============
if FIREBASE_CRED:
    try:
        cred_dict = json.loads(FIREBASE_CRED)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred, {'databaseURL': FIREBASE_DB_URL})
        print("✅ Main Firebase connected!")
    except Exception as e:
        print(f"❌ Firebase init error: {e}")
        class FakeDB:
            def __init__(self):
                self.data = {}
            def child(self, path):
                return self
            def get(self):
                return None
            def set(self, value):
                pass
            def push(self, value):
                return None
            def update(self, value):
                pass
        db = FakeDB()
else:
    print("⚠️ Main Firebase credentials missing. Using local fallback.")
    class FakeDB:
        def __init__(self):
            self.data = {}
        def child(self, path):
            return self
        def get(self):
            return None
        def set(self, value):
            pass
        def push(self, value):
            return None
        def update(self, value):
            pass
    db = FakeDB()

# ============ DATABASE HELPERS (Main) ============
def get_user_data(user_id):
    ref = db.child(f"users/{user_id}")
    data = ref.get()
    if not data:
        return {"credits": DAILY_CREDITS, "history": [], "referrals": 0, "referred_by": None, "last_daily": None}
    return data

def update_user_data(user_id, data):
    ref = db.child(f"users/{user_id}")
    ref.set(data)

def log_sms_job(user_id, job_id, data):
    ref = db.child(f"jobs/{user_id}/{job_id}")
    ref.set(data)

def get_all_users():
    ref = db.child("users")
    return ref.get() or {}

def generate_gift_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=GIFT_CODE_LENGTH))

def save_gift_code(code, amount):
    ref = db.child(f"gift_codes/{code}")
    ref.set({"amount": amount, "used": False, "used_by": None})

def redeem_gift_code(user_id, code):
    ref = db.child(f"gift_codes/{code}")
    data = ref.get()
    if not data or data.get("used", False):
        return None, "Invalid or already used code."
    ref.update({"used": True, "used_by": user_id})
    return data.get("amount"), None

# ============ MULTI-FIREBASE HELPERS ============
def get_firebase_configs():
    ref = db.child("firebase_configs")
    configs = ref.get()
    return configs or {}

def add_firebase_config(name, cred_json, db_url):
    ref = db.child("firebase_configs")
    new_ref = ref.push()
    new_ref.set({
        "name": name,
        "credentials": cred_json,
        "db_url": db_url,
        "added_at": datetime.now().isoformat()
    })
    return new_ref.key

def get_total_devices_all_firebase():
    configs = get_firebase_configs()
    total = 0
    for key, config in configs.items():
        try:
            cred_dict = json.loads(config["credentials"])
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred, {'databaseURL': config["db_url"]}, name=key)
            device_ref = db.reference("/device_count", app=firebase_admin.get_app(key))
            count = device_ref.get()
            if count and isinstance(count, int):
                total += count
            else:
                users_ref = db.reference("/users", app=firebase_admin.get_app(key))
                users = users_ref.get()
                if users:
                    total += len(users)
        except Exception as e:
            print(f"Error reading Firebase {key}: {e}")
    return total

# ============ DAILY CREDITS RESET ============
async def reset_daily_credits(context: ContextTypes.DEFAULT_TYPE = None):
    try:
        users = get_all_users()
        if not users:
            return
        count = 0
        for uid in users:
            try:
                user_data = users[uid]
                user_data['credits'] = user_data.get('credits', 0) + DAILY_CREDITS
                user_data['last_daily'] = datetime.now().isoformat()
                update_user_data(int(uid), user_data)
                count += 1
            except Exception as e:
                print(f"Error resetting credits for {uid}: {e}")
        print(f"✅ Daily credits reset for {count} users at {datetime.now()}")
    except Exception as e:
        print(f"❌ Daily reset error: {e}")

async def check_and_add_daily_credits(user_id):
    user_data = get_user_data(user_id)
    last_daily = user_data.get('last_daily')
    today = datetime.now().date()
    if last_daily:
        last_date = datetime.fromisoformat(last_daily).date()
        if last_date == today:
            return user_data
    user_data['credits'] = user_data.get('credits', 0) + DAILY_CREDITS
    user_data['last_daily'] = datetime.now().isoformat()
    update_user_data(user_id, user_data)
    return user_data

# ============ BOT ============
bot_app = ApplicationBuilder().token(TOKEN).build()

# ============ KEYBOARDS ============
def main_keyboard(user_id):
    buttons = [
        [InlineKeyboardButton("📱 Send SMS", callback_data='send_sms')],
        [InlineKeyboardButton("💰 Credits", callback_data='credits')],
        [InlineKeyboardButton("🔄 Redeem", callback_data='redeem')],
        [InlineKeyboardButton("👥 Refer", callback_data='refer')],
        [InlineKeyboardButton("📊 Stats", callback_data='stats')],
        [InlineKeyboardButton("📜 My SMS History", callback_data='history')],
        [InlineKeyboardButton("💳 Buy Credits", callback_data='buy_credits')],
        [InlineKeyboardButton("ℹ️ Info", callback_data='info')],
    ]
    if user_id in ADMIN_IDS:
        buttons.append([InlineKeyboardButton("📢 Broadcast", callback_data='broadcast')])
        buttons.append([InlineKeyboardButton("🎁 Generate Gift Code", callback_data='gen_gift')])
        buttons.append([InlineKeyboardButton("➕ Add Firebase", callback_data='add_firebase')])
        buttons.append([InlineKeyboardButton("📊 Total Devices", callback_data='total_devices')])
    return InlineKeyboardMarkup(buttons)

def speed_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ Fast", callback_data='speed_fast')],
        [InlineKeyboardButton("⏳ Medium", callback_data='speed_medium')],
        [InlineKeyboardButton("🐢 Slow", callback_data='speed_slow')],
    ])

def count_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("100", callback_data='count_100')],
        [InlineKeyboardButton("500", callback_data='count_500')],
        [InlineKeyboardButton("1000", callback_data='count_1000')],
        [InlineKeyboardButton("Custom", callback_data='count_custom')]
    ])

def stop_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🛑 Stop", callback_data='stop_sms')]])

def force_join_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Join Channel", url=FORCE_CHANNEL)],
        [InlineKeyboardButton("✅ I Have Joined", callback_data='check_join')]
    ])

# ============ FORCE JOIN ============
async def is_member(user_id, context):
    try:
        member = await context.bot.get_chat_member(FORCE_CHANNEL_USERNAME, user_id)
        if member.status in ['left', 'kicked']:
            return False
        return True
    except:
        return False

# ============ SMS SENDING ENGINE ============
async def send_sms_worker(context, user_id, job_id, number, message, speed, count):
    sent = 0
    failed = 0
    stop_flag = False

    delays = {'fast': 0.15, 'medium': 0.6, 'slow': 1.2}
    delay = delays.get(speed, 0.5)

    progress_msg = await context.bot.send_message(
        chat_id=user_id,
        text=f"⏳ **Sending SMS...**\n\nTarget: `{number}`\nSent: 0 / {count}\nFailed: 0",
        reply_markup=stop_keyboard(),
        parse_mode='Markdown'
    )

    for i in range(count):
        if context.user_data.get(f'stop_{job_id}', False):
            stop_flag = True
            break

        try:
            resp = requests.post(
                SMS_API_URL,
                data={
                    'apikey': SMS_API_KEY,
                    'numbers': number,
                    'message': message,
                    'sender': 'TXTLCL'
                },
                timeout=5
            )
            if resp.status_code == 200 and resp.json().get('status') == 'success':
                sent += 1
            else:
                failed += 1
        except:
            failed += 1

        if (i+1) % 5 == 0 or i == count-1:
            try:
                await progress_msg.edit_text(
                    f"⏳ **Sending SMS...**\n\nTarget: `{number}`\nSent: {sent} / {count}\nFailed: {failed}",
                    reply_markup=stop_keyboard() if not stop_flag else None,
                    parse_mode='Markdown'
                )
            except:
                pass

        await asyncio.sleep(delay)

    status = "✅ **Completed!**" if not stop_flag else "🛑 **Stopped by user**"
    await progress_msg.edit_text(
        f"{status}\n\nTarget: `{number}`\nSent: {sent}\nFailed: {failed}\nTotal: {count}\nDuration: ~{count * delay:.0f}s",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Home", callback_data='home')]]),
        parse_mode='Markdown'
    )

    user_data = get_user_data(user_id)
    new_credits = max(0, user_data.get('credits', 0) - sent)
    user_data['credits'] = new_credits
    update_user_data(user_id, user_data)

    job_data = {
        'number': number,
        'message': message,
        'speed': speed,
        'count': count,
        'sent': sent,
        'failed': failed,
        'status': 'stopped' if stop_flag else 'completed',
        'timestamp': datetime.now().isoformat(),
        'credits_used': sent,
        'credits_remaining': new_credits
    }
    log_sms_job(user_id, job_id, job_data)

    if f'stop_{job_id}' in context.user_data:
        del context.user_data[f'stop_{job_id}']

# ============ HANDLERS ============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id

    if not await is_member(user_id, context):
        await update.message.reply_text(
            "⚠️ **Please join our channel first!**\n\nClick the button below to join, then click 'I Have Joined'.",
            reply_markup=force_join_keyboard(),
            parse_mode='Markdown'
        )
        return

    if get_user_data(user_id) == {"credits": DAILY_CREDITS, "history": [], "referrals": 0, "referred_by": None, "last_daily": None}:
        update_user_data(user_id, {"credits": DAILY_CREDITS, "history": [], "referrals": 0, "referred_by": None, "last_daily": datetime.now().isoformat()})

    user_data = await check_and_add_daily_credits(user_id)
    credits = user_data.get('credits', 0)

    await update.message.reply_text(
        f"**🚀 SMS Blast Bot v3.0-ULTRA**\n\n"
        f"👤 Role: {'ADMIN' if user_id in ADMIN_IDS else 'FREE'}\n"
        f"💰 Credits: `{credits}`\n"
        f"📊 Uses: {len(user_data.get('history', []))}\n"
        f"🔌 APIs: 15 online\n"
        f"📱 Scanner: {random.randint(300, 500)} devices | Updated 34s ago\n"
        f"✨ Daily Free Credits: `{DAILY_CREDITS}` (resets at 11:59 PM)\n\n"
        f"Tap **Send SMS** to start",
        reply_markup=main_keyboard(user_id),
        parse_mode='Markdown'
    )

async def check_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if await is_member(user_id, context):
        await query.edit_message_text(
            "✅ **Verified!** You can now use the bot.\n\nClick /start to begin.",
            reply_markup=main_keyboard(user_id),
            parse_mode='Markdown'
        )
    else:
        await query.edit_message_text(
            "❌ **Still not joined!**\n\nPlease join the channel first:",
            reply_markup=force_join_keyboard(),
            parse_mode='Markdown'
        )

async def send_sms_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_data = get_user_data(user_id)
    if user_data.get('credits', 0) <= 0:
        await query.edit_message_text(
            "❌ **Insufficient Credits!**\n\nYou get 50 free credits daily at midnight.\nOr buy more using /buy or redeem a gift code.",
            reply_markup=main_keyboard(user_id),
            parse_mode='Markdown'
        )
        return
    context.user_data['step'] = 'number'
    await query.edit_message_text(
        "**📱 Step 1/4 – Number**\n\nPlease enter the target phone number (with country code):\nExample: `+918538091022`",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data='cancel_sms')]]),
        parse_mode='Markdown'
    )

async def cancel_sms(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text("❌ Cancelled.", reply_markup=main_keyboard(query.from_user.id))

async def handle_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('step') != 'number':
        return
    number = update.message.text.strip()
    if not number.startswith('+') or not number[1:].isdigit():
        await update.message.reply_text("❌ Invalid number! Use format: +919876543210")
        return
    context.user_data['number'] = number
    context.user_data['step'] = 'message'
    await update.message.reply_text(
        "**📝 Step 2/4 – Message**\n\nType your custom SMS message:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data='cancel_sms')]]),
        parse_mode='Markdown'
    )

async def handle_message_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('step') == 'message':
        msg = update.message.text.strip()
        if not msg:
            await update.message.reply_text("❌ Message cannot be empty!")
            return
        context.user_data['message'] = msg
        context.user_data['step'] = 'speed'
        await update.message.reply_text(
            "**⚡ Step 3/4 – Speed**\n\nSelect sending speed:",
            reply_markup=speed_keyboard(),
            parse_mode='Markdown'
        )

async def speed_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    speed = query.data.replace('speed_', '')
    context.user_data['speed'] = speed
    context.user_data['step'] = 'count'
    await query.edit_message_text(
        "**🔢 Step 4/4 – Count**\n\nHow many SMS to send? (max 10000)",
        reply_markup=count_keyboard(),
        parse_mode='Markdown'
    )

async def count_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == 'count_custom':
        context.user_data['step'] = 'custom_count'
        await query.edit_message_text(
            "Enter custom count (max 10000):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data='cancel_sms')]]),
            parse_mode='Markdown'
        )
        return
    count = int(query.data.split('_')[1])
    context.user_data['count'] = count
    await start_sms(update, context)

async def handle_custom_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('step') != 'custom_count':
        return
    try:
        count = int(update.message.text.strip())
        if count <= 0 or count > 10000:
            raise ValueError
        context.user_data['count'] = count
        context.user_data['step'] = None
        await start_sms(update, context)
    except:
        await update.message.reply_text("❌ Invalid count! Enter a number between 1 and 10000.")

async def start_sms(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    number = context.user_data['number']
    message = context.user_data['message']
    speed = context.user_data['speed']
    count = context.user_data['count']

    user_data = get_user_data(user_id)
    if user_data.get('credits', 0) < count:
        await update.message.reply_text(
            f"❌ **Insufficient Credits!**\n\nYou need `{count}` credits but you have `{user_data.get('credits', 0)}`.\n\nYou get 50 free credits daily at midnight.",
            reply_markup=main_keyboard(user_id),
            parse_mode='Markdown'
        )
        return

    job_id = f"job_{datetime.now().strftime('%Y%m%d%H%M%S')}_{user_id}"
    context.user_data['job_id'] = job_id
    context.user_data[f'stop_{job_id}'] = False

    asyncio.create_task(send_sms_worker(context, user_id, job_id, number, message, speed, count))

    await update.message.reply_text(
        f"✅ **SMS Blast Started!**\n\nTarget: `{number}`\nCount: {count}\nSpeed: {speed}\n\nProgress will be updated here.",
        reply_markup=stop_keyboard(),
        parse_mode='Markdown'
    )

async def stop_sms_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    job_id = context.user_data.get('job_id')
    if job_id:
        context.user_data[f'stop_{job_id}'] = True
        await query.edit_message_text("🛑 **Stopping...** Please wait.", reply_markup=None)
    else:
        await query.edit_message_text("❌ No active job.")

async def credits_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = get_user_data(user_id)
    credits = data.get('credits', 0)
    await query.edit_message_text(
        f"💰 **Your Credits**\n\nYou have `{credits}` credits.\n\n✨ Daily Free: `{DAILY_CREDITS}` credits (resets at 11:59 PM)\n💳 To buy more, use /buy or redeem a gift code.\n\n👨‍💻 Developer: @T4HKR",
        reply_markup=main_keyboard(user_id),
        parse_mode='Markdown'
    )

async def redeem_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    await query.edit_message_text(
        "🎁 **Redeem Gift Code**\n\nEnter the gift code you received:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data='cancel_sms')]]),
        parse_mode='Markdown'
    )
    context.user_data['redeem_mode'] = True

async def handle_redeem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('redeem_mode'):
        return
    code = update.message.text.strip().upper()
    user_id = update.effective_user.id
    amount, error = redeem_gift_code(user_id, code)
    if error:
        await update.message.reply_text(f"❌ {error}", reply_markup=main_keyboard(user_id))
    else:
        user_data = get_user_data(user_id)
        user_data['credits'] = user_data.get('credits', 0) + amount
        update_user_data(user_id, user_data)
        await update.message.reply_text(
            f"✅ **Redeemed Successfully!**\n\nYou got `{amount}` credits.\nNew balance: `{user_data['credits']}`",
            reply_markup=main_keyboard(user_id),
            parse_mode='Markdown'
        )
    context.user_data['redeem_mode'] = False

async def refer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_data = get_user_data(user_id)
    ref_count = user_data.get('referrals', 0)
    bot_username = (await context.bot.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    await query.edit_message_text(
        f"👥 **Refer & Earn**\n\nEarn `{REFER_BONUS}` credits for each friend who joins using your link!\n\nYour referral link:\n`{ref_link}`\n\nTotal Referrals: {ref_count}",
        reply_markup=main_keyboard(user_id),
        parse_mode='Markdown'
    )

async def start_with_ref(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        ref_id = context.args[0]
        if ref_id.startswith('ref_'):
            ref_user_id = int(ref_id.replace('ref_', ''))
            user_id = update.effective_user.id
            if user_id != ref_user_id:
                ref_data = get_user_data(ref_user_id)
                ref_data['referrals'] = ref_data.get('referrals', 0) + 1
                ref_data['credits'] = ref_data.get('credits', 0) + REFER_BONUS
                update_user_data(ref_user_id, ref_data)
                try:
                    await context.bot.send_message(
                        chat_id=ref_user_id,
                        text=f"👥 **New Referral!**\n\nUser `{update.effective_user.first_name}` joined using your link!\nYou earned `{REFER_BONUS}` credits!",
                        parse_mode='Markdown'
                    )
                except:
                    pass
    await start(update, context)

# ============ ADMIN: GENERATE GIFT CODE ============
async def gen_gift_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if user_id not in ADMIN_IDS:
        await query.edit_message_text("❌ Access Denied.")
        return
    await query.edit_message_text(
        "🎁 **Generate Gift Code**\n\nEnter the amount of credits for this gift code:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data='cancel_sms')]]),
        parse_mode='Markdown'
    )
    context.user_data['gen_gift_mode'] = True

async def handle_gen_gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('gen_gift_mode'):
        return
    try:
        amount = int(update.message.text.strip())
        if amount <= 0:
            raise ValueError
        code = generate_gift_code()
        save_gift_code(code, amount)
        await update.message.reply_text(
            f"✅ **Gift Code Generated!**\n\nCode: `{code}`\nAmount: `{amount}` credits\n\nSend this code to users.",
            reply_markup=main_keyboard(update.effective_user.id),
            parse_mode='Markdown'
        )
    except:
        await update.message.reply_text("❌ Invalid amount! Enter a positive number.")
    context.user_data['gen_gift_mode'] = False

# ============ ADMIN: ADD FIREBASE ============
async def add_firebase_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if user_id not in ADMIN_IDS:
        await query.edit_message_text("❌ Access Denied.")
        return
    await query.edit_message_text(
        "➕ **Add Firebase**\n\nStep 1/3: Enter a **name** for this Firebase (e.g., 'Firebase 2'):",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data='cancel_sms')]]),
        parse_mode='Markdown'
    )
    context.user_data['add_firebase_step'] = 'name'

async def handle_add_firebase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('add_firebase_step'):
        return
    step = context.user_data['add_firebase_step']
    text = update.message.text.strip()
    user_id = update.effective_user.id

    if step == 'name':
        context.user_data['fb_name'] = text
        context.user_data['add_firebase_step'] = 'credentials'
        await update.message.reply_text(
            "Step 2/3: Send the **Firebase credentials JSON** (as a single string).\n\nExample: `{\"type\":\"service_account\",...}`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data='cancel_sms')]]),
            parse_mode='Markdown'
        )
    elif step == 'credentials':
        try:
            json.loads(text)
            context.user_data['fb_credentials'] = text
            context.user_data['add_firebase_step'] = 'db_url'
            await update.message.reply_text(
                "Step 3/3: Send the **Firebase Database URL**:\nExample: `https://your-db.firebaseio.com/`",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data='cancel_sms')]]),
                parse_mode='Markdown'
            )
        except:
            await update.message.reply_text("❌ Invalid JSON! Please send valid Firebase credentials.")
    elif step == 'db_url':
        db_url = text
        name = context.user_data.get('fb_name')
        cred_json = context.user_data.get('fb_credentials')
        if not db_url.startswith('https://') or not db_url.endswith('.firebaseio.com/'):
            await update.message.reply_text("❌ Invalid DB URL! Should be like: `https://your-db.firebaseio.com/`")
            return
        try:
            add_firebase_config(name, cred_json, db_url)
            await update.message.reply_text(
                f"✅ **Firebase Added Successfully!**\n\nName: {name}\nDB URL: {db_url}\n\nTotal Firebase added: {len(get_firebase_configs())}",
                reply_markup=main_keyboard(user_id),
                parse_mode='Markdown'
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Error adding Firebase: {e}")
        context.user_data['add_firebase_step'] = None
        context.user_data.pop('fb_name', None)
        context.user_data.pop('fb_credentials', None)

# ============ ADMIN: TOTAL DEVICES ============
async def total_devices_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if user_id not in ADMIN_IDS:
        await query.edit_message_text("❌ Access Denied.")
        return
    total = get_total_devices_all_firebase()
    configs = get_firebase_configs()
    count_fb = len(configs)
    await query.edit_message_text(
        f"📊 **Total Devices Across All Firebase**\n\n"
        f"Total Devices: `{total}`\n"
        f"Total Firebase Added: `{count_fb}`\n\n"
        f"📌 Main Firebase: `{FIREBASE_DB_URL}`\n"
        f"📌 Added Firebase: {', '.join([c['name'] for c in configs.values()]) if configs else 'None'}\n\n"
        f"👨‍💻 Developer: @T4HKR",
        reply_markup=main_keyboard(user_id),
        parse_mode='Markdown'
    )

# ============ ADMIN: BROADCAST ============
async def broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if user_id not in ADMIN_IDS:
        await query.edit_message_text("❌ Access Denied.")
        return
    await query.edit_message_text(
        "📢 **Broadcast Mode**\n\nSend the message you want to broadcast to all users.\nType /cancel to stop.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data='cancel_sms')]]),
        parse_mode='Markdown'
    )
    context.user_data['broadcast_mode'] = True

async def handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('broadcast_mode'):
        return
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Access Denied.")
        return
    msg = update.message.text
    users = get_all_users()
    if not users:
        await update.message.reply_text("❌ No users to broadcast.")
        return
    success = 0
    for uid in users:
        try:
            await context.bot.send_message(chat_id=int(uid), text=f"📢 **BROADCAST**\n\n{msg}", parse_mode='Markdown')
            success += 1
        except:
            pass
    await update.message.reply_text(f"✅ Broadcast sent to {success} users.")
    context.user_data['broadcast_mode'] = False

# ============ STATS ============
async def stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_data = get_user_data(user_id)
    total_users = len(get_all_users())
    total_jobs = sum(len(u.get('history', [])) for u in get_all_users().values())
    configs = get_firebase_configs()
    fb_count = len(configs)
    await query.edit_message_text(
        f"📊 **Your Stats**\n\n"
        f"Total Users: `{total_users}`\n"
        f"Your Queries: `{len(user_data.get('history', []))}`\n"
        f"Total SMS Sent (all users): `{total_jobs}`\n"
        f"Credits: `{user_data.get('credits', 0)}`\n"
        f"Total Firebase Added: `{fb_count}`\n\n"
        f"👨‍💻 Developer: @T4HKR",
        reply_markup=main_keyboard(user_id),
        parse_mode='Markdown'
    )

# ============ HISTORY ============
async def history_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_data = get_user_data(user_id)
    history = user_data.get('history', [])[-10:]
    if not history:
        await query.edit_message_text("📜 No SMS history yet.", reply_markup=main_keyboard(user_id))
        return
    text = "📜 **Last 10 SMS Jobs**\n\n"
    for job in history:
        text += f"📱 {job.get('number')} | Sent: {job.get('sent')} | Failed: {job.get('failed')} | Status: {job.get('status')}\n"
    await query.edit_message_text(text, reply_markup=main_keyboard(user_id), parse_mode='Markdown')

# ============ INFO ============
async def info_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    await query.edit_message_text(
        "ℹ️ **SMS Blast Bot v3.0-ULTRA**\n\n"
        "🔹 Send bulk SMS with speed control.\n"
        "🔹 Credit system with gift codes.\n"
        "🔹 Refer & Earn credits.\n"
        "🔹 Real-time progress and stop.\n"
        "🔹 Admin panel for broadcasting, gift code generation, and Firebase management.\n"
        "🔹 Daily 50 free credits (resets at 11:59 PM).\n"
        "🔹 Multi-Firebase support with total device count.\n\n"
        "👨‍💻 **Developer:** @T4HKR\n"
        "📌 **Channel:** @SUMITNETW0RK",
        reply_markup=main_keyboard(user_id),
        parse_mode='Markdown'
    )

async def buy_credits_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    await query.edit_message_text(
        "💳 **Buy Credits**\n\nContact @T4HKR to purchase credits.\n\n**Prices:**\n100 credits - ₹99\n500 credits - ₹399\n1000 credits - ₹699\n\n💵 UPI/GPay accepted.",
        reply_markup=main_keyboard(user_id),
        parse_mode='Markdown'
    )

async def home_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    await start(update, context)

# ============ REGISTER ============
bot_app.add_handler(CommandHandler("start", start_with_ref))
bot_app.add_handler(CommandHandler("cancel", lambda u, c: cancel_sms(u, c)))

bot_app.add_handler(CallbackQueryHandler(check_join, pattern='^check_join$'))
bot_app.add_handler(CallbackQueryHandler(send_sms_callback, pattern='^send_sms$'))
bot_app.add_handler(CallbackQueryHandler(cancel_sms, pattern='^cancel_sms$'))
bot_app.add_handler(CallbackQueryHandler(speed_callback, pattern='^speed_'))
bot_app.add_handler(CallbackQueryHandler(count_callback, pattern='^count_'))
bot_app.add_handler(CallbackQueryHandler(stop_sms_callback, pattern='^stop_sms$'))
bot_app.add_handler(CallbackQueryHandler(credits_callback, pattern='^credits$'))
bot_app.add_handler(CallbackQueryHandler(redeem_callback, pattern='^redeem$'))
bot_app.add_handler(CallbackQueryHandler(refer_callback, pattern='^refer$'))
bot_app.add_handler(CallbackQueryHandler(stats_callback, pattern='^stats$'))
bot_app.add_handler(CallbackQueryHandler(history_callback, pattern='^history$'))
bot_app.add_handler(CallbackQueryHandler(info_callback, pattern='^info$'))
bot_app.add_handler(CallbackQueryHandler(buy_credits_callback, pattern='^buy_credits$'))
bot_app.add_handler(CallbackQueryHandler(broadcast_callback, pattern='^broadcast$'))
bot_app.add_handler(CallbackQueryHandler(gen_gift_callback, pattern='^gen_gift$'))
bot_app.add_handler(CallbackQueryHandler(add_firebase_callback, pattern='^add_firebase$'))
bot_app.add_handler(CallbackQueryHandler(total_devices_callback, pattern='^total_devices$'))
bot_app.add_handler(CallbackQueryHandler(home_callback, pattern='^home$'))

bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_number))
bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message_text))
bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_custom_count))
bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_redeem))
bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_gen_gift))
bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_firebase))
bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_broadcast))

# ============ SCHEDULE DAILY CREDITS RESET ============
async def daily_reset_callback(context: ContextTypes.DEFAULT_TYPE):
    await reset_daily_credits(context)

async def daily_reset_loop():
    """Fallback if JobQueue not available - run every day at 23:59"""
    while True:
        now = datetime.now()
        next_run = now.replace(hour=23, minute=59, second=0, microsecond=0)
        if now >= next_run:
            next_run += timedelta(days=1)
        wait_seconds = (next_run - now).total_seconds()
        await asyncio.sleep(wait_seconds)
        await reset_daily_credits(None)
        print(f"✅ Daily credits reset at {datetime.now()}")

def schedule_daily_reset(app):
    job_queue = app.job_queue
    if job_queue:
        job_queue.run_daily(
            daily_reset_callback,
            time=time(23, 59, 0),
            days=(0, 1, 2, 3, 4, 5, 6)
        )
        print("✅ Daily credits reset scheduled with JobQueue at 11:59 PM")
    else:
        print("⚠️ JobQueue not available. Using async loop fallback.")
        asyncio.create_task(daily_reset_loop())

# ============ MAIN ============
if __name__ == '__main__':
    print("✅ SMS Blast Bot started! Developer: @T4HKR")
    print(f"👑 Admins: {ADMIN_IDS}")
    print(f"📢 Force Join Channel: {FORCE_CHANNEL}")
    print(f"✨ Daily Free Credits: {DAILY_CREDITS} (resets at 11:59 PM)")
    print(f"📊 Multi-Firebase support enabled.")
    schedule_daily_reset(bot_app)
    bot_app.run_polling(allowed_updates=Update.ALL_TYPES)
