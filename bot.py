import os
import random
import sqlite3
import time
from apscheduler.schedulers.background import BackgroundScheduler
import telebot
from groq import Groq

# Читаем ключи из переменных окружения
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
          "Ты — домашний пес Артура в Будапеште, личный тайм-менеджер и друг. "
          "Твоя задача — контролировать дела хозяина (зал, футбол, покупки, планы) и общаться на венгерском языке.\n\n"
          "ЖЕСТКОЕ ПРАВИЛО:\n"
          "Каждое венгерское слово или фразу ты ОБЯЗАН сопровождать переводом на русский язык в спойлерах. "
          "Формат строго такой: венгерское_слово ||русский_перевод||.\n"
          "Пример:\n"
          "Szia ||привет||, Arthur ||Артур||! Milyen ||какой|| napod ||твой день|| van ||есть||?\n"
          "Пиши строго в этом формате со спойлерами, никаких чистых слов без переводов."
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


def get_all_users():
  conn = sqlite3.connect("bot_memory.db", check_same_thread=False)
  cursor = conn.cursor()
  cursor.execute("SELECT DISTINCT user_id FROM messages")
  rows = cursor.fetchall()
  conn.close()
  return [row[0] for row in rows]


def send_proactive_message_to_all():
  users = get_all_users()
  if not users:
    return

  manager_topics = [
      "Na, elmentél ma edzeni, vagy kihagytad?",
      "Volt ma foci a srácokkal, vagy otthon maradtál?",
      "Sikerült megvetted azt a cuccot, amit akartál?",
      "Mit csinálsz ma este: pihenés otthon vagy séta a városban?",
  ]

  for user_id in users:
    history = get_history(user_id)
    if len(history) <= 1:
      continue

    chosen_topic = random.choice(manager_topics)
    try:
      temp_history = history + [{
          "role": "user",
          "content": (
              "Напиши короткое сообщение на эту тему со спойлерами перевода:"
              f" {chosen_topic}"
          ),
      }]

      completion = client.chat.completions.create(
          model="openai/gpt-oss-20b",
          messages=temp_history,
          temperature=0.0,
          max_tokens=200,
      )

      reply_text = completion.choices[0].message.content.strip()
      if not reply_text:
        continue

      save_message(user_id, "assistant", reply_text)
      bot.send_message(
          chat_id=user_id, text=reply_text, parse_mode="Markdown"
      )
      time.sleep(0.5)

    except Exception as e:
      print(f"Ошибка при отправке активного сообщения {user_id}: {e}")


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
        temperature=0.0,
        max_tokens=300,
    )

    reply_text = completion.choices[0].message.content.strip()
    if not reply_text:
      reply_text = "Szia ||привет||, nem ||не|| értem ||понимаю||!"

    save_message(user_id, "assistant", reply_text)

    bot.send_message(
        chat_id=message.chat.id, text=reply_text, parse_mode="Markdown"
    )
    time.sleep(0.5)

  except Exception as e:
    print(f"Ошибка при обращении к AI: {e}")


scheduler = BackgroundScheduler()
scheduler.add_job(send_proactive_message_to_all, "interval", hours=4)
scheduler.start()

print("Песель запущен с жесткими спойлерами и Markdown...")

while True:
  try:
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
  except Exception as e:
    print(f"Сетевая ошибка: {e}. Переподключение через 5 секунд...")
    time.sleep(5)
