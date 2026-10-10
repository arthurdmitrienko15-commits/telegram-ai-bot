import os
import random
import threading
import time
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

import telebot
from telebot.types import KeyboardButton, ReplyKeyboardMarkup

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
bot = telebot.TeleBot(TELEGRAM_TOKEN)

BUDAPEST_TZ = ZoneInfo("Europe/Budapest")

active_trainings = {}
all_users = set()

# (форма «он/она» = ключ, русский, английский, инфинитив)
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

ORDER = ["csinál", "olvas", "ír", "eszik", "iszik", "lát", "hall", "vesz"]

# Правильные ответы для шага 3 (полная фраза)
STEP3_ANSWERS = {
    "csinál": "mit csinálsz?",
    "olvas": "mit olvasol?",
    "ír": "mit írsz?",
    "eszik": "mit eszel?",
    "iszik": "mit iszol?",
    "lát": "mit látsz?",
    "hall": "mit hallasz?",
    "vesz": "mit veszel?",
}


def L(forms, phrases):
    return dict(zip(ORDER, forms)), dict(zip(ORDER, phrases))


_ru_forms, _ru_phr = L(
    ["делает", "читает", "пишет", "ест", "пьёт", "видит", "слышит", "покупает"],
    ["Что ты делаешь?", "Что ты читаешь?", "Что ты пишешь?", "Что ты ешь?",
     "Что ты пьёшь?", "Что ты видишь?", "Что ты слышишь?", "Что ты покупаешь?"],
)
_uk_forms, _uk_phr = L(
    ["робить", "читає", "пише", "їсть", "п'є", "бачить", "чує", "купує"],
    ["Що ти робиш?", "Що ти читаєш?", "Що ти пишеш?", "Що ти їси?",
     "Що ти п'єш?", "Що ти бачиш?", "Що ти чуєш?", "Що ти купуєш?"],
)
_en_forms, _en_phr = L(
    ["does", "reads", "writes", "eats", "drinks", "sees", "hears", "buys"],
    ["What are you doing?", "What are you reading?", "What are you writing?",
     "What are you eating?", "What are you drinking?", "What do you see?",
     "What do you hear?", "What are you buying?"],
)
_es_forms, _es_phr = L(
    ["hace", "lee", "escribe", "come", "bebe", "ve", "oye", "compra"],
    ["¿Qué haces?", "¿Qué lees?", "¿Qué escribes?", "¿Qué comes?",
     "¿Qué bebes?", "¿Qué ves?", "¿Qué oyes?", "¿Qué compras?"],
)
_fr_forms, _fr_phr = L(
    ["fait", "lit", "écrit", "mange", "boit", "voit", "entend", "achète"],
    ["Qu'est-ce que tu fais ?", "Qu'est-ce que tu lis ?",
     "Qu'est-ce que tu écris ?", "Qu'est-ce que tu manges ?",
     "Qu'est-ce que tu bois ?", "Qu'est-ce que tu vois ?",
     "Qu'est-ce que tu entends ?", "Qu'est-ce que tu achètes ?"],
)
_de_forms, _de_phr = L(
    ["macht", "liest", "schreibt", "isst", "trinkt", "sieht", "hört", "kauft"],
    ["Was machst du?", "Was liest du?", "Was schreibst du?", "Was isst du?",
     "Was trinkst du?", "Was siehst du?", "Was hörst du?", "Was kaufst du?"],
)
_it_forms, _it_phr = L(
    ["fa", "legge", "scrive", "mangia", "beve", "vede", "sente", "compra"],
    ["Cosa fai?", "Cosa leggi?", "Cosa scrivi?", "Cosa mangi?", "Cosa bevi?",
     "Cosa vedi?", "Cosa senti?", "Cosa compri?"],
)
_pl_forms, _pl_phr = L(
    ["robi", "czyta", "pisze", "je", "pije", "widzi", "słyszy", "kupuje"],
    ["Co robisz?", "Co czytasz?", "Co piszesz?", "Co jesz?", "Co pijesz?",
     "Co widzisz?", "Co słyszysz?", "Co kupujesz?"],
)
_zh_forms, _zh_phr = L(
    ["做", "读", "写", "吃", "喝", "看见", "听见", "买"],
    ["你在做什么？", "你在读什么？", "你在写什么？", "你在吃什么？",
     "你在喝什么？", "你看到了什么？", "你听到了什么？", "你在买什么？"],
)
_pt_forms, _pt_phr = L(
    ["faz", "lê", "escreve", "come", "bebe", "vê", "ouve", "compra"],
    ["O que você está fazendo?", "O que você está lendo?",
     "O que você está escrevendo?", "O que você está comendo?",
     "O que você está bebendo?", "O que você vê?", "O que você ouve?",
     "O que você está comprando?"],
)

