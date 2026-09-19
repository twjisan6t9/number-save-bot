import os
import asyncio
import logging
from threading import Thread
from flask import Flask
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from pymongo import MongoClient
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
MONGO_URI = os.environ.get("MONGO_URI")
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH")

mongo = MongoClient(MONGO_URI)
db = mongo["numbersavebot"]
numbers_col = db["numbers"]

flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "Bot is running!"

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

class LoginState(StatesGroup):
    waiting_code = State()
    waiting_password = State()

login_sessions = {}

@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer(
        "👋 Welcome!\n\n"
        "/addnumber +880X - Number add\n"
        "/login +880X - Login\n"
        "/accounts - List\n"
        "/delete +880X - Delete"
    )

@dp.message(Command("addnumber"))
async def addnumber(message: types.Message):
    if message.from_user.id != OWNER_ID:
        await message.answer("❌ Permission nai!")
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Use: /addnumber +880XXXXXXXXX")
        return
    phone = args[1]
    if numbers_col.find_one({"phone": phone}):
        await message.answer(f"⚠️ {phone} already ache!")
        return
    numbers_col.insert_one({"phone": phone, "session": None, "active": False})
    await message.answer(f"✅ {phone} saved!")

@dp.message(Command("accounts"))
async def accounts(message: types.Message):
    if message.from_user.id != OWNER_ID:
        await message.answer("❌ Permission nai!")
        return
    all_numbers = list(numbers_col.find())
    if not all_numbers:
        await message.answer("📋 Kono number nai!")
        return
    text = "📋 Numbers:\n\n"
    for i, acc in enumerate(all_numbers, 1):
        status = "✅ Active" if acc.get("active") else "❌ Not logged in"
        text += f"{i}. {acc['phone']} - {status}\n"
    await message.answer(text)

@dp.message(Command("login"))
async def login(message: types.Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        await message.answer("❌ Permission nai!")
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Use: /login +880XXXXXXXXX")
        return
    phone = args[1]
    if not numbers_col.find_one({"phone": phone}):
        await message.answer(f"❌ {phone} list-e nai!")
        return
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.connect()
    await client.send_code_request(phone)
    login_sessions[message.from_user.id] = {"client": client, "phone": phone}
    await state.set_state(LoginState.waiting_code)
    await message.answer("📱 OTP pathano hoyeche! Code dao:")

@dp.message(LoginState.waiting_code)
async def get_code(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    code = message.text.strip()
    session_data = login_sessions.get(user_id)
    if not session_data:
        await state.clear()
        return
    client = session_data["client"]
    phone = session_data["phone"]
    try:
        await client.sign_in(phone, code)
        session_string = client.session.save()
        numbers_col.update_one({"phone": phone}, {"$set": {"session": session_string, "active": True}})
        await client.disconnect()
        del login_sessions[user_id]
        await state.clear()
        await message.answer(f"✅ {phone} login hoyeche!")
    except SessionPasswordNeededError:
        await state.set_state(LoginState.waiting_password)
        await message.answer("🔐 2FA password dao:")
    except Exception as e:
        await state.clear()
        await message.answer(f"❌ Error: {str(e)}")

@dp.message(LoginState.waiting_password)
async def get_password(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    password = message.text.strip()
    session_data = login_sessions.get(user_id)
    if not session_data:
        await state.clear()
        return
    client = session_data["client"]
    phone = session_data["phone"]
    try:
        await client.sign_in(password=password)
        session_string = client.session.save()
        numbers_col.update_one({"phone": phone}, {"$set": {"session": session_string, "active": True}})
        await client.disconnect()
        del login_sessions[user_id]
        await state.clear()
        await message.answer(f"✅ Login hoyeche!")
    except Exception as e:
        await state.clear()
        await message.answer(f"❌ Error: {str(e)}")

@dp.message(Command("delete"))
async def delete_number(message: types.Message):
    if message.from_user.id != OWNER_ID:
        await message.answer("❌ Permission nai!")
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Use: /delete +880XXXXXXXXX")
        return
    phone = args[1]
    result = numbers_col.delete_one({"phone": phone})
    if result.deleted_count:
        await message.answer(f"✅ {phone} deleted!")
    else:
        await message.answer(f"❌ {phone} pawa jaini!")

def run_bot():
    async def main():
        print("Bot starting...")
        await dp.start_polling(bot)
    asyncio.run(main())

if __name__ == "__main__":
    t = Thread(target=run_bot, daemon=True)
    t.start()
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port)
