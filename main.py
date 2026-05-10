import telebot
from telebot import types
from PIL import Image, ImageOps
import os
import tempfile
import io
import requests

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
REMOVE_BG_API_KEY = os.getenv("REMOVE_BG_API_KEY")

if not TELEGRAM_TOKEN or not REMOVE_BG_API_KEY:
    raise ValueError("Missing TELEGRAM_TOKEN or REMOVE_BG_API_KEY env variable")

bot = telebot.TeleBot(TELEGRAM_TOKEN)

# user state: 0 = waiting for background image, 1 = waiting for main image (background already received)
user_state = {}
# store temporary background image path for each user
user_bg_path = {}

@bot.message_handler(commands=["start", "reset"])
def start_handler(message):
    chat_id = message.chat.id
    user_state[chat_id] = 0
    if chat_id in user_bg_path:
        try:
            os.unlink(user_bg_path[chat_id])
        except:
            pass
        del user_bg_path[chat_id]
    bot.send_message(chat_id, "👋 နှုတ်ဆက်ပါတယ်။\n\nအဆင့် ၁: နောက်ခံအနေနဲ့ ထားချင်တဲ့ ပုံကို အရင်ပို့ပေးပါ။")

@bot.message_handler(content_types=["photo"])
def handle_photo(message):
    chat_id = message.chat.id
    state = user_state.get(chat_id, 0)
    
    # Case 1: Waiting for background image
    if state == 0:
        # Download background image
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded = bot.download_file(file_info.file_path)
        
        # Save as temp file
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(downloaded)
            bg_path = tmp.name
        
        user_bg_path[chat_id] = bg_path
        user_state[chat_id] = 1
        
        bot.reply_to(message, "✅ နောက်ခံပုံကို သိမ်းဆည်းပြီးပါပြီ။\n\nအဆင့် ၂: နောက်ခံဖျောက်ချင်တဲ့ ပုံကို ပို့ပေးပါ။")
    
    # Case 2: Waiting for main image (to remove background)
    elif state == 1:
        if chat_id not in user_bg_path:
            bot.reply_to(message, "⚠️ နောက်ခံပုံ မရှိပါ။ /start နဲ့ ပြန်စပါ။")
            user_state[chat_id] = 0
            return
        
        bot.reply_to(message, "⏳ ပုံကို လုပ်ဆောင်နေပါပြီ... (စက္ကန့် ၂၀ ခန့်ကြာနိုင်ပါသည်)")
        
        try:
            # 1. Download main image from user
            file_info = bot.get_file(message.photo[-1].file_id)
            downloaded_img = bot.download_file(file_info.file_path)
            
            # 2. Call Remove.bg API
            response = requests.post(
                'https://api.remove.bg/v1.0/removebg',
                files={'image_file': ('image.png', downloaded_img, 'image/png')},
                data={'size': 'auto'},
                headers={'X-Api-Key': REMOVE_BG_API_KEY},
            )
            
            if response.status_code != 200:
                bot.reply_to(message, f"❌ API အလုပ်မလုပ်ပါ။ Error: {response.status_code}")
                return
            
            # 3. Convert result to PIL image with transparency
            foreground = Image.open(io.BytesIO(response.content)).convert('RGBA')
            
            # 4. Load background image (user uploaded)
            background = Image.open(user_bg_path[chat_id]).convert('RGBA')
            # Resize background to exactly match foreground size (cover style)
            background = ImageOps.fit(background, foreground.size, method=Image.Resampling.LANCZOS)
            
            # 5. Composite: put foreground on top of background
            result = Image.alpha_composite(background, foreground)
            
            # 6. Save result to temp file
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                result.save(tmp.name)
                result_path = tmp.name
            
            # 7. Send result
            with open(result_path, "rb") as f:
                bot.send_photo(chat_id, f, caption="✅ ပြီးပါပြီ။ နောက်တစ်ခါထပ်လုပ်ရန် /start နှိပ်ပါ။")
            
            # 8. Cleanup
            os.unlink(result_path)
            os.unlink(user_bg_path[chat_id])
            del user_bg_path[chat_id]
            user_state[chat_id] = 0
            
        except Exception as e:
            bot.reply_to(message, "❌ အမှားတစ်ခု ဖြစ်သွားပါသည်။ /start နဲ့ ပြန်စပါ။")
            print(f"Error: {e}")
            # Cleanup on error
            if chat_id in user_bg_path:
                try:
                    os.unlink(user_bg_path[chat_id])
                except:
                    pass
                del user_bg_path[chat_id]
            user_state[chat_id] = 0
    else:
        bot.reply_to(message, "ကျေးဇူးပြုပြီး /start နဲ့ ပြန်စတင်ပါ။")
        user_state[chat_id] = 0

# Fallback for other messages
@bot.message_handler(func=lambda m: True)
def unknown(message):
    bot.reply_to(message, "📌 ကျေးဇူးပြု၍ /start နှိပ်ပြီး ပုံများကို အဆင့်အတိုင်းပို့ပါ။")

if __name__ == "__main__":
    bot.infinity_polling()
