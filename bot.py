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

# Состояние тренировки: {user_id: {"verb": "hall", "ru": "слышать", "step": 1}}
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
        "1. lépés: Как будет инфинитив (начальная форма «делать?») для глагола *{ru}*?"
    ),
    2: (
        "2. lépés: Напиши форму 3-го лица ед. числа (он/она делает) для глагола *{hu}*."
    ),
    3: "3. lépés: Как спросить «Что ты делаешь?» используя этот глагол?",
    4: "4. lépés: Напиши форму для «я делаю» с этим глаголом (*{hu}*).",
    5: "5. lépés (последний): Переведи предложение: «Он/она сейчас делает это».",
}


def get_verbs_keyboard():
  selected = random.sample(VERBS_DATABASE, 3)
  markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
  for hu, ru in selected:
    markup.add(KeyboardButton(text=f"{hu} ({ru})"))
  return markup


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

  # 1. Проверяем выбор глагола из меню
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
    bot.send_message(
        message.chat.id, STEP_QUESTIONS[1].format(ru=found_ru), parse_mode="Markdown"
    )
    return

  # 2. Если пользователь в процессе тренировки
  if user_id in active_trainings:
    data = active_trainings[user_id]
    step = data["step"]
    hu = data["verb"]
    ru = data["ru"]

    # ИИ анализирует сообщение на любом языке (вопрос/помощь vs ответ)
    prompt = (
        f"Ты — Réka, строгая, но дружелюбная учительница венгерского языка (21 год, Будапешт).\n"
        f"Ученик сейчас на шаге №{step} тренировки глагола '{hu}' ({ru}).\n"
        f"Шаги:\n"
        f"1: инфинитив\n"
        f"2: 3-е лицо ед.ч. (он/она)\n"
        f"3: вопрос 'Что ты делаешь?'\n"
        f"4: 1-е лицо ед.ч. (я)\n"
        f"5: перевод 'Он/она сейчас делает это'\n\n"
        f"Ученик написал тебе на своем языке: '{text}'\n\n"
        f"Инструкция:\n"
        f"1. Если это ВОПРОС, просьба о помощи или непонятный термин (на любом языке — русском, английском, украинском и т.д.) — объясни правило на языке ученика, дай подсказку и попроси ответить еще раз. НЕ переходи к следующему шагу.\n"
        f"2. Если это ОТВЕТ (попытка решить шаг) — оцени его, дай короткую обратную связь и обязательно напиши в конце ключевое слово 'NEXT_STEP', чтобы бот перешел к следующему шагу."
    )

    try:
      completion = client.chat.completions.create(
          model="openai/gpt-oss-20b",
          messages=[{"role": "user", "content": prompt}],
          temperature=0.3,
          max_tokens=300,
      )
      ai_response = (completion.choices[0].message.content or "").strip()
    except Exception as e:
      ai_response = "NEXT_STEP"

    # Если ИИ определил, что это ответ (есть метка NEXT_STEP)
    if "NEXT_STEP" in ai_response:
      clean_response = ai_response.replace("NEXT_STEP", "").strip()
      if clean_response:
        bot.send_message(message.chat.id, clean_response, parse_mode="Markdown")

      data["step"] += 1
      next_step = data["step"]

      if next_step <= 5:
        q_text = STEP_QUESTIONS[next_step].format(hu=hu, ru=ru)
        bot.send_message(message.chat.id, q_text, parse_mode="Markdown")
      else:
        del active_trainings[user_id]
        bot.send_message(
            message.chat.id,
            "Szép munka! Ты успешно прошел все 5 шагов! 🎉 Выбери новый глагол:",
            reply_markup=get_verbs_keyboard(),
        )
    else:
      # Ученик задал вопрос — отвечаем на его языке, шаг НЕ меняем
      bot.send_message(message.chat.id, ai_response, parse_mode="Markdown")
    return

  # 3. Если вне тренировки
  bot.send_message(
      message.chat.id,
      "Давай потренируемся! Выбери глагол для тренировки с помощью кнопок внизу:",
      reply_markup=get_verbs_keyboard(),
  )


print("Река с многоязычной поддержкой запущена...")

while True:
  try:
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
  except Exception as e:
    print(f"Ошибка: {e}")
    time.sleep(5)
