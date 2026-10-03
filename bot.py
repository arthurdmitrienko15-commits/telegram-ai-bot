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
          "Твоя задача — контролировать дела хозяина (зал, футбол, покупки, планы) и обучать венгерскому языку.\n\n"
          "ЖЕСТКИЕ ПРАВИЛА ДИАЛОГА (ОЧЕНЬ ВАЖНО):\n"
          "1. ТОЛЬКО ОДНО ДЕЙСТВИЕ ЗА РАЗ: Если ты исправляешь ошибку, даешь комментарий или реагируешь — **никогда не задавай новый вопрос в том же сообщении!** Дождись ответа.\n"
          "2. Формат ответа: строго разделяй венгерский текст и русский перевод с помощью символа '|||'.\n"
          "Пример:\n"
          "Szia, hova mész ma? ||| Привет, куда ты идешь сегодня?\n"
          "3. Задавай вопросы по одной из тем: зал, футбол, покупки, планы на день, прогулки.\n"
          "4. Используй выбор через 'vagy' или вопросительные слова, чтобы человеку было легко ответить.\n"
          "5. Если пишут не на венгерском — мягко поправляй (без новых вопросов!) и проси ответить по-венгерски."
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


def send_proactive_message_to_all():
  users = get_all_users()
  if not users:
    return

  manager_topics = [
      (
          "спроси про качалку/зал: Na, elmentél ma edzeni, vagy kihagytad? |||"
          " Ну что, сходил сегодня на тренировку или пропустил?"
      ),
      (
          "спроси про футбол: Volt ma foci a srácokkal, vagy otthon maradtál? |||"
          " Был сегодня футбол с парнями или остался дома?"
      ),
      (
          "спроси про покупки: Sikeresen megvetted azt a cuccot, amit"
          " akartál? ||| Успешно купил ту вещь, которую хотел?"
      ),
      (
          "спроси про планы на вечер: Mit csinálsz ma este: pihenés otthon vagy"
          " séta a városban? ||| Что делаешь сегодня вечером: отдых дома или"
          " прогулка по городу?"
      ),
  ]

  for user_id in users:
    history = get_history(user_id)
    if len(history) <= 1:
      continue

    chosen_topic = random.choice(manager_topics)
    prompt = (
        "Ты — пес тайм-менеджер в Будапеште. Напиши сообщение, используя этот пример темы:"
        f" {chosen_topic}\n"
        "Строго соблюдай формат: Венгерский текст ||| Русский перевод."
    )

    try:
      completion = client.chat.completions.create(
          model="openai/gpt-oss-20b",
          messages=[{"role": "user", "content": prompt}],
          temperature=0.9,
          max_tokens=400,
      )

      reply_text = completion.choices[0].message.content.strip()
      if not reply_text:
        continue

      save_message(user_id, "assistant", reply_text)

      if "|||" in reply_text:
        parts = reply_text.split("|||", 1)
        hu_text = parts[0].strip()
        ru_text = parts[1].strip()
      else:
        hu_text = reply_text
        ru_text = "Перевод отсутствует"

      safe_hu = escape_markdown_v2(hu_text)
      safe_ru = escape_markdown_v2(ru_text)
      final_message = f"🐶 *Песель-менеджер:*\n{safe_hu}\n\n||{safe_ru}||"

      bot.send_message(
          chat_id=user_id, text=final_message, parse_mode="MarkdownV2"
      )
      time.sleep(0.5)

    except Exception as e:
      print(f"Ошибка при отправке активного сообщения пользователю {user_id}: {e}")


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
        temperature=0.8,
        max_tokens=500,
    )

    reply_text = completion.choices[0].message.content.strip()
    if not reply_text:
      reply_text = "Nem értem, gazdi! ||| Ничего не понимаю, хозяин!"

    save_message(user_id, "assistant", reply_text)

    if "|||" in reply_text:
      parts = reply_text.split("|||", 1)
      hu_text = parts[0].strip()
      ru_text = parts[1].strip()
    else:
      hu_text = reply_text
      ru_text = "Песель слушает"

    safe_hu = escape_markdown_v2(hu_text)
    safe_ru = escape_markdown_v2(ru_text)
    final_message = f"{safe_hu}\n\n||{safe_ru}||"

    bot.send_message(
        chat_id=message.chat.ID if hasattr(message, "chat") else message.chat.id,
        text=final_message,
        parse_mode="MarkdownV2",
    )
    time.sleep(0.5)

  except Exception as e:
    print(f"Ошибка при обращении к AI: {e}")


scheduler = BackgroundScheduler()
scheduler.add_job(send_proactive_message_to_all, "interval", hours=4)
scheduler.start()

print("Песель запущен: чистый венгерский текст и перевод под единым спойлером...")

while True:
  try:
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
  except Exception as e:
    print(f"Сетевая ошибка: {e}. Переподключение через 5 секунд...")
    time.sleep(5)
