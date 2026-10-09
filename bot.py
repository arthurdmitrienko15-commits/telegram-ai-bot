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

# Храним состояние: {user_id: {"verb_hu": "ír", "verb_ru": "писать", "step": 1}}
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
  """Отправляет ответ, где под спойлером ИСКЛЮЧИТЕЛЬНО одно слово на венгерском"""
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

  # 1. Проверяем выбор глагола из кнопок
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
    # Шаг 1: Инфинитив. Под спойлером — только инфинитив с -ni (например, "írni" или "enni")
    inf_word = (
        found_hu + "ni"
        if not found_hu.endswith("ik")
        else found_hu.replace("ik", "ni")
    )
    if found_hu == "eszik":
      inf_word = "enni"
    if found_hu == "iszik":
      inf_word = "inni"
    if found_hu == "vesz":
      inf_word = "venni"

    send_reply(
        message.chat.id,
        f"Шаг 1: Как будет глагол «{found_ru}» в начальной форме (инфинитив)?",
        inf_word,
    )
    return

  # 2. Если идет тренировка
  if user_id in active_trainings:
    data = active_trainings[user_id]
    step = data["step"]
    hu = data["verb_hu"]
    ru = data["verb_ru"]

    # Используем ИИ для оценки ответа и формирования следующего шага
    prompt = (
        f"Ты — Réka, строгая, но дружелюбная учительница венгерского языка. "
        f"Глагол тренировки: '{hu}' ({ru}).\n"
        f"Текущий шаг ученика: {step} из 3.\n"
        f"- Шаг 1 был: Инфинитив\n"
        f"- Шаг 2 сейчас: Форма 3-го лица ед.ч. (он/она делает?)\n"
        f"- Шаг 3 сейчас: Вопрос 'Что ты делаешь?' (Mit csinálsz?)\n\n"
        f"Ученик написал ответ: '{text}'\n\n"
        f"Инструкция:\n"
        f"1. Оцени его ответ на языке ученика (напиши коротко 'Правильно!' или исправь ошибку).\n"
        f"2. Задай следующий вопрос (Шаг 2 или Шаг 3) на языке ученика.\n"
        f"3. Если Шаг 3 пройден, поздравь ученика и предложи выбрать новый глагол.\n"
        f"В самом конце ответа с новой строки напиши маркер: NEXT_STEP (если переходим дальше) или STAY (если ученик ошибся и нужно остаться)."
    )

    try:
      completion = client.chat.completions.create(
          model="openai/gpt-oss-20b",
          messages=[{"role": "user", "content": prompt}],
          temperature=0.3,
          max_tokens=300,
      )
      ai_response = (completion.choices[0].message.content or "").strip()
    except Exception:
      ai_response = "Отлично! NEXT_STEP"

    if "NEXT_STEP" in ai_response:
      clean_text = ai_response.replace("NEXT_STEP", "").strip()
      data["step"] += 1
      next_step = data["step"]

      if next_step == 2:
        # Под спойлером только форма он/она (например, hu сам по себе для 3 лица)
        spoiler_word = hu
        send_reply(message.chat.id, f"{clean_text}\n\nШаг 2: Он/она делает?", spoiler_word)
      elif next_step == 3:
        spoiler_word = "Mit csinálsz?"
        send_reply(message.chat.id, f"{clean_text}\n\nШаг 3: Что ты делаешь?", spoiler_word)
      else:
        del active_trainings[user_id]
        bot.send_message(
            message.chat.id,
            f"{clean_text}\n\n🎉 Тренировка завершена! Выбери новый глагол:",
            reply_markup=get_verbs_keyboard(),
        )
    else:
      clean_text = ai_response.replace("STAY", "").strip()
      send_reply(message.chat.id, clean_text, hu)
    return

  # 3. Если вне тренировки
  bot.send_message(
      message.chat.id,
      "Давай потренируемся! Выбери глагол для тренировки с помощью кнопок внизу:",
      reply_markup=get_verbs_keyboard(),
  )


print("Река запущена: чистые спойлеры без лишнего текста...")

while True:
  try:
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
  except Exception as e:
    print(f"Ошибка: {e}")
    time.sleep(5)
