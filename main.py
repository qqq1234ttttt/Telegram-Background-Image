import os
import tempfile
import io
import requests
from PIL import Image, ImageOps
from flask import Flask, request, jsonify
import telebot
from telebot import types

# ==================== 1. CONFIGURATION ====================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
REMOVE_BG_API_KEY = os.getenv("REMOVE_BG_API_KEY")

if not TELEGRAM_TOKEN or not REMOVE_BG_API_KEY:
    raise ValueError("Missing TELEGRAM_TOKEN or REMOVE_BG_API_KEY env variable")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)

# User state: 0 = waiting for first image, 1 = waiting for background image
user_state = {}
user_foreground_no_bg = {}  # store the image with background removed (PIL Image)

# ==================== 2. WEBHOOK ENDPOINT ====================
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        json_str = request.get_data().decode('UTF-8')
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        print(f"Webhook error: {e}")
        return jsonify({"status": "error"}), 500

# ==================== 3. BOT HANDLERS ====================
@bot.message_handler(commands=["start", "reset"])
def start_handler(message):
    chat_id = message.chat.id
    user_state[chat_id] = 0
    if chat_id in user_foreground_no_bg:
        del user_foreground_no_bg[chat_id]
    bot.send_message(chat_id, "👋 နှုတ်ဆက်ပါတယ်။\n\nနောက်ခံဖျက်ချင်တဲ့ ပုံကို ပို့ပေးပါ။")

@bot.message_handler(content_types=["photo"])
def handle_photo(message):
    chat_id = message.chat.id
    state = user_state.get(chat_id, 0)

    # Case 1: User sends first photo (need to remove background)
    if state == 0:
        bot.reply_to(message, "⏳ နောက်ခံဖျက်နေပါပြီ...")

        try:
            # Download the image
            file_info = bot.get_file(message.photo[-1].file_id)
            downloaded_img = bot.download_file(file_info.file_path)

            # ⭐⭐⭐ FORCE PNG OUTPUT - FIXED VERSION ⭐⭐⭐
            response = requests.post(
                'https://api.remove.bg/v1.0/removebg',
                files={'image_file': ('image.png', downloaded_img, 'image/png')},
                data={
                    'size': 'auto',
                    'format': 'png',
                    'image_file': 'image.png'
                },
                headers={'X-Api-Key': REMOVE_BG_API_KEY},
            )

            if response.status_code != 200:
                bot.reply_to(message, f"❌ API Error: {response.status_code}")
                return

            # Log content type for debugging
            content_type = response.headers.get('Content-Type', '')
            print(f"Content-Type: {content_type}")

            # Save as PNG
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp.write(response.content)
                temp_path = tmp.name

            # Check image mode
            img_check = Image.open(temp_path)
            print(f"Image Mode: {img_check.mode}")  # Should be RGBA for transparent

            # Ensure RGBA mode (transparent)
            if img_check.mode != 'RGBA':
                img_check = img_check.convert('RGBA')
                img_check.save(temp_path)

            # Send the transparent background image to user
            with open(temp_path, "rb") as f:
                bot.send_photo(
                    chat_id, 
                    f, 
                    caption="✅ နောက်ခံဖျက်ပြီးသား ပုံပါ။\n\n📌 ဒီပုံကို Save လိုက်ရင် PNG format အတိုင်း နောက်ခံမပါဘဲ သိမ်းပါလိမ့်မယ်။\n\nအခု ဒီပုံပေါ်မှာ ထည့်ချင်တဲ့ **နောက်ခံပုံ** ကို ထပ်ပို့ပေးပါ။"
                )

            # Store the image for later composition
            user_foreground_no_bg[chat_id] = Image.open(temp_path).convert('RGBA')
            user_state[chat_id] = 1

            # Cleanup temp file
            os.unlink(temp_path)

        except Exception as e:
            bot.reply_to(message, f"❌ အမှားဖြစ်သွားပါသည်။ /start နဲ့ ပြန်စပါ။")
            print(f"Error: {e}")

    # Case 2: User sends background image (after receiving first result)
    elif state == 1:
        if chat_id not in user_foreground_no_bg:
            bot.reply_to(message, "⚠️ နောက်ခံဖျက်ပြီးသားပုံ မရှိပါ။ /start နဲ့ ပြန်စပါ။")
            user_state[chat_id] = 0
            return

        bot.reply_to(message, "⏳ နောက်ခံပုံနဲ့ ပေါင်းနေပါပြီ...")

        try:
            # Download background image from user
            file_info = bot.get_file(message.photo[-1].file_id)
            downloaded_bg = bot.download_file(file_info.file_path)

            # Load background image
            background = Image.open(io.BytesIO(downloaded_bg)).convert('RGBA')

            # Get the foreground image (background already removed)
            foreground = user_foreground_no_bg[chat_id]

            # Resize background to match foreground size
            background = ImageOps.fit(background, foreground.size, method=Image.Resampling.LANCZOS)

            # Composite: put foreground on top of background
            result = Image.alpha_composite(background, foreground)

            # Save result
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                result.save(tmp.name)
                result_path = tmp.name

            # Send final result
            with open(result_path, "rb") as f:
                bot.send_photo(chat_id, f, caption="✅ ပြီးပါပြီ။ /start နဲ့ ထပ်လုပ်ပါ။")

            # Cleanup
            os.unlink(result_path)
            del user_foreground_no_bg[chat_id]
            user_state[chat_id] = 0

        except Exception as e:
            bot.reply_to(message, "❌ အမှားဖြစ်သွားပါသည်။ /start နဲ့ ပြန်စပါ။")
            print(f"Error: {e}")
            if chat_id in user_foreground_no_bg:
                del user_foreground_no_bg[chat_id]
            user_state[chat_id] = 0

    else:
        bot.reply_to(message, "📌 /start နှိပ်ပြီး ပြန်စတင်ပါ။")
        user_state[chat_id] = 0

@bot.message_handler(func=lambda m: True)
def unknown(message):
    bot.reply_to(message, "📌 /start နှိပ်ပြီး ပုံများကို အဆင့်အတိုင်းပို့ပါ။")

# ==================== 4. START SERVER ====================
if __name__ == "__main__":
    # Remove any existing webhook
    bot.remove_webhook()
    
    # Set webhook
    port = int(os.environ.get("PORT", "10000"))
    webhook_url = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME', 'localhost')}/webhook"
    
    bot.set_webhook(url=webhook_url)
    print(f"Webhook set to: {webhook_url}")
    
    # Start Flask server
    app.run(host='0.0.0.0', port=port)
