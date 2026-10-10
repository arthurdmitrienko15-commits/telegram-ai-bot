import os
import random
import threading
import time
import telebot
from telebot.types import KeyboardButton, ReplyKeyboardMarkup

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# Храним состояние: {user_id: {"lang": "ru/en/...", "step": 0}}
active_trainings = {}
# Список активных пользователей для рассылки
all_users = set()

VERBS_DATABASE = [
    ("csinál", "делать", "to do", "csinálni"),
    ("olvas", "читать", "to read", "olvasni"),
    ("ír", "писать", "to write", "írni"),
    ("eszik", "есть", "to eat", "enni"),
    ("iszik", "пить", "to drink", "inni"),
    ("lát", "видеть", "to see", "látni"),
    ("hall", "слышать", "to hear", "hallani"),
    ("vesz", "брать / покупать", "to buy", "venni"),
]

LANGUAGES = {
    "ru": {
        "name": "🇷🇺 Русский",
        "choose": "Выберите язык интерфейса:",
        "welcome": (
            "Отлично! Выбери глагол для тренировки с помощью кнопок внизу:"
        ),
        "choose_btn": "Пожалуйста, выбери глагол с помощью кнопок:",
        "correct": "Правильно! 🎉",
        "fire": "Отлично! 🔥",
        "finish": "🎉 Молодчина! Все 3 шага пройдены! Выбери новый глагол:",
        "retry": "Не совсем так. Попробуй еще раз для глагола «{v}»:",
        "q1": "Шаг 1: Как будет глагол «{v}» в начальной форме (инфинитив)?",
        "q2": "Шаг 2: Как будет «он / она делает» для глагола «{v}»?",
        "q3_eszik": "Как спросить «Что ты ешь?» с этим глаголом?",
        "q3_iszik": "Как спросить «Что ты пьешь?» с этим глаголом?",
        "q3_ír": "Как спросить «Что ты пишешь?» с этим глаголом?",
        "q3_olvas": "Как спросить «Что ты читаешь?» с этим глаголом?",
        "q3_lát": "Как спросить «Что ты видишь?» с этим глаголом?",
        "q3_def": "Как спросить «Что ты делаешь?» с этим глаголом?",
        "morning": "☀️ Доброе утро! Время повторить венгерские глаголы?",
        "day": "☕️ Как проходит день? Давай разомнемся и повторим пару глаголов!",
        "evening": "🌙 Вечернее повторение! Не забудь закрепить глаголы перед сном.",
    },
    "en": {
        "name": "🇬🇧 English",
        "choose": "Choose your language:",
        "welcome": "Great! Choose a verb to practice using the buttons below:",
        "choose_btn": "Please choose a verb using the buttons:",
        "correct": "Correct! 🎉",
        "fire": "Great! 🔥",
        "finish": (
            "🎉 Awesome! All 3 steps completed! Choose a new verb:"
        ),
        "retry": "Not quite. Try again for «{v}»:",
        "q1": "Step 1: What is the infinitive form for «{v}»?",
        "q2": "Step 2: What is the 'he/she' form for «{v}»?",
        "q3_eszik": "How to ask «What are you eating?» with this verb?",
        "q3_iszik": "How to ask «What are you drinking?» with this verb?",
        "q3_ír": "How to ask «What are you writing?» with this verb?",
        "q3_olvas": "How to ask «What are you reading?» with this verb?",
        "q3_lát": "How to ask «What do you see?» with this verb?",
        "q3_def": "How to ask «What are you doing?» with this verb?",
        "morning": "☀️ Good morning! Time to practice Hungarian verbs?",
        "day": "☕️ How is your day going? Let's practice a few verbs!",
        "evening": (
            "🌙 Evening review! Don't forget to practice before sleep."
        ),
    },
    "uk": {
        "name": "🇺🇦 Українська",
        "choose": "Виберіть мову інтерфейсу:",
        "welcome": (
            "Чудово! Вибери дієслово для тренування за допомогою кнопок внизу:"
        ),
        "choose_btn": "Будь ласка, вибери дієслово за допомогою кнопок:",
        "correct": "Правильно! 🎉",
        "fire": "Чудово! 🔥",
        "finish": (
            "🎉 Молодчина! Всі 3 кроки пройдено! Вибери нове дієслово:"
        ),
        "retry": "Не зовсім так. Спробуй ще раз для дієслова «{v}»:",
        "q1": "Крок 1: Як буде дієслово «{v}» в початковій формі (інфінітив)?",
        "q2": "Крок 2: Як буде «він / вона робить» для дієслова «{v}»?",
        "q3_eszik": "Як спитати «Що ти їшь?» з цим дієсловом?",
        "q3_iszik": "Як спитати «Що ти п'єш?» з цим дієсловом?",
        "q3_ír": "Як спитати «Що ти пишеш?» з цим дієсловом?",
        "q3_olvas": "Як спитати «Що ти читаєш?» з цим дієсловом?",
        "q3_lát": "Як спитати «Що ти бачиш?» з цим дієсловом?",
        "q3_def": "Як спитати «Що ти робиш?» з цим дієсловом?",
        "morning": "☀️ Доброго ранку! Час повторити угорські дієслова?",
        "day": "☕️ Як проходить день? Давай розімнемося і повторимо пару дієслів!",
        "evening": "🌙 Вечірнє повторення! Не забудь закріпити дієслова перед сном.",
    },
}


def get_language_keyboard():
  markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
  for code, data in LANGUAGES.items():
    markup.add(KeyboardButton(text=data["name"]))
  return markup