LANGUAGES = {
    "ru": {
        "name": "🇷🇺 Русский",
        "welcome": "Отлично! Выбери глагол для тренировки с помощью кнопок внизу:",
        "choose_btn": "Пожалуйста, выбери глагол с помощью кнопок:",
        "correct": "Правильно! 🎉",
        "fire": "Отлично! 🔥",
        "finish": "🎉 Молодчина! Все 3 шага пройдены! Выбери новый глагол:",
        "retry": "Не совсем так. Попробуй ещё раз для глагола «{v}»:",
        "q1": "Шаг 1: Как будет «{v}» по-венгерски?",
        "q2": "Шаг 2: Как будет «он / она {f}»?",
        "q3": "Шаг 3: Как будет «{p}»?",
        "forms": _ru_forms,
        "phrases": _ru_phr,
        "morning": "☀️ Доброе утро! Время повторить венгерские глаголы?",
        "day": "☕️ Как проходит день? Давай разомнёмся и повторим пару глаголов!",
        "evening": "🌙 Вечернее повторение! Не забудь закрепить глаголы перед сном.",
    },
    "en": {
        "name": "🇬🇧 English",
        "welcome": "Great! Choose a verb to practice using the buttons below:",
        "choose_btn": "Please choose a verb using the buttons:",
        "correct": "Correct! 🎉",
        "fire": "Great! 🔥",
        "finish": "🎉 Awesome! All 3 steps completed! Choose a new verb:",
        "retry": "Not quite. Try again for «{v}»:",
        "q1": "Step 1: How do you say «{v}» in Hungarian?",
        "q2": "Step 2: How do you say 'he/she {f}'?",
        "q3": "Step 3: How do you say «{p}»?",
        "forms": _en_forms,
        "phrases": _en_phr,
        "morning": "☀️ Good morning! Time to practice Hungarian verbs?",
        "day": "☕️ How is your day going? Let's practice a few verbs!",
        "evening": "🌙 Evening review! Don't forget to practice before sleep.",
    },
    "es": {
        "name": "🇪🇸 Español",
        "welcome": "¡Genial! Elige un verbo para practicar usando los botones de abajo:",
        "choose_btn": "Por favor, elige un verbo usando los botones:",
        "correct": "¡Correcto! 🎉",
        "fire": "¡Excelente! 🔥",
        "finish": "🎉 ¡Increíble! ¡Los 3 pasos completados! Elige un nuevo verbo:",
        "retry": "No exactamente. Inténtalo de nuevo para «{v}»:",
        "q1": "Paso 1: ¿Cómo se dice «{v}» en húngaro?",
        "q2": "Paso 2: ¿Cómo se dice «él/ella {f}»?",
        "q3": "Paso 3: ¿Cómo se dice «{p}»?",
        "forms": _es_forms,
        "phrases": _es_phr,
        "morning": "☀️ ¡Buenos días! ¿Hora de repasar verbos?",
        "day": "☕️ ¿Cómo va el día? ¡Vamos a practicar unos verbos!",
        "evening": "🌙 ¡Repaso nocturno! No olvides practicar antes de dormir.",
    },
    "fr": {
        "name": "🇫🇷 Français",
        "welcome": "Super ! Choisissez un verbe à pratiquer en utilisant les boutons ci-dessous :",
        "choose_btn": "Veuillez choisir un verbe en utilisant les boutons :",
        "correct": "Correct ! 🎉",
        "fire": "Excellent ! 🔥",
        "finish": "🎉 Bravo ! Les 3 étapes sont terminées ! Choisissez un nouveau verbe :",
        "retry": "Pas tout à fait. Réessayez pour «{v}» :",
        "q1": "Étape 1 : Comment dit-on «{v}» en hongrois ?",
        "q2": "Étape 2 : Comment dit-on « il/elle {f} » ?",
        "q3": "Étape 3 : Comment dit-on « {p} » ?",
        "forms": _fr_forms,
        "phrases": _fr_phr,
        "morning": "☀️ Bonjour ! Il est temps de réviser les verbes ?",
        "day": "☕️ Comment se passe ta journée ? Pratiquons quelques verbes !",
        "evening": "🌙 Révision du soir ! N'oublie pas de réviser avant de dormir.",
    },
    "de": {
        "name": "🇩🇪 Deutsch",
        "welcome": "Super! Wähle ein Verb zum Üben mit den Buttons unten:",
        "choose_btn": "Bitte wähle ein Verb über die Buttons:",
        "correct": "Richtig! 🎉",
        "fire": "Super! 🔥",
        "finish": "🎉 Geschafft! Alle 3 Schritte abgeschlossen! Wähle ein neues Verb:",
        "retry": "Nicht ganz. Versuche es noch einmal für «{v}»:",
        "q1": "Schritt 1: Wie sagt man «{v}» auf Ungarisch?",
        "q2": "Schritt 2: Wie sagt man „er/sie {f}“?",
        "q3": "Schritt 3: Wie sagt man „{p}“?",
        "forms": _de_forms,
        "phrases": _de_phr,
        "morning": "☀️ Guten Morgen! Zeit, Verben zu üben?",
        "day": "☕️ Wie läuft dein Tag? Lass uns ein paar Verben üben!",
        "evening": "🌙 Abendliche Wiederholung! Vergiss nicht, vor dem Schlafen zu üben.",
    },
    "it": {
        "name": "🇮🇹 Italiano",
        "welcome": "Ottimo! Scegli un verbo da praticare usando i pulsanti in basso:",
        "choose_btn": "Per favore, scegli un verbo usando i pulsanti:",
        "correct": "Corretto! 🎉",
        "fire": "Ottimo! 🔥",
        "finish": "🎉 Ottimo lavoro! 3 passaggi completati! Scegli un nuovo verbo:",
        "retry": "Non proprio. Riprova per «{v}»:",
        "q1": "Passo 1: Come si dice «{v}» in ungherese?",
        "q2": "Passo 2: Come si dice «lui/lei {f}»?",
        "q3": "Passo 3: Come si dice «{p}»?",
        "forms": _it_forms,
        "phrases": _it_phr,
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
        "q1": "Krok 1: Jak będzie «{v}» po węgiersku?",
        "q2": "Krok 2: Jak będzie „on/ona {f}”?",
        "q3": "Krok 3: Jak będzie „{p}”?",
        "forms": _pl_forms,
        "phrases": _pl_phr,
        "morning": "☀️ Dzień dobry! Czas powtórzyć czasowniki?",
        "day": "☕️ Jak mija dzień? Przećwiczmy kilka czasowników!",
        "evening": "🌙 Wieczorna powtórka! Nie zapomnij poćwiczyć przed snem.",
    },
    "uk": {
        "name": "🇺🇦 Українська",
        "welcome": "Чудово! Вибери дієслово для тренування за допомогою кнопок внизу:",
        "choose_btn": "Будь ласка, вибери дієслово за допомогою кнопок:",
        "correct": "Правильно! 🎉",
        "fire": "Чудово! 🔥",
        "finish": "🎉 Молодчина! Всі 3 кроки пройдено! Вибери нове дієслово:",
        "retry": "Не зовсім так. Спробуй ще раз для дієслова «{v}»:",
        "q1": "Крок 1: Як буде «{v}» угорською?",
        "q2": "Крок 2: Як буде «він / вона {f}»?",
        "q3": "Крок 3: Як буде «{p}»?",
        "forms": _uk_forms,
        "phrases": _uk_phr,
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
        "q1": "第一步：「{v}」用匈牙利语怎么说？",
        "q2": "第二步：“他/她{f}”用匈牙利语怎么说？",
        "q3": "第三步：“{p}”用匈牙利语怎么说？",
        "forms": _zh_forms,
        "phrases": _zh_phr,
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
        "q1": "Passo 1: Como se diz «{v}» em húngaro?",
        "q2": "Passo 2: Como se diz «ele/ela {f}»?",
        "q3": "Passo 3: Como se diz «{p}»?",
        "forms": _pt_forms,
        "phrases": _pt_phr,
        "morning": "☀️ Bom dia! Hora de praticar os verbos húngaros?",
        "day": "☕️ Como está sendo o seu dia? Vamos praticar alguns verbos!",
        "evening": "🌙 Revisão da noite! Não se esqueça de praticar antes de dormir.",
    },
}


