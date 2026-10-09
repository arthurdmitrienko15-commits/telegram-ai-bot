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


def send_reply(chat_id, text_main, spoiler_hu=""):
  """Отправляет ответ с подсказкой/ответом на венгерском под спойлером"""
  msg = escape_markdown_v2(text_main)
  if spoiler_hu:
    msg += f"\n\n||{escape_markdown_v2(spoiler_hu)}||"

  try:
    bot.send_message(chat_id=chat_id, text=msg, parse_mode="MarkdownV2")
  except Exception as e:
    print(f"Ошибка MarkdownV2: {e}")
    fallback = text_main
    if spoiler_hu:
      fallback += f"\n\n({spoiler_hu})"
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
    send_reply(
        message.chat.id,
        f"Шаг 1: Как будет глагол «{found_ru}» в начальной форме (инфинитив)?",
        f"Правильно по-венгерски: {found_hu}ni (или смотреть по правилам)",
    )
    return

  # 2. Если идет тренировка — через Groq проверяем ответ пользователя и даем следующий шаг
  if user_id in active_trainings:
    data = active_trainings[user_id]
    step = data["step"]
    hu = data["verb_hu"]
    ru = data["verb_ru"]

    # Формируем промпт для ИИ, чтобы он проверил ответ и выдал следующий вопрос на языке пользователя
    prompt = (
        f"Ты — Réka, строгая, но дружелюбная учительница венгерского языка. "
        f"Глагол тренировки: '{hu}' ({ru}).\n"
        f"Текущий шаг ученика: {step} из 3.\n"
        f"- Шаг 1: Инфинитив (делать?)\n"
        f"- Шаг 2: Форма 3-го лица ед.ч. (он/она делает?)\n"
        f"- Шаг 3: Вопрос 'Что ты делаешь?' или форма с этим глаголом.\n\n"
        f"Ученик написал ответ: '{text}'\n\n"
        f"Твоя задача:\n"
        f"1. Оцени его ответ на том языке, на котором он пишет (напиши 'Правильно!' либо исправь ошибку).\n"
        f"2. Задай следующий вопрос по этому же глаголу для следующего шага.\n"
        f"3. Если это был последний шаг, поздравь ученика и предложи выбрать новый глагол.\n"
        f"Формат ответа: Сначала текст проверки и новый вопрос, а в самом конце с новой строки напиши маркер перехода: NEXT_STEP (если шаг пройден и надо двигаться дальше) или STAY (если нужно переспросить этот же шаг)."
    )

    try:
      completion = client.chat.completions.create(
          model="openai/gpt-oss-20b",
          messages=[{"role": "user", "content": prompt}],
          temperature=0.3,
          max_tokens=400,
      )
      ai_response = (completion.choices[0].message.content or "").strip()
    except Exception:
      ai_response = "Отлично! NEXT_STEP"

    # Обрабатываем решение ИИ
    if "NEXT_STEP" in ai_response:
      clean_text = ai_response.replace("NEXT_STEP", "").strip()
      data["step"] += 1
      next_step = data["step"]

      if next_step <= 3:
        # Формируем подсказку на венгерском под спойлер в зависимости от шага
        if next_step == 2:
          spoiler = f"Подсказка (он/она): ő {hu}..."
        else:
          spoiler = f"Подсказка (ты): Mit csinálsz?"

        send_reply(message.chat.id, clean_text, spoiler)
      else:
        del active_trainings[user_id]
        bot.send_message(
            message.chat.id,
            f"{clean_text}\n\n🎉 Отлично! Тренировка завершена. Выбери новый глагол:",
            reply_markup=get_verbs_keyboard(),
        )
    else:
      # Если нужно остаться на шаге (ошибка в ответе)
      clean_text = ai_response.replace("STAY", "").strip()
      send_reply(
          message.chat.id,
          clean_text,
          f"Попробуй еще раз учесть правила для {hu}",
      )
    return

  # 3. Если вне тренировки
  bot.send_message(
      message.chat.id,
      "Давай потренируемся! Выбери глагол для тренировки с помощью кнопок внизу:",
      reply_markup=get_verbs_keyboard(),
  )


print("Река запущена с проверкой ответов и подсказками под спойлером...")

while True:
  try:
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
  except Exception as e:
    print(f"Ошибка: {e}")
    time.sleep(5)
