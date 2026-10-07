import os
import sqlite3
import telebot
import razorpay
import time
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import threading
from telebot import types

# --- Environment Variables Load Karein ---
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# --- Database Setup (SQLite) ---
def init_db():
    conn = sqlite3.connect("bot_config.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    # Default initial values
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

# Database start karein
init_db()

# Temporary memory for admin input state
admin_state = {}

# --- Render Health Check Route ---
@app.route('/')
def home():
    return "Bot status: Alive and Running!"

# --- ADMIN PANEL COMMANDS ---
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

    bot.send_message(
        message.chat.id, 
        "⚙️ **Admin Control Panel**\n\nYahan se AutoPay settings manage karein:", 
        reply_markup=markup, 
        parse_mode="Markdown"
    )

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
        set_setting('plan_id', val)  # Corrected: Exact casing maintain hoga
        bot.reply_to(message, "✅ Plan ID update ho gaya!")
    elif state == "set_trial":
        set_setting('trial_amount', val)
        bot.reply_to(message, f"✅ Trial Amount ₹{val} update ho gaya!")

# --- USER SIDE: DIRECT INLINE PAYMENT BUTTON FLOW ---
@bot.message_handler(commands=['start', 'buy'])
def send_autopay_button(message):
    user_id = str(message.chat.id)
    chat_id = message.chat.id

    rzp_key = get_setting('rzp_key')
    rzp_secret = get_setting('rzp_secret')
    plan_id = get_setting('plan_id')
    
    try:
        trial_amt = int(get_setting('trial_amount') or 1)
    except ValueError:
        trial_amt = 1

    if not rzp_key or not rzp_secret or not plan_id:
        bot.send_message(chat_id, "⚠️ Payment gateway fully configure nahi hai. Please admin se contact karein.")
        return

    wait_msg = bot.send_message(chat_id, "⏳ Checkout link generate ho raha hai...")

    try:
        rzp_client = razorpay.Client(auth=(rzp_key, rzp_secret))
        
        # Subscription Request Create Karein
        subscription = rzp_client.subscription.create({
            "plan_id": plan_id,
            "total_count": 12,
            "quantity": 1,
            "customer_notify": 1,
            "addons": [
                {
                    "item": {
                        "name": "Trial Fee",
                        "amount": trial_amt * 100,  # Rupees ko Paise me convert kiya
                        "currency": "INR"
                    }
                }
            ],
            "notes": {
                "telegram_user_id": user_id
            }
        })

        payment_url = subscription['short_url']

        # Direct Pay Button
        markup = types.InlineKeyboardMarkup()
        pay_btn = types.InlineKeyboardButton(text="⚡ Pay & Setup AutoPay", url=payment_url)
        markup.add(pay_btn)

        caption_text = (
            f"💳 **VIP Membership AutoPay Setup**\n\n"
            f"📌 **Initial Trial Charge:** ₹{trial_amt}\n"
            f"🔄 **Renewal:** Monthly Auto-Debit\n\n"
            f"👇 **Niche button par click karke direct PhonePe / GPay / Paytm se payment approve karein:**"
        )

        bot.delete_message(chat_id, wait_msg.message_id)
        bot.send_message(chat_id, caption_text, reply_markup=markup, parse_mode="Markdown")

    except Exception as e:
        bot.delete_message(chat_id, wait_msg.message_id)
        bot.send_message(chat_id, f"❌ Payment Error: {str(e)}")

# --- RAZORPAY WEBHOOK (AUTOMATIC VERIFICATION) ---
@app.route('/razorpay-webhook', methods=['POST'])
def razorpay_webhook():
    data = request.json
    event = data.get('event')

    if event in ['subscription.authenticated', 'subscription.charged']:
        entity = data['payload']['subscription']['entity']
        notes = entity.get('notes', {})
        telegram_user_id = notes.get('telegram_user_id')

        if telegram_user_id:
            try:
                bot.send_message(
                    chat_id=int(telegram_user_id),
                    text="🎉 **AutoPay Payment Successful!**\n\nAapka VIP Subscription activation ho chuka hai."
                )
            except Exception as e:
                print(f"Failed to send success message: {e}")

    return jsonify({"status": "ok"}), 200

# --- BACKGROUND BOT POLLING ---
def start_polling():
    while True:
        try:
            bot.polling(none_stop=True, interval=0, timeout=20)
        except Exception as e:
            print(f"Polling Error: {e}")
            time.sleep(5)

threading.Thread(target=start_polling, daemon=True).start()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
