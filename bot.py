from datetime import datetime, timedelta, timezone
import os
import random
import threading
import time
import telebot
from telebot.types import KeyboardButton, ReplyKeyboardMarkup

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
bot = telebot.TeleBot(TELEGRAM_TOKEN)

active_trainings = {}
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
        "q3_eszik": "Шаг 3: Как спросить «Что ты ешь?» с этим глаголом?",
        "q3_iszik": "Шаг 3: Как спросить «Что ты пьешь?» с этим глаголом?",
        "q3_ír": "Шаг 3: Как спросить «Что ты пишешь?» с этим глаголом?",
        "q3_olvas": "Шаг 3: Как спросить «Что ты читаешь?» с этим глаголом?",
        "q3_lát": "Шаг 3: Как спросить «Что ты видишь?» с этим глаголом?",
        "q3_hall": "Шаг 3: Как спросить «Что ты слышишь?» с этим глаголом?",
        "q3_vesz": "Шаг 3: Как спросить «Что ты покупаешь / берешь?» с этим глаголом?",
        "q3_csinál": "Шаг 3: Как спросить «Что ты делаешь?» с этим глаголом?",
        "morning": "☀️ Доброе утро! Время повторить венгерские глаголы?",
        "day": "☕️ Как проходит день? Давай разомнемся и повторим пару глаголов!",
        "evening": "🌙 Вечернее повторение! Не забудь закрепить глаголы перед сном.",
    },
    "en": {
        "name": "🇬🇧 English",
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
        "q3_eszik": "Step 3: How to ask «What are you eating?» with this verb?",
        "q3_iszik": "Step 3: How to ask «What are you drinking?» with this verb?",
        "q3_ír": "Step 3: How to ask «What are you writing?» with this verb?",
        "q3_olvas": "Step 3: How to ask «What are you reading?» with this verb?",
        "q3_lát": "Step 3: How to ask «What do you see?» with this verb?",
        "q3_hall": "Step 3: How to ask «What do you hear?» with this verb?",
        "q3_vesz": "Step 3: How to ask «What are you buying?» with this verb?",
        "q3_csinál": "Step 3: How to ask «What are you doing?» with this verb?",
        "morning": "☀️ Good morning! Time to practice Hungarian verbs?",
        "day": "☕️ How is your day going? Let's practice a few verbs!",
        "evening": (
            "🌙 Evening review! Don't forget to practice before sleep."
        ),
    },
    "es": {
        "name": "🇪🇸 Español",
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
        "q3_eszik": "Paso 3: ¿Cómo preguntar «¿Qué comes?» con este verbo?",
        "q3_iszik": "Paso 3: ¿Cómo preguntar «¿Qué bebes?» con este verbo?",
        "q3_ír": "Paso 3: ¿Cómo preguntar «¿Qué escribes?» con este verbo?",
        "q3_olvas": "Paso 3: ¿Cómo preguntar «¿Qué lees?» con este verbo?",
        "q3_lát": "Paso 3: ¿Cómo preguntar «¿Qué ves?» con este verbo?",
        "q3_hall": "Paso 3: ¿Cómo preguntar «¿Qué oyes?» con este verbo?",
        "q3_vesz": "Paso 3: ¿Cómo preguntar «¿Qué compras?» con este verbo?",
        "q3_csinál": "Paso 3: ¿Cómo preguntar «¿Qué haces?» con este verbo?",
        "morning": "☀️ ¡Buenos Aires! ¿Hora de repasar verbos?",
        "day": "☕️ ¿Cómo va el día? ¡Vamos a practicar unos verbos!",
        "evening": (
            "🌙 Repaso nocturno! No olvides practicar antes de dormir."
        ),
    },
    "fr": {
        "name": "🇫🇷 Français",
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
        "q3_eszik": (
            "Étape 3 : Comment demander « Qu'est-ce que tu manges ? » ?"
        ),
        "q3_iszik": "Étape 3 : Comment demander « Qu'est-ce que tu bois ? » ?",
        "q3_ír": "Étape 3 : Comment demander « Qu'est-ce que tu écris ? » ?",
        "q3_olvas": "Étape 3 : Comment demander « Qu'est-ce que tu lis ? » ?",
        "q3_lát": "Étape 3 : Comment demander « Qu'est-ce que tu vois ? » ?",
        "q3_hall": "Étape 3 : Comment demander « Qu'est-ce que tu entends ? » ?",
        "q3_vesz": "Étape 3 : Comment demander « Qu'est-ce que tu achètes ? » ?",
        "q3_csinál": "Étape 3 : Comment demander « Qu'est-ce que tu fais ? » ?",
        "morning": "☀️ Bonjour ! Il est temps de réviser les verbes ?",
        "day": "☕️ Comment se passe ta journée ? Pratiquons quelques verbes !",
        "evening": "🌙 Révision du soir ! N'oublie pas de réviser avant de dormir.",
    },
    "de": {
        "name": "🇩🇪 Deutsch",
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
        "q3_eszik": (
            "Schritt 3: Wie fragt man „Was isst du?“ mit diesem Verb?"
        ),
        "q3_iszik": (
            "Schritt 3: Wie fragt man „Was trinkst du?“ mit diesem Verb?"
        ),
        "q3_ír": (
            "Schritt 3: Wie fragt man „Was schreibst du?“ mit diesem Verb?"
        ),
        "q3_olvas": "Schritt 3: Wie fragt man „Was liest du?“ mit diesem Verb?",
        "q3_lát": "Schritt 3: Wie fragt man „Was siehst du?“ mit diesem Verb?",
        "q3_hall": "Schritt 3: Wie fragt man „Was hörst du?“ mit diesem Verb?",
        "q3_vesz": "Schritt 3: Wie fragt man „Was kaufst du?“ mit diesem Verb?",
        "q3_csinál": "Schritt 3: Wie fragt man „Was machst du?“ mit diesem Verb?",
        "morning": "☀️ Guten Morgen! Zeit, Verben zu üben?",
        "day": "☕️ Wie läuft dein Tag? Lass uns ein paar Verben üben!",
        "evening": "🌙 Abendliche Wiederholung! Vergiss nicht, vor dem Schlafen zu üben.",
    },
    "it": {
        "name": "🇮🇹 Italiano",
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
        "q3_eszik": "Passo 3: Come chiedere «Cosa mangi?» con questo verbo?",
        "q3_iszik": "Passo 3: Come chiedere «Cosa bevi?» con questo verbo?",
        "q3_ír": "Passo 3: Come chiedere «Cosa scrivi?» con questo verbo?",
        "q3_olvas": "Passo 3: Come chiedere «Cosa leggi?» con questo verbo?",
        "q3_lát": "Passo 3: Come chiedere «Cosa vedi?» con questo verbo?",
        "q3_hall": "Passo 3: Come chiedere «Cosa senti?» con questo verbo?",
        "q3_vesz": "Passo 3: Come chiedere «Cosa compri?» con questo verbo?",
        "q3_csinál": "Passo 3: Come chiedere «Cosa fai?» con questo verbo?",
        "morning": "☀️ Buongiorno! È ora di ripassare i verbi?",
        "day": "☕️ Come va la giornata? Facciamo un po' di pratica!",
        "evening": "🌙 Ripasso serale! Non dimenticare di ripassare prima di dormire.",
    },
    "pl": {
        "name": "🇵🇱 Polski",
        "welcome": "Świetnie! Wybierz czasownik do ćwiczeń za pomocą przycisków:",
        "choose_btn": "Proszę wybrać czasownik za pomocą przycisków:",
        "correct": "Dobrze! 🎉",
        "fire": "Świetnie! 🔥",
        "finish": "🎉 Super! Wszystko zrobione! Wybierz nowy czasownik:",
        "retry": "Nie do końca. Spróbuj ponownie dla «{v}»:",
        "q1": "Krok 1: Jaki jest bezokolicznik dla «{v}»?",
        "q2": "Krok 2: Jaka jest forma 'on/ona' dla «{v}»?",
        "q3_eszik": "Krok 3: Jak zapytać „Co jesz?” tym czasownikiem?",
        "q3_iszik": "Krok 3: Jak zapytać „Co pijesz?” tym czasownikiem?",
        "q3_ír": "Krok 3: Jak zapytać „Co piszesz?” tym czasownikiem?",
        "q3_olvas": "Krok 3: Jak zapytać „Co czytasz?” tym czasownikiem?",
        "q3_lát": "Krok 3: Jak zapytać „Co widzisz?” tym czasownikiem?",
        "q3_hall": "Krok 3: Jak zapytać „Co słyszysz?” tym czasownikiem?",
        "q3_vesz": "Krok 3: Jak zapytać „Co kupujesz?” tym czasownikiem?",
        "q3_csinál": "Krok 3: Jak zapytać „Co robisz?” tym czasownikiem?",
        "morning": "☀️ Dzień dobry! Czas powtórzyć czasowniki?",
        "day": "☕️ Jak mija dzień? Przećwiczmy kilka czasowników!",
        "evening": "🌙 Wieczorna powtórka! Nie zapomnij poćwiczyć przed snem.",
    },
    "uk": {
        "name": "🇺🇦 Українська",
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
        "q3_eszik": "Крок 3: Як спитати «Що ти їшь?» з цим дієсловом?",
        "q3_iszik": "Крок 3: Як спитати «Що ти п'єш?» з цим дієсловом?",
        "q3_ír": "Крок 3: Як спитати «Що ти пишеш?» з цим дієсловом?",
        "q3_olvas": "Крок 3: Як спитати «Що ти читаєш?» з цим дієсловом?",
        "q3_lát": "Крок 3: Як спитати «Що ти бачиш?» з цим дієсловом?",
        "q3_hall": "Крок 3: Як спитати «Що ти чуєш?» з цим дієсловом?",
        "q3_vesz": "Крок 3: Як спитати «Що ти купуєш / береш?» з цим дієсловом?",
        "q3_csinál": "Крок 3: Як спитати «Що ти робиш?» з цим дієсловом?",
        "morning": "☀️ Доброго ранку! Час повторити угорські дієслова?",
        "day": "☕️ Як проходить день? Давай розімнемося і повторимо пару дієслів!",
        "evening": "🌙 Вечірнє повторення! Не забудь закріпити дієслова перед сном.",
    },
    "zh": {
        "name": "🇨🇳 中文",
        "welcome": "太好了！请使用下方的按钮选择要练习的动词：",
        "choose_btn": "请使用按钮选择动词：",
        "correct": "正确！🎉",
        "fire": "太棒了！🔥",
        "finish": "🎉 太棒了！3个步骤已全部完成！请选择新动词：",
        "retry": "不太对。请再试一次「{v}」：",
        "q1": "第一步：「{v}」的不定式是什么？",
        "q2": "第二步：「{v}」的第三人称（他/她）形式是什么？",
        "q3_eszik": "第三步：如何用这个动词问“你在吃什么？”？",
        "q3_iszik": "第三步：如何用这个动词问“你在喝什么？”？",
        "q3_ír": "第三步：如何用这个动词问“你在写什么？”？",
        "q3_olvas": "第三步：如何用这个动词问“你在读什么？”？",
        "q3_lát": "第三步：如何用这个动词问“你看到了什么？”？",
        "q3_hall": "第三步：如何用这个动词问“你听到了什么？”？",
        "q3_vesz": "第三步：如何用这个动词问你在买什么？",
        "q3_csinál": "第三步：如何用这个动词问“你在做什么？”？",
        "morning": "☀️ 早上好！是时候练习匈牙利语动词了吗？",
        "day": "☕️ 今天过得怎么样？让我们练习几个动词吧！",
        "evening": "🌙 晚间复习！睡觉前别忘了复习动词。",
    },
    "pt": {
        "name": "🇵🇹 Português",
        "welcome": "Ótimo! Escolha um verbo para praticar usando os botões abaixo:",
        "choose_btn": "Por favor, escolha um verbo usando os botões:",
        "correct": "Correto! 🎉",
        "fire": "Excelente! 🔥",
        "finish": "🎉 Parabéns! 3 etapas concluídas! Escolha um novo verbo:",
        "retry": "Não exatamente. Tente novamente para «{v}»:",
        "q1": "Passo 1: Qual é o infinitivo para «{v}»?",
        "q2": "Passo 2: Qual é a forma de ele/ela para «{v}»?",
        "q3_eszik": "Passo 3: Como perguntar «O que você está comendo?»?",
        "q3_iszik": "Passo 3: Como perguntar «O que você está bebendo?»?",
        "q3_ír": "Passo 3: Como perguntar «O que você está escrevendo?»?",
        "q3_olvas": "Passo 3: Como perguntar «O que você está lendo?»?",
        "q3_lát": "Passo 3: Como perguntar «O que você vê?»?",
        "q3_hall": "Passo 3: Como perguntar «O que você ouve?»?",
        "q3_vesz": "Passo 3: Como perguntar «O que você está comprando?»?",
        "q3_csinál": "Passo 3: Como perguntar «O que você está fazendo?»?",
        "morning": "☀️ Bom dia! Hora de praticar os verbos húngaros?",
        "day": "☕️ Como está sendo o seu dia? Vamos praticar alguns verbos!",
        "evening": "🌙 Revisão da noite! Não se esqueça de praticar antes de dormir.",
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

  current_lang = active_trainings.get(user_id, {}).get("lang")

  if current_lang and current_lang in LANGUAGES:
    active_trainings[user_id] = {"lang": current_lang, "step": 0}
    l_data = LANGUAGES[current_lang]
    bot.send_message(
        message.chat.id,
        l_data["welcome"],
        reply_markup=get_verbs_keyboard(current_lang),
    )
  else:
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
      # Точные вопросы для Шага 2 под каждый глагол
      if hu == "eszik":
        q2_text = (
            f"Шаг 2: Как будет «он / она ест» для глагола «{verb_name}»?"
            if lang == "ru"
            else f"Step 2: What is 'he/she eats' for «{verb_name}»?"
        )
      elif hu == "iszik":
        q2_text = (
            f"Шаг 2: Как будет «он / она пьет» для глагола «{verb_name}»?"
            if lang == "ru"
            else f"Step 2: What is 'he/she drinks' for «{verb_name}»?"
        )
      elif hu == "ír":
        q2_text = (
            f"Шаг 2: Как будет «он / она пишет» для глагола «{verb_name}»?"
            if lang == "ru"
            else f"Step 2: What is 'he/she writes' for «{verb_name}»?"
        )
      elif hu == "olvas":
        q2_text = (
            f"Шаг 2: Как будет «он / она читает» для глагола «{verb_name}»?"
            if lang == "ru"
            else f"Step 2: What is 'he/she reads' for «{verb_name}»?"
        )
      elif hu == "lát":
        q2_text = (
            f"Шаг 2: Как будет «он / она видит» для глагола «{verb_name}»?"
            if lang == "ru"
            else f"Step 2: What is 'he/she sees' for «{verb_name}»?"
        )
      elif hu == "hall":
        q2_text = (
            f"Шаг 2: Как будет «он / она слышит» для глагола «{verb_name}»?"
            if lang == "ru"
            else f"Step 2: What is 'he/she hears' for «{verb_name}»?"
        )
      elif hu == "vesz":
        q2_text = (
            f"Шаг 2: Как будет «он / она берет / покупает» для глагола"
            f" «{verb_name}»?"
            if lang == "ru"
            else f"Step 2: What is 'he/she buys' for «{verb_name}»?"
        )
      else:
        q2_text = l_data["q2"].format(v=verb_name)

      send_reply(message.chat.id, f"{l_data['correct']}\n\n{q2_text}", hu)
    elif next_step == 3:
      q3_key = f"q3_{hu}"
      q3_text = l_data.get(q3_key, l_data["q3_csinál"])

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


# Настройка часового пояса Центральной Европы (Будапешт / UTC+2 летом, UTC+1 зимой)
BUDAPEST_TZ = timezone(timedelta(hours=2))


def daily_reminders_loop():
  while True:
    now_hour = datetime.now(BUDAPEST_TZ).hour
    if now_hour in [9, 14, 20]:
      time_key = (
          "morning"
          if now_hour == 9
          else ("day" if now_hour == 14 else "evening")
      )
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
      time.sleep(3700)
    else:
      time.sleep(600)


threading.Thread(target=daily_reminders_loop, daemon=True).start()

print("Река запущена со всеми исправлениями...")

while True:
  try:
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
  except Exception as e:
    print(f"Ошибка: {e}")
    time.sleep(5)
