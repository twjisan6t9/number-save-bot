import os
import threading
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from pymongo import MongoClient
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError

# Flask app for Render free tier
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

# Config
BOT_TOKEN = os.environ.get("BOT_TOKEN")
MONGO_URI = os.environ.get("MONGO_URI")
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH")

# MongoDB
mongo = MongoClient(MONGO_URI)
db = mongo["numbersavebot"]
numbers_col = db["numbers"]

WAITING_CODE = 1
WAITING_PASSWORD = 2
login_sessions = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to Number Save Bot!\n\n"
        "Commands:\n"
        "/addnumber +880XXXXXXXXX - Number add koro\n"
        "/login +880XXXXXXXXX - Login koro\n"
        "/accounts - Sob accounts dekho\n"
        "/delete +880XXXXXXXXX - Number delete koro"
    )

async def addnumber(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Permission nai!")
        return
    if not context.args:
        await update.message.reply_text("❌ Use: /addnumber +880XXXXXXXXX")
        return
    phone = context.args[0]
    existing = numbers_col.find_one({"phone": phone})
    if existing:
        await update.message.reply_text(f"⚠️ {phone} already ache!")
        return
    numbers_col.insert_one({"phone": phone, "session": None, "active": False})
    await update.message.reply_text(f"✅ {phone} save hoyeche!")

async def accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Permission nai!")
        return
    all_numbers = list(numbers_col.find())
    if not all_numbers:
        await update.message.reply_text("📋 Kono number nai!")
        return
    text = "📋 Saved Numbers:\n\n"
    for i, acc in enumerate(all_numbers, 1):
        status = "✅ Active" if acc.get("active") else "❌ Not logged in"
        text += f"{i}. {acc['phone']} - {status}\n"
    await update.message.reply_text(text)

async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Permission nai!")
        return
    if not context.args:
        await update.message.reply_text("❌ Use: /login +880XXXXXXXXX")
        return
    phone = context.args[0]
    acc = numbers_col.find_one({"phone": phone})
    if not acc:
        await update.message.reply_text(f"❌ {phone} list-e nai!")
        return
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.connect()
    await client.send_code_request(phone)
    login_sessions[update.effective_user.id] = {"client": client, "phone": phone}
    await update.message.reply_text(f"📱 OTP pathano hoyeche!\n\nCode dao:")
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
        await update.message.reply_text(f"✅ {phone} login successful!")
        return ConversationHandler.END
    except SessionPasswordNeededError:
        await update.message.reply_text("🔐 2FA password dao:")
        return WAITING_PASSWORD
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
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
        await update.message.reply_text(f"✅ {phone} login successful!")
        return ConversationHandler.END
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
        return ConversationHandler.END

async def delete_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Permission nai!")
        return
    if not context.args:
        await update.message.reply_text("❌ Use: /delete +880XXXXXXXXX")
        return
    phone = context.args[0]
    result = numbers_col.delete_one({"phone": phone})
    if result.deleted_count:
        await update.message.reply_text(f"✅ {phone} delete hoyeche!")
    else:
        await update.message.reply_text(f"❌ {phone} pawa jaini!")

def run_bot():
    application = Application.builder().token(BOT_TOKEN).build()
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("login", login)],
        states={
            WAITING_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_code)],
            WAITING_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_password)],
        },
        fallbacks=[]
    )
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("addnumber", addnumber))
    application.add_handler(CommandHandler("accounts", accounts))
    application.add_handler(CommandHandler("delete", delete_number))
    application.add_handler(conv_handler)
    application.run_polling()

if __name__ == "__main__":
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
