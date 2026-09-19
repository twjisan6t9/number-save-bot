import os
import logging
import asyncio
from pymongo import MongoClient
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
MONGO_URI = os.environ.get("MONGO_URI")
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH")

mongo = MongoClient(MONGO_URI)
db = mongo["numbersavebot"]
numbers_col = db["numbers"]

WAITING_CODE = 1
WAITING_PASSWORD = 2
WAITING_NUMBER_ADD = 3
WAITING_LOGIN_NUMBER = 4
WAITING_DELETE_NUMBER = 5
login_sessions = {}
active_listeners = {}

def get_next_position():
    """পরবর্তী position নম্বর বের করো"""
    all_numbers = list(numbers_col.find().sort("position", -1).limit(1))
    if not all_numbers:
        return 1
    return all_numbers[0].get("position", 0) + 1

def reorder_positions():
    """Delete এর পরে position ঠিক করো"""
    all_numbers = list(numbers_col.find().sort("position", 1))
    for i, acc in enumerate(all_numbers, 1):
        numbers_col.update_one(
            {"_id": acc["_id"]},
            {"$set": {"position": i}}
        )

async def get_telegram_name(session_string):
    """Telegram account এর নাম বের করো"""
    try:
        client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
        await client.connect()
        if await client.is_user_authorized():
            me = await client.get_me()
            first = me.first_name or ""
            last = me.last_name or ""
            full_name = f"{first} {last}".strip()
            await client.disconnect()
            return full_name
        await client.disconnect()
        return "Unknown"
    except:
        return "Unknown"

