import os
import random
import time
import telebot
from telebot.types import KeyboardButton, ReplyKeyboardMarkup

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# Храним состояние: {user_id: {"verb_hu": "lát", "verb_ru": "видеть", "step": 1}}
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


def send_reply(chat_id, text_main, spoiler_word=""):
  msg = escape_markdown_v2(text_main)
  if spoiler_word:
    msg += f"\n\n||{escape_markdown_v2(spoiler_word)}||"

  try:
    bot.send_message(chat_id=chat_id, text=msg, parse_mode="MarkdownV2")
  except Exception as e:
    print(f"Ошибка MarkdownV2: {e}")
    fallback = text_main
    if spoiler_word:
      fallback += f"\n\n({spoiler_word})"
    bot.send_message(chat_id=chat_id, text=fallback)


@bot.message_handler(commands=["start", "reset", "verbs"])
def cmd_start(message):
  user_id = message.from_user.id
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

  # 1. СНАЧАЛА проверяем, идет ли активная тренировка
  if user_id in active_trainings:
    data = active_trainings[user_id]
    step = data["step"]
    hu = data["verb_hu"]
    ru = data["verb_ru"]

    # Определяем правильный ответ для текущего шага
    if step == 1:
      if hu == "eszik":
        correct = "enni"
      elif hu == "iszik":
        correct = "inni"
      elif hu == "vesz":
        correct = "venni"
      else:
        correct = hu + "ni"
    elif step == 2:
      correct = hu
    elif step == 3:
      # Точный смысловой ответ для 3 шага под каждый глагол
      if hu == "eszik":
        correct = "mit eszel?"
      elif hu == "iszik":
        correct = "mit iszol?"
      elif hu == "ír":
        correct = "mit írsz?"
      elif hu == "olvas":
        correct = "mit olvasol?"
      elif hu == "lát":
        correct = "mit látsz?"
      elif hu == "hall":
        correct = "mit hallasz?"
      elif hu == "vesz":
        correct = "mit veszel?"
      else:
        correct = "mit csinálsz?"
    else:
      correct = ""

    # Проверяем ответ (разрешаем небольшие вариации с диакритикой)
    clean_text = text.replace("á", "a").replace("í", "i").replace("é", "e")
    clean_correct = correct.replace("á", "a").replace("í", "i").replace("é", "e")

    if clean_correct in clean_text or clean_text in clean_correct:
      data["step"] += 1
      next_step = data["step"]

      if next_step == 2:
        send_reply(
            message.chat.id,
            f"Правильно! 🎉\n\nШаг 2: Как будет «он / она делает» для глагола «{ru}»?",
            hu,
        )
      elif next_step == 3:
        # Динамический и правильный текст вопроса для Шага 3
        if hu == "eszik":
          step3_q = "Как спросить «Что ты ешь?» с этим глаголом?"
        elif hu == "iszik":
          step3_q = "Как спросить «Что ты пьешь?» с этим глаголом?"
        elif hu == "ír":
          step3_q = "Как спросить «Что ты пишешь?» с этим глаголом?"
        elif hu == "olvas":
          step3_q = "Как спросить «Что ты читаешь?» с этим глаголом?"
        elif hu == "lát":
          step3_q = "Как спросить «Что ты видишь?» с этим глаголом?"
        elif hu == "hall":
          step3_q = "Как спросить «Что ты слышишь?» с этим глаголом?"
        elif hu == "vesz":
          step3_q = "Как спросить «Что ты покупаешь/берешь?» с этим глаголом?"
        else:
          step3_q = "Как спросить «Что ты делаешь?» с этим глаголом?"

        send_reply(message.chat.id, f"Отлично! 🔥\n\nШаг 3: {step3_q}", correct)
      else:
        del active_trainings[user_id]
        bot.send_message(
            message.chat.id,
            "🎉 Молодчина! Все 3 шага пройдены! Выбери новый глагол:",
            reply_markup=get_verbs_keyboard(),
        )
    else:
      # Ошибка — повторяем шаг с подсказкой
      if step == 1:
        spoiler = (
            "enni"
            if hu == "eszik"
            else ("inni" if hu == "iszik" else ("venni" if hu == "vesz" else hu + "ni"))
        )
      elif step == 2:
        spoiler = hu
      else:
        spoiler = correct

      send_reply(
          message.chat.id,
          f"Не совсем так. Попробуй еще раз для глагола «{ru}»:",
          spoiler,
      )
    return

  # 2. Если тренировки нет — выбираем глагол
  found_hu = None
  found_ru = None
  for hu, ru in VERBS_DATABASE:
    if hu in text:
      found_hu = hu
      found_ru = ru
      break

  if found_hu:
    active_trainings[user_id] = {
        "verb_hu": found_hu,
        "verb_ru": found_ru,
        "step": 1,
    }

    if found_hu == "eszik":
      inf_word = "enni"
    elif found_hu == "iszik":
      inf_word = "inni"
    elif found_hu == "vesz":
      inf_word = "venni"
    else:
      inf_word = found_hu + "ni"

    send_reply(
        message.chat.id,
        f"Шаг 1: Как будет глагол «{found_ru}» в начальной форме (инфинитив)?",
        inf_word,
    )
    return

  bot.send_message(
      message.chat.id,
      "Давай потренируемся! Выбери глагол для тренировки с помощью кнопок внизу:",
      reply_markup=get_verbs_keyboard(),
  )


print("Река запущена с точной проверкой и уникальными вопросами Шага 3...")

while True:
  try:
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
  except Exception as e:
    print(f"Ошибка: {e}")
    time.sleep(5)
