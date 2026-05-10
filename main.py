import telebot
from telebot import types
from rembg import remove
from PIL import Image
import logging
import os
import tempfile

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# In-memory storage for user's background choice
user_choice = {}

@bot.message_handler(commands=["start"])
def start_handler(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("အဖြူရောင် ⬜", "အမည်းရောင် ⬛")
    bot.send_message(message.chat.id, "အရင်ဆုံး နောက်ခံအရောင်ရွေးပါ။", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text in ["အဖြူရောင် ⬜", "အမည်းရောင် ⬛"])
def choose_background(message):
    user_choice[message.chat.id] = message.text
    bot.reply_to(message, f"{message.text} ကိုရွေးချယ်ပြီးပါပြီ။\nအခု ဓာတ်ပုံတစ်ပုံပို့ပေးပါ။")

@bot.message_handler(content_types=["photo"])
def handle_photo(message):
    if message.chat.id not in user_choice:
        bot.reply_to(message, "ကျေးဇူးပြုပြီး အရင်ဆုံး နောက်ခံအရောင်ရွေးပါ။")
        return
    
    bot.reply_to(message, "ဓာတ်ပုံကို လုပ်ဆောင်နေပါပြီ... ⏳")
    
    # Download photo
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded = bot.download_file(file_info.file_path)
    
    # Save temp file
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_in:
        temp_in.write(downloaded)
        temp_in_path = temp_in.name
    
    # Remove background
    with open(temp_in_path, "rb") as f:
        input_img = Image.open(f)
        output_img = remove(input_img)
    
    # Create background
    if "အဖြူ" in user_choice[message.chat.id]:
        bg = Image.new('RGBA', output_img.size, (255, 255, 255, 255))
    else:
        bg = Image.new('RGBA', output_img.size, (0, 0, 0, 255))
    
    # Combine
    result = Image.alpha_composite(bg, output_img)
    
    # Save result
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_out:
        result.save(temp_out.name)
        temp_out_path = temp_out.name
    
    # Send result
    with open(temp_out_path, "rb") as f:
        bot.send_photo(message.chat.id, f)
    
    # Cleanup
    os.unlink(temp_in_path)
    os.unlink(temp_out_path)

if __name__ == "__main__":
    bot.polling()
