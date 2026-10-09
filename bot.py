import os
import random
import time
import telebot
from telebot.types import KeyboardButton, ReplyKeyboardMarkup

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# Простой словарь в памяти для шагов: {user_id: {"verb": "hall", "ru": "слышать", "step": 1}}
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


@bot.message_handler(commands=["start", "reset", "verbs"])
def cmd_start(message):
  user_id = message.from_user.id
  # Сбрасываем тренировку
  if user_id in active_trainings:
    del active_trainings[user_id]

  bot.send_message(
      message.chat.id,
      "Szia! Выбери глагол для тренировки с помощью кнопок внизу:",
      reply_markup=get_verbs_keyboard(),
  )


@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
  user_id = message.from_user.id
  text = message.text.strip().lower()

  print(
      f"Получено сообщение от {user_id}: '{text}'"
  )  # Будем видеть в консоли всё, что пишет юзер

  # 1. Проверяем, не нажал ли пользователь кнопку с глаголом
  found_verb = None
  found_ru = None
  for hu, ru in VERBS_DATABASE:
    if hu in text:
      found_verb = hu
      found_ru = ru
      break

  if found_verb:
    # Запускаем тренировку
    active_trainings[user_id] = {
        "verb": found_verb,
        "ru": found_ru,
        "step": 1,
    }
    bot.send_message(
        message.chat.id,
        f"1. lépés: Как будет инфинитив (делать?) для глагола *{found_ru}*?",
        parse_mode="Markdown",
    )
    print(f"Старт тренировки для глагола: {found_verb}")
    return

  # 2. Если пользователь уже в процессе тренировки
  if user_id in active_trainings:
    data = active_trainings[user_id]
    data["step"] += 1
    step = data["step"]
    hu = data["verb"]

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
      # Завершение
      del active_trainings[user_id]
      bot.send_message(
          message.chat.id,
          "Szép munka! Ты успешно прошел все 5 шагов! 🎉 Выбери новый глагол:",
          reply_markup=get_verbs_keyboard(),
      )
      return

    bot.send_message(message.chat.id, reply_text, parse_mode="Markdown")
    return

  # 3. Если ничего не подошло
  bot.send_message(
      message.chat.id,
      "Выбери глагол для тренировки с помощью кнопок внизу:",
      reply_markup=get_verbs_keyboard(),
  )


print("Бот запущен в максимально простом режиме...")

while True:
  try:
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
  except Exception as e:
    print(f"Ошибка: {e}")
    time.sleep(5)
