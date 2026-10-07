import os
import time
import sqlite3
import threading
import telebot
import razorpay
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from telebot import types

# Selenium Imports
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# Database Setup
def init_db():
    conn = sqlite3.connect("bot_config.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    cursor.execute("INSERT OR IGNORE INTO settings VALUES ('rzp_key', ?)", (os.getenv("RAZORPAY_KEY_ID", ""),))
    cursor.execute("INSERT OR IGNORE INTO settings VALUES ('rzp_secret', ?)", (os.getenv("RAZORPAY_KEY_SECRET", ""),))
    cursor.execute("INSERT OR IGNORE INTO settings VALUES ('plan_id', ?)", (os.getenv("RAZORPAY_PLAN_ID", ""),))
    cursor.execute("INSERT OR IGNORE INTO settings VALUES ('trial_amount', ?)", (os.getenv("TRIAL_AMOUNT", "1"),))
    conn.commit()
    conn.close()

def get_setting(key):
    conn = sqlite3.connect("bot_config.db")
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key=?", (key,))
    res = cursor.fetchone()
    conn.close()
    return res[0] if res else ""

def set_setting(key, value):
    conn = sqlite3.connect("bot_config.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE settings SET value=? WHERE key=?", (value, key))
    conn.commit()
    conn.close()

init_db()

# --- Headless Chrome Runner ---
def get_chrome_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1280,1024")
    
    # Custom User-Agent to prevent bot detection
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36")

    # Render Chromium path detection
    if os.path.exists("/usr/bin/chromium"):
        chrome_options.binary_location = "/usr/bin/chromium"
        service = Service("/usr/bin/chromedriver")
    elif os.path.exists("/usr/bin/chromium-browser"):
        chrome_options.binary_location = "/usr/bin/chromium-browser"
        service = Service("/usr/bin/chromedriver")
    else:
        service = Service(ChromeDriverManager().install())

    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver

# --- QR Capture Task ---
def capture_and_send_qr(chat_id, payment_url):
    driver = None
    try:
        bot.send_message(chat_id, "⚙️ Browser open ho raha hai, QR Code fetch kiya ja raha hai (10-15 seconds wait karein)...")
        
        driver = get_chrome_driver()
        driver.get(payment_url)

        # Wait for Checkout UI to load
        wait = WebDriverWait(driver, 20)
        
        # Click on UPI Option if present
        try:
            upi_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'UPI')]")))
            upi_btn.click()
            time.sleep(2)
        except Exception as e:
            print("UPI Tab Auto-Select Skip or Failed:", e)

        # Click on UPI QR Option if present
        try:
            qr_tab = wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'UPI QR')]")))
            qr_tab.click()
            time.sleep(3)
        except Exception as e:
            print("UPI QR Tab Selection Skip or Failed:", e)

        # Screenshot the page or QR element
        screenshot_path = f"qr_{chat_id}.png"
        driver.save_screenshot(screenshot_path)

        # Send Screenshot to Telegram
        with open(screenshot_path, 'rb') as photo:
            bot.send_photo(
                chat_id, 
                photo, 
                caption="⏳ **UPI AutoPay QR Code**\n\n📌 *Is QR Code ko scan karke AutoPay approve karein. Note: Timer active hai.*",
                parse_mode="Markdown"
            )

        # Cleanup Screenshot file
        if os.path.exists(screenshot_path):
            os.remove(screenshot_path)

    except Exception as e:
        bot.send_message(chat_id, f"❌ Selenium Automation Error: {str(e)}")
    finally:
        if driver:
            driver.quit()  # Free RAM memory after execution

# --- Start Handler ---
@bot.message_handler(commands=['start', 'buy'])
def start_payment_flow(message):
    chat_id = message.chat.id

    rzp_key = get_setting('rzp_key')
    rzp_secret = get_setting('rzp_secret')
    plan_id = get_setting('plan_id')
    trial_amt = int(get_setting('trial_amount') or 1)

    if not rzp_key or not rzp_secret or not plan_id:
        bot.send_message(chat_id, "⚠️ Gateway settings missing. `/admin` me configure karein.")
        return

    try:
        rzp_client = razorpay.Client(auth=(rzp_key, rzp_secret))
        
        subscription = rzp_client.subscription.create({
            "plan_id": plan_id,
            "total_count": 12,
            "quantity": 1,
            "customer_notify": 1,
            "addons": [{
                "item": {
                    "name": "Trial Fee",
                    "amount": trial_amt * 100,
                    "currency": "INR"
                }
            }],
            "notes": {"telegram_user_id": str(chat_id)}
        })

        payment_url = subscription['short_url']

        # Run Selenium in a Background Thread so it doesn't block Telegram Bot
        threading.Thread(target=capture_and_send_qr, args=(chat_id, payment_url)).start()

    except Exception as e:
        bot.send_message(chat_id, f"❌ Subscription Error: {str(e)}")

# --- Admin Panel & Webhook Standard Code ---
@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.chat.id != ADMIN_ID:
        return
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔑 Set Key ID", callback_data="set_key"))
    markup.add(types.InlineKeyboardButton("🔐 Set Secret", callback_data="set_secret"))
    markup.add(types.InlineKeyboardButton("📋 Set Plan ID", callback_data="set_plan"))
    markup.add(types.InlineKeyboardButton("💰 Set Trial Amount", callback_data="set_trial"))
    bot.send_message(message.chat.id, "⚙️ **Admin Control Panel**", reply_markup=markup)

@app.route('/')
def home():
    return "Bot with Selenium is Alive!"

def start_polling():
    while True:
        try:
            bot.polling(none_stop=True, interval=0, timeout=20)
        except Exception as e:
            time.sleep(5)

threading.Thread(target=start_polling, daemon=True).start()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
