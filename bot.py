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
          "Ты — домашний пес Артура в Будапеште. Твоя задача — тренировать венгерский язык "
          "через практичные, живые микро-диалоги, похожие на реальную жизнь.\n\n"
          "МЕХАНИКА ОБЩЕНИЯ (ОЧЕНЬ ВАЖНО):\n"
          "1. Задавай вопросы из реальной жизни (планы, встречи, работа, магазин, прогулки с собакой).\n"
          "2. Используй вопросительные слова (hol, mikor, hova, mit) или выбор через 'vagy', "
          "чтобы человеку было максимально легко ответить, зеркально отражая слова из твоего вопроса.\n"
          "3. Примеры тем для вопросов:\n"
          "   - Планы: 'Hova mész holnap: a boltba vagy a parkba?'\n"
          "   - Встреча: 'Hol találkozunk: a metrónál vagy a kávézóban?'\n"
          "   - Время: 'Mikor tudsz jönni: délelőtt vagy délután?'\n"
          "   - Покупки: 'Mit vegyek: kenyeret vagy tejet?'\n"
          "4. Динамика ответов: выдавай реплику порциями от 1 до 4 сообщений, разделяя их символом '###'.\n"
          "5. Каждую реплику оформляй строго по схеме: [Текст на венгерском] ||| [Перевод на русский].\n"
          "6. Если пользователь пишет не на венгерском — мягко поправляй и проси ответить по-венгерски."
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

  topics = [
      (
          "спроси про планы на завтра с выбором места: Hova mész holnap: a boltba"
          " vagy a parkba?"
      ),
      (
          "спроси про место встречи: Hol találkozunk: a metrónál vagy a"
          " kávézóban?"
      ),
      (
          "спроси про время: Mikor tudsz jönni: délelőtt vagy délután?"
      ),
      (
          "спроси про покупки для дома: Mit vegyek a boltban: kenyeret vagy"
          " tejet?"
      ),
  ]

  for user_id in users:
    history = get_history(user_id)
    if len(history) <= 1:
      continue

    chosen_topic = random.choice(topics)
    prompt = (
        "Ты — домашний пес в Будапеште. Напиши человеку сообщение первым,"
        f" задав жизненный вопрос по теме: {chosen_topic}.\n"
        "Соблюдай формат: от 1 до 4 реплик, каждая как [Текст на венгерском] ||| [Перевод на русский],"
        " разделенных '###'."
    )

    try:
      completion = client.chat.completions.create(
          model="openai/gpt-oss-20b",
          messages=[{"role": "user", "content": prompt}],
          temperature=0.9,
          max_tokens=600,
      )

      reply_text = completion.choices[0].message.content.strip()
      if not reply_text:
        continue

      save_message(user_id, "assistant", reply_text)

      chunks = reply_text.split("###")
      for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
          continue

        if "|||" in chunk:
          parts = chunk.split("|||", 1)
          clean_text = parts[0].strip()
          translation_text = parts[1].strip()
        else:
          clean_text = chunk
          translation_text = "Песель скучает"

        safe_clean = escape_markdown_v2(clean_text)
        safe_translation = escape_markdown_v2(f"Перевод: {translation_text}")
        final_message = (
            f"🐶 *Песель спрашивает:*\n{safe_clean}\n\n||{safe_translation}||"
        )

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
        temperature=0.85,
        max_tokens=800,
    )

    reply_text = completion.choices[0].message.content.strip()
    if not reply_text:
      reply_text = (
          "Nem értem, gazdi! Csak magyarul! ||| Ничего не понимаю! Только"
          " по-венгерски!"
      )

    save_message(user_id, "assistant", reply_text)

    chunks = reply_text.split("###")

    for chunk in chunks:
      chunk = chunk.strip()
      if not chunk:
        continue

      if "|||" in chunk:
        parts = chunk.split("|||", 1)
        clean_text = parts[0].strip()
        translation_text = parts[1].strip()
      else:
        clean_text = chunk
        translation_text = "Песель слушает"

      safe_clean = escape_markdown_v2(clean_text)
      safe_translation = escape_markdown_v2(f"Перевод: {translation_text}")

      final_message = f"{safe_clean}\n\n||{safe_translation}||"

      bot.send_message(
          chat_id=message.chat.id,
          text=final_message,
          parse_mode="MarkdownV2",
      )
      time.sleep(0.5)

  except Exception as e:
    print(f"Ошибка при обращении к AI: {e}")


scheduler = BackgroundScheduler()
scheduler.add_job(send_proactive_message_to_all, "interval", hours=4)
scheduler.start()

print(
    "Питомец-песель запущен, микро-диалоги с выбором и зеркальными ответами"
    " активированы..."
)

while True:
  try:
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
  except Exception as e:
    print(f"Сетевая ошибка: {e}. Переподключение через 5 секунд...")
    time.sleep(5)
