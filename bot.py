import os
import logging
from pymongo import MongoClient
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes, ConversationHandler

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
    # আগে নিচের Reply keyboard সরাও
    await update.message.reply_text(
        "লোড হচ্ছে...",
        reply_markup=ReplyKeyboardRemove()
    )
    # তারপর Inline মেনু দেখাও
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
        await query.message.reply_text("📝 নতুন নম্বর লিখুন (যেমন: +8801XXXXXXXXX):")
        return WAITING_NUMBER_ADD

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
        await query.message.reply_text("📝 লগইন করতে নম্বর লিখুন:")
        return WAITING_LOGIN_NUMBER

    elif query.data == "delete":
        await query.message.reply_text("📝 ডিলিট করতে নম্বর লিখুন:")
        return WAITING_DELETE_NUMBER

    elif query.data == "menu":
        await query.message.reply_text(
            "👑 *JISAN NUMBER BOT*\n\nমেনু:",
            parse_mode="Markdown",
            reply_markup=main_menu()
        )

async def add_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    if numbers_col.find_one({"phone": phone}):
        await update.message.reply_text(f"⚠️ {phone} আগে থেকেই আছে!", reply_markup=main_menu())
        return ConversationHandler.END
    numbers_col.insert_one({"phone": phone, "session": None, "active": False})
    await update.message.reply_text(f"✅ {phone} সেভ হয়েছে!", reply_markup=main_menu())
    return ConversationHandler.END

async def login_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    if not numbers_col.find_one({"phone": phone}):
        await update.message.reply_text(f"❌ {phone} লিস্টে নেই!", reply_markup=main_menu())
        return ConversationHandler.END
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.connect()
    await client.send_code_request(phone)
    login_sessions[update.effective_user.id] = {"client": client, "phone": phone}
    await update.message.reply_text("📱 OTP পাঠানো হয়েছে! কোড দিন:")
    return WAITING_CODE

async def get_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    code = update.message.text.strip()
    session_data = login_sessions.get(user_id)
    if not session_data:
        return ConversationHandler.END
    client = session_data["client"]
    phone = session_data["phone"]
    try:
        await client.sign_in(phone, code)
        session_string = client.session.save()
        numbers_col.update_one({"phone": phone}, {"$set": {"session": session_string, "active": True}})
        await client.disconnect()
        del login_sessions[user_id]
        await update.message.reply_text(f"✅ {phone} লগইন সফল!", reply_markup=main_menu())
        return ConversationHandler.END
    except SessionPasswordNeededError:
        await update.message.reply_text("🔐 2FA পাসওয়ার্ড দিন:")
        return WAITING_PASSWORD
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}", reply_markup=main_menu())
        return ConversationHandler.END

async def get_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    password = update.message.text.strip()
    session_data = login_sessions.get(user_id)
    if not session_data:
        return ConversationHandler.END
    client = session_data["client"]
    phone = session_data["phone"]
    try:
        await client.sign_in(password=password)
        session_string = client.session.save()
        numbers_col.update_one({"phone": phone}, {"$set": {"session": session_string, "active": True}})
        await client.disconnect()
        del login_sessions[user_id]
        await update.message.reply_text("✅ লগইন সফল!", reply_markup=main_menu())
        return ConversationHandler.END
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}", reply_markup=main_menu())
        return ConversationHandler.END

async def delete_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    result = numbers_col.delete_one({"phone": phone})
    if result.deleted_count:
        await update.message.reply_text(f"✅ {phone} ডিলিট হয়েছে!", reply_markup=main_menu())
    else:
        await update.message.reply_text(f"❌ {phone} পাওয়া যায়নি!", reply_markup=main_menu())
    return ConversationHandler.END

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler)],
        states={
            WAITING_NUMBER_ADD: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_number)],
            WAITING_LOGIN_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_number)],
            WAITING_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_code)],
            WAITING_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_password)],
            WAITING_DELETE_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, delete_number)],
        },
        fallbacks=[CommandHandler("start", start)]
    )
    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv)
    print("Bot running!")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
