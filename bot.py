import os
import random
import sqlite3
import time
import telebot
from telebot.types import KeyboardButton, ReplyKeyboardMarkup
from groq import Groq

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = Groq(api_key=GROQ_API_KEY)

WELCOME_TEXT = (
    "Szia! I am Réka, 21 years old, from Budapest. 🇭🇺\n\n"
    "Давай потренируем венгерские глаголы! Выбери глагол кнопкой внизу:"
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


def init_db():
  conn = sqlite3.connect("bot_memory.db", check_same_thread=False)
  cursor = conn.cursor()
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


def get_verbs_keyboard():
  selected = random.sample(VERBS_DATABASE, 3)
  markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
  for hu, ru in selected:
    markup.add(KeyboardButton(text=f"{hu} ({ru})"))
  return markup


@bot.message_handler(commands=["start", "reset", "verbs"])
def cmd_start(message):
  user_id = message.from_user.id
  conn = sqlite3.connect("bot_memory.db", check_same_thread=False)
  cursor = conn.cursor()
  cursor.execute("DELETE FROM verb_training WHERE user_id = ?", (user_id,))
  conn.commit()
  conn.close()

  bot.send_message(
      message.chat.id, WELCOME_TEXT, reply_markup=get_verbs_keyboard()
  )


@bot.message_handler(func=lambda message: True)
def handle_message(message):
  user_id = message.from_user.id
  text = message.text.strip().lower()
  if not text:
    return

  conn = sqlite3.connect("bot_memory.db", check_same_thread=False)
  cursor = conn.cursor()

  # Ищем, содержит ли сообщение венгерский глагол из нашей базы (по вхождению подстроки)
  matched_verb = None
  for hu, ru in VERBS_DATABASE:
    if hu in text:
      matched_verb = (hu, ru)
      break

  if matched_verb:
    hu, ru = matched_verb
    cursor.execute(
        "INSERT OR REPLACE INTO verb_training (user_id, verb_hu, verb_ru, step)"
        " VALUES (?, ?, ?, 1)",
        (user_id, hu, ru, 1),
    )
    conn.commit()
    conn.close()

    bot.send_message(
        message.chat.id,
        f"1. lépés: Как будет инфинитив (делать?) для глагола *{ru}*?",
        parse_mode="Markdown",
    )
    return

  # Проверяем активный шаг тренировки
  cursor.execute(
      "SELECT verb_hu, verb_ru, step FROM verb_training WHERE user_id = ?",
      (user_id,),
  )
  v_row = cursor.fetchone()

  if v_row:
    hu, ru, step = v_row
    step += 1

    if step == 2:
      reply_text = f"2. lépés: Напиши форму 3-го лица ед. числа (он/она делает) для глагола *{hu}*."
    elif step == 3:
      reply_text = f"3. lépés: Как спросить «Что ты делаешь?» используя этот глагол?"
    elif step == 4:
      reply_text = (
          f"4. lépés: Напиши форму для «я делаю» с этим глаголом (*{hu}*)."
      )
    elif step == 5:
      reply_text = (
          f"5. lépés (последний): Переведи предложение: «Он/она сейчас делает это»."
      )
    else:
      cursor.execute("DELETE FROM verb_training WHERE user_id = ?", (user_id,))
      conn.commit()
      conn.close()
      bot.send_message(
          message.chat.id,
          "Szép munka! Ты успешно прошел все 5 шагов! 🎉 Выбери новый глагол:",
          reply_markup=get_verbs_keyboard(),
      )
      return

    cursor.execute(
        "UPDATE verb_training SET step = ? WHERE user_id = ?", (step, user_id)
    )
    conn.commit()
    conn.close()

    bot.send_message(message.chat.id, reply_text, parse_mode="Markdown")
    return

  conn.close()

  # Если не выбрал глагол и не в тренировке — просим нажать кнопку
  bot.send_message(
      message.chat.id,
      "Давай потренируемся! Выбери глагол с помощью кнопок внизу:",
      reply_markup=get_verbs_keyboard(),
  )


print("Réka запущена в исправленном режиме...")

while True:
  try:
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
  except Exception as e:
    print(f"Сетевая ошибка: {e}. Переподключение через 5 секунд...")
    time.sleep(5)
