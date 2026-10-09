import os
import random
import sqlite3
import time
from apscheduler.schedulers.background import BackgroundScheduler
import telebot
from groq import Groq

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = Groq(api_key=GROQ_API_KEY)

HISTORY_LIMIT = 20

WELCOME_TEXT = (
    "Szia! I am Réka, 21 years old, from Budapest. 🇭🇺\n\n"
    "I am your virtual Hungarian teacher. Write to me in any language you prefer "
    "(Russian, Ukrainian, English, etc.), and let's practice!"
)

SYSTEM_PROMPT = (
    "Ты — Réka, виртуальная учительница венгерского языка из Будапешта. 21 год. "
    "Строгая, но дружелюбная, с юмором. Ты помогаешь ученику учить венгерский.\n\n"
    "ЖЕСТКИЕ ПРАВИЛА:\n"
    "1. ФОРМАТ: Каждая реплика строго вида: [Венгерский текст] ||| [Русский перевод или объяснение]. "
    "Если реплик несколько, разделяй их через '###'. Никогда не оставляй предложения оборванными!\n"
    "2. РЕАКЦИЯ НА НЕПОНИМАНИЕ: Если ученик пишет 'не понял', 'что отвечать' или задает вопрос по-русски — "
    "ЗАПРЕЩЕНО задавать новые вопросы! Объясни грамматику простыми словами, разбери конструкцию "
    "и дай готовый пример, который можно использовать.\n"
    "3. ЕДА: Если ученик в ответ на вопрос о еде пишет 'Pizza', 'Sushi', 'Gyros' — не придирайся, "
    "это нормальная еда в Будапеште, принимай с юмором.\n"
    "4. Не пиши слишком длинно (максимум 2 коротких абзаца/реплики)."
)

DAILY_WORDS = [
    ("beszél", "говорит"),
    ("egészségére", "на здоровье / будь здоров"),
    ("szépen", "красиво / мило"),
    ("biztosan", "точно / наверняка"),
    ("pillanat", "момент / минутка"),
    ("lépés", "шаг"),
    ("kávézó", "кафе"),
    ("szükség", "нужда / необходимость"),
]


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
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_words (
            user_id INTEGER PRIMARY KEY,
            word_hu TEXT,
            word_ru TEXT,
            count INTEGER
        )
    """)
  conn.commit()
  conn.close()


init_db()


def get_or_set_user_word(user_id):
  conn = sqlite3.connect("bot_memory.db", check_same_thread=False)
  cursor = conn.cursor()
  cursor.execute(
      "SELECT word_hu, word_ru, count FROM user_words WHERE user_id = ?",
      (user_id,),
  )
  row = cursor.fetchone()

  if not row:
    hu, ru = random.choice(DAILY_WORDS)
    count = 1
    cursor.execute(
        "INSERT INTO user_words (user_id, word_hu, word_ru, count) VALUES (?, ?, ?, ?)",
        (user_id, hu, ru, count),
    )
  else:
    hu, ru, count = row
    count += 1
    if count > 5:
      hu, ru = random.choice(DAILY_WORDS)
      count = 1
    cursor.execute(
        "UPDATE user_words SET word_hu = ?, word_ru = ?, count = ? WHERE user_id = ?",
        (hu, ru, count, user_id),
    )

  conn.commit()
  conn.close()
  return hu, ru, count


def clear_history(user_id):
  conn = sqlite3.connect("bot_memory.db", check_same_thread=False)
  cursor = conn.cursor()
  cursor.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
  conn.commit()
  conn.close()


def get_history(user_id):
  conn = sqlite3.connect("bot_memory.db", check_same_thread=False)
  cursor = conn.cursor()
  cursor.execute(
      "SELECT role, content FROM messages WHERE user_id = ? "
      "ORDER BY rowid DESC LIMIT ?",
      (user_id, HISTORY_LIMIT),
  )
  rows = cursor.fetchall()[::-1]
  conn.close()

  history = [{"role": "system", "content": SYSTEM_PROMPT}]
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


def send_reply(chat_id, reply_text):
  blocks = reply_text.split("###")
  for block in blocks:
    block = block.strip()
    if not block:
      continue

    if "|||" in block:
      parts = block.split("|||")
      hu = parts[0].strip()
      ru = parts[1].strip() if len(parts) > 1 else ""
    else:
      hu = block
      ru = ""

    msg = escape_markdown_v2(hu)
    if ru:
      msg += f"\n\n||{escape_markdown_v2(ru)}||"

    try:
      bot.send_message(chat_id=chat_id, text=msg, parse_mode="MarkdownV2")
    except Exception as e:
      print(f"Ошибка отправки сообщения: {e}")
      bot.send_message(chat_id=chat_id, text=f"{hu}\n\n({ru})")


def send_proactive_message(slot_name):
  conn = sqlite3.connect("bot_memory.db", check_same_thread=False)
  cursor = conn.cursor()
  cursor.execute("SELECT DISTINCT user_id FROM messages")
  users = [row[0] for row in cursor.fetchall()]
  conn.close()

  if not users:
    return

  for user_id in users:
    try:
      hu, ru, count = get_or_set_user_word(user_id)

      if count <= 4:
        # Первые 4 раза: формат как ты просил (слово — перевод)
        text_to_send = f"{hu} — {ru} ||| {hu} — {ru}"
      else:
        # На 5-й раз: только венгерское слово, перевод пустой (пиши сам)
        text_to_send = f"{hu} —  ||| Напиши перевод для слова {hu} (Правильный ответ: {ru})"

      save_message(user_id, "assistant", text_to_send)
      send_reply(user_id, text_to_send)
    except Exception as e:
      print(f"Ошибка проактивной рассылки для {user_id}: {e}")


@bot.message_handler(commands=["reset", "start"])
def send_welcome(message):
  user_id = message.from_user.id
  clear_history(user_id)
  bot.send_message(message.chat.id, WELCOME_TEXT)


@bot.message_handler(func=lambda message: True)
def handle_message(message):
  user_id = message.from_user.id
  text = message.text
  if not text:
    return

  try:
    bot.send_chat_action(message.chat.id, "typing")
  except Exception:
    pass

  save_message(user_id, "user", text)
  history = get_history(user_id)

  try:
    completion = client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=history,
        temperature=0.3,
        max_tokens=600,
    )

    reply_text = (completion.choices[0].message.content or "").strip()
    if not reply_text:
      reply_text = "Magyarul, kérlek! ||| In Hungarian, please!"

    save_message(user_id, "assistant", reply_text)
    send_reply(message.chat.id, reply_text)

  except Exception as e:
    print(f"Ошибка при обращении к AI: {e}")


scheduler = BackgroundScheduler()
scheduler.add_job(
    send_proactive_message, "cron", hour=9, minute=0, args=["morning"]
)
scheduler.add_job(
    send_proactive_message, "cron", hour=13, minute=0, args=["day"]
)
scheduler.add_job(
    send_proactive_message, "cron", hour=17, minute=0, args=["evening"]
)
scheduler.add_job(
    send_proactive_message, "cron", hour=21, minute=0, args=["night_check"]
)
scheduler.start()

print("Réka запущена в чистом формате словаря...")

while True:
  try:
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
  except Exception as e:
    print(f"Сетевая ошибка: {e}. Переподключение через 5 секунд...")
    time.sleep(5)
