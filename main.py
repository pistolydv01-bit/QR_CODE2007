import os
import io
import sqlite3
import telebot
import razorpay
import qrcode
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import threading
from telebot import types

# Load Environment Variables from .env file
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# --- Database Initialization ---
def init_db():
    conn = sqlite3.connect("bot_config.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    # Environment variables se initial values database me set karein
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

admin_state = {}

# --- Flask Health Check Route for Render ---
@app.route('/')
def home():
    return "Bot is alive and running!"

# --- ADMIN PANEL ---
@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.chat.id != ADMIN_ID:
        bot.reply_to(message, "❌ Aapke paas Admin access nahi hai.")
        return

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔑 Set Razorpay Key ID", callback_data="set_key"))
    markup.add(types.InlineKeyboardButton("🔐 Set Razorpay Secret", callback_data="set_secret"))
    markup.add(types.InlineKeyboardButton("📋 Set Plan ID", callback_data="set_plan"))
    markup.add(types.InlineKeyboardButton("💰 Set Trial Amount (₹)", callback_data="set_trial"))
    markup.add(types.InlineKeyboardButton("📊 View Settings", callback_data="view_settings"))

    bot.send_message(message.chat.id, "⚙️ **Admin Control Panel**\n\nYahan se AutoPay settings manage karein:", reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_') or call.data == 'view_settings')
def handle_admin_clicks(call):
    if call.message.chat.id != ADMIN_ID:
        return

    key = call.data
    if key == "view_settings":
        text = (
            f"📋 **Current Settings:**\n\n"
            f"• Razorpay Key ID: `{get_setting('rzp_key')}`\n"
            f"• Razorpay Secret: `{get_setting('rzp_secret')}`\n"
            f"• Plan ID: `{get_setting('plan_id')}`\n"
            f"• Trial Amount: ₹{get_setting('trial_amount')}"
        )
        bot.send_message(call.message.chat.id, text, parse_mode="Markdown")
    else:
        admin_state[call.message.chat.id] = key
        bot.send_message(call.message.chat.id, f"📝 Nayi value bhejein ({key}):")

@bot.message_handler(func=lambda m: m.chat.id in admin_state)
def process_admin_input(message):
    state = admin_state.pop(message.chat.id)
    val = message.text.strip()

    if state == "set_key":
        set_setting('rzp_key', val)
        bot.reply_to(message, "✅ Razorpay Key ID update ho gayi!")
    elif state == "set_secret":
        set_setting('rzp_secret', val)
        bot.reply_to(message, "✅ Razorpay Secret update ho gaya!")
    elif state == "set_plan":
        set_setting('plan_id', val)
        bot.reply_to(message, "✅ Plan ID update ho gaya!")
    elif state == "set_trial":
        set_setting('trial_amount', val)
        bot.reply_to(message, f"✅ Trial Amount ₹{val} update ho gaya!")

# --- USER SIDE: AUTOPAY QR GENERATION ---
@bot.message_handler(commands=['start', 'buy'])
def send_autopay_qr(message):
    user_id = str(message.chat.id)
    chat_id = message.chat.id

    rzp_key = get_setting('rzp_key')
    rzp_secret = get_setting('rzp_secret')
    plan_id = get_setting('plan_id')
    trial_amt = int(get_setting('trial_amount') or 1)

    if not rzp_key or not rzp_secret or not plan_id:
        bot.send_message(chat_id, "⚠️ Payment gateway configure nahi hua hai. Admin se sampark karein.")
        return

    bot.send_message(chat_id, "⏳ Payment QR Code generate ho raha hai...")

    try:
        rzp_client = razorpay.Client(auth=(rzp_key, rzp_secret))
        
        subscription = rzp_client.subscription.create({
            "plan_id": plan_id,
            "total_count": 12,
            "quantity": 1,
            "customer_notify": 1,
            "addons": [
                {
                    "item": {
                        "name": "Trial Fee",
                        "amount": trial_amt * 100,  # Rupee to Paise
                        "currency": "INR"
                    }
                }
            ],
            "notes": {
                "telegram_user_id": user_id
            }
        })

        payment_url = subscription['short_url']

        # QR Code Generation
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(payment_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        img_buffer = io.BytesIO()
        img.save(img_buffer, format='PNG')
        img_buffer.seek(0)

        caption_text = (
            f"💳 **UPI AutoPay Payment QR Code**\n\n"
            f"📌 **Trial Amount:** ₹{trial_amt}\n"
            f"🔄 **Renewal:** Monthly Auto-Debit\n\n"
            f"1️⃣ Is QR Code ko **PhonePe, Paytm, ya GPay** se scan karein.\n"
            f"2️⃣ Screen par **'Setup AutoPay'** ka request aayega.\n"
            f"3️⃣ UPI PIN dalkar ₹{trial_amt} approve karein.\n\n"
            f"✅ Verification automatic hoga (Screenshot bhejane ki zarurat nahi hai)!"
        )

        bot.send_photo(chat_id, photo=img_buffer, caption=caption_text, parse_mode="Markdown")

    except Exception as e:
        bot.send_message(chat_id, f"❌ Payment error: {str(e)}")

# --- WEBHOOK FOR AUTO-VERIFICATION ---
@app.route('/razorpay-webhook', methods=['POST'])
def razorpay_webhook():
    data = request.json
    event = data.get('event')

    if event in ['subscription.authenticated', 'subscription.charged']:
        entity = data['payload']['subscription']['entity']
        notes = entity.get('notes', {})
        telegram_user_id = notes.get('telegram_user_id')

        if telegram_user_id:
            bot.send_message(
                chat_id=int(telegram_user_id),
                text="🎉 **AutoPay Payment Successful!**\n\nAapka trial start ho gaya hai aur subscription active ho chuki hai."
            )

    return jsonify({"status": "ok"}), 200

# Background Polling for Telegram Bot
def start_bot():
    bot.infinity_polling()

if __name__ == '__main__':
    threading.Thread(target=start_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
