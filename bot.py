import telebot
from google import genai
import time
import os

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8926102288:AAGfDPfbXE0j1kycZCB_Zd_USDpsu5v17wY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AIzaSyBtFftYldCrnsuoYIAmh-uAgnEZd44Q_0g")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = genai.Client(api_key=GEMINI_API_KEY)

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    for attempt in range(10):
        try:
            response = client.models.generate_content(
                model="gemini-3.5-flash",
                contents=message.text,
            )
            bot.reply_to(message, response.text)
            return
        except Exception as e:
            if "503" in str(e) and attempt < 9:
                time.sleep(2)
                continue
            elif "429" in str(e) and attempt < 9:
                time.sleep(5)
                continue
            else:
                bot.reply_to(message, f"Ошибка: {e}")
                break

print("Бот успешно запущен в облаке...")
bot.infinity_polling()
