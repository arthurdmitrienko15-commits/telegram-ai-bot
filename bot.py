import os
import random
import time
import telebot
from telebot.types import KeyboardButton, ReplyKeyboardMarkup
from groq import Groq

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = Groq(api_key=GROQ_API_KEY)

# Храним состояние тренировки: {user_id: {"verb": "esik", "ru": "есть", "step": 1}}
active_trainings = {}

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


def get_verbs_keyboard():
  selected = random.sample(VERBS_DATABASE, 3)
  markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
  for hu, ru in selected:
    markup.add(KeyboardButton(text=f"{hu} ({ru})"))
  return markup


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


def send_reply(chat_id, hu_text, ru_text):
  """Отправляет сообщение в жестком формате: венгерский текст + перевод под спойлером"""
  msg = escape_markdown_v2(hu_text)
  if ru_text:
    msg += f"\n\n||{escape_markdown_v2(ru_text)}||"

  try:
    bot.send_message(chat_id=chat_id, text=msg, parse_mode="MarkdownV2")
  except Exception as e:
    print(f"Ошибка отправки MarkdownV2: {e}")
    bot.send_message(chat_id=chat_id, text=f"{hu_text}\n\n({ru_text})")


@bot.message_handler(commands=["start", "reset", "verbs"])
def cmd_start(message):
  user_id = message.from_user.id
  if user_id in active_trainings:
    del active_trainings[user_id]

  bot.send_message(
      message.chat.id,
      "Szia! Válaszd ki a gyakorolni kívánt igét: / Выбери глагол для тренировки:",
      reply_markup=get_verbs_keyboard(),
  )


@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
  user_id = message.from_user.id
  text = message.text.strip()
  text_lower = text.lower()

  # 1. Проверяем выбор глагола из кнопок
  found_verb = None
  found_ru = None
  for hu, ru in VERBS_DATABASE:
    if hu in text_lower:
      found_verb = hu
      found_ru = ru
      break

  if found_verb:
    active_trainings[user_id] = {
        "verb": found_verb,
        "ru": found_ru,
        "step": 1,
    }
    send_reply(
        message.chat.id,
        f"1. lépés: Mi az infinitive (csinálni?) a(z) *{found_ru}* igénél?",
        f"Шаг 1: Какая инфинитивная форма (делать?) у глагола «{found_ru}»?",
    )
    return

  # 2. Если пользователь в процессе тренировки — двигаем шаг по любому его ответу
  if user_id in active_trainings:
    data = active_trainings[user_id]
    data["step"] += 1
    step = data["step"]
    hu = data["verb"]
    ru = data["ru"]

    if step == 2:
      hu_q = f"2. lépés: Írd le a 3. személy egyes számú (ő) alakot a(z) *{hu}* igéhez."
      ru_q = f"Шаг 2: Напиши форму 3-го лица ед. числа (он/она) для глагола «{hu}»."
    elif step == 3:
      hu_q = (
          f"3. lépés: Hogyan kérdezed meg: «Mit csinálsz?» ehhez az igéhez?"
      )
      ru_q = f"Шаг 3: Как спросить «Что ты делаешь?» с этим глаголом?"
    elif step == 4:
      hu_q = f"4. lépés: Írd le az 1. személy egyes számú (én) alakot: *{hu}*."
      ru_q = f"Шаг 4: Напиши форму для 1-го лица ед. числа (я) с этим глаголом."
    elif step == 5:
      hu_q = f"5. lépés (utolsó): Fordítsd le: «Ő most ezt csinálja»."
      ru_q = (
          f"Шаг 5 (последний): Переведи предложение: «Он/она сейчас делает это»."
      )
    else:
      del active_trainings[user_id]
      bot.send_message(
          message.chat.id,
          "Szép munka! Sikeresen teljesítetted mind az 5 lépést! 🎉",
          parse_mode="Markdown",
      )
      bot.send_message(
          message.chat.id,
          "Válassz egy új igét / Выбери новый глагол:",
          reply_markup=get_verbs_keyboard(),
      )
      return

    send_reply(message.chat.id, hu_q, ru_q)
    return

  # 3. Если вне тренировки
  bot.send_message(
      message.chat.id,
      "Válassz egy igét a gyakorláshoz / Выбери глагол для тренировки:",
      reply_markup=get_verbs_keyboard(),
  )


print("Réka запущена стабильно со спойлерами и без обрывов...")

while True:
  try:
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
  except Exception as e:
    print(f"Ошибка: {e}")
    time.sleep(5)