def main_menu():
    keyboard = [
        [InlineKeyboardButton("➕ নতুন নম্বর যোগ করুন", callback_data="add")],
        [InlineKeyboardButton("📱 সেভ করা নম্বর", callback_data="list")],
        [InlineKeyboardButton("🔑 লগইন করুন", callback_data="login")],
        [InlineKeyboardButton("🗑️ নম্বর ডিলিট করুন", callback_data="delete")],
        [InlineKeyboardButton("⚡ OTP নিন", callback_data="get_otp")],
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = None
    await update.message.reply_text(
        "লোড হচ্ছে...",
        reply_markup=ReplyKeyboardRemove()
    )
    await update.message.reply_text(
        "👑 *JISAN NUMBER BOT*\n\nস্বাগতম! নিচের মেনু থেকে অপশন বেছে নিন।",
        parse_mode="Markdown",
        reply_markup=main_menu()
    )

async def get_otp_for_number(phone, session_string, bot_app):
    try:
        client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
        await client.connect()

        if not await client.is_user_authorized():
            await bot_app.bot.send_message(
                OWNER_ID,
                f"❌ `{phone}` এর session expired! আবার login করুন।",
                parse_mode="Markdown"
            )
            await client.disconnect()
            return

        await bot_app.bot.send_message(
            OWNER_ID,
            f"👂 `{phone}` নম্বর listen করছে...\n\n"
            f"⚠️ অন্য device থেকে login করার সময়\n"
            f"*'Send via Telegram app'* বেছে নিন!\n\n"
            f"⏳ ১২০ সেকেন্ড অপেক্ষা করছি...",
            parse_mode="Markdown"
        )

        otp_received = False

        @client.on(events.NewMessage(from_users=777000))
        async def otp_handler(event):
            nonlocal otp_received
            otp_received = True
            msg = event.message.text
            await bot_app.bot.send_message(
                OWNER_ID,
                f"⚡ *OTP এসেছে!*\n\n"
                f"📱 নম্বর: `{phone}`\n"
                f"🔑 মেসেজ:\n{msg}",
                parse_mode="Markdown"
            )

        active_listeners[phone] = client

        for _ in range(120):
            await asyncio.sleep(1)
            if otp_received:
                break

        if not otp_received:
            await bot_app.bot.send_message(
                OWNER_ID,
                f"⏰ `{phone}` এর OTP timeout হয়েছে!\nআবার চেষ্টা করুন।",
                parse_mode="Markdown"
            )

        await client.disconnect()
        if phone in active_listeners:
            del active_listeners[phone]

    except Exception as e:
        await bot_app.bot.send_message(OWNER_ID, f"❌ Error: {str(e)}")
        if phone in active_listeners:
            del active_listeners[phone]

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.from_user.id != OWNER_ID:
        await query.message.reply_text("❌ Permission নেই!")
        return

    if query.data == "add":
        context.user_data["state"] = WAITING_NUMBER_ADD
        await query.message.reply_text("📝 নতুন নম্বর লিখুন (যেমন: +8801XXXXXXXXX):")

    elif query.data == "list":
        all_numbers = list(numbers_col.find().sort("position", 1))
        if not all_numbers:
            await query.message.reply_text("📋 কোনো নম্বর নেই!", reply_markup=main_menu())
        else:
            text = "📱 *সেভ করা নম্বর:*\n\n"
            for acc in all_numbers:
                pos = acc.get("position", "?")
                name = acc.get("tg_name", "Unknown")
                status = "✅ Active" if acc.get("active") else "❌ Login নেই"
                listener = "👂" if acc['phone'] in active_listeners else ""
                text += f"{pos}️⃣ {name} - `{acc['phone']}` {status} {listener}\n"
            await query.message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu())

    elif query.data == "login":
        context.user_data["state"] = WAITING_LOGIN_NUMBER
        await query.message.reply_text("📝 লগইন করতে নম্বর লিখুন:")

    elif query.data == "delete":
        context.user_data["state"] = WAITING_DELETE_NUMBER
        # নম্বর list দেখাও
        all_numbers = list(numbers_col.find().sort("position", 1))
        if not all_numbers:
            await query.message.reply_text("📋 কোনো নম্বর নেই!", reply_markup=main_menu())
            return
        keyboard = []
        for acc in all_numbers:
            pos = acc.get("position", "?")
            name = acc.get("tg_name", "Unknown")
            keyboard.append([InlineKeyboardButton(
                f"{pos}️⃣ {name} - {acc['phone']}",
                callback_data=f"del_{acc['phone']}"
            )])
        keyboard.append([InlineKeyboardButton("🔙 ব্যাক", callback_data="menu")])
        await query.message.reply_text(
            "কোন নম্বর ডিলিট করতে চান?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data.startswith("del_"):
        phone = query.data.replace("del_", "")
        if phone in active_listeners:
            await active_listeners[phone].disconnect()
            del active_listeners[phone]
        result = numbers_col.delete_one({"phone": phone})
        if result.deleted_count:
            reorder_positions()
            await query.message.reply_text(f"✅ {phone} ডিলিট হয়েছে!", reply_markup=main_menu())
        else:
            await query.message.reply_text(f"❌ {phone} পাওয়া যায়নি!", reply_markup=main_menu())

    elif query.data == "get_otp":
        all_numbers = list(numbers_col.find({"active": True}).sort("position", 1))
        if not all_numbers:
            await query.message.reply_text(
                "❌ কোনো Active নম্বর নেই!\nআগে নম্বর login করুন।",
                reply_markup=main_menu()
            )
            return
        if len(all_numbers) == 1:
            acc = all_numbers[0]
            name = acc.get("tg_name", "Unknown")
            await query.message.reply_text(
                f"⏳ `{acc['phone']}` এ OTP listen শুরু হচ্ছে...",
                parse_mode="Markdown"
            )
            asyncio.create_task(
                get_otp_for_number(acc['phone'], acc['session'], context.application)
            )
        else:
            keyboard = []
            for acc in all_numbers:
                pos = acc.get("position", "?")
                name = acc.get("tg_name", "Unknown")
                keyboard.append([InlineKeyboardButton(
                    f"{pos}️⃣ {name} - {acc['phone']}",
                    callback_data=f"otp_{acc['phone']}"
                )])
            keyboard.append([InlineKeyboardButton("🔙 ব্যাক", callback_data="menu")])
            await query.message.reply_text(
                "কোন নম্বরের OTP নিতে চান?",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

    elif query.data.startswith("otp_"):
        phone = query.data.replace("otp_", "")
        acc = numbers_col.find_one({"phone": phone})
        if not acc:
            await query.message.reply_text("❌ নম্বর পাওয়া যায়নি!", reply_markup=main_menu())
            return
        await query.message.reply_text(
            f"⏳ `{phone}` এ OTP listen শুরু হচ্ছে...",
            parse_mode="Markdown"
        )
        asyncio.create_task(
            get_otp_for_number(phone, acc['session'], context.application)
        )

    elif query.data == "menu":
        context.user_data["state"] = None
        await query.message.reply_text(
            "👑 *JISAN NUMBER BOT*\n\nমেনু:",
            parse_mode="Markdown",
            reply_markup=main_menu()
        )

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return

    state = context.user_data.get("state")
    text = update.message.text.strip()

    if state == WAITING_NUMBER_ADD:
        context.user_data["state"] = None
        if not text.startswith("+"):
            await update.message.reply_text("❌ নম্বর + দিয়ে শুরু করুন!", reply_markup=main_menu())
            return
        if numbers_col.find_one({"phone": text}):
            await update.message.reply_text(f"⚠️ {text} আগে থেকেই আছে!", reply_markup=main_menu())
            return
        position = get_next_position()
        numbers_col.insert_one({
            "phone": text,
            "session": None,
            "active": False,
            "position": position,
            "tg_name": "Unknown"
        })
        await update.message.reply_text(f"✅ {text} সেভ হয়েছে! ({position} নম্বরে)", reply_markup=main_menu())

    elif state == WAITING_LOGIN_NUMBER:
        if not numbers_col.find_one({"phone": text}):
            context.user_data["state"] = None
            await update.message.reply_text(f"❌ {text} লিস্টে নেই!", reply_markup=main_menu())
            return
        try:
            client = TelegramClient(StringSession(), API_ID, API_HASH)
            await client.connect()
            await client.send_code_request(text)
            login_sessions[update.effective_user.id] = {"client": client, "phone": text}
            context.user_data["state"] = WAITING_CODE
            await update.message.reply_text("📱 OTP পাঠানো হয়েছে! কোড দিন:")
        except Exception as e:
            context.user_data["state"] = None
            await update.message.reply_text(f"❌ Error: {str(e)}", reply_markup=main_menu())

    elif state == WAITING_CODE:
        session_data = login_sessions.get(update.effective_user.id)
        if not session_data:
            context.user_data["state"] = None
            await update.message.reply_text("❌ Session নেই!", reply_markup=main_menu())
            return
        client = session_data["client"]
        phone = session_data["phone"]
        try:
            await client.sign_in(phone, text)
            session_string = client.session.save()
            # Telegram নাম বের করো
            me = await client.get_me()
            first = me.first_name or ""
            last = me.last_name or ""
            tg_name = f"{first} {last}".strip()
            numbers_col.update_one(
                {"phone": phone},
                {"$set": {"session": session_string, "active": True, "tg_name": tg_name}}
            )
            await client.disconnect()
            del login_sessions[update.effective_user.id]
            context.user_data["state"] = None
            await update.message.reply_text(
                f"✅ {phone} লগইন সফল!\n👤 নাম: {tg_name}",
                reply_markup=main_menu()
            )
        except SessionPasswordNeededError:
            context.user_data["state"] = WAITING_PASSWORD
            await update.message.reply_text("🔐 2FA পাসওয়ার্ড দিন:")
        except Exception as e:
            context.user_data["state"] = None
            if update.effective_user.id in login_sessions:
                del login_sessions[update.effective_user.id]
            await update.message.reply_text(f"❌ Error: {str(e)}", reply_markup=main_menu())

    elif state == WAITING_PASSWORD:
        session_data = login_sessions.get(update.effective_user.id)
        if not session_data:
            context.user_data["state"] = None
            await update.message.reply_text("❌ Session নেই!", reply_markup=main_menu())
            return
        client = session_data["client"]
        phone = session_data["phone"]
        try:
            await client.sign_in(password=text)
            session_string = client.session.save()
            me = await client.get_me()
            first = me.first_name or ""
            last = me.last_name or ""
            tg_name = f"{first} {last}".strip()
            numbers_col.update_one(
                {"phone": phone},
                {"$set": {"session": session_string, "active": True, "tg_name": tg_name}}
            )
            await client.disconnect()
            del login_sessions[update.effective_user.id]
            context.user_data["state"] = None
            await update.message.reply_text(
                f"✅ {phone} লগইন সফল!\n👤 নাম: {tg_name}",
                reply_markup=main_menu()
            )
        except Exception as e:
            context.user_data["state"] = None
            if update.effective_user.id in login_sessions:
                del login_sessions[update.effective_user.id]
            await update.message.reply_text(f"❌ Error: {str(e)}", reply_markup=main_menu())

    else:
        context.user_data["state"] = None
        await update.message.reply_text(
            "👑 *JISAN NUMBER BOT*",
            parse_mode="Markdown",
            reply_markup=main_menu()
        )

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    print("Bot running!")
    application.run_polling(drop_pending_updates=False)

if __name__ == "__main__":
    main()
