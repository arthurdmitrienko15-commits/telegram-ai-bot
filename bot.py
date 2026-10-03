import os
import sqlite3
import time
import telebot
from groq import Groq

# Читаем ключи из переменных окружения (безопасно для Railway и GitHub)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = Groq(api_key=GROQ_API_KEY)


def init_db():
  conn = sqlite3.connect("bot_memory.db", check_same_thread=False)
  cursor = conn.cursor()
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            user_id INTEGER,
            role TEXT,
            content TEXT
        )
    """)
  conn.commit()
  conn.close()


init_db()


def get_history(user_id):
  conn = sqlite3.connect("bot_memory.db", check_same_thread=False)
  cursor = conn.cursor()
  cursor.execute(
      "SELECT role, content FROM messages WHERE user_id = ?", (user_id,)
  )
  rows = cursor.fetchall()
  conn.close()

  history = [{
      "role": "system",
      "content": (
          "Ты — домашний пес Артура, который живет с ним в Будапеште. Отвечай"
          " ВСЕГДА осмысленно и по делу на то, что тебе пишут, общаясь строго на"
          " венгерском языке. Твой стиль: дружелюбный, живой, иногда капризный"
          " песель. ФОРМАТ ОТВЕТА: ты обязан разделить свой венгерский ответ и"
          " перевод с помощью ровно трех символов '|||'. Пример: Szia, gazdi!"
          " ||| Привет, хозяин!"
      ),
  }]

  for role, content in rows:
    history.append({"role": role, "content": content})
  return history


def save_message(user_id, role, content):
  conn = sqlite3.connect("bot_memory.db", check_same_thread=False)
  cursor = conn.cursor()
  cursor.execute(
      "INSERT INTO messages (user_id, role, content) VALUES (?, ?, ?)",
      (user_id, role, content),
  )
  conn.commit()
  conn.close()


# Функция для экранирования спецсимволов MarkdownV2, чтобы Telegram не падал с ошибкой
def escape_markdown_v2(text):
  special_chars = [
      "_",
      "*",
      "[",
      "]",
      "(",
      ")",
      "~",
      "`",
      ">",
      "#",
      "+",
      "-",
      "=",
      "|",
      "{",
      "}",
      ".",
      "!",
  ]
  for char in special_chars:
    text = text.replace(char, f"\\{char}")
  return text


@bot.message_handler(func=lambda message: True)
def handle_message(message):
  user_id = message.from_user.id
  text = message.text

  try:
    bot.send_chat_action(message.chat.id, "typing")
  except Exception:
    pass

  save_message(user_id, "user", text)
  history = get_history(user_id)

  if len(history) > 26:
    history = [history[0]] + history[-25:]

  try:
    completion = client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=history,
        temperature=0.85,
        max_tokens=800,
    )

    reply_text = completion.choices[0].message.content.strip()
    if not reply_text:
      reply_text = "Szia, Артур! ||| Привет, Артур!"

    if "|||" in reply_text:
      parts = reply_text.split("|||", 1)
      clean_text = parts[0].strip()
      translation_text = parts[1].strip()
    else:
      clean_text = reply_text
      translation_text = "Песель лает от переизбытка чувств"

    save_message(user_id, "assistant", reply_text)

    safe_clean = escape_markdown_v2(clean_text)
    safe_translation = escape_markdown_v2(f"Перевод: {translation_text}")

    final_message = f"{safe_clean}\n\n||{safe_translation}||"

    try:
      bot.send_message(
          chat_id=message.chat.id,
          text=final_message,
          parse_mode="MarkdownV2",
          reply_to_message_id=message.message_id,
      )
    except Exception as send_err:
      print(f"Ошибка отправки сообщения: {send_err}")

  except Exception as e:
    print(f"Ошибка при обращении к AI: {e}")


print("Питомец-песель запущен и ждет Артура...")

while True:
  try:
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
  except Exception as e:
    print(f"Сетевая ошибка: {e}. Переподключение через 5 секунд...")
    time.sleep(5)