# ---------------------------------------------------------------- helpers

def verb_name(lang, ru, en):
    """Как называть глагол в вопросе: по-русски для ru/uk, иначе по-английски."""
    return ru if lang in ("ru", "uk") else en


def norm(text):
    """Нормализация для сравнения: регистр, акценты, знаки препинания, пробелы."""
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    for ch in "?!.,":
        text = text.replace(ch, "")
    return " ".join(text.split())


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
        markup.add(KeyboardButton(text=f"{hu} ({verb_name(lang, ru, en)})"))
    return markup


def find_verb(text):
    """Ищем глагол по нажатой кнопке «hall (слышать)» или по точному слову."""
    t = text.lower().strip()
    head = t.split(" (")[0].strip()
    for verb in VERBS_DATABASE:
        hu, ru, en, inf = verb
        if head in (hu, inf) or t in (ru.lower(), en.lower()):
            return verb
    return None


def escape_markdown_v2(text):
    special_chars = "_*[]()~`>#+-=|{}.!"
    for char in special_chars:
        text = text.replace(char, f"\\{char}")
    return text


def send_reply(chat_id, text_main, spoiler_word=""):
    """Отправляет текст; подсказка (полный ответ) идёт под спойлером."""
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


def correct_answer(step, hu, inf):
    if step == 1:
        return inf
    if step == 2:
        return hu
    return STEP3_ANSWERS.get(hu, "mit csinálsz?")


