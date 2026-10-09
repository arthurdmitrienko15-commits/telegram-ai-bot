import os
import random
import sqlite3
import time
from apscheduler.schedulers.background import BackgroundScheduler
import telebot
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup
from groq import Groq

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = Groq(api_key=GROQ_API_KEY)

HISTORY_LIMIT = 20

WELCOME_TEXT = (
    "Szia! I am Réka, 21 years old, from Budapest. 🇭🇺\n\n"
    "Я твоя виртуальная учительница венгерского. Давай потренируем глаголы! "
    "Выбери глагол с помощью кнопок ниже:"
)

VERBS_DATABASE = [
    ("csinál", "делать"),
    ("olvas", "читать"),
    ("ír", "писать"),
    ("eszik", "есть"),
    ("iszik", "пить"),
    ("lát", "видеть"),
    ("hall", "слышать"),
    ("vesz", "брать / покупать"),
]

DAILY_WORDS = [
    ("beszél", "говорит"),
    ("egészségére", "на здоровье / будь здоров"),
    ("szépen", "красиво / мило"),
    ("biztosan", "точно / наверняка"),
    ("pillanat", "момент / минутка"),
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
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS verb_training (
            user_id INTEGER PRIMARY KEY,
            verb_hu TEXT,
            verb_ru TEXT,
            step INTEGER
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
  cursor.execute("DELETE FROM verb_training WHERE user_id = ?", (user_id,))
  conn.commit()
  conn.close()


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
        text_to_send = f"{hu} — {ru} ||| {hu} — {ru}"
      else:
        text_to_send = (
            f"{hu} —  ||| Напиши перевод для слова {hu} (Правильный ответ: {ru})"
        )
      save_message(user_id, "assistant", text_to_send)
      send_reply(user_id, text_to_send)
    except Exception as e:
      print(f"Ошибка проактивной рассылки для {user_id}: {e}")


def show_verbs_menu(chat_id):
  selected = random.sample(VERBS_DATABASE, 3)
  markup = InlineKeyboardMarkup()
  for hu, ru in selected:
    markup.add(
        InlineKeyboardButton(
            text=f"{hu} ({ru})", callback_data=f"verb_{hu}_{ru}"
        )
    )
  bot.send_message(
      chat_id,
      "Válassz egy igét a gyakorláshoz! / Выбери глагол для тренировки:",
      reply_markup=markup,
  )


@bot.message_handler(commands=["verbs", "start", "reset"])
def cmd_start(message):
  user_id = message.from_user.id
  clear_history(user_id)
  bot.send_message(message.chat.id, WELCOME_TEXT)
  show_verbs_menu(message.chat.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("verb_"))
def handle_verb_choice(call):
  # ЖЕСТКО гасим анимацию загрузки на кнопке, чтобы она не мигала
  try:
    bot.answer_callback_query(call.id)
  except Exception:
    pass

  user_id = call.from_user.id
  _, hu, ru = call.data.split("_", 2)

  conn = sqlite3.connect("bot_memory.db", check_same_thread=False)
  cursor = conn.cursor()
  cursor.execute(
      "INSERT OR REPLACE INTO verb_training (user_id, verb_hu, verb_ru, step)"
      " VALUES (?, ?, ?, 1)",
      (user_id, hu, ru, 1),
  )
  conn.commit()
  conn.close()

  # Шаг 1
  text = (
      f"1. lépés: Как будет инфинитив (делать?) для глагола *{ru}*? ||| "
      f"Шаг 1: Как будет инфинитив (делать?) для глагола «{ru}»?"
  )
  save_message(user_id, "assistant", text)
  send_reply(call.message.chat.id, text)


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

  conn = sqlite3.connect("bot_memory.db", check_same_thread=False)
  cursor = conn.cursor()
  cursor.execute(
      "SELECT verb_hu, verb_ru, step FROM verb_training WHERE user_id = ?",
      (user_id,),
  )
  v_row = cursor.fetchone()

  if v_row:
    hu, ru, step = v_row
    step += 1

    if step == 2:
      reply_text = (
          f"2. lépés: Напиши форму 3-го лица ед. числа (он/она делает) "
          f"для глагола *{hu}*. ||| Шаг 2: Напиши форму 3-го лица ед. числа (он/она делает)."
      )
    elif step == 3:
      reply_text = (
          f"3. lépés: Как спросить «Что ты делаешь?» используя этот глагол? ||| "
          f"Шаг 3: Как спросить «Что ты делаешь?» используя этот глагол?"
      )
    elif step == 4:
      reply_text = (
          f"4. lépés: Напиши форму для «я делаю» с этим глаголом. ||| "
          f"Шаг 4: Напиши форму для «я делаю» с этим глаголом."
      )
    elif step == 5:
      reply_text = (
          f"5. lépés (последний): Переведи предложение: «Он/она сейчас делает это». ||| "
          f"Шаг 5 (последний): Переведи предложение: «Он/она сейчас делает это»."
      )
    else:
      reply_text = (
          f"Szép munka! Ты прошел все 5 шагов для глагола *{hu}*! 🎉 "
          f"Выбери новый глагол ниже: ||| Отличная работа! Ты прошел все 5 шагов!"
      )
      cursor.execute("DELETE FROM verb_training WHERE user_id = ?", (user_id,))
      save_message(user_id, "user", text)
      save_message(user_id, "assistant", reply_text)
      send_reply(message.chat.id, reply_text)
      conn.commit()
      conn.close()
      # Сразу автоматически предлагаем новые слова кнопками
      show_verbs_menu(message.chat.id)
      return

    cursor.execute(
        "UPDATE verb_training SET step = ? WHERE user_id = ?", (step, user_id)
    )
    conn.commit()
    conn.close()

    save_message(user_id, "user", text)
    save_message(user_id, "assistant", reply_text)
    send_reply(message.chat.id, reply_text)
    return

  conn.close()

  # Если тренировка не запущена, бот сам предлагает выбрать глагол через кнопки вместо лишних текстов
  bot.send_message(
      message.chat.id,
      "Давай потренируемся! Выбери глагол для тренировки:",
  )
  show_verbs_menu(message.chat.id)


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

print("Réka запущена, инлайн-кнопки починены...")

while True:
  try:
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
  except Exception as e:
    print(f"Сетевая ошибка: {e}. Переподключение через 5 секунд...")
    time.sleep(5)
