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

user_state = {}          # 0 = waiting for format, 1 = waiting for first image, 2 = waiting for background image
user_format = {}         # store selected format: 'png' or 'jpg'
user_foreground_no_bg = {}  # store the image content (bytes)

# ==================== WEBHOOK ====================
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

# ==================== START COMMAND ====================
@bot.message_handler(commands=["start", "reset"])
def start_handler(message):
    chat_id = message.chat.id
    user_state[chat_id] = 0
    user_format[chat_id] = None
    if chat_id in user_foreground_no_bg:
        del user_foreground_no_bg[chat_id]
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    btn_png = types.KeyboardButton("🔘 နောက်ခံမပါ (PNG - Transparent)")
    btn_jpg = types.KeyboardButton("⚪ နောက်ခံအဖြူ (JPG)")
    markup.add(btn_png, btn_jpg)
    
    bot.send_message(chat_id, "👋မင်္ဂလာပါ KMT Bot မှကြိုဆိုပါတယ်။\n\nဘယ်လို Output မျိုး လိုချင်လဲ ရွေးပါ။", reply_markup=markup)

# ==================== FORMAT SELECTION ====================
@bot.message_handler(func=lambda m: m.text in ["🔘 နောက်ခံမပါ (PNG - Transparent)", "⚪ နောက်ခံအဖြူ (JPG)"])
def format_handler(message):
    chat_id = message.chat.id
    if message.text == "🔘 နောက်ခံမပါ (PNG - Transparent)":
        user_format[chat_id] = "png"
        bot.reply_to(message, "✅ **PNG (Transparent)** ကို ရွေးချယ်ပြီးပါပြီ။\n\nအခု နောက်ခံဖျက်ချင်တဲ့ ပုံကို ပို့ပေးပါ။", parse_mode="Markdown")
    else:
        user_format[chat_id] = "jpg"
        bot.reply_to(message, "✅ **JPG (နောက်ခံအဖြူ)** ကို ရွေးချယ်ပြီးပါပြီ။\n\nအခု နောက်ခံဖျက်ချင်တဲ့ ပုံကို ပို့ပေးပါ။", parse_mode="Markdown")
    
    user_state[chat_id] = 1

# ==================== PHOTO HANDLER ====================
@bot.message_handler(content_types=["photo"])
def handle_photo(message):
    chat_id = message.chat.id
    state = user_state.get(chat_id, 0)

    # Case: Waiting for first image (after format selected)
    if state == 1:
        if user_format.get(chat_id) not in ["png", "jpg"]:
            bot.reply_to(message, "⚠️ ကျေးဇူးပြုပြီး /start နဲ့ ပြန်စပါ။")
            return

        bot.reply_to(message, "⏳ နောက်ခံဖျက်နေပါပြီ... (စက္ကန့် ၃၀ အထိ ကြာနိုင်ပါသည်)")

        try:
            file_info = bot.get_file(message.photo[-1].file_id)
            downloaded_img = bot.download_file(file_info.file_path)
            output_format = user_format[chat_id]

            # API Call
            encoded_img = base64.b64encode(downloaded_img).decode('utf-8')
            response = requests.post(
                'https://api.remove.bg/v1.0/removebg',
                data={
                    'image_file_b64': encoded_img,
                    'size': 'auto',
                    'format': output_format
                },
                headers={'X-Api-Key': REMOVE_BG_API_KEY},
                timeout=30
            )

            if response.status_code != 200:
                bot.reply_to(message, f"❌ API Error: {response.status_code}")
                return

            # Store the image content for later use (background composition)
            user_foreground_no_bg[chat_id] = response.content

            # Send result based on format
            if output_format == "png":
                # Send as DOCUMENT to preserve transparency
                bot.send_document(
                    chat_id,
                    ("foreground.png", response.content),
                    caption="✅ နောက်ခံဖျက်ပြီးသား **PNG (Transparent)** ဖိုင်။\n\nSave လုပ်ပြီး Picsart/Photoshop နဲ့ ဖွင့်ကြည့်ပါ။\n\nအခု **နောက်ခံပုံ** ကို ထပ်ပို့ပေးပါ။"
                )
            else:
                # Send as PHOTO (JPG with white background)
                bot.send_photo(
                    chat_id,
                    response.content,
                    caption="✅ နောက်ခံဖျက်ပြီးသား **JPG (နောက်ခံအဖြူ)** ပုံ။\n\nအခု **နောက်ခံပုံ** ကို ထပ်ပို့ပေးပါ။"
                )

            user_state[chat_id] = 2  # wait for background image

        except Exception as e:
            bot.reply_to(message, f"❌ Error: {str(e)[:100]}")
            print(f"Error: {e}")

    # Case: Waiting for background image (after getting foreground)
    elif state == 2:
        if chat_id not in user_foreground_no_bg:
            bot.reply_to(message, "⚠️ /start နဲ့ ပြန်စပါ။")
            user_state[chat_id] = 0
            return

        bot.reply_to(message, "⏳ နောက်ခံပုံနဲ့ ပေါင်းနေပါပြီ...")

        try:
            # Download background image
            file_info = bot.get_file(message.photo[-1].file_id)
            downloaded_bg = bot.download_file(file_info.file_path)

            # Load background as RGBA
            background = Image.open(io.BytesIO(downloaded_bg)).convert('RGBA')
            
            # ⭐ CRITICAL FIX: Load foreground and force convert to RGBA
            # First, save the stored bytes to a BytesIO object
            foreground_bytes = io.BytesIO(user_foreground_no_bg[chat_id])
            foreground = Image.open(foreground_bytes).convert('RGBA')
            
            # Resize background to match foreground
            background = ImageOps.fit(background, foreground.size, method=Image.Resampling.LANCZOS)
            
            # Composite (foreground on top of background)
            result = Image.alpha_composite(background, foreground)

            # Save result as PNG (preserve transparency)
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                result.save(tmp.name, format='PNG')
                result_path = tmp.name

            # Send final result
            with open(result_path, "rb") as f:
                bot.send_photo(chat_id, f, caption="✅ ပြီးပါပြီ။ /start နဲ့ ထပ်လုပ်ပါ။")

            # Cleanup
            os.unlink(result_path)
            del user_foreground_no_bg[chat_id]
            user_state[chat_id] = 0
            user_format[chat_id] = None

        except Exception as e:
            error_msg = f"❌ အမှားဖြစ်သွားသည်။\n\nError: {str(e)[:150]}"
            bot.reply_to(message, error_msg)
            print(f"Error: {e}")
            if chat_id in user_foreground_no_bg:
                del user_foreground_no_bg[chat_id]
            user_state[chat_id] = 0

    else:
        bot.reply_to(message, "📌 /start နှိပ်ပြီး Format ကို အရင်ရွေးပါ။")

# ==================== FALLBACK ====================
@bot.message_handler(func=lambda m: True)
def unknown(message):
    bot.reply_to(message, "📌 /start နှိပ်ပြီး Format ကို အရင်ရွေးပါ။")

# ==================== START SERVER ====================
if __name__ == "__main__":
    bot.remove_webhook()
    port = int(os.environ.get("PORT", "10000"))
    webhook_url = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME', 'localhost')}/webhook"
    bot.set_webhook(url=webhook_url)
    print(f"Webhook set to: {webhook_url}")
    app.run(host='0.0.0.0', port=port)
