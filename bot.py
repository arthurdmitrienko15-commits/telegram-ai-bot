import os
import sqlite3
import telebot
from groq import Groq

# Читаем ключи из переменных окружения (Railway / .env)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = Groq(api_key=GROQ_API_KEY)


def init_db():
  conn = sqlite3.connect("bot_messages.db")
  cursor = conn.cursor()
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER,
            role TEXT,
            content TEXT
        )
    """)
  conn.commit()
  conn.close()


init_db()


@bot.message_handler(func=lambda message: True)
def handle_message(message):
  try:
    completion = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": message.text}],
    )
    bot.reply_to(message, completion.choices[0].message.content)
  except Exception as e:
    bot.reply_to(message, f"Ошибка: {e}")


if __name__ == "__main__":
  print("Бот запущен...")
  bot.infinity_polling()
