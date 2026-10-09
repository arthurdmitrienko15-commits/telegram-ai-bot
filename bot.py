import os
import random
import time
import telebot
from telebot.types import KeyboardButton, ReplyKeyboardMarkup

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# Храним состояние тренировки: {user_id: {"verb": "iszik", "ru": "пить", "step": 1}}
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
  """Отправляет сообщение строго со спойлером через |||"""
  msg = escape_markdown_v2(hu_text)
  if ru_text:
    msg += f"\n\n||{escape_markdown_v2(ru_text)}||"

  try:
    bot.send_message(chat_id=chat_id, text=msg, parse_mode="MarkdownV2")
  except Exception as e:
    print(f"Ошибка MarkdownV2: {e}")
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
        f"1. lépés: Mi az infinitive (csinálni?) a(z) *{found_hu}* ({found_ru}) igénél?",
        f"Шаг 1: Какая инфинитивная форма (делать?) у глагола «{found_ru}»?",
    )
    return

  # 2. Если в процессе тренировки — двигаем шаги по порядку
  if user_id in active_trainings:
    data = active_trainings[user_id]
    data["step"] += 1
    step = data["step"]
    hu = data["verb"]
    ru = data["ru"]

    if step == 2:
      send_reply(
          message.chat.id,
          f"2. lépés: Írd le a 3. személy egyes számú (ő) alakot a(z) *{hu}* igéhez.",
          f"Шаг 2: Напиши форму 3-го лица ед. числа (он/она делает) для глагола «{ru}».",
      )
    elif step == 3:
      send_reply(
          message.chat.id,
          f"3. lépés: Hogyan kérdezed meg: «Mit csinálsz?» ehhez az igéhez?",
          f"Шаг 3: Как спросить «Что ты делаешь?» с этим глаголом?",
      )
    elif step == 4:
      send_reply(
          message.chat.id,
          f"4. lépés: Írd le az 1. személy egyes számú (én) alakot: *{hu}*.",
          f"Шаг 4: Напиши форму 1-го лица ед. числа (я делаю) с этим глаголом.",
      )
    elif step == 5:
      send_reply(
          message.chat.id,
          f"5. lépés (utolsó): Fordítsd le: «Ő most ezt csinálja» a(z) *{hu}* igével.",
          f"Шаг 5 (последний): Переведи предложение: «Он/она сейчас делает это» (с этим глаголом).",
      )
    else:
      del active_trainings[user_id]
      bot.send_message(
          message.chat.id,
          "Szép munka! Sikeresen teljesítetted mind az 5 lépést! 🎉",
      )
      bot.send_message(
          message.chat.id,
          "Válassz egy új igét / Выбери новый глагол:",
          reply_markup=get_verbs_keyboard(),
      )
    return

  # 3. Если вне тренировки
  bot.send_message(
      message.chat.id,
      "Válassz egy igét a gyakorláshoz / Выбери глагол для тренировки:",
      reply_markup=get_verbs_keyboard(),
  )


print("Réka запущена со стабильными спойлерами...")

while True:
  try:
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
  except Exception as e:
    print(f"Ошибка: {e}")
    time.sleep(5)
