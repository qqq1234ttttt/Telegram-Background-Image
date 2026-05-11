import os
import tempfile
import io
import requests
import base64
from PIL import Image, ImageOps
from flask import Flask, request, jsonify
import telebot
from telebot import types

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
REMOVE_BG_API_KEY = os.getenv("REMOVE_BG_API_KEY")

if not TELEGRAM_TOKEN or not REMOVE_BG_API_KEY:
    raise ValueError("Missing TELEGRAM_TOKEN or REMOVE_BG_API_KEY")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)

user_state = {}
user_foreground_no_bg = {}

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

@bot.message_handler(commands=["start", "reset"])
def start_handler(message):
    chat_id = message.chat.id
    user_state[chat_id] = 0
    if chat_id in user_foreground_no_bg:
        del user_foreground_no_bg[chat_id]
    bot.send_message(chat_id, "👋 နောက်ခံဖျက်ချင်တဲ့ ပုံကို ပို့ပေးပါ။")

@bot.message_handler(content_types=["photo"])
def handle_photo(message):
    chat_id = message.chat.id
    state = user_state.get(chat_id, 0)

    if state == 0:
        bot.reply_to(message, "⏳ နောက်ခံဖျက်နေပါပြီ...")

        try:
            file_info = bot.get_file(message.photo[-1].file_id)
            downloaded_img = bot.download_file(file_info.file_path)

            # API call
            encoded_img = base64.b64encode(downloaded_img).decode('utf-8')
            response = requests.post(
                'https://api.remove.bg/v1.0/removebg',
                data={
                    'image_file_b64': encoded_img,
                    'size': 'auto',
                    'format': 'png'
                },
                headers={'X-Api-Key': REMOVE_BG_API_KEY},
                timeout=30
            )

            # Send debug info to user
            debug_msg = f"📡 API Status: {response.status_code}\n📄 Content-Type: {response.headers.get('Content-Type', 'unknown')}"
            bot.send_message(chat_id, debug_msg)

            if response.status_code != 200:
                bot.reply_to(message, f"❌ API Error: {response.status_code}\n\n{response.text[:200]}")
                return

            # Save and check image
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp.write(response.content)
                temp_path = tmp.name

            img = Image.open(temp_path)
            mode_msg = f"🖼️ Image Mode: {img.mode}"
            bot.send_message(chat_id, mode_msg)

            # Force RGBA
            if img.mode != 'RGBA':
                img = img.convert('RGBA')
                img.save(temp_path)
                bot.send_message(chat_id, "⚠️ Image was not RGBA, converted to RGBA")

            # Send result
            with open(temp_path, "rb") as f:
                bot.send_photo(chat_id, f, caption="✅ နောက်ခံဖျက်ပြီးသား PNG။\n\nနောက်ခံပုံထပ်ပို့ပါ။")

            user_foreground_no_bg[chat_id] = img
            user_state[chat_id] = 1
            os.unlink(temp_path)

        except Exception as e:
            bot.reply_to(message, f"❌ အမှားဖြစ်သွားသည်။\n\nError: {str(e)[:100]}")
            print(f"Error: {e}")

    elif state == 1:
        # ... (background composition code - same as before) ...
        if chat_id not in user_foreground_no_bg:
            bot.reply_to(message, "⚠️ /start နဲ့ ပြန်စပါ။")
            user_state[chat_id] = 0
            return

        bot.reply_to(message, "⏳ နောက်ခံပုံနဲ့ ပေါင်းနေပါပြီ...")

        try:
            file_info = bot.get_file(message.photo[-1].file_id)
            downloaded_bg = bot.download_file(file_info.file_path)

            background = Image.open(io.BytesIO(downloaded_bg)).convert('RGBA')
            foreground = user_foreground_no_bg[chat_id]
            background = ImageOps.fit(background, foreground.size, method=Image.Resampling.LANCZOS)
            result = Image.alpha_composite(background, foreground)

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                result.save(tmp.name)
                result_path = tmp.name

            with open(result_path, "rb") as f:
                bot.send_photo(chat_id, f, caption="✅ ပြီးပါပြီ။ /start နဲ့ ထပ်လုပ်ပါ။")

            os.unlink(result_path)
            del user_foreground_no_bg[chat_id]
            user_state[chat_id] = 0

        except Exception as e:
            bot.reply_to(message, "❌ အမှားဖြစ်သွားသည်။ /start ပြန်နှိပ်ပါ။")
            print(f"Error: {e}")
            if chat_id in user_foreground_no_bg:
                del user_foreground_no_bg[chat_id]
            user_state[chat_id] = 0

    else:
        bot.reply_to(message, "/start နှိပ်ပါ။")
        user_state[chat_id] = 0

@bot.message_handler(func=lambda m: True)
def unknown(message):
    bot.reply_to(message, "/start နှိပ်ပါ။")

if __name__ == "__main__":
    bot.remove_webhook()
    port = int(os.environ.get("PORT", "10000"))
    webhook_url = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME', 'localhost')}/webhook"
    bot.set_webhook(url=webhook_url)
    app.run(host='0.0.0.0', port=port)