# --------------------------------------------------------------- handlers

@bot.message_handler(commands=["start", "reset", "verbs"])
def cmd_start(message):
    user_id = message.from_user.id
    all_users.add(user_id)

    current_lang = active_trainings.get(user_id, {}).get("lang")

    if current_lang in LANGUAGES:
        active_trainings[user_id] = {"lang": current_lang, "step": 0}
        bot.send_message(
            message.chat.id,
            LANGUAGES[current_lang]["welcome"],
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
    if not message.text:
        return

    user_id = message.from_user.id
    all_users.add(user_id)
    text = message.text.strip()

    # --- выбор языка
    if (
        user_id not in active_trainings
        or active_trainings[user_id].get("lang") is None
    ):
        selected_lang = "ru"
        for code, info in LANGUAGES.items():
            if text == info["name"]:
                selected_lang = code
                break

        active_trainings[user_id] = {"lang": selected_lang, "step": 0}
        bot.send_message(
            message.chat.id,
            LANGUAGES[selected_lang]["welcome"],
            reply_markup=get_verbs_keyboard(selected_lang),
        )
        return

    data = active_trainings[user_id]
    lang = data["lang"]
    l_data = LANGUAGES.get(lang, LANGUAGES["ru"])

    # --- выбор глагола
    if "verb" not in data:
        found = find_verb(text)
        if not found:
            bot.send_message(
                message.chat.id,
                l_data["choose_btn"],
                reply_markup=get_verbs_keyboard(lang),
            )
            return

        data["verb"] = found
        data["step"] = 1
        hu, ru, en, inf = found
        q_text = l_data["q1"].format(v=verb_name(lang, ru, en))
        send_reply(message.chat.id, q_text, inf)
        return

    # --- проверка ответа
    step = data["step"]
    hu, ru, en, inf = data["verb"]
    expected = correct_answer(step, hu, inf)

    if norm(text) == norm(expected):
        step += 1
        data["step"] = step

        if step == 2:
            q2 = l_data["q2"].format(f=l_data["forms"][hu])
            send_reply(message.chat.id, f"{l_data['correct']}\n\n{q2}", hu)
        elif step == 3:
            q3 = l_data["q3"].format(p=l_data["phrases"][hu])
            full_answer = correct_answer(3, hu, inf)  # полная фраза, напр. «mit hallasz?»
            send_reply(message.chat.id, f"{l_data['fire']}\n\n{q3}", full_answer)
        else:
            data.pop("verb", None)
            data["step"] = 0
            bot.send_message(
                message.chat.id,
                l_data["finish"],
                reply_markup=get_verbs_keyboard(lang),
            )
    else:
        retry_text = l_data["retry"].format(v=verb_name(lang, ru, en))
        send_reply(message.chat.id, retry_text, expected)


# ---------------------------------------------------------- напоминания

def daily_reminders_loop():
    while True:
        now_hour = datetime.now(BUDAPEST_TZ).hour
        if now_hour in (9, 14, 20):
            time_key = (
                "morning" if now_hour == 9 else ("day" if now_hour == 14 else "evening")
            )
            for user_id in list(all_users):
                try:
                    state = active_trainings.get(user_id, {})
                    user_lang = state.get("lang") or "ru"
                    l_data = LANGUAGES.get(user_lang, LANGUAGES["ru"])
                    # сбрасываем незаконченную тренировку, чтобы кнопки работали
                    state.pop("verb", None)
                    state["step"] = 0
                    active_trainings[user_id] = state
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

print("Река запущена...")

while True:
    try:
        bot.infinity_polling(timeout=60, long_polling_timeout=60)
    except Exception as e:
        print(f"Ошибка: {e}")
        time.sleep(5)
