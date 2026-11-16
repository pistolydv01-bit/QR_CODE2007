import os
import time
import pickle
import telebot
from telebot import types
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
bot = telebot.TeleBot(TOKEN)

# यूजर के लिए मेनू कीबोर्ड
def main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("🎨 Generate Image"))
    return markup

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.send_message(
        message.chat.id, 
        "नमस्ते! चैटजीपीटी इमेज जनरेटर बोट में आपका स्वागत है। नीचे दिए गए बटन पर क्लिक करें:", 
        reply_markup=main_menu()
    )

@bot.message_handler(func=lambda message: message.text == "🎨 Generate Image")
def ask_for_prompt(message):
    msg = bot.send_message(message.chat.id, "कृपया वह विषय या विवरण भेजें जिसके लिए आप इमेज बनाना चाहते हैं:")
    bot.register_next_step_handler(msg, process_image_generation)

def process_image_generation(message):
    user_prompt = message.text
    chat_id = message.chat.id
    
    bot.send_message(chat_id, "⏳ आपकी इमेज जनरेट हो रही है, कृपया प्रतीक्षा करें (इसमें 1-2 मिनट लग सकते हैं)...")

    image_path = generate_image_with_cookies(user_prompt, chat_id)

    if image_path and os.path.exists(image_path):
        with open(image_path, 'rb') as img:
            bot.send_photo(chat_id, img, caption="✨ लीजिए आपकी जनरेट की गई इमेज तैयार है!")
        os.remove(image_path) # भेजने के बाद लोकल फाइल डिलीट करें
    else:
        bot.send_message(chat_id, "❌ इमेज जनरेट करने में विफल रहा। कृपया कुकीज़ या नेटवर्क जांचें।")

def generate_image_with_cookies(prompt_text, chat_id):
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")  # रेंडर के लिए हेडलेस जरूरी है
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    
    if os.path.exists("/usr/bin/chromium"):
        chrome_options.binary_location = "/usr/bin/chromium"

    driver = webdriver.Chrome(options=chrome_options)

    try:
        # 1. पहले वेबसाइट खोलें
        driver.get("https://chatgpt.com/")
        time.sleep(3)

        # 2. कुकीज़ लोड करें (ताकि लॉगिन करने की जरूरत न पड़े)
        if os.path.exists("chatgpt_cookies.pkl"):
            with open("chatgpt_cookies.pkl", "rb") as f:
                cookies = pickle.load(f)
                for cookie in cookies:
                    if 'expiry' in cookie:
                        del cookie['expiry']
                    driver.add_cookie(cookie)
            
            driver.refresh()
            time.sleep(5)
        else:
            print("⚠️ चेतावनी: 'chatgpt_cookies.pkl' फाइल नहीं मिली!")

        # 3. चैट बॉक्स ढूंढकर प्रॉम्प्ट टाइप करें
        chat_box = WebDriverWait(driver, 25).until(
            EC.presence_of_element_located((By.XPATH, "//div[@id='prompt-textarea']"))
        )
        
        default_prefix = os.getenv("DEFAULT_PROMPT", "Generate an image of:")
        final_prompt = f"{default_prefix} {prompt_text}"
        
        chat_box.click()
        chat_box.send_keys(final_prompt)
        chat_box.send_keys(Keys.RETURN)

        # 4. इमेज जनरेट होने का इंतज़ार
        print("⏳ इमेज जनरेट हो रही है...")
        time.sleep(35) 

        # 5. जनरेट हुई इमेज का स्क्रीनशॉट लेना
        img_element = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.XPATH, "//img[contains(@alt, 'Generated') or contains(@class, 'rounded')]"))
        )
        
        local_image_path = f"generated_img_{chat_id}.png"
        img_element.screenshot(local_image_path)

        driver.quit()
        return local_image_path

    except Exception as e:
        print(f"❌ Selenium Error: {e}")
        try:
            driver.quit()
        except:
            pass
        return None

if __name__ == "__main__":
    print("🚀 टेलीग्राम बोट आरंभ हो गया है...")
    bot.infinity_polling(skip_pending=True)
