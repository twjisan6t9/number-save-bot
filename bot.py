import os
import logging
from pymongo import MongoClient
from telethon import TelegramClient
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

def main_menu():
    keyboard = [
        [InlineKeyboardButton("➕ নতুন নম্বর যোগ করুন", callback_data="add")],
        [InlineKeyboardButton("📱 সেভ করা নম্বর", callback_data="list")],
        [InlineKeyboardButton("🔑 লগইন করুন", callback_data="login")],
        [InlineKeyboardButton("🗑️ নম্বর ডিলিট করুন", callback_data="delete")],
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
        all_numbers = list(numbers_col.find())
        if not all_numbers:
            await query.message.reply_text("📋 কোনো নম্বর নেই!", reply_markup=main_menu())
        else:
            text = "📱 *সেভ করা নম্বর:*\n\n"
            for i, acc in enumerate(all_numbers, 1):
                status = "✅ Active" if acc.get("active") else "❌ Login নেই"
                text += f"{i}. `{acc['phone']}` - {status}\n"
            await query.message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu())

    elif query.data == "login":
        context.user_data["state"] = WAITING_LOGIN_NUMBER
        await query.message.reply_text("📝 লগইন করতে নম্বর লিখুন:")

    elif query.data == "delete":
        context.user_data["state"] = WAITING_DELETE_NUMBER
        await query.message.reply_text("📝 ডিলিট করতে নম্বর লিখুন:")

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
            await update.message.reply_text("❌ নম্বর + দিয়ে শুরু করুন!\nযেমন: +8801XXXXXXXXX", reply_markup=main_menu())
            return
        if numbers_col.find_one({"phone": text}):
            await update.message.reply_text(f"⚠️ {text} আগে থেকেই আছে!", reply_markup=main_menu())
            return
        numbers_col.insert_one({"phone": text, "session": None, "active": False})
        await update.message.reply_text(f"✅ {text} সেভ হয়েছে!", reply_markup=main_menu())

    elif state == WAITING_LOGIN_NUMBER:
        if not numbers_col.find_one({"phone": text}):
            context.user_data["state"] = None
            await update.message.reply_text(f"❌ {text} লিস্টে নেই!\nআগে নম্বর যোগ করুন।", reply_markup=main_menu())
            return
        try:
            client = TelegramClient(StringSession(), API_ID, API_HASH)
            await client.connect()
            await client.send_code_request(text)
            login_sessions[update.effective_user.id] = {"client": client, "phone": text}
            context.user_data["state"] = WAITING_CODE
            await update.message.reply_text("📱 OTP পাঠানো হয়েছে!\nTelegram থেকে কোডটি দিন:")
        except Exception as e:
            context.user_data["state"] = None
            await update.message.reply_text(f"❌ Error: {str(e)}", reply_markup=main_menu())

    elif state == WAITING_CODE:
        session_data = login_sessions.get(update.effective_user.id)
        if not session_data:
            context.user_data["state"] = None
            await update.message.reply_text("❌ Session নেই! আবার চেষ্টা করুন।", reply_markup=main_menu())
            return
        client = session_data["client"]
        phone = session_data["phone"]
        try:
            await client.sign_in(phone, text)
            session_string = client.session.save()
            numbers_col.update_one({"phone": phone}, {"$set": {"session": session_string, "active": True}})
            await client.disconnect()
            del login_sessions[update.effective_user.id]
            context.user_data["state"] = None
            await update.message.reply_text(f"✅ {phone} লগইন সফল!", reply_markup=main_menu())
        except SessionPasswordNeededError:
            context.user_data["state"] = WAITING_PASSWORD
            await update.message.reply_text("🔐 2FA চালু আছে!\nপাসওয়ার্ড দিন:")
        except Exception as e:
            context.user_data["state"] = None
            if update.effective_user.id in login_sessions:
                del login_sessions[update.effective_user.id]
            await update.message.reply_text(f"❌ Error: {str(e)}", reply_markup=main_menu())

    elif state == WAITING_PASSWORD:
        session_data = login_sessions.get(update.effective_user.id)
        if not session_data:
            context.user_data["state"] = None
            await update.message.reply_text("❌ Session নেই! আবার চেষ্টা করুন।", reply_markup=main_menu())
            return
        client = session_data["client"]
        phone = session_data["phone"]
        try:
            await client.sign_in(password=text)
            session_string = client.session.save()
            numbers_col.update_one({"phone": phone}, {"$set": {"session": session_string, "active": True}})
            await client.disconnect()
            del login_sessions[update.effective_user.id]
            context.user_data["state"] = None
            await update.message.reply_text(f"✅ {phone} লগইন সফল!", reply_markup=main_menu())
        except Exception as e:
            context.user_data["state"] = None
            if update.effective_user.id in login_sessions:
                del login_sessions[update.effective_user.id]
            await update.message.reply_text(f"❌ Error: {str(e)}", reply_markup=main_menu())

    elif state == WAITING_DELETE_NUMBER:
        context.user_data["state"] = None
        result = numbers_col.delete_one({"phone": text})
        if result.deleted_count:
            await update.message.reply_text(f"✅ {text} ডিলিট হয়েছে!", reply_markup=main_menu())
        else:
            await update.message.reply_text(f"❌ {text} পাওয়া যায়নি!", reply_markup=main_menu())

    else:
        context.user_data["state"] = None
        await update.message.reply_text(
            "👑 *JISAN NUMBER BOT*\n\nমেনু থেকে অপশন বেছে নিন।",
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
