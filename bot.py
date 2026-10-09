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

# Храним состояние тренировки: {user_id: {"verb": "ír", "ru": "писать", "step": 1}}
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

STEP_QUESTIONS = {
    1: (
        "1. lépés: Mi az infinitive a(z) *{ru}* igéhez? (pl. -ni végződés)\n\n||Шаг"
        " 1: Какая инфинитивная форма (начальная с суффиксом -ni) у глагола"
        " «{ru}»?||"
    ),
    2: (
        "2. lépés: Írd le a 3. személy egyes számú (ő) alakot a(z) *{hu}*"
        " igéhez.\n\n||Шаг 2: Напиши форму 3-го лица ед. числа (он/она — ő) для"
        " глагола «{hu}».||"
    ),
    3: (
        "3. lépés: Hogyan kérdezed meg: «Mit csinálsz?» ehhez az"
        " igéhez?\n\n||Шаг 3: Как спросить «Что ты делаешь?» используя этот"
        " глагол?||"
    ),
    4: (
        "4. lépés: Írd le az 1. személy egyes számú (én) alakot: *{hu}*.\n\n||Шаг"
        " 4: Напиши форму для 1-го лица ед. числа (я — én) с этим глаголом.||"
    ),
    5: (
        "5. lépés (utolsó): Fordítsd le: «Ő most ezt csinálja».\n\n||Шаг 5"
        " (последний): Переведи предложение: «Он/она сейчас делает это».||"
    ),
}


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
    q_text = STEP_QUESTIONS[1].format(hu=found_verb, ru=found_ru)
    bot.send_message(message.chat.id, q_text, parse_mode="Markdown")
    return

  # 2. Если пользователь в процессе тренировки — двигаем шаг по любому его ответу
  if user_id in active_trainings:
    data = active_trainings[user_id]
    data["step"] += 1
    step = data["step"]
    hu = data["verb"]
    ru = data["ru"]

    if step <= 5:
      q_text = STEP_QUESTIONS[step].format(hu=hu, ru=ru)
      bot.send_message(message.chat.id, q_text, parse_mode="Markdown")
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

  # 3. Если вне тренировки
  bot.send_message(
      message.chat.id,
      "Válassz egy igét a gyakorláshoz / Выбери глагол для тренировки:",
      reply_markup=get_verbs_keyboard(),
  )


print("Réka запущена в идеальном пошаговом режиме...")

while True:
  try:
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
  except Exception as e:
    print(f"Ошибка: {e}")
    time.sleep(5)
