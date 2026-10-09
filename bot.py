import os
import random
import time
import telebot
from telebot.types import KeyboardButton, ReplyKeyboardMarkup

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# Храним состояние: {user_id: {"lang": "ru/en/...", "step": 0}}
active_trainings = {}

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

# Поддерживаемые языки и их переводы интерфейса
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
    },
    "es": {
        "name": "🇪🇸 Español",
        "choose": "Elige tu idioma:",
        "welcome": (
            "¡Genial! Elige un verbo para practicar usando los botones de"
            " abajo:"
        ),
        "choose_btn": "Por favor, elige un verbo usando los botones:",
        "correct": "¡Correcto! 🎉",
        "fire": "¡Excelente! 🔥",
        "finish": (
            "🎉 ¡Increíble! ¡Los 3 pasos completados! Elige un nuevo verbo:"
        ),
        "retry": "No exactamente. Inténtalo de nuevo para «{v}»:",
        "q1": "Paso 1: ¿Cuál es el infinitivo para «{v}»?",
        "q2": "Paso 2: ¿Cuál es la forma de él/ella para «{v}»?",
        "q3_eszik": "¿Cómo preguntar «¿Qué comes?» con este verbo?",
        "q3_iszik": "¿Cómo preguntar «¿Qué bebes?» con este verbo?",
        "q3_ír": "¿Cómo preguntar «¿Qué escribes?» con este verbo?",
        "q3_olvas": "¿Cómo preguntar «¿Qué lees?» con este verbo?",
        "q3_lát": "¿Cómo preguntar «¿Qué ves?» con este verbo?",
        "q3_def": "¿Cómo preguntar «¿Qué haces?» con este verbo?",
    },
    "fr": {
        "name": "🇫🇷 Français",
        "choose": "Choisissez votre langue :",
        "welcome": (
            "Super ! Choisissez un verbe à pratiquer en utilisant les boutons"
            " ci-dessous :"
        ),
        "choose_btn": "Veuillez choisir un verbe en utilisant les boutons :",
        "correct": "Correct ! 🎉",
        "fire": "Excellent ! 🔥",
        "finish": (
            "🎉 Bravo ! Les 3 étapes sont terminées ! Choisissez un nouveau"
            " verbe :"
        ),
        "retry": "Pas tout à fait. Réessayez pour «{v}» :",
        "q1": "Étape 1 : Quel est l'infinitif pour «{v}» ?",
        "q2": "Étape 2 : Quelle est la forme 'il/elle' pour «{v}» ?",
        "q3_eszik": "Comment demander « Qu'est-ce que tu manges ? » ?",
        "q3_iszik": "Comment demander « Qu'est-ce que tu bois ? » ?",
        "q3_ír": "Comment demander « Qu'est-ce que tu écris ? » ?",
        "q3_olvas": "Comment demander « Qu'est-ce que tu lis ? » ?",
        "q3_lát": "Comment demander « Qu'est-ce que tu vois ? » ?",
        "q3_def": "Comment demander « Qu'est-ce que tu fais ? » ?",
    },
    "de": {
        "name": "🇩🇪 Deutsch",
        "choose": "Wähle deine Sprache:",
        "welcome": (
            "Super! Wähle ein Verb zum Üben mit den Buttons unten:"
        ),
        "choose_btn": "Bitte wähle ein Verb über die Buttons:",
        "correct": "Richtig! 🎉",
        "fire": "Super! 🔥",
        "finish": (
            "🎉 Geschafft! Alle 3 Schritte abgeschlossen! Wähle ein neues Verb:"
        ),
        "retry": "Nicht ganz. Versuche es noch einmal für «{v}»:",
        "q1": "Schritt 1: Wie lautet der Infinitiv für «{v}»?",
        "q2": "Schritt 2: Wie lautet die 'er/sie'-Form für «{v}»?",
        "q3_eszik": "Wie fragt man „Was isst du?“ mit diesem Verb?",
        "q3_iszik": "Wie fragt man „Was trinkst du?“ mit diesem Verb?",
        "q3_ír": "Wie fragt man „Was schreibst du?“ mit diesem Verb?",
        "q3_olvas": "Wie fragt man „Was liest du?“ mit diesem Verb?",
        "q3_lát": "Wie fragt man „Was siehst du?“ mit diesem Verb?",
        "q3_def": "Wie fragt man „Was machst du?“ mit diesem Verb?",
    },
    "it": {
        "name": "🇮🇹 Italiano",
        "choose": "Scegli la tua lingua:",
        "welcome": (
            "Ottimo! Scegli un verbo da praticare usando i pulsanti in basso:"
        ),
        "choose_btn": "Per favore, scegli un verbo usando i pulsanti:",
        "correct": "Corretto! 🎉",
        "fire": "Ottimo! 🔥",
        "finish": "🎉 Ottimo lavoro! 3 passaggi completati! Scegli un nuovo verbo:",
        "retry": "Non proprio. Riprova per «{v}»:",
        "q1": "Passo 1: Qual è l'infinito per «{v}»?",
        "q2": "Passo 2: Qual è la forma 'lui/lei' per «{v}»?",
        "q3_eszik": "Come chiedere «Cosa mangi?» con questo verbo?",
        "q3_iszik": "Come chiedere «Cosa bevi?» con questo verbo?",
        "q3_ír": "Come chiedere «Cosa scrivi?» con questo verbo?",
        "q3_olvas": "Come chiedere «Cosa leggi?» con questo verbo?",
        "q3_lát": "Come chiedere «Cosa vedi?» con questo verbo?",
        "q3_def": "Come chiedere «Cosa fai?» con questo verbo?",
    },
    "pl": {
        "name": "🇵🇱 Polski",
        "choose": "Wybierz swój język:",
        "welcome": "Świetnie! Wybierz czasownik do ćwiczeń za pomocą przycisków:",
        "choose_btn": "Proszę wybrać czasownik za pomocą przycisków:",
        "correct": "Dobrze! 🎉",
        "fire": "Świetnie! 🔥",
        "finish": "🎉 Super! Wszystko zrobione! Wybierz nowy czasownik:",
        "retry": "Nie do końca. Spróbuj ponownie dla «{v}»:",
        "q1": "Krok 1: Jaki jest bezokolicznik dla «{v}»?",
        "q2": "Krok 2: Jaka jest forma 'on/ona' dla «{v}»?",
        "q3_eszik": "Jak zapytać „Co jesz?” tym czasownikiem?",
        "q3_iszik": "Jak zapytać „Co pijesz?” tym czasownikiem?",
        "q3_ír": "Jak zapytać „Co piszesz?” tym czasownikiem?",
        "q3_olvas": "Jak zapytać „Co czytasz?” tym czasownikiem?",
        "q3_lát": "Jak zapytać „Co widzisz?” tym czasownikiem?",
        "q3_def": "Jak zapytać „Co robisz?” tym czasownikiem?",
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
    },
    "zh": {
        "name": "🇨🇳 中文",
        "choose": "请选择您的语言：",
        "welcome": "太好了！请使用下方的按钮选择要练习的动词：",
        "choose_btn": "请使用按钮选择动词：",
        "correct": "正确！🎉",
        "fire": "太棒了！🔥",
        "finish": "🎉 太棒了！3个步骤已全部完成！请选择新动词：",
        "retry": "不太对。请再试一次「{v}」：",
        "q1": "第一步：「{v}」的不定式是什么？",
        "q2": "第二步：「{v}」的第三人称（他/她）形式是什么？",
        "q3_eszik": "如何用这个动词问“你在吃什么？”？",
        "q3_iszik": "如何用这个动词问“你在喝什么？”？",
        "q3_ír": "如何用这个动词问“你在写什么？”？",
        "q3_olvas": "如何用这个动词问“你在读什么？”？",
        "q3_lát": "如何用这个动词问“你看到了什么？”？",
        "q3_def": "如何用这个动词问“你在做什么？”？",
    },
    "pt": {
        "name": "🇵🇹 Português",
        "choose": "Escolha o seu idioma:",
        "welcome": "Ótimo! Escolha um verbo para praticar usando os botões abaixo:",
        "choose_btn": "Por favor, escolha um verbo usando os botões:",
        "correct": "Correto! 🎉",
        "fire": "Excelente! 🔥",
        "finish": "🎉 Parabéns! 3 etapas concluídas! Escolha um novo verbo:",
        "retry": "Não exatamente. Tente novamente para «{v}»:",
        "q1": "Passo 1: Qual é o infinitivo para «{v}»?",
        "q2": "Passo 2: Qual é a forma de ele/ela para «{v}»?",
        "q3_eszik": "Como perguntar «O que você está comendo?» com este verbo?",
        "q3_iszik": "Como perguntar «O que você está bebendo?» com este verbo?",
        "q3_ír": "Como perguntar «O que você está escrevendo?» com este verbo?",
        "q3_olvas": "Como perguntar «O que você está lendo?» com este verbo?",
        "q3_lát": "Como perguntar «O que você vê?» com este verbo?",
        "q3_def": "Como perguntar «O que você está fazendo?» com este verbo?",
    },
}


