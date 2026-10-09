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
  text = message.text.strip()
  text_lower = text.lower()

  # 1. Проверяем выбор глагола из кнопок (старт тренировки)
  found_hu = None
  found_ru = None
  for hu, ru in VERBS_DATABASE:
    if hu in text_lower:
      found_hu = hu
      found_ru = ru
      break

  if found_hu:
    active_trainings[user_id] = {
        "verb_hu": found_hu,
        "verb_ru": found_ru,
        "step": 1,
    }

    # Инфинитив для подсказки
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

  # 2. Если идет тренировка — проверяем ответ через Groq
  if user_id in active_trainings:
    data = active_trainings[user_id]
    step = data["step"]
    hu = data["verb_hu"]
    ru = data["verb_ru"]

    # Промпт для строгой проверки ответа ИИ
    prompt = (
        f"Ты — Réka, учительница венгерского языка. Ученик тренирует глагол '{hu}' ({ru}).\n"
        f"Текущий шаг: {step} из 3.\n"
        f"- Шаг 1: Инфинитив (например, látni для lát)\n"
        f"- Шаг 2: Форма 3-го лица ед.ч. (он/она, например lát)\n"
        f"- Шаг 3: Вопрос 'Что ты делаешь?' с этим глаголом (или форма 1-го лица/вопрос)\n\n"
        f"Ученик написал ответ: '{text}'\n\n"
        f"Инструкция:\n"
        f"1. Проверь, правильный ли это ответ для текущего шага. Если ученик написал бред, 'ок' или ошибся — напиши короткое исправление или попроси ответить нормально, и в конце напиши маркер: STAY\n"
        f"2. Если ответ правильный (или близкий к нему) — похвали ученика и в конце напиши маркер: NEXT_STEP"
    )

    try:
      completion = client.chat.completions.create(
          model="openai/gpt-oss-20b",
          messages=[{"role": "user", "content": prompt}],
          temperature=0.2,
          max_tokens=200,
      )
      ai_response = (completion.choices[0].message.content or "").strip()
    except Exception:
      ai_response = "Правильно! NEXT_STEP"

    if "NEXT_STEP" in ai_response:
      clean_text = ai_response.replace("NEXT_STEP", "").strip()
      data["step"] += 1
      next_step = data["step"]

      if next_step == 2:
        send_reply(
            message.chat.id,
            f"{clean_text}\n\nШаг 2: Как будет «он / она делает» для глагола «{ru}»?",
            hu,
        )
      elif next_step == 3:
        # Для третьего шага формируем правильный вопрос/ответ под этот глагол
        spoiler_ans = f"Mit csinálsz?"
        send_reply(
            message.chat.id,
            f"{clean_text}\n\nШаг 3: Как спросить «Что ты делаешь?» используя глагол «{ru}»?",
            spoiler_ans,
        )
      else:
        del active_trainings[user_id]
        bot.send_message(
            message.chat.id,
            f"{clean_text}\n\n🎉 Отлично! Все 3 шага пройдены! Выбери новый глагол:",
            reply_markup=get_verbs_keyboard(),
        )
    else:
      # Если ответ неправильный — оставляем на том же шаге
      clean_text = ai_response.replace("STAY", "").strip()
      if not clean_text:
        clean_text = "Не совсем так. Попробуй еще раз!"
      
      # Возвращаем подсказку в зависимости от шага
      if step == 1:
        spoiler = (
            "enni"
            if hu == "eszik"
            else ("inni" if hu == "iszik" else ("venni" if hu == "vesz" else hu + "ni"))
        )
      elif step == 2:
        spoiler = hu
      else:
        spoiler = "Mit csinálsz?"

      send_reply(message.chat.id, clean_text, spoiler)
    return

  # 3. Если вне тренировки
  bot.send_message(
      message.chat.id,
      "Давай потренируемся! Выбери глагол для тренировки с помощью кнопок внизу:",
      reply_markup=get_verbs_keyboard(),
  )


print("Река запущена с умной проверкой ответов...")

while True:
  try:
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
  except Exception as e:
    print(f"Ошибка: {e}")
    time.sleep(5)
