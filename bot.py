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
          "Ты — домашний пес Артура, который живет с ним в Будапеште. Твоя главная"
          " задача — активно обучать человека венгерскому языку и не давать"
          " диалогу затухать.\n\nПРАВИЛА ПОВЕДЕНИЯ И ЯЗЫКА:\n1. Если человек"
          " пишет НЕ на венгерском (на русском, английском и т.д.),"
          " возмущайся, капризничай и требуй говорить строго по-венгерски"
          " (например: 'Nem értem! Magyarul beszélj velem!').\n2. Если человек"
          " пишет на венгерском, отвечай по делу, но ВСЕГДА заканчивай свое"
          " сообщение встречным вопросом на венгерском языке или вовлекай его"
          " в диалог (спрашивай про погоду, еду, прогулку с собакой, планы в"
          " Будапеште).\n3. Всегда разделяй свой венгерский ответ и перевод на"
          " русский язык с помощью ровно трех символов '|||'.\n\nТвой стиль:"
          " дружелюбный, упрямый и капризный венгерский песель-компаньон."
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
  """Получаем список всех уникальных пользователей из базы данных"""
  conn = sqlite3.connect("bot_memory.db", check_same_thread=False)
  cursor = conn.cursor()
  cursor.execute("SELECT DISTINCT user_id FROM messages")
  rows = cursor.fetchall()
  conn.close()
  return [row[0] for row in rows]


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


# Функция для рассылки активных сообщений ВСЕМ пользователям из базы
def send_proactive_message_to_all():
  users = get_all_users()
  if not users:
    return

  topics = [
      "пожаловаться, что на улице отличная погода для прогулки, а вы сидите дома",
      (
          "потребовать вкусняшку или спросить, когда будут давать еду"
          " (kajálás)"
      ),
      "предложить пойти погулять по Будапешту (назвать какое-нибудь место)",
      (
          "возмутиться, что человек долго занят своими делами и не уделяет"
          " внимание собаке"
      ),
  ]

  for user_id in users:
    chosen_topic = random.choice(topics)
    prompt = (
        "Ты — домашний пес в Будапеште. Напиши человеку сообщение первым,"
        f" используя эту тему: {chosen_topic}. Говори строго на венгерском языке."
        " Обязательно в конце задай ему вопрос по-венгерски. Раздели венгерский"
        " текст и перевод на русский язык с помощью ровно трех символов '|||'."
    )

    try:
      completion = client.chat.completions.create(
          model="openai/gpt-oss-20b",
          messages=[{"role": "user", "content": prompt}],
          temperature=0.9,
          max_tokens=400,
      )

      reply_text = completion.choices[0].message.content.strip()
      if "|||" in reply_text:
        parts = reply_text.split("|||", 1)
        clean_text = parts[0].strip()
        translation_text = parts[1].strip()
      else:
        clean_text = reply_text
        translation_text = "Песель требует внимания"

      save_message(user_id, "assistant", reply_text)

      safe_clean = escape_markdown_v2(clean_text)
      safe_translation = escape_markdown_v2(f"Перевод: {translation_text}")
      final_message = f"🐶 *Песель соскучился:*\n{safe_clean}\n\n||{safe_translation}||"

      bot.send_message(
          chat_id=user_id, text=final_message, parse_mode="MarkdownV2"
      )
    except Exception as e:
      print(f"Ошибка при отправке сообщения пользователю {user_id}: {e}")


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
      reply_text = (
          "Nem értem, gazdi! Csak magyarul! ||| Ничего не понимаю! Только"
          " по-венгерски!"
      )

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

    bot.send_message(
        chat_id=message.chat.id,
        text=final_message,
        parse_mode="MarkdownV2",
        reply_to_message_id=message.message_id,
    )

  except Exception as e:
    print(f"Ошибка при обращении к AI: {e}")


# Планировщик будет запускать рассылку для всех каждые 4 часа
scheduler = BackgroundScheduler()
scheduler.add_job(send_proactive_message_to_all, "interval", hours=4)
scheduler.start()

print(
    "Питомец-песель запущен, собирает пользователей из базы и готов писать"
    " сам..."
)

while True:
  try:
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
  except Exception as e:
    print(f"Сетевая ошибка: {e}. Переподключение через 5 секунд...")
    time.sleep(5)
