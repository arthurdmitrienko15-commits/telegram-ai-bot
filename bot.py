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
    "I am your virtual Hungarian teacher. Выбери команду /verbs, чтобы выбрать глагол для тренировки, "
    "или просто пиши мне в чат!"
)

SYSTEM_PROMPT = (
    "Ты — Réka, виртуальная учительница венгерского языка из Будапешта. 21 год. "
    "Строгая, но дружелюбная, с юмором. Ты ведешь пошаговую тренировку глаголов с учеником.\n\n"
    "ЖЕСТКИЕ ПРАВИЛА:\n"
    "1. ФОРМАТ (СТРОГО): Каждая реплика должна быть разделена на венгерскую часть и перевод через разделитель `|||`. "
    "Пример: Nagyon jó! ||| Очень хорошо!\n"
    "2. Если реплик несколько, разделяй их через `###`.\n"
    "3. Никогда не повторяй слова ученика слепо, веди диалог и проверяй формы глаголов."
)

# База глаголов для тренировки (инфинитив и перевод)
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
  # Таблица для отслеживания шагов тренировки глаголов (глагол и текущий шаг от 1 до 5)
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


@bot.message_handler(commands=["verbs"])
def choose_verbs(message):
  user_id = message.from_user.id
  # Выбираем 3 случайных глагола для кнопок
  selected = random.sample(VERBS_DATABASE, 3)
  markup = InlineKeyboardMarkup()
  for hu, ru in selected:
    markup.add(
        InlineKeyboardButton(
            text=f"{hu} ({ru})", callback_data=f"verb_{hu}_{ru}"
        )
    )

  bot.send_message(
      message.chat.id,
      "Válassz egy igét a gyakorláshoz! / Выбери глагол для тренировки:",
      reply_markup=markup,
  )


@bot.callback_query_handler(func=lambda call: call.data.startswith("verb_"))
def handle_verb_choice(call):
  user_id = call.from_user.id
  _, hu, ru = call.data.split("_", 2)

  conn = sqlite3.connect("bot_memory.db", check_same_thread=False)
  cursor = conn.cursor()
  # Записываем выбранный глагол и обнуляем шаг (начинаем с 1)
  cursor.execute(
      "INSERT OR REPLACE INTO verb_training (user_id, verb_hu, verb_ru, step)"
      " VALUES (?, ?, ?, 1)",
      (user_id, hu, ru, 1),
  )
  conn.commit()
  conn.close()

  bot.answer_callback_query(call.id, text=f"Выбран глагол: {hu} ({ru})")
  # Шаг 1: Написать инфинитив / значение (делать?)
  text = (
      f"Kezdjük! 1. lépés: Как будет инфинитив (делать?) для глагола *{ru}*? ||| "
      f"Начнем! Шаг 1: Как будет инфинитив (делать?) для глагола «{ru}»?"
  )
  save_message(user_id, "assistant", text)
  send_reply(call.message.chat.id, text)


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

  # Проверяем, идет ли у пользователя активная тренировка глаголов
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
          f"Helyes! 2. lépés: Напиши форму для 3-го лица ед. числа ((он/она делает) "
          f"для глагола *{hu}*). ||| Правильно! Шаг 2: Напиши форму "
          f"для 3-го лица ед. числа (он/она делает)."
      )
    elif step == 3:
      reply_text = (
          f"Ügyes vagy! 3. lépés: Как спросить «Что ты делаешь?» используя этот глагол? ||| "
          f"Молодец! Шаг 3: Как спросить «Что ты делаешь?» используя этот глагол?"
      )
    elif step == 4:
      reply_text = (
          f"Jó! 4. lépés: Составь короткое предложение с этим глаголом в 1-м лице (я...). ||| "
          f"Хорошо! Шаг 4: Составь короткое предложение с этим глаголом для «я»."
      )
    elif step == 5:
      reply_text = (
          f"Utolsó, 5. lépés: Переведи на венгерский: «Он/она сейчас делает это». ||| "
          f"Последний, 5-й шаг: Переведи на венгерский: «Он/она сейчас делает это»."
      )
    else:
      reply_text = (
          f"Gratulálok! Ты успешно прошел все 5 шагов для глагола *{hu}*! "
          f"Выбери новый глагол через /verbs. ||| Поздравляю! Ты прошел все 5 шагов! Выбери новый глагол через /verbs."
      )
      cursor.execute("DELETE FROM verb_training WHERE user_id = ?", (user_id,))

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

  # Стандартная логика общения, если тренировка не запущена
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


# Настройка расписания рассылок (4 раза в день)
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

print("Réka запущена с системой выбора глаголов по кнопкам...")

while True:
  try:
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
  except Exception as e:
    print(f"Сетевая ошибка: {e}. Переподключение через 5 секунд...")
    time.sleep(5)
