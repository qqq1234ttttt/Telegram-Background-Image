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

# User state management
user_state = {}      # 0 = waiting for bg, 1 = waiting for main image
user_bg_path = {}    # store background image temp path

# ==================== 2. WEBHOOK ENDPOINT ====================
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        # Get update from Telegram
        json_str = request.get_data().decode('UTF-8')
        update = telebot.types.Update.de_json(json_str)
        
        # Process the update
        bot.process_new_updates([update])
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        print(f"Webhook error: {e}")
        return jsonify({"status": "error"}), 500

# ==================== 3. BOT HANDLERS (same as before) ====================
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

    if state == 0:
        # Download background image
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded = bot.download_file(file_info.file_path)

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(downloaded)
            bg_path = tmp.name

        user_bg_path[chat_id] = bg_path
        user_state[chat_id] = 1

        bot.reply_to(message, "✅ နောက်ခံပုံကို သိမ်းဆည်းပြီးပါပြီ။\n\nအဆင့် ၂: နောက်ခံဖျောက်ချင်တဲ့ ပုံကို ပို့ပေးပါ။")

    elif state == 1:
        if chat_id not in user_bg_path:
            bot.reply_to(message, "⚠️ နောက်ခံပုံ မရှိပါ။ /start နဲ့ ပြန်စပါ။")
            user_state[chat_id] = 0
            return

        bot.reply_to(message, "⏳ ပုံကို လုပ်ဆောင်နေပါပြီ...")

        try:
            # Download main image
            file_info = bot.get_file(message.photo[-1].file_id)
            downloaded_img = bot.download_file(file_info.file_path)

            # Call Remove.bg API
            response = requests.post(
                'https://api.remove.bg/v1.0/removebg',
                files={'image_file': ('image.png', downloaded_img, 'image/png')},
                data={'size': 'auto'},
                headers={'X-Api-Key': REMOVE_BG_API_KEY},
            )

            if response.status_code != 200:
                bot.reply_to(message, f"❌ API Error: {response.status_code}")
                return

            foreground = Image.open(io.BytesIO(response.content)).convert('RGBA')

            # Load and resize background
            background = Image.open(user_bg_path[chat_id]).convert('RGBA')
            background = ImageOps.fit(background, foreground.size, method=Image.Resampling.LANCZOS)

            # Composite
            result = Image.alpha_composite(background, foreground)

            # Save result
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                result.save(tmp.name)
                result_path = tmp.name

            # Send result
            with open(result_path, "rb") as f:
                bot.send_photo(chat_id, f, caption="✅ ပြီးပါပြီ။ /start နဲ့ ထပ်လုပ်ပါ။")

            # Cleanup
            os.unlink(result_path)
            os.unlink(user_bg_path[chat_id])
            del user_bg_path[chat_id]
            user_state[chat_id] = 0

        except Exception as e:
            bot.reply_to(message, "❌ အမှားဖြစ်သွားပါသည်။ /start နဲ့ ပြန်စပါ။")
            print(f"Error: {e}")
            if chat_id in user_bg_path:
                try:
                    os.unlink(user_bg_path[chat_id])
                except:
                    pass
                del user_bg_path[chat_id]
            user_state[chat_id] = 0

@bot.message_handler(func=lambda m: True)
def unknown(message):
    bot.reply_to(message, "📌 /start နှိပ်ပြီး ပုံများကို အဆင့်အတိုင်းပို့ပါ။")

# ==================== 4. START SERVER ====================
if __name__ == "__main__":
    # Remove any existing webhook
    bot.remove_webhook()
    
    # Set webhook (Render provides PORT env variable)
    port = int(os.environ.get("PORT", "10000"))
    webhook_url = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME', 'localhost')}/webhook"
    
    bot.set_webhook(url=webhook_url)
    print(f"Webhook set to: {webhook_url}")
    
    # Start Flask server
    app.run(host='0.0.0.0', port=port)