def get_verbs_keyboard(lang="ru"):
  selected = random.sample(VERBS_DATABASE, 3)
  markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
  for hu, ru, en, inf in selected:
    if lang == "en":
      label = f"{hu} ({en})"
    else:
      label = f"{hu} ({ru})"
    markup.add(KeyboardButton(text=label))
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
  all_users.add(user_id)
  active_trainings[user_id] = {"lang": None, "step": 0}

  bot.send_message(
      message.chat.id,
      "🌍 Выберите язык интерфейса / Choose your language:",
      reply_markup=get_language_keyboard(),
  )


@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
  user_id = message.from_user.id
  all_users.add(user_id)
  text = message.text.strip()
  text_lower = text.lower()

  if (
      user_id not in active_trainings
      or active_trainings[user_id].get("lang") is None
  ):
    selected_lang = "ru"
    for code, data in LANGUAGES.items():
      if data["name"].lower() in text_lower or code in text_lower:
        selected_lang = code
        break

    active_trainings[user_id] = {"lang": selected_lang, "step": 0}
    l_data = LANGUAGES.get(selected_lang, LANGUAGES["ru"])

    bot.send_message(
        message.chat.id,
        l_data["welcome"],
        reply_markup=get_verbs_keyboard(selected_lang),
    )
    return

  data = active_trainings[user_id]
  lang = data["lang"]
  l_data = LANGUAGES.get(lang, LANGUAGES["ru"])

  if "verb_hu" not in data:
    found_verb = None
    for hu, ru, en, inf in VERBS_DATABASE:
      if hu in text_lower or ru.lower() in text_lower or en.lower() in text_lower:
        found_verb = (hu, ru, en, inf)
        break

    if found_verb:
      hu, ru, en, inf = found_verb
      data["verb_hu"] = hu
      data["verb_ru"] = ru
      data["verb_en"] = en
      data["inf"] = inf
      data["step"] = 1

      verb_name = ru if lang in ["ru", "uk"] else (en if lang != "ru" else hu)
      q_text = l_data["q1"].format(v=verb_name)
      send_reply(message.chat.id, q_text, inf)
    else:
      bot.send_message(
          message.chat.id,
          l_data["choose_btn"],
          reply_markup=get_verbs_keyboard(lang),
      )
    return

  step = data["step"]
  hu = data["verb_hu"]
  ru = data["verb_ru"]
  en = data["verb_en"]
  inf = data["inf"]
  verb_name = ru if lang in ["ru", "uk"] else (en if lang != "ru" else hu)

  if step == 1:
    correct = inf
  elif step == 2:
    correct = hu
  elif step == 3:
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

  clean_text = (
      text_lower.replace("á", "a")
      .replace("í", "i")
      .replace("é", "e")
      .replace("?", "")
      .strip()
  )
  clean_correct = (
      correct.replace("á", "a")
      .replace("í", "i")
      .replace("é", "e")
      .replace("?", "")
      .strip()
  )

  if clean_correct in clean_text or clean_text in clean_correct:
    data["step"] += 1
    next_step = data["step"]

    if next_step == 2:
      q2_text = l_data["q2"].format(v=verb_name)
      send_reply(message.chat.id, f"{l_data['correct']}\n\n{q2_text}", hu)
    elif next_step == 3:
      if hu == "eszik":
        q3_text = l_data["q3_eszik"]
      elif hu == "iszik":
        q3_text = l_data["q3_iszik"]
      elif hu == "ír":
        q3_text = l_data["q3_ír"]
      elif hu == "olvas":
        q3_text = l_data["q3_olvas"]
      elif hu == "lát":
        q3_text = l_data["q3_lát"]
      else:
        q3_text = l_data["q3_def"]

      send_reply(message.chat.id, f"{l_data['fire']}\n\n{q3_text}", correct)
    else:
      del data["verb_hu"]
      del data["verb_ru"]
      del data["verb_en"]
      del data["inf"]
      data["step"] = 0

      bot.send_message(
          message.chat.id,
          l_data["finish"],
          reply_markup=get_verbs_keyboard(lang),
      )
  else:
    if step == 1:
      spoiler = inf
    elif step == 2:
      spoiler = hu
    else:
      spoiler = correct

    retry_text = l_data["retry"].format(v=verb_name)
    send_reply(message.chat.id, retry_text, spoiler)


# Фоновый поток для отправки утренних, дневных и вечерних напоминаний
def daily_reminders_loop():
  while True:
    now_hour = time.localtime().tm_hour
    # Отправляем в 9:00 (утро), 14:00 (день), 20:00 (вечер)
    if now_hour in [9, 14, 20]:
      time_key = "morning" if now_hour == 9 else ("day" if now_hour == 14 else "evening")
      for user_id in list(all_users):
        try:
          user_lang = active_trainings.get(user_id, {}).get("lang", "ru")
          l_data = LANGUAGES.get(user_lang, LANGUAGES["ru"])
          bot.send_message(
              user_id,
              l_data[time_key],
              reply_markup=get_verbs_keyboard(user_lang),
          )
        except Exception as e:
          print(f"Ошибка отправки напоминания пользователю {user_id}: {e}")
      # Ждем больше часа, чтобы сообщение не отправилось дважды в тот же час
      time.sleep(3700)
    else:
      time.sleep(600)


# Запускаем фоновый поток рассылки
threading.Thread(target=daily_reminders_loop, daemon=True).start()

print("Река запущена с рассылкой (утро, день, вечер) и языками...")

while True:
  try:
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
  except Exception as e:
    print(f"Ошибка: {e}")
    time.sleep(5)
