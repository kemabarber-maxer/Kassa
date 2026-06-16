import asyncio
import logging
import os
import sqlite3
import re
from datetime import datetime

from aiogram import Bot, Dispatcher, types, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# Selenium
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

# ========== KONFIGURASIYA ==========
BOT_TOKEN = os.getenv("BOT_TOKEN", "8990195591:AAEdvqBuko34uisWUgmAgP4GjG__slW1Qmo")
OWNER_PHONE = os.getenv("OWNER_PHONE", "+99362237781")

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
                  bot_balance REAL DEFAULT 0,
                  created_at TEXT)''')
    conn.commit()
    conn.close()

def save_user(user_id, phone, so_password):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO users (user_id, phone, so_password, bot_balance, created_at) VALUES (?, ?, ?, 0, ?)",
              (user_id, phone, so_password, datetime.now().isoformat()))
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

# ========== SELENIUM TMCELL ==========
class TMCELLSelenium:
    def __init__(self):
        self.driver = None
    
    def setup_driver(self):
        """Chrome browser gurna - Railway üçin"""
        chrome_options = Options()
        
        # Headless mode
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        
        # Chrome binary ýolu (Dockerfile-dan)
        chrome_options.binary_location = os.getenv("CHROME_BIN", "/usr/bin/chromium")
        
        # ChromeDriver ýolu
        chromedriver_path = os.getenv("CHROMEDRIVER_PATH", "/usr/bin/chromedriver")
        
        service = Service(executable_path=chromedriver_path)
        self.driver = webdriver.Chrome(service=service, options=chrome_options)
        self.driver.implicitly_wait(15)
    
    def login_and_get_balance(self, phone: str, password: str):
        """Şahsy otaga girip balansy al"""
        try:
            self.setup_driver()
            
            # 1. Saýta giriň
            self.driver.get("https://my.tmcell.tm")
            logging.info("Sayta girildi")
            
            # 2. "Şahsy otag" saýla (eger dropdown bar bolsa)
            try:
                dropdown = WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located((By.XPATH, "//select"))
                )
                # Option saýla
                from selenium.webdriver.support.ui import Select
                select = Select(dropdown)
                select.select_by_visible_text("Şahsy otag")
            except:
                logging.info("Dropdown tapylmady, geçildi")
            
            # 3. Nomer giriz (993 + 62237781)
            # Suratda görkezilen ýaly: 993 aýry, 62237781 aýry
            phone_input = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.XPATH, "//input[@type='tel' or @name='msisdn' or @placeholder]"))
            )
            phone_input.clear()
            phone_input.send_keys(phone.replace("993", ""))  # 62237781
            logging.info(f"Nomer girildi: {phone.replace('993', '')}")
            
            # 4. Parol giriz
            password_input = self.driver.find_element(By.XPATH, "//input[@type='password']")
            password_input.clear()
            password_input.send_keys(password)
            logging.info("Parol girildi")
            
            # 5. Giriş bas
            login_button = self.driver.find_element(By.XPATH, "//button[contains(text(), 'ULGAMA GIR')]")
            login_button.click()
            logging.info("Giris basyldy")
            
            # 6. Balansy gözle (suratda görkezilen ýaly)
            # "11.24 manat" ýa-da "Balans"
            try:
                # Biraz garaş
                import time
                time.sleep(3)
                
                # Balans element-i
                balance_element = WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'manat') or contains(text(), 'Balans')]"))
                )
                balance_text = balance_element.text
                logging.info(f"Balans text: {balance_text}")
                
                # Balansy parse et
                balance_match = re.search(r'(\d+\.?\d*)\s*manat', balance_text, re.IGNORECASE)
                if balance_match:
                    balance = float(balance_match.group(1))
                else:
                    # Başga format
                    balance_match = re.search(r'(\d+\.?\d*)', balance_text)
                    balance = float(balance_match.group(1)) if balance_match else 0
                
                return {
                    "success": True,
                    "balance": balance,
                    "message": f"Balans: {balance} TMT"
                }
                
            except Exception as e:
                logging.error(f"Balans tapylmady: {e}")
                # Screenshot al
                self.driver.save_screenshot("/tmp/balance_error.png")
                return {
                    "success": True,
                    "balance": 0,
                    "message": "Giriş üstünlikli, ýöne balans tapylmady"
                }
                
        except Exception as e:
            logging.error(f"Selenium error: {e}")
            # Screenshot al
            if self.driver:
                self.driver.save_screenshot("/tmp/login_error.png")
            return {
                "success": False,
                "message": f"Ýalňyş: {str(e)}"
            }
        finally:
            self.close()
    
    def close(self):
        if self.driver:
            self.driver.quit()
            self.driver = None

tmcell = TMCELLSelenium()

# ========== BOT ==========
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ========== HANDLERS ==========
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user = get_user(message.from_user.id)
    
    if user:
        await message.answer(
            f"👋 Hoş geldiňiz!\n\n"
            f"📱 Nomer: +{user[1]}\n"
            f"🤖 Bot balansy: {user[3]} TMT\n\n"
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
        f"❓ Paroly 0831 belgä SMS ugradyp görüp bilersiňiz",
        reply_markup=back_kb()
    )
    await state.set_state(UserState.waiting_so_code)

@dp.message(UserState.waiting_so_code)
async def process_so_code(message: Message, state: FSMContext):
    so_password = message.text.strip()
    data = await state.get_data()
    phone = data['phone']
    
    await message.answer("⏳ Şahsy otaga giriş edilýar... (Bu 10-20 sekunt wagt alýar)")
    
    # SELENIUM arkaly balansy barla
    result = tmcell.login_and_get_balance(phone, so_password)
    
    if result["success"]:
        save_user(message.from_user.id, phone, so_password)
        
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
    
    await message.answer(
        f"💰 Bot balansy doldurmak\n\n"
        f"📱 Nomer: +{user[1]}\n"
        f"📥 Pul geçiriljek: {OWNER_PHONE}\n\n"
        f"⚠️ my.tmcell.tm sahypasynda awtomatik pul geçirmek mümkin däl.\n"
        f"💵 Mukdar saýlaň (bot balansy ýatda saklar):",
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
        
        # Bot balansyny artdyr (ulanyjy elden pul geçirse)
        update_balance(message.from_user.id, amount)
        
        await message.answer(
            f"✅ Bot balansy dolduruldy!\n\n"
            f"💰 Mukdar: {amount} TMT\n"
            f"🤖 Bot balansyňyz: {get_balance(message.from_user.id)} TMT\n\n"
            f"📥 Pul geçirmek üçin:\n"
            f"USSD: *100*{amount}*{OWNER_PHONE.replace('+', '')}#\n"
            f"ýa-da TMCELL ilçihanasyna ýüz tutuň",
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
    
    await message.answer(
        f"📊 Hasabym\n\n"
        f"👤 ID: {message.from_user.id}\n"
        f"📱 Nomer: +{user[1]}\n"
        f"🤖 Bot balansy: {user[3]} TMT\n"
        f"📅 Hasap açylan: {user[4][:10] if user[4] else 'N/A'}",
        reply_markup=main_kb()
    )

@dp.message(F.text == "❓ Kömek")
async def help_cmd(message: Message):
    await message.answer(
        f"❓ Kömek\n\n"
        f"1️⃣ /start - Boty başlat\n"
        f"2️⃣ TMCELL nomeriňizi giriziň\n"
        f"3️⃣ Şahsy otag parolyňyzy giriziň\n"
        f"4️⃣ Bot balansy doldurmak üçin pul geçiriň\n\n"
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