def get_language_keyboard():
  markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
  keys = list(LANGUAGES.keys())
  for i in range(0, len(keys), 2):
    row = [KeyboardButton(text=LANGUAGES[keys[i]]["name"])]
    if i + 1 < len(keys):
      row.append(KeyboardButton(text=LANGUAGES[keys[i + 1]]["name"]))
    markup.add(*row)
  return markup


def get_verbs_keyboard(lang="ru"):
  selected = random.sample(VERBS_DATABASE, 3)
  markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
  for hu, ru, en, inf in selected:
    if lang == "en":
      label = f"{hu} ({en})"
    elif lang == "ru" or lang == "uk":
      label = f"{hu} ({ru})"
    else:
      label = f"{hu} ({en})"
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
  active_trainings[user_id] = {"lang": None, "step": 0}

  bot.send_message(
      message.chat.id,
      "🌍 Выберите язык интерфейса / Choose your language:",
      reply_markup=get_language_keyboard(),
  )


@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
  user_id = message.from_user.id
  text = message.text.strip()
  text_lower = text.lower()

  # 1. Проверяем выбор языка
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
    l_data = LANGUAGES[selected_lang]

    bot.send_message(
        message.chat.id,
        l_data["welcome"],
        reply_markup=get_verbs_keyboard(selected_lang),
    )
    return

  data = active_trainings[user_id]
  lang = data["lang"]
  l_data = LANGUAGES[lang]

  # 2. Если ждем выбор глагола
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

      verb_name = (
          ru if lang in ["ru", "uk"] else (en if lang != "ru" else hu)
      )
      q_text = l_data["q1"].format(v=verb_name)
      send_reply(message.chat.id, q_text, inf)
    else:
      bot.send_message(
          message.chat.id,
          l_data["choose_btn"],
          reply_markup=get_verbs_keyboard(lang),
      )
    return

  # 3. Активная тренировка по шагам
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


print("Réka запущена с поддержкой топ-10 мировых языков...")

while True:
  try:
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
  except Exception as e:
    print(f"Ошибка: {e}")
    time.sleep(5)
