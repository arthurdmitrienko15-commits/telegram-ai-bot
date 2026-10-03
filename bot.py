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
          "ПРАВИЛА:\n"
          "1. Отвечай СТРОГО на венгерском языке.\n"
          "2. Пиши короткими, понятными предложениями."
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


def add_spoilers_programmatically(hungarian_text):
  """Жестко заставляет модель перевести каждое слово в формате слово=перевод,

  после чего Python сам собирает строку со спойлерами. Никаких ошибок тегов.
  """
  try:
    prompt = (
        f'Переведи каждое слово из этого венгерского предложения: "{hungarian_text}"\n'
        "Выдай ответ СТРОГО в формате пар слово-перевод через запятую, например:\n"
        "Szia=привет, Arthur=Артур, miben=в чем\n"
        "Не пиши ничего лишнего, только пары слово=перевод."
    )
    completion = client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=300,
    )
    raw_res = completion.choices[0].message.content.strip()

    # Парсим пары слово=перевод
    translations = {}
    pairs = raw_res.split(",")
    for pair in pairs:
      if "=" in pair:
        parts = pair.split("=")
        if len(parts) == 2:
          word = parts[0].strip()
          translation = parts[1].strip()
          translations[word.lower()] = translation

    # Собираем исходный текст обратно, оборачивая каждое слово в спойлер
    words = hungarian_text.split(" ")
    result_parts = []
    for w in words:
      # Очищаем слово от знаков препинания для поиска в словаре
      clean_w = "".join(filter(str.isalnum, w))
      tr = translations.get(clean_w.lower())

      if tr:
        # Заменяем чистое слово на слово + спойлер, сохраняя знаки препинания
        formatted = w.replace(clean_w, f"{clean_w} ||{tr}||")
        result_parts.append(formatted)
      else:
        result_parts.append(w)

    return " ".join(result_parts)

  except Exception as e:
    print(f"Ошибка программных спойлеров: {e}")
    return hungarian_text


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
      completion = client.chat.completions.create(
          model="openai/gpt-oss-20b",
          messages=[{
              "role": "user",
              "content": (
                  "Напиши короткое сообщение на венгерском языке на тему:"
                  f" {chosen_topic}"
              ),
          }],
          temperature=0.8,
          max_tokens=150,
      )

      hu_text = completion.choices[0].message.content.strip()
      if not hu_text:
        continue

      save_message(user_id, "assistant", hu_text)
      final_message = add_spoilers_programmatically(hu_text)

      bot.send_message(chat_id=user_id, text=final_message)
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
        temperature=0.8,
        max_tokens=300,
    )

    hu_text = completion.choices[0].message.content.strip()
    if not hu_text:
      hu_text = "Nem értem!"

    save_message(user_id, "assistant", hu_text)

    # Надежно добавляем спойлеры через код Python
    final_message = add_spoilers_programmatically(hu_text)

    bot.send_message(chat_id=message.chat.id, text=final_message)
    time.sleep(0.5)

  except Exception as e:
    print(f"Ошибка при обращении к AI: {e}")


scheduler = BackgroundScheduler()
scheduler.add_job(send_proactive_message_to_all, "interval", hours=4)
scheduler.start()

print("Песель запущен: программные спойлеры активны...")

while True:
  try:
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
  except Exception as e:
    print(f"Сетевая ошибка: {e}. Переподключение через 5 секунд...")
    time.sleep(5)
