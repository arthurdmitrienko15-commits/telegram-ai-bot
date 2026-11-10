import asyncio
import copy
import functools
import hashlib
import json
import math
import os
import random
import re
import threading
import time
import unicodedata
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import telebot
try:
    from groq import Groq
except Exception:  # библиотека не установлена — бот всё равно работает
    Groq = None
try:
    import edge_tts
except Exception:  # без озвучки бот тоже работает, просто без кнопки 🔊
    edge_tts = None
from telebot.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
bot = telebot.TeleBot(TELEGRAM_TOKEN)

_orig_message_handler = bot.message_handler


def _tracked_message_handler(*a, **kw):
    """Все обработчики сообщений запоминают входящее сообщение, чтобы потом убрать его из чата."""
    deco = _orig_message_handler(*a, **kw)

    def outer(f):
        @functools.wraps(f)
        def g(message, *x, **y):
            try:
                tidy_track(message.chat.id, message.message_id, "user")
            except Exception:
                pass
            return f(message, *x, **y)
        deco(g)
        return f
    return outer


bot.message_handler = _tracked_message_handler

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
client = Groq(api_key=GROQ_API_KEY) if (Groq and GROQ_API_KEY) else None
# llama3-8b-8192 закрыт в Groq, поэтому пробуем актуальные модели по очереди
GROQ_MODELS = ["llama-3.1-8b-instant", "llama-3.3-70b-versatile"]

BUDAPEST_TZ = ZoneInfo("Europe/Budapest")

# Сколько последних выученных глаголов не показывать на кнопках
RECENT_LIMIT = 6

active_trainings = {}
DATA_DIR = os.getenv("DATA_DIR") or os.path.dirname(os.path.abspath(__file__))
try:
    os.makedirs(DATA_DIR, exist_ok=True)
except Exception as e:
    print(f"Не удалось создать папку данных {DATA_DIR}: {e}")
USERS_FILE = os.path.join(DATA_DIR, "users.json")


def save_users():
    """Запоминаем пользователей и язык в файл, чтобы рассылки переживали перезапуск."""
    try:
        data = {
            str(u): (active_trainings.get(u) or {}).get("lang") for u in all_users
        }
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"Не удалось сохранить users.json: {e}")


class UserSet(set):
    def add(self, x):
        is_new = x not in self
        super().add(x)
        if is_new:
            save_users()


all_users = UserSet()


def load_users():
    try:
        with open(USERS_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return
    for k, lang in data.items():
        uid = int(k)
        set.add(all_users, uid)
        if lang:
            active_trainings.setdefault(uid, {"lang": lang, "step": 0, "recent": []})


load_users()

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
    ("kér", "просить", "to ask for", "kérni"),
    ("tanul", "учить", "to learn", "tanulni"),
    ("dolgozik", "работать", "to work", "dolgozni"),
    ("lakik", "жить", "to live", "lakni"),
    ("beszél", "говорить", "to speak", "beszélni"),
    ("tud", "знать / уметь", "to know / can", "tudni"),
    ("akar", "хотеть", "to want", "akarni"),
    ("megy", "идти / ехать", "to go", "menni"),
    ("jön", "приходить", "to come", "jönni"),
    ("alszik", "спать", "to sleep", "aludni"),
    ("főz", "готовить", "to cook", "főzni"),
    ("szeret", "любить", "to love / like", "szeretni"),
    ("ad", "давать", "to give", "adni"),
    ("kap", "получать", "to get", "kapni"),
    ("fut", "бежать", "to run", "futni"),
    ("nyit", "открывать", "to open", "nyitni"),
    ("vár", "ждать", "to wait", "várni"),
    ("keres", "искать", "to look for", "keresni"),
    ("játszik", "играть", "to play", "játszani"),
    ("fizet", "платить", "to pay", "fizetni"),
    ("segít", "помогать", "to help", "segíteni"),
    ("tesz", "класть / ставить", "to put", "tenni"),
    ("gondolkodik", "думать", "to think", "gondolkodni"),
    ("gépel", "печатать", "to type", "gépelni"),
    ("rajzol", "рисовать", "to draw", "rajzolni"),
]

# Спряжение: глагол -> (én, te, mi, ők, прошедшее «ő»)
# Форма «ő» (он/она) = сам ключ.
CONJ = {
    "csinál": ("csinálok", "csinálsz", "csinálunk", "csinálnak", "csinált"),
    "olvas": ("olvasok", "olvasol", "olvasunk", "olvasnak", "olvasott"),
    "ír": ("írok", "írsz", "írunk", "írnak", "írt"),
    "eszik": ("eszem", "eszel", "eszünk", "esznek", "evett"),
    "iszik": ("iszom", "iszol", "iszunk", "isznak", "ivott"),
    "lát": ("látok", "látsz", "látunk", "látnak", "látott"),
    "hall": ("hallok", "hallasz", "hallunk", "hallanak", "hallott"),
    "vesz": ("veszek", "veszel", "veszünk", "vesznek", "vett"),
    "kér": ("kérek", "kérsz", "kérünk", "kérnek", "kért"),
    "tanul": ("tanulok", "tanulsz", "tanulunk", "tanulnak", "tanult"),
    "dolgozik": ("dolgozom", "dolgozol", "dolgozunk", "dolgoznak", "dolgozott"),
    "lakik": ("lakom", "laksz", "lakunk", "laknak", "lakott"),
    "beszél": ("beszélek", "beszélsz", "beszélünk", "beszélnek", "beszélt"),
    "tud": ("tudok", "tudsz", "tudunk", "tudnak", "tudott"),
    "akar": ("akarok", "akarsz", "akarunk", "akarnak", "akart"),
    "megy": ("megyek", "mész", "megyünk", "mennek", "ment"),
    "jön": ("jövök", "jössz", "jövünk", "jönnek", "jött"),
    "alszik": ("alszom", "alszol", "alszunk", "alszanak", "aludt"),
    "főz": ("főzök", "főzöl", "főzünk", "főznek", "főzött"),
    "szeret": ("szeretek", "szeretsz", "szeretünk", "szeretnek", "szeretett"),
    "ad": ("adok", "adsz", "adunk", "adnak", "adott"),
    "kap": ("kapok", "kapsz", "kapunk", "kapnak", "kapott"),
    "fut": ("futok", "futsz", "futunk", "futnak", "futott"),
    "nyit": ("nyitok", "nyitsz", "nyitunk", "nyitnak", "nyitott"),
    "vár": ("várok", "vársz", "várunk", "várnak", "várt"),
    "keres": ("keresek", "keresel", "keresünk", "keresnek", "keresett"),
    "játszik": ("játszom", "játszol", "játszunk", "játszanak", "játszott"),
    "fizet": ("fizetek", "fizetsz", "fizetünk", "fizetnek", "fizetett"),
    "segít": ("segítek", "segítesz", "segítünk", "segítenek", "segített"),
    "tesz": ("teszek", "teszel", "teszünk", "tesznek", "tett"),
    "gondolkodik": ("gondolkodom", "gondolkodsz", "gondolkodunk", "gondolkodnak", "gondolkodott"),
    "gépel": ("gépelek", "gépelsz", "gépelünk", "gépelnek", "gépelt"),
    "rajzol": ("rajzolok", "rajzolsz", "rajzolunk", "rajzolnak", "rajzolt"),
}

# Будущее время: fog + инфинитив
FOG = {"ő": "fog", "én": "fogok", "te": "fogsz", "ők": "fognak"}

# Прошедшее время для «ты» (te): вопрос «Ты работал?» -> dolgoztál?
PAST_TE = {
    "csinál": "csináltál", "olvas": "olvastál", "ír": "írtál", "eszik": "ettél",
    "iszik": "ittál", "lát": "láttál", "hall": "hallottál", "vesz": "vettél",
    "kér": "kértél", "tanul": "tanultál", "dolgozik": "dolgoztál",
    "lakik": "laktál", "beszél": "beszéltél", "tud": "tudtál",
    "akar": "akartál", "megy": "mentél", "jön": "jöttél", "alszik": "aludtál",
    "főz": "főztél", "szeret": "szerettél", "ad": "adtál", "kap": "kaptál",
    "fut": "futottál", "nyit": "nyitottál", "vár": "vártál",
    "keres": "kerestél", "játszik": "játszottál", "fizet": "fizettél",
    "segít": "segítettél", "tesz": "tettél",
    "gondolkodik": "gondolkodtál", "gépel": "gépeltél", "rajzol": "rajzoltál",
}

# Шаги, которые подаются как вопрос (со знаком «?» в подсказке)
QUESTION_KEYS = {"te", "past_te", "f_te"}

# Допустимые разговорные варианты формы «te»
ALT_TE = {"lakik": ["lakol"], "gondolkodik": ["gondolkodol"]}

# Определённое спряжение (én, te) — для вопроса «Какой ты ищешь?» -> melyiket keresed?
DEF_CONJ = {
    "csinál": ("csinálom", "csinálod"),
    "olvas": ("olvasom", "olvasod"),
    "ír": ("írom", "írod"),
    "eszik": ("eszem", "eszed"),
    "iszik": ("iszom", "iszod"),
    "lát": ("látom", "látod"),
    "hall": ("hallom", "hallod"),
    "vesz": ("veszem", "veszed"),
    "kér": ("kérem", "kéred"),
    "tanul": ("tanulom", "tanulod"),
    "tud": ("tudom", "tudod"),
    "akar": ("akarom", "akarod"),
    "főz": ("főzöm", "főzöd"),
    "szeret": ("szeretem", "szereted"),
    "ad": ("adom", "adod"),
    "kap": ("kapom", "kapod"),
    "nyit": ("nyitom", "nyitod"),
    "keres": ("keresem", "keresed"),
    "fizet": ("fizetem", "fizeted"),
    "tesz": ("teszem", "teszed"),
    "rajzol": ("rajzolom", "rajzolod"),
}

# Вопросительные слова, которые осмысленно сочетаются с глаголом:
#   mit = что, hol = где, kit = кого, melyik = какой, hova = куда
WH = {
    "csinál": ["mit", "melyik"],
    "olvas": ["mit", "hol", "melyik"],
    "ír": ["mit", "hol", "melyik"],
    "eszik": ["mit", "hol", "melyik"],
    "iszik": ["mit", "hol", "melyik"],
    "lát": ["mit", "kit", "melyik"],
    "hall": ["mit", "kit", "melyik"],
    "vesz": ["mit", "hol", "melyik"],
    "kér": ["mit", "melyik"],
    "tanul": ["mit", "hol", "melyik"],
    "dolgozik": ["hol"],
    "lakik": ["hol"],
    "beszél": ["hol"],
    "tud": ["mit", "melyik"],
    "akar": ["mit", "kit", "melyik"],
    "megy": ["hova"],
    "jön": ["hova"],
    "alszik": ["hol"],
    "főz": ["mit", "hol", "melyik"],
    "szeret": ["mit", "kit", "melyik"],
    "ad": ["mit", "melyik"],
    "kap": ["mit", "melyik"],
    "fut": ["hol", "hova"],
    "nyit": ["mit", "melyik"],
    "vár": ["mit", "kit", "hol"],
    "keres": ["mit", "hol", "kit", "melyik"],
    "játszik": ["mit", "hol"],
    "fizet": ["mit", "hol", "melyik"],
    "segít": ["hol"],
    "tesz": ["mit", "melyik"],
    "gondolkodik": ["hol"],
    "gépel": ["mit", "hol"],
    "rajzol": ["mit", "hol", "melyik"],
}

# Венгерское слово в ответе («melyik» требует винительного: melyiket)
WH_HU = {"mit": "mit", "hol": "hol", "kit": "kit", "melyik": "melyiket", "hova": "hova"}

# Вопросительные слова на языках интерфейса (для языков без естественных фраз)
WH_LABELS = {
    "ru": {"mit": "что", "hol": "где", "kit": "кого", "melyik": "какой", "hova": "куда"},
    "en": {"mit": "what", "hol": "where", "kit": "who", "melyik": "which one", "hova": "where to"},
    "es": {"mit": "qué", "hol": "dónde", "kit": "a quién", "melyik": "cuál", "hova": "adónde"},
    "fr": {"mit": "quoi", "hol": "où", "kit": "qui", "melyik": "lequel", "hova": "vers où"},
    "de": {"mit": "was", "hol": "wo", "kit": "wen", "melyik": "welchen", "hova": "wohin"},
    "it": {"mit": "cosa", "hol": "dove", "kit": "chi", "melyik": "quale", "hova": "verso dove"},
    "pl": {"mit": "co", "hol": "gdzie", "kit": "kogo", "melyik": "który", "hova": "dokąd"},
    "uk": {"mit": "що", "hol": "де", "kit": "кого", "melyik": "який", "hova": "куди"},
    "zh": {"mit": "什么", "hol": "哪里", "kit": "谁", "melyik": "哪个", "hova": "去哪里"},
    "pt": {"mit": "o que", "hol": "onde", "kit": "quem", "melyik": "qual", "hova": "para onde"},
}


def is_question(key):
    return key in QUESTION_KEYS or key.startswith("wh_")

# Русские формы для естественных фраз: я, ты, мы, они (настоящее время)
RU_PRES = {
    "csinál": ("делаю", "делаешь", "делаем", "делают"),
    "olvas": ("читаю", "читаешь", "читаем", "читают"),
    "ír": ("пишу", "пишешь", "пишем", "пишут"),
    "eszik": ("ем", "ешь", "едим", "едят"),
    "iszik": ("пью", "пьёшь", "пьём", "пьют"),
    "lát": ("вижу", "видишь", "видим", "видят"),
    "hall": ("слышу", "слышишь", "слышим", "слышат"),
    "vesz": ("покупаю", "покупаешь", "покупаем", "покупают"),
    "kér": ("прошу", "просишь", "просим", "просят"),
    "tanul": ("учу", "учишь", "учим", "учат"),
    "dolgozik": ("работаю", "работаешь", "работаем", "работают"),
    "lakik": ("живу", "живёшь", "живём", "живут"),
    "beszél": ("говорю", "говоришь", "говорим", "говорят"),
    "tud": ("знаю", "знаешь", "знаем", "знают"),
    "akar": ("хочу", "хочешь", "хотим", "хотят"),
    "megy": ("иду", "идёшь", "идём", "идут"),
    "jön": ("прихожу", "приходишь", "приходим", "приходят"),
    "alszik": ("сплю", "спишь", "спим", "спят"),
    "főz": ("готовлю", "готовишь", "готовим", "готовят"),
    "szeret": ("люблю", "любишь", "любим", "любят"),
    "ad": ("даю", "даёшь", "даём", "дают"),
    "kap": ("получаю", "получаешь", "получаем", "получают"),
    "fut": ("бегу", "бежишь", "бежим", "бегут"),
    "nyit": ("открываю", "открываешь", "открываем", "открывают"),
    "vár": ("жду", "ждёшь", "ждём", "ждут"),
    "keres": ("ищу", "ищешь", "ищем", "ищут"),
    "játszik": ("играю", "играешь", "играем", "играют"),
    "fizet": ("плачу", "платишь", "платим", "платят"),
    "segít": ("помогаю", "помогаешь", "помогаем", "помогают"),
    "tesz": ("кладу", "кладёшь", "кладём", "кладут"),
    "gondolkodik": ("думаю", "думаешь", "думаем", "думают"),
    "gépel": ("печатаю", "печатаешь", "печатаем", "печатают"),
    "rajzol": ("рисую", "рисуешь", "рисуем", "рисуют"),
}

# Русское прошедшее время (род не важен — пишем «(а)»)
RU_PAST = {
    "csinál": "делал(а)", "olvas": "читал(а)", "ír": "писал(а)",
    "eszik": "ел(а)", "iszik": "пил(а)", "lát": "видел(а)",
    "hall": "слышал(а)", "vesz": "покупал(а)", "kér": "просил(а)",
    "tanul": "учил(а)", "dolgozik": "работал(а)", "lakik": "жил(а)",
    "beszél": "говорил(а)", "tud": "знал(а)", "akar": "хотел(а)",
    "megy": "шёл(шла)", "jön": "приходил(а)", "alszik": "спал(а)",
    "főz": "готовил(а)", "szeret": "любил(а)", "ad": "давал(а)",
    "kap": "получал(а)", "fut": "бежал(а)", "nyit": "открывал(а)",
    "vár": "ждал(а)", "keres": "искал(а)", "játszik": "играл(а)",
    "fizet": "платил(а)", "segít": "помогал(а)", "tesz": "клал(а)",
    "gondolkodik": "думал(а)", "gépel": "печатал(а)", "rajzol": "рисовал(а)",
}

# Английское прошедшее время (he/she ...)
EN_PAST = {
    "csinál": "did", "olvas": "read", "ír": "wrote", "eszik": "ate",
    "iszik": "drank", "lát": "saw", "hall": "heard", "vesz": "bought",
    "kér": "asked for", "tanul": "learned", "dolgozik": "worked",
    "lakik": "lived", "beszél": "spoke", "tud": "knew", "akar": "wanted",
    "megy": "went", "jön": "came", "alszik": "slept", "főz": "cooked",
    "szeret": "loved", "ad": "gave", "kap": "got", "fut": "ran",
    "nyit": "opened", "vár": "waited", "keres": "looked for",
    "játszik": "played", "fizet": "paid", "segít": "helped", "tesz": "put",
    "gondolkodik": "thought", "gépel": "typed", "rajzol": "drew",
}

_RU_PRON = {"én": "я", "te": "ты", "mi": "мы", "ők": "они"}
_RU_BUDU = {
    "én": "я буду", "te": "ты будешь", "ő": "он / она будет",
    "mi": "мы будем", "ők": "они будут",
}
_PRES_IDX = {"én": 0, "te": 1, "mi": 2, "ők": 3}
_EN_PRON = {"én": "I", "te": "you", "mi": "we", "ők": "they"}


def _cap(s):
    return s[:1].upper() + s[1:]


def ru_natural(key, hu, ru, en, l_data):
    """Естественная русская фраза: «Я буду работать», «Ты работал(а)?» ..."""
    if key.startswith("wh_"):  # «Что ты ищешь?», «Где я работаю?» ...
        _, w, p = key.split("_")
        pron = "ты" if p == "te" else "я"
        verb = RU_PRES[hu][1 if p == "te" else 0]
        s = f"{WH_LABELS['ru'][w]} {pron} {verb}"
    elif key == "ő":
        s = f"он / она {l_data['forms'][hu]}"
    elif key in _PRES_IDX:
        s = f"{_RU_PRON[key]} {RU_PRES[hu][_PRES_IDX[key]]}"
    elif key == "past":
        s = f"он / она {RU_PAST[hu]}"
    elif key == "past_te":
        s = f"ты {RU_PAST[hu]}"
    else:  # f_ő, f_én, f_te, f_ők
        s = f"{_RU_BUDU[key[2:]]} {ru}"
    if is_question(key):
        s += "?"
    return _cap(s)


def en_natural(key, hu, ru, en, l_data):
    """Естественная английская фраза: «I will work», «Did you work?» ..."""
    bare = en[3:] if en.startswith("to ") else en
    if key.startswith("wh_"):  # «What do you look for?», «Where do I work?» ...
        _, w, p = key.split("_")
        pron = "you" if p == "te" else "I"
        if w == "hova":
            s = f"where do {pron} {bare} to"
        else:
            s = f"{WH_LABELS['en'][w]} do {pron} {bare}"
    elif key == "ő":
        s = f"he / she {l_data['forms'][hu]}"
    elif key == "te":
        s = f"do you {bare}"
    elif key in _EN_PRON:
        s = f"{_EN_PRON[key]} {bare}"
    elif key == "past":
        s = f"he / she {EN_PAST[hu]}"
    elif key == "past_te":
        s = f"did you {bare}"
    else:  # f_ő, f_én, f_te, f_ők
        who = key[2:]
        if who == "te":
            s = f"will you {bare}"
        elif who == "ő":
            s = f"he / she will {bare}"
        else:
            s = f"{_EN_PRON[who]} will {bare}"
    if is_question(key):
        s += "?"
    return _cap(s)


# Языки, где вопросы пишутся естественной фразой
NATURAL = {"ru": ru_natural, "en": en_natural}


def hint_for(key, hu, inf):
    """Подсказка под спойлером; у вопросов («ты ...?») добавляем «?»."""
    a = answers_for(key, hu, inf)[0]
    if is_question(key) and not a.endswith("?"):
        a += "?"
    return a

# Вопрос «Что ты ...?» — только для глаголов, у которых есть объект
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

ORDER = ["csinál", "olvas", "ír", "eszik", "iszik", "lát", "hall", "vesz"]


def L(forms, phrases):
    return dict(zip(ORDER, forms)), dict(zip(ORDER, phrases))


_ru_forms, _ru_phr = L(
    ["делает", "читает", "пишет", "ест", "пьёт", "видит", "слышит", "покупает"],
    ["Что ты делаешь?", "Что ты читаешь?", "Что ты пишешь?", "Что ты ешь?",
     "Что ты пьёшь?", "Что ты видишь?", "Что ты слышишь?", "Что ты покупаешь?"],
)
_ru_forms.update({
    "kér": "просит", "tanul": "учит", "dolgozik": "работает", "lakik": "живёт",
    "beszél": "говорит", "tud": "знает / умеет", "akar": "хочет",
    "megy": "идёт / едет", "jön": "приходит", "alszik": "спит",
    "főz": "готовит", "szeret": "любит", "ad": "даёт", "kap": "получает",
    "fut": "бежит", "nyit": "открывает", "vár": "ждёт", "keres": "ищет",
    "játszik": "играет", "fizet": "платит", "segít": "помогает",
    "tesz": "кладёт / ставит",
    "gondolkodik": "думает", "gépel": "печатает", "rajzol": "рисует",
})
_uk_forms, _uk_phr = L(
    ["робить", "читає", "пише", "їсть", "п'є", "бачить", "чує", "купує"],
    ["Що ти робиш?", "Що ти читаєш?", "Що ти пишеш?", "Що ти їси?",
     "Що ти п'єш?", "Що ти бачиш?", "Що ти чуєш?", "Що ти купуєш?"],
)
_uk_forms.update({
    "kér": "просить", "tanul": "вчить", "dolgozik": "працює", "lakik": "живе",
    "beszél": "говорить", "tud": "знає / вміє", "akar": "хоче",
    "megy": "йде / їде", "jön": "приходить", "alszik": "спить",
    "főz": "готує", "szeret": "любить", "ad": "дає", "kap": "отримує",
    "fut": "біжить", "nyit": "відкриває", "vár": "чекає", "keres": "шукає",
    "játszik": "грає", "fizet": "платить", "segít": "допомагає",
    "tesz": "кладе / ставить",
    "gondolkodik": "думає", "gépel": "друкує", "rajzol": "малює",
})
_en_forms, _en_phr = L(
    ["does", "reads", "writes", "eats", "drinks", "sees", "hears", "buys"],
    ["What are you doing?", "What are you reading?", "What are you writing?",
     "What are you eating?", "What are you drinking?", "What do you see?",
     "What do you hear?", "What are you buying?"],
)
_en_forms.update({
    "kér": "asks for", "tanul": "learns", "dolgozik": "works", "lakik": "lives",
    "beszél": "speaks", "tud": "knows", "akar": "wants", "megy": "goes",
    "jön": "comes", "alszik": "sleeps", "főz": "cooks", "szeret": "loves",
    "ad": "gives", "kap": "gets", "fut": "runs", "nyit": "opens",
    "vár": "waits", "keres": "looks for", "játszik": "plays", "fizet": "pays",
    "segít": "helps", "tesz": "puts",
    "gondolkodik": "thinks", "gépel": "types", "rajzol": "draws",
})
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

# pron: я, ты, он/она, мы, они — для вопросов вида «я + глагол»
LANGUAGES = {
    "ru": {
        "name": "🇷🇺 Русский",
        "welcome": "Отлично! Выбери глагол для тренировки с помощью кнопок внизу:",
        "choose_btn": "Пожалуйста, выбери глагол с помощью кнопок:",
        "correct": "Правильно! 🎉",
        "fire": "Отлично! 🔥",
        "finish": "🎉 Молодчина! Глагол пройден полностью! Выбери новый:",
        "retry": "Не совсем так. Попробуй ещё раз для глагола «{v}»:",
        "step": "Шаг {n}/{t}: ",
        "q1": "Как будет «{v}» по-венгерски?",
        "q2": "Как будет «он / она {f}»?",
        "q3": "Как будет «{p}»?",
        "qg": "Как будет: {who} + «{v}»?",
        "qn": "Как будет «{s}»?",
        "pron": {"én": "я", "te": "ты", "ő": "он / она", "mi": "мы", "ők": "они"},
        "past": "прошедшее",
        "future": "будущее",
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
        "finish": "🎉 Awesome! Verb completed! Choose a new one:",
        "retry": "Not quite. Try again for «{v}»:",
        "step": "Step {n}/{t}: ",
        "q1": "How do you say «{v}» in Hungarian?",
        "q2": "How do you say 'he/she {f}'?",
        "q3": "How do you say «{p}»?",
        "qg": "How do you say: {who} + «{v}»?",
        "qn": "How do you say «{s}»?",
        "pron": {"én": "I", "te": "you", "ő": "he / she", "mi": "we", "ők": "they"},
        "past": "past",
        "future": "future",
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
        "finish": "🎉 ¡Increíble! ¡Verbo completado! Elige uno nuevo:",
        "retry": "No exactamente. Inténtalo de nuevo para «{v}»:",
        "step": "Paso {n}/{t}: ",
        "q1": "¿Cómo se dice «{v}» en húngaro?",
        "q2": "¿Cómo se dice «él/ella {f}»?",
        "q3": "¿Cómo se dice «{p}»?",
        "qg": "¿Cómo se dice: {who} + «{v}»?",
        "pron": {"én": "yo", "te": "tú", "ő": "él / ella", "mi": "nosotros", "ők": "ellos"},
        "past": "pasado",
        "future": "futuro",
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
        "finish": "🎉 Bravo ! Verbe terminé ! Choisissez-en un nouveau :",
        "retry": "Pas tout à fait. Réessayez pour «{v}» :",
        "step": "Étape {n}/{t} : ",
        "q1": "Comment dit-on «{v}» en hongrois ?",
        "q2": "Comment dit-on « il/elle {f} » ?",
        "q3": "Comment dit-on « {p} » ?",
        "qg": "Comment dit-on : {who} + «{v}» ?",
        "pron": {"én": "je", "te": "tu", "ő": "il / elle", "mi": "nous", "ők": "ils"},
        "past": "passé",
        "future": "futur",
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
        "finish": "🎉 Geschafft! Verb abgeschlossen! Wähle ein neues:",
        "retry": "Nicht ganz. Versuche es noch einmal für «{v}»:",
        "step": "Schritt {n}/{t}: ",
        "q1": "Wie sagt man «{v}» auf Ungarisch?",
        "q2": "Wie sagt man „er/sie {f}“?",
        "q3": "Wie sagt man „{p}“?",
        "qg": "Wie sagt man: {who} + «{v}»?",
        "pron": {"én": "ich", "te": "du", "ő": "er / sie", "mi": "wir", "ők": "sie (Plural)"},
        "past": "Vergangenheit",
        "future": "Zukunft",
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
        "finish": "🎉 Ottimo lavoro! Verbo completato! Scegline uno nuovo:",
        "retry": "Non proprio. Riprova per «{v}»:",
        "step": "Passo {n}/{t}: ",
        "q1": "Come si dice «{v}» in ungherese?",
        "q2": "Come si dice «lui/lei {f}»?",
        "q3": "Come si dice «{p}»?",
        "qg": "Come si dice: {who} + «{v}»?",
        "pron": {"én": "io", "te": "tu", "ő": "lui / lei", "mi": "noi", "ők": "loro"},
        "past": "passato",
        "future": "futuro",
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
        "finish": "🎉 Super! Czasownik zaliczony! Wybierz nowy:",
        "retry": "Nie do końca. Spróbuj ponownie dla «{v}»:",
        "step": "Krok {n}/{t}: ",
        "q1": "Jak będzie «{v}» po węgiersku?",
        "q2": "Jak będzie „on/ona {f}”?",
        "q3": "Jak będzie „{p}”?",
        "qg": "Jak będzie: {who} + «{v}»?",
        "pron": {"én": "ja", "te": "ty", "ő": "on / ona", "mi": "my", "ők": "oni"},
        "past": "przeszłość",
        "future": "przyszłość",
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
        "finish": "🎉 Молодчина! Дієслово пройдено повністю! Вибери нове:",
        "retry": "Не зовсім так. Спробуй ще раз для дієслова «{v}»:",
        "step": "Крок {n}/{t}: ",
        "q1": "Як буде «{v}» угорською?",
        "q2": "Як буде «він / вона {f}»?",
        "q3": "Як буде «{p}»?",
        "qg": "Як буде: {who} + «{v}»?",
        "pron": {"én": "я", "te": "ти", "ő": "він / вона", "mi": "ми", "ők": "вони"},
        "past": "минуле",
        "future": "майбутнє",
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
        "finish": "🎉 太棒了！这个动词已全部完成！请选择新动词：",
        "retry": "不太对。请再试一次「{v}」：",
        "step": "第{n}/{t}步：",
        "q1": "「{v}」用匈牙利语怎么说？",
        "q2": "“他/她{f}”用匈牙利语怎么说？",
        "q3": "“{p}”用匈牙利语怎么说？",
        "qg": "用匈牙利语怎么说：{who} + 「{v}」？",
        "pron": {"én": "我", "te": "你", "ő": "他 / 她", "mi": "我们", "ők": "他们"},
        "past": "过去",
        "future": "将来",
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
        "finish": "🎉 Parabéns! Verbo concluído! Escolha um novo:",
        "retry": "Não exatamente. Tente novamente para «{v}»:",
        "step": "Passo {n}/{t}: ",
        "q1": "Como se diz «{v}» em húngaro?",
        "q2": "Como se diz «ele/ela {f}»?",
        "q3": "Como se diz «{p}»?",
        "qg": "Como se diz: {who} + «{v}»?",
        "pron": {"én": "eu", "te": "você", "ő": "ele / ela", "mi": "nós", "ők": "eles"},
        "past": "passado",
        "future": "futuro",
        "forms": _pt_forms,
        "phrases": _pt_phr,
        "morning": "☀️ Bom dia! Hora de praticar os verbos húngaros?",
        "day": "☕️ Como está sendo o seu dia? Vamos praticar alguns verbos!",
        "evening": "🌙 Revisão da noite! Não se esqueça de praticar antes de dormir.",
    },
}


# ---------------------------------------------------------------- helpers

# --- Каомодзи вместо обычных эмодзи (случайный из набора каждый раз) ---
KAO_HAPPY = [  # «Правильно!»
    "ʕ•ᴥ•ʔ", "(≧◡≦)", "(๑>ᴗ<๑)", "(o˘◡˘o)", "(｡•ㅅ•｡)♡",
    "( ´ ω ` )♡", "(づᴗ_ᴗ)づ♡", "(=^･ω･^=)", "ʕっ•ᴥ•ʔっ", "ฅ^•ﻌ•^ฅ",
]
KAO_GREAT = [  # «Отлично!»
    "ʕ≧ᴥ≦ʔ", "(>ᴗ<)", "(=`ω´=)", "(≧◡≦)♡", "ʕっ•ᴥ•ʔっ", "(๑>ᴗ<๑)",
]
KAO_DONE = [  # глагол пройден полностью
    "ʕっ•ᴥ•ʔっ♡", "(づᴗ_ᴗ)づ♡", "(๑>ᴗ<๑)♡", "ʕ≧ᴥ≦ʔ♡",
]
KAO_SAD = [  # неправильный ответ
    "ʕ´•ᴥ•`ʔ", "(´･ω･`)", "(´• ω •`)",
]
KAO_TIME = {  # напоминания
    "morning": ["(≧◡≦)♡", "ʕ•ᴥ•ʔ", "(o˘◡˘o)"],
    "day": ["(=^･ω･^=)", "ฅ^•ﻌ•^ฅ", "(｡•ㅅ•｡)♡"],
    "evening": ["(˘ω˘)zzZ", "ʕ-ᴥ-ʔ♡", "( ´ ω ` )♡"],
}
K_LANG = "(=^･ω･^=)"
CARDS_BTN = "Cards (=^･ω･^=)"  # кнопка запуска игры с картинками

# Убираем обычные эмодзи из текстов (флаги в названиях языков не трогаем)
_EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF☀-➿️‍]+")


def _strip_emoji(s):
    return _EMOJI_RE.sub("", s).strip()


for _l in LANGUAGES.values():
    for _k in ("correct", "fire", "finish", "morning", "day", "evening"):
        _l[_k] = _strip_emoji(_l[_k])


def verb_name(lang, ru, en):
    """Как называть глагол в вопросе: по-русски для ru/uk, иначе по-английски."""
    return ru if lang in ("ru", "uk") else en


def norm(text):
    """Нормализация: регистр, акценты, знаки препинания, пробелы."""
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    for ch in "?!.,":
        text = text.replace(ch, "")
    return " ".join(text.split())


# Местоимения (после norm: én→en, ő→o, ők→ok) — их можно писать перед ответом
_PRON_NORM = {"en", "te", "o", "mi", "ti", "ok"}


def strip_pronoun(text):
    parts = text.split(" ", 1)
    if len(parts) == 2 and parts[0] in _PRON_NORM and parts[1]:
        return parts[1]
    return text


def build_steps(hu, l_data):
    steps = ["inf", "ő", "én", "te", "mi", "ők"]
    # вопросы с вопросительным словом: «Что ты ищешь?», «Где я ищу?» ...
    for w in WH.get(hu, []):
        steps += [f"wh_{w}_te", f"wh_{w}_én"]
    steps += [
        "past", "past_te",
        "f_ő", "f_én", "f_te", "f_ők",
    ]
    return steps


def answers_for(key, hu, inf):
    """Список допустимых ответов; первый — тот, что показываем в подсказке."""
    én, te, mi, ők, past = CONJ[hu]
    if key == "inf":
        return [inf]
    if key == "ő":
        return [hu]
    if key.startswith("wh_"):
        _, w, p = key.split("_")
        if w == "melyik":
            form = DEF_CONJ[hu][0 if p == "én" else 1]
            forms = [form]
        elif p == "én":
            forms = [én]
        else:
            forms = [te] + ALT_TE.get(hu, [])
        return [f"{WH_HU[w]} {f}?" for f in forms]
    if key == "én":
        return [én]
    if key == "te":
        return [te] + ALT_TE.get(hu, [])
    if key == "mi":
        return [mi]
    if key == "ők":
        return [ők]
    if key == "past":
        return [past]
    if key == "past_te":
        return [PAST_TE[hu]]
    if key.startswith("f_"):
        fog = FOG[key[2:]]
        return [f"{fog} {inf}", f"{inf} {fog}"]
    return [hu]


def make_question(l_data, lang, steps, step, verb):
    hu, ru, en, inf = verb
    key = steps[step - 1]
    prefix = l_data["step"].format(n=step, t=len(steps))
    v = verb_name(lang, ru, en)
    pron = l_data["pron"]

    if key == "inf":
        body = l_data["q1"].format(v=v)
    elif key == "wh_mit_te" and lang not in NATURAL and hu in l_data["phrases"]:
        body = l_data["q3"].format(p=l_data["phrases"][hu])
    elif lang in NATURAL:
        body = l_data["qn"].format(s=NATURAL[lang](key, hu, ru, en, l_data))
    elif key == "ő" and hu in l_data["forms"]:
        body = l_data["q2"].format(f=l_data["forms"][hu])
    else:
        if key == "past":
            who = f"{pron['ő']} ({l_data['past']})"
        elif key == "past_te":
            who = f"{pron['te']} ({l_data['past']})"
        elif key.startswith("wh_"):
            _, w, p = key.split("_")
            who = f"{WH_LABELS[lang][w]} + {pron[p]}"
        elif key.startswith("f_"):
            who = f"{pron[key[2:]]} ({l_data['future']})"
        else:
            who = pron[key]
        body = l_data["qg"].format(who=who, v=v)
    # если фраза в кавычках уже заканчивается на «?», не дублируем знак после неё
    for dup, fixed in (("?»?", "?»"), ("?“?", "?“"), ("?”?", "?”"), ("? » ?", "? »")):
        body = body.replace(dup, fixed)
    return prefix + body


def get_language_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    keys = list(LANGUAGES.keys())
    for i in range(0, len(keys), 2):
        row = [KeyboardButton(text=LANGUAGES[keys[i]]["name"])]
        if i + 1 < len(keys):
            row.append(KeyboardButton(text=LANGUAGES[keys[i + 1]]["name"]))
        markup.add(*row)
    return markup


def get_verbs_keyboard(lang="ru", exclude=()):
    """3 случайных глагола для прописей, кроме недавно выученных."""
    pool = [v for v in VERBS_DATABASE if v[0] not in exclude]
    if len(pool) < 3:
        pool = VERBS_DATABASE
    selected = random.sample(pool, 3)
    markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    for hu, ru, en, inf in selected:
        markup.add(KeyboardButton(text=f"{hu} ({verb_name(lang, ru, en)})"))
    markup.add(KeyboardButton(text=exit_label(lang)))
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
    text = text.replace("\\", "\\\\")  # сначала сам обратный слеш
    special_chars = "_*[]()~`>#+-=|{}.!"
    for char in special_chars:
        text = text.replace(char, f"\\{char}")
    return text


def send_reply(chat_id, text_main, spoiler_word="", reply_markup=None):
    """Отправляет текст; подсказка (полный ответ) идёт под спойлером."""
    msg = escape_markdown_v2(text_main)
    if spoiler_word:
        msg += f"\n\n||{escape_markdown_v2(spoiler_word)}||"
    try:
        bot.send_message(chat_id=chat_id, text=msg, parse_mode="MarkdownV2", reply_markup=reply_markup)
    except Exception as e:
        print(f"Ошибка MarkdownV2: {e}")
        fallback = text_main
        if spoiler_word:
            fallback += f"\n\n({spoiler_word})"
        bot.send_message(chat_id=chat_id, text=fallback, reply_markup=reply_markup)


def new_state(user_id, lang):
    recent = active_trainings.get(user_id, {}).get("recent", [])
    active_trainings[user_id] = {"lang": lang, "step": 0, "recent": recent}
    save_users()
    return active_trainings[user_id]


# --------------------------------------------------------------- handlers

# ------------------------------------------------------------ карточки

# ------------------------------------------------ маленькие разговоры Réka
# Короткие тёплые фразы между тренировкой и карточками. Зависят от времени
# суток в Будапеште. Для языков без своего списка берём английский.
CHAT_LINES = {
    "ru": {
        "night": [
            "Уже поздно, а ты всё учишь. Горжусь тобой. Спокойной ночи и сладких снов!",
            "Спокойной ночи! Венгерский подождёт до утра, а во сне слова тоже отлично укладываются.",
            "Ночь на дворе. Ещё чуть-чуть и спать, хорошо? Я рядом, когда проснёшься.",
        ],
        "morning": [
            "Доброе утро! Рада тебя видеть. Пара глаголов к кофе?",
            "С добрым утром! Сегодня у нас всё получится.",
        ],
        "day": [
            "Привет! Как день? Давай немного позанимаемся, я никуда не спешу.",
            "Ты молодец, что заглянул. Продолжим?",
        ],
        "evening": [
            "Добрый вечер! Ты хорошо поработал. Ещё немного, и можно отдыхать.",
            "Вечер, самое время для спокойного повторения. Я с тобой.",
        ],
    },
    "en": {
        "night": [
            "It's late and you're still learning. I'm proud of you. Good night and sweet dreams!",
            "Good night! Hungarian can wait until morning, and words settle in nicely while you sleep.",
            "It's night already. Just a little more and then sleep, okay? I'll be here when you wake up.",
        ],
        "morning": [
            "Good morning! So nice to see you. A few verbs with your coffee?",
            "Good morning! Today is going to go well.",
        ],
        "day": [
            "Hi! How is your day? Let's practice a little, I'm in no rush.",
            "I'm glad you came by. Shall we continue?",
        ],
        "evening": [
            "Good evening! You've done well today. A little more and then rest.",
            "Evening is a calm time to review. I'm with you.",
        ],
    },
    "uk": {
        "night": [
            "Вже пізно, а ти все вчиш. Пишаюся тобою. На добраніч і солодких снів!",
            "На добраніч! Угорська зачекає до ранку, а уві сні слова теж добре вкладаються.",
        ],
        "morning": ["Доброго ранку! Радію тебе бачити. Кілька дієслів до кави?"],
        "day": ["Привіт! Як день? Давай трохи позаймаємося, я нікуди не поспішаю."],
        "evening": ["Добрий вечір! Ти добре попрацював. Ще трохи, і можна відпочивати."],
    },
}


def chat_period():
    h = datetime.now(BUDAPEST_TZ).hour
    if h >= 22 or h < 5:
        return "night"
    if h < 11:
        return "morning"
    if h < 18:
        return "day"
    return "evening"


# Réka говорит по-венгерски. Перевод прячется под спойлер.
CHAT_HU = {
    "night": [
        "Már késő van, és te még tanulsz. Büszke vagyok rád! Jó éjszakát, szép álmokat!",
        "Jó éjszakát! A magyar megvár reggelig, a szavak alvás közben is a helyükre kerülnek.",
        "Már éjszaka van. Még egy kicsit, aztán aludj, jó? Itt leszek, amikor felébredsz.",
    ],
    "morning": [
        "Jó reggelt! Örülök, hogy látlak. Néhány ige a kávé mellé?",
        "Jó reggelt! Ma minden sikerülni fog.",
    ],
    "day": [
        "Szia! Hogy telik a napod? Gyakoroljunk egy kicsit, nem sietek sehová.",
        "Örülök, hogy benéztél. Folytatjuk?",
    ],
    "evening": [
        "Jó estét! Ma jól dolgoztál. Még egy kicsit, aztán pihenj.",
        "Az este nyugodt idő az ismétlésre. Veled vagyok.",
    ],
}


def reka_chat(lang):
    """Возвращает (текст, parse_mode): венгерская фраза + перевод в спойлере."""
    period = chat_period()
    i = random.randrange(len(CHAT_HU[period]))
    hu = CHAT_HU[period][i]
    tr_list = (CHAT_LINES.get(lang) or CHAT_LINES["en"])[period]
    if i >= len(tr_list):
        tr_list = CHAT_LINES["en"][period]
    tr = tr_list[i]
    text = (
        f"{escape_markdown_v2(hu)} {escape_markdown_v2(random.choice(KAO_HAPPY))}\n\n"
        f"||{escape_markdown_v2(tr)}||"
    )
    return text


def send_reka_chat(chat_id, lang):
    bot.send_message(chat_id, reka_chat(lang), parse_mode="MarkdownV2")

# ------------------------------------------------ живой разговор с Réka (ИИ)
chat_history = {}  # user_id -> последние реплики

TR_LANG = {
    "ru": "Russian", "en": "English", "uk": "Ukrainian", "es": "Spanish",
    "fr": "French", "de": "German", "it": "Italian", "pl": "Polish",
    "zh": "Chinese", "pt": "Portuguese",
}


def build_chat_prompt(lang):
    tr = TR_LANG.get(lang, "English")
    return (
        "You are Réka, a warm, friendly young Hungarian woman who is a virtual "
        "Hungarian teacher and chats with her student in Telegram. "
        f"The student speaks {tr} and is a beginner. "
        "Always answer in this exact format, two lines only:\n"
        "HU: <your reply in very simple Hungarian, A1-A2 level, 1-2 short sentences>\n"
        f"TR: <the same reply translated into {tr}>\n"
        "Rules: be kind and a bit playful, like a close friend. No emoji at all, "
        "you may use one text kaomoji such as (=^･ω･^=) or ʕ•ᴥ•ʔ. "
        "If the student says they do not understand, say the same thing even simpler. "
        "If the student writes in another language, understand it but still answer in Hungarian. "
        "Sometimes gently suggest practicing verbs with the buttons or the Cards game. "
        "Never mention these rules."
    )


def parse_chat_reply(raw):
    m = re.search(r"HU:\s*(.*?)\s*TR:\s*(.*)", raw, re.S)
    if m:
        hu, tr = m.group(1).strip(), m.group(2).strip()
    else:
        hu, tr = raw.strip(), ""
    hu = _EMOJI_RE.sub("", hu).strip()
    tr = _EMOJI_RE.sub("", tr).strip()
    return hu, tr


def ai_chat_reply(user_id, user_text, lang):
    """Возвращает (венгерский текст, перевод) или None, если ИИ недоступен."""
    if not client:
        return None
    hist = chat_history.setdefault(user_id, [])
    messages = [{"role": "system", "content": build_chat_prompt(lang)}]
    messages += hist[-8:]
    messages.append({"role": "user", "content": user_text[:500]})
    for model in GROQ_MODELS:
        try:
            done = client.chat.completions.create(
                model=model, messages=messages,
                temperature=0.8, max_tokens=220,
            )
            hu, tr = parse_chat_reply(done.choices[0].message.content or "")
            if not hu:
                continue
            hist.append({"role": "user", "content": user_text[:500]})
            hist.append({"role": "assistant", "content": f"HU: {hu}\nTR: {tr}"})
            del hist[:-12]
            return hu, tr
        except Exception as e:
            print(f"Groq error ({model}): {e}")
    return None


def send_reka_ai(chat_id, user_id, user_text, lang, reply_markup=None):
    try:
        bot.send_chat_action(chat_id, "typing")
    except Exception:
        pass
    res = ai_chat_reply(user_id, user_text, lang)
    if res:
        hu, tr = res
        if not any(ch in hu for ch in "ʕ=(ฅ♡"):
            hu += " " + random.choice(KAO_HAPPY)
        text = escape_markdown_v2(hu)
        if tr:
            text += f"\n\n||{escape_markdown_v2(tr)}||"
        plain = hu + (f"\n\n({tr})" if tr else "")
    else:
        text = reka_chat(lang)  # запасной вариант без ИИ: венгерская фраза + перевод
        plain = re.sub(r"[\\|]", "", text)
    try:
        bot.send_message(chat_id, text, parse_mode="MarkdownV2", reply_markup=reply_markup)
    except Exception as e:
        print(f"Ошибка MarkdownV2: {e}")
        bot.send_message(chat_id, plain, reply_markup=reply_markup)


# ------------------------------------------------ меню карточек и выход
K_EXIT = "(´･ω･`)"
MENU_TXT = {
    "ru": {"main": "Выбери раздел:", "title": "Что тренируем?", "v": "Глаголы", "c": "Цвета", "a": "Всё вместе", "mode": "Режим", "exit": "Выйти"},
    "en": {"main": "Choose a section:", "title": "What shall we practice?", "v": "Verbs", "c": "Colors", "a": "Everything", "mode": "Mode", "exit": "Exit"},
    "uk": {"main": "Обери розділ:", "title": "Що тренуємо?", "v": "Дієслова", "c": "Кольори", "a": "Все разом", "mode": "Режим", "exit": "Вийти"},
    "es": {"main": "Elige una sección:", "title": "¿Qué practicamos?", "v": "Verbos", "c": "Colores", "a": "Todo", "mode": "Modo", "exit": "Salir"},
    "fr": {"main": "Choisis une section :", "title": "Qu'est-ce qu'on s'entraîne ?", "v": "Verbes", "c": "Couleurs", "a": "Tout", "mode": "Mode", "exit": "Quitter"},
    "de": {"main": "Wähle einen Bereich:", "title": "Was üben wir?", "v": "Verben", "c": "Farben", "a": "Alles", "mode": "Modus", "exit": "Beenden"},
    "it": {"main": "Scegli una sezione:", "title": "Cosa esercitiamo?", "v": "Verbi", "c": "Colori", "a": "Tutto", "mode": "Modalità", "exit": "Esci"},
    "pl": {"main": "Wybierz dział:", "title": "Co ćwiczymy?", "v": "Czasowniki", "c": "Kolory", "a": "Wszystko", "mode": "Tryb", "exit": "Wyjdź"},
    "zh": {"main": "请选择板块：", "title": "练习什么？", "v": "动词", "c": "颜色", "a": "全部", "mode": "模式", "exit": "退出"},
    "pt": {"main": "Escolha uma seção:", "title": "O que vamos praticar?", "v": "Verbos", "c": "Cores", "a": "Tudo", "mode": "Modo", "exit": "Sair"},
}
EXIT_BTNS = {f"{m['exit']} {K_EXIT}" for m in MENU_TXT.values()}


def menu_txt(lang):
    return MENU_TXT.get(lang) or MENU_TXT["en"]


def exit_label(lang):
    return f"{menu_txt(lang)['exit']} {K_EXIT}"


def exit_keyboard(lang):
    """Кнопка выхода внизу экрана на время тренировки глагола."""
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    if edge_tts is not None:
        kb.row(KeyboardButton(text=AUDIO_BTN), KeyboardButton(text=exit_label(lang)))
    else:
        kb.add(KeyboardButton(text=exit_label(lang)))
    return kb


K_VERBS = "ʕ•ᴥ•ʔ"
VERBS_BTNS = {f"{m['v']} {K_VERBS}" for m in MENU_TXT.values()}


def verbs_label(lang):
    return f"{menu_txt(lang)['v']} {K_VERBS}"


MODES_NAMES = {
    "ru": "Режимы", "en": "Modes", "uk": "Режими", "es": "Modos", "fr": "Modes",
    "de": "Modi", "it": "Modalità", "pl": "Tryby", "zh": "模式", "pt": "Modos",
}
# в сравнении убираем невидимый знак эмодзи (U+FE0F): Telegram может его потерять
MODES_BTNS = {f"⚙️ {n}".replace("\ufe0f", "") for n in MODES_NAMES.values()}


def modes_label(lang):
    return f"⚙️ {MODES_NAMES.get(lang) or MODES_NAMES['en']}"


def main_keyboard(lang, uid=None):
    """Внизу одна кнопка «➡️ Дальше» (её можно выключить в /settings)."""
    if uid is not None and not U(uid)["next_btn"]:
        return ReplyKeyboardRemove()
    return next_keyboard(lang)


def exit_to_menu(chat_id, user_id):
    """Выход из тренировки или карточек: возвращаем список глаголов."""
    state = active_trainings.get(user_id)
    if not state or state.get("lang") not in LANGUAGES:
        bot.send_message(
            chat_id,
            f"{K_LANG} Выберите язык интерфейса / Choose your language:",
            reply_markup=get_language_keyboard(),
        )
        return
    lang = state["lang"]
    state.pop("verb", None)
    state.pop("steps", None)
    state["step"] = 0
    bot.send_message(
        chat_id,
        f"{random.choice(KAO_DONE)} {main_prompt(lang)}",
        reply_markup=main_keyboard(lang, user_id),
    )


def card_menu_markup(lang):
    m = menu_txt(lang)
    cards = available_cards()
    has_v = any(c.startswith("v:") for c in cards)
    has_c = any(c.startswith("c:") for c in cards)
    mk = InlineKeyboardMarkup(row_width=2)
    row = []
    if has_v:
        row.append(InlineKeyboardButton(text=m["v"], callback_data="cm:v"))
    if has_c:
        row.append(InlineKeyboardButton(text=m["c"], callback_data="cm:c"))
    if row:
        mk.row(*row)
    if has_v and has_c:
        mk.row(InlineKeyboardButton(text=m["a"], callback_data="cm:a"))
    mk.row(InlineKeyboardButton(text=exit_label(lang), callback_data="cq"))
    return mk


def show_card_menu(chat_id, lang):
    bot.send_message(
        chat_id,
        f"{menu_txt(lang)['title']} {random.choice(KAO_HAPPY)}",
        reply_markup=card_menu_markup(lang),
    )


# Папка с картинками лежит рядом с bot.py: bot.py + cards/ad.jpg, cards/fut.jpg ...
CARDS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cards")

# Глагол -> файл с картинкой Réka
CARD_FILES = {
    "ad": "ad.jpg",
    "gondolkodik": "gondolkodik.jpg",
    "fut": "fut.jpg",
    "ír": "ir.jpg",
    "dolgozik": "dolgozik.jpg",
    "rajzol": "rajzol.jpg",
    "tanul": "tanul.jpg",
}

# Глаголы, которые нельзя предлагать как неправильные варианты:
# они тоже подходят к картинке, и ответ был бы спорным.
CARD_CONFLICTS = {
    "ad": {"kér", "tesz", "vesz", "kap", "eszik"},
    "gondolkodik": {"tanul", "tud", "akar"},
    "fut": {"megy", "jön"},
    "ír": {"gépel", "rajzol", "tanul", "dolgozik", "olvas"},
    "dolgozik": {"gépel", "ír", "tanul", "olvas"},
    "rajzol": {"ír", "játszik", "dolgozik"},
    "tanul": {"olvas", "ír", "gondolkodik", "dolgozik"},
}

# Telegram запоминает загруженную картинку: после первой отправки
# дальше шлём её по file_id, без повторной загрузки.
CARD_FILE_IDS = {}

VERB_INDEX = {v[0]: i for i, v in enumerate(VERBS_DATABASE)}

NO_CARDS_MSG = (
    "Нет картинок. Положи папку cards рядом с bot.py / "
    "No card images: put the cards folder next to bot.py"
)

CARDS_TXT = {
    "ru": {"q": "Что делает Réka?", "no": "Не то, попробуй ещё", "next": "Дальше", "score": "Счёт"},
    "en": {"q": "What is Réka doing?", "no": "Not that one, try again", "next": "Next", "score": "Score"},
    "es": {"q": "¿Qué hace Réka?", "no": "Esa no, prueba otra", "next": "Siguiente", "score": "Puntos"},
    "fr": {"q": "Que fait Réka ?", "no": "Pas celle-là, réessaie", "next": "Suivant", "score": "Score"},
    "de": {"q": "Was macht Réka?", "no": "Nicht das, versuch's nochmal", "next": "Weiter", "score": "Punkte"},
    "it": {"q": "Cosa fa Réka?", "no": "Non quella, riprova", "next": "Avanti", "score": "Punti"},
    "pl": {"q": "Co robi Réka?", "no": "Nie to, spróbuj jeszcze raz", "next": "Dalej", "score": "Wynik"},
    "uk": {"q": "Що робить Réka?", "no": "Не те, спробуй ще", "next": "Далі", "score": "Рахунок"},
    "zh": {"q": "Réka在做什么？", "no": "不是这个，再试试", "next": "下一张", "score": "得分"},
    "pt": {"q": "O que a Réka está fazendo?", "no": "Não é essa, tente de novo", "next": "Próxima", "score": "Pontos"},
}


# Цветные карточки: ключ -> (файл, русский, украинский, английский)
COLOR_CARDS = {
    "fekete": ("c_fekete.jpg", "чёрный", "чорний", "black"),
    "világoskék": ("c_vilagoskek.jpg", "голубой", "блакитний", "light blue"),
    "fehér": ("c_feher.jpg", "белый", "білий", "white"),
    "narancssárga": ("c_narancssarga.jpg", "оранжевый", "помаранчевий", "orange"),
    "rózsaszín": ("c_rozsaszin.jpg", "розовый", "рожевий", "pink"),
    "piros": ("c_piros.jpg", "красный", "червоний", "red"),
    "zöld": ("c_zold.jpg", "зелёный", "зелений", "green"),
    "sárga": ("c_sarga.jpg", "жёлтый", "жовтий", "yellow"),
}
COLOR_INDEX = {k: i for i, k in enumerate(COLOR_CARDS)}
COLOR_KEYS = list(COLOR_CARDS)
COLOR_Q = {
    "ru": "Какого цвета?", "en": "What color is it?", "uk": "Якого кольору?",
    "es": "¿De qué color es?", "fr": "De quelle couleur ?", "de": "Welche Farbe?",
    "it": "Di che colore è?", "pl": "Jaki to kolor?", "zh": "这是什么颜色？",
    "pt": "Qual é a cor?",
}


def color_name(lang, key):
    _, ru, uk, en = COLOR_CARDS[key]
    return ru if lang == "ru" else (uk if lang == "uk" else en)


def available_cards():
    """Ключи карточек, для которых картинка реально лежит в папке cards.
    'v:глагол' — глагол, 'c:цвет' — цвет."""
    out = [
        f"v:{hu}" for hu, fn in CARD_FILES.items()
        if os.path.exists(os.path.join(CARDS_DIR, fn))
    ]
    out += [
        f"c:{k}" for k, v in COLOR_CARDS.items()
        if os.path.exists(os.path.join(CARDS_DIR, v[0]))
    ]
    return out


def card_path(key):
    kind, name = key.split(":", 1)
    fn = CARD_FILES[name] if kind == "v" else COLOR_CARDS[name][0]
    return os.path.join(CARDS_DIR, fn)


def send_card(chat_id, user_id, replace_msg_id=None):
    """Присылает картинку Réka и 4 кнопки (глагол или цвет)."""
    state = active_trainings.setdefault(
        user_id, {"lang": None, "step": 0, "recent": []}
    )
    lang = state.get("lang") or "ru"
    t = CARDS_TXT.get(lang, CARDS_TXT["ru"])

    cards = available_cards()
    if not cards:
        bot.send_message(chat_id, NO_CARDS_MSG)
        return
    mode = state.get("card_mode", "a")
    if mode in ("v", "c"):
        cards = [c for c in cards if c.startswith(mode + ":")] or cards

    # одна и та же картинка возвращается не раньше чем через 3 других
    hist = state.setdefault("card_hist", [])
    blocked = hist[-min(3, len(cards) - 1):] if len(cards) > 1 else []
    pool = [c for c in cards if c not in blocked] or cards
    key = random.choice(pool)
    hist.append(key)
    del hist[:-6]

    kind, name = key.split(":", 1)
    if kind == "v":
        correct = name
        wrong_pool = [
            v[0] for v in VERBS_DATABASE
            if v[0] != correct and v[0] not in CARD_CONFLICTS.get(correct, ())
        ]
        options = random.sample(wrong_pool, 3) + [correct]
        random.shuffle(options)
        buttons = [
            InlineKeyboardButton(
                text=o, callback_data=f"cd:{VERB_INDEX[o]}:{VERB_INDEX[correct]}"
            )
            for o in options
        ]
        question = t["q"]
    else:
        correct = name
        others = [k for k in COLOR_KEYS if k != correct]
        options = random.sample(others, 3) + [correct]
        random.shuffle(options)
        buttons = [
            InlineKeyboardButton(
                text=o, callback_data=f"cl:{COLOR_INDEX[o]}:{COLOR_INDEX[correct]}"
            )
            for o in options
        ]
        question = COLOR_Q.get(lang, COLOR_Q["en"])

    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(*buttons)
    m = menu_txt(lang)
    markup.row(
        InlineKeyboardButton(text=m["mode"], callback_data="cs"),
        InlineKeyboardButton(text=exit_label(lang), callback_data="cq"),
    )

    state["last_card"] = key
    state["card_missed"] = False
    caption = f"{question} {random.choice(KAO_HAPPY)}"

    # Следующая карточка заменяет предыдущую в том же сообщении:
    # в чате и во вкладке «Медиа» не копятся десятки картинок.
    if replace_msg_id:
        try:
            file_id = CARD_FILE_IDS.get(key)
            if file_id:
                bot.edit_message_media(
                    InputMediaPhoto(file_id, caption=caption),
                    chat_id, replace_msg_id, reply_markup=markup,
                )
            else:
                with open(card_path(key), "rb") as f:
                    res = bot.edit_message_media(
                        InputMediaPhoto(f, caption=caption),
                        chat_id, replace_msg_id, reply_markup=markup,
                    )
                if getattr(res, "photo", None):
                    CARD_FILE_IDS[key] = res.photo[-1].file_id
            return
        except Exception as e:
            print(f"Не удалось заменить карточку, шлю новую: {e}")
            try:
                bot.delete_message(chat_id, replace_msg_id)
            except Exception:
                pass

    file_id = CARD_FILE_IDS.get(key)
    if file_id:
        bot.send_photo(chat_id, file_id, caption=caption, reply_markup=markup)
    else:
        with open(card_path(key), "rb") as f:
            msg = bot.send_photo(chat_id, f, caption=caption, reply_markup=markup)
        CARD_FILE_IDS[key] = msg.photo[-1].file_id


def drop_card_message(chat_id, msg_id):
    """Удаляем карточку из чата (если не вышло, хотя бы убираем кнопки)."""
    try:
        bot.delete_message(chat_id, msg_id)
    except Exception:
        try:
            bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=None)
        except Exception:
            pass


def start_cards(chat_id, user_id):
    """Вход в игру: сначала короткая фраза от Réka, потом первая карточка."""
    lang = active_trainings.get(user_id, {}).get("lang") or "ru"
    send_reka_chat(chat_id, lang)
    time.sleep(1.0)
    show_card_menu(chat_id, lang)


@bot.message_handler(commands=["menu", "exit"])
def cmd_exit(message):
    all_users.add(message.from_user.id)
    exit_to_menu(message.chat.id, message.from_user.id)


@bot.message_handler(commands=["cards"])
def cmd_cards(message):
    all_users.add(message.from_user.id)
    start_cards(message.chat.id, message.from_user.id)


@bot.callback_query_handler(
    func=lambda call: call.data in ("cn", "cx", "cq", "cs") or call.data.startswith(("cd:", "cl:", "cm:"))
)
def on_card_callback(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    msg_id = call.message.message_id
    state = active_trainings.setdefault(
        user_id, {"lang": None, "step": 0, "recent": []}
    )
    lang = state.get("lang") or "ru"
    t = CARDS_TXT.get(lang, CARDS_TXT["ru"])

    # выбор режима карточек
    if call.data.startswith("cm:"):
        state["card_mode"] = call.data.split(":")[1]
        state["card_ok"] = 0
        state["card_total"] = 0
        state["card_hist"] = []
        bot.answer_callback_query(call.id)
        try:
            bot.delete_message(chat_id, msg_id)
        except Exception:
            pass
        send_card(chat_id, user_id)
        return

    # сменить режим карточек
    if call.data == "cs":
        bot.answer_callback_query(call.id)
        drop_card_message(chat_id, msg_id)
        show_card_menu(chat_id, lang)
        return

    # выход из карточек
    if call.data == "cq":
        bot.answer_callback_query(call.id)
        drop_card_message(chat_id, msg_id)
        exit_to_menu(chat_id, user_id)
        return

    # нажатие на уже подсвеченную зелёную кнопку — ничего не делаем
    if call.data == "cx":
        bot.answer_callback_query(call.id)
        return

    # кнопка «Дальше» (на случай старых сообщений)
    if call.data == "cn":
        bot.answer_callback_query(call.id)
        try:
            bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=None)
        except Exception:
            pass
        send_card(chat_id, user_id)
        return

    kind, chosen, correct = call.data.split(":")

    if chosen == correct:
        if kind == "cd":
            hu, ru, en, inf = VERBS_DATABASE[int(correct)]
            title = f"{hu} ({inf}) — {verb_name(lang, ru, en)}"
        else:
            ckey = COLOR_KEYS[int(correct)]
            title = f"{ckey} — {color_name(lang, ckey)}"
            hu = ckey
        state["card_total"] = state.get("card_total", 0) + 1
        if not state.get("card_missed"):
            state["card_ok"] = state.get("card_ok", 0) + 1
        caption = (
            f"{title}\n"
            f"{t['score']}: {state.get('card_ok', 0)}/{state['card_total']} "
            f"{random.choice(KAO_HAPPY)}"
        )
        # правильная кнопка становится зелёной (✅), остальные убираем
        old_kb = call.message.reply_markup.keyboard if call.message.reply_markup else []
        chosen_text = next(
            (b.text for row in old_kb for b in row if b.callback_data == call.data),
            hu,
        )
        green = InlineKeyboardMarkup()
        green.add(InlineKeyboardButton(text=f"✅ {chosen_text}", callback_data="cx"))
        bot.answer_callback_query(call.id, text=random.choice(KAO_GREAT))
        try:
            bot.edit_message_caption(
                caption=caption, chat_id=chat_id, message_id=msg_id,
                reply_markup=green,
            )
        except Exception:
            pass
        time.sleep(1.2)  # даём увидеть зелёный ответ
        send_card(chat_id, user_id, replace_msg_id=msg_id)
    else:
        state["card_missed"] = True
        bot.answer_callback_query(
            call.id, text=f"{random.choice(KAO_SAD)} {t['no']}"
        )
        old = call.message.reply_markup.keyboard if call.message.reply_markup else []
        flat = [b for row in old for b in row]
        opts = [
            b for b in flat
            if b.callback_data != call.data and b.callback_data.startswith(("cd:", "cl:"))
        ]
        ctrl = [b for b in flat if b.callback_data in ("cs", "cq")]
        new_markup = InlineKeyboardMarkup(row_width=2)
        new_markup.add(*opts)
        if ctrl:
            new_markup.row(*ctrl)
        bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=new_markup)


@bot.message_handler(commands=["start", "reset", "verbs"])
def cmd_start(message):
    user_id = message.from_user.id
    all_users.add(user_id)

    current_lang = active_trainings.get(user_id, {}).get("lang")

    if current_lang in LANGUAGES:
        new_state(user_id, current_lang)
        if U(user_id)["setup"] == "ready":
            bot.send_message(message.chat.id, T(current_lang, "welcome_back").format(kao=random.choice(KAO_HAPPY)),
                             reply_markup=main_keyboard(current_lang, user_id))
        else:
            start_onboarding(user_id, message.chat.id)
    else:
        new_state(user_id, None)
        bot.send_message(
            message.chat.id,
            f"{K_LANG} Выберите язык интерфейса / Choose your language:",
            reply_markup=get_language_keyboard(),
        )


# ---------------------------------------------------------- курс: 60 базовых глаголов по частоте
# Недели по 12 глаголов. Кортеж: (инфинитив, «он/она», «я», ru, en, фраза hu, фраза ru, фраза en).
# Форма «я» обязательно стоит во фразе: на ней строится вопрос «вставь форму».
VERB_COURSE = [
    # неделя 1: самые нужные
    ("lenni", "van", "vagyok", "быть", "to be", "Itt vagyok.", "Я здесь.", "I'm here."),
    ("menni", "megy", "megyek", "идти / ехать", "to go", "Haza megyek.", "Я иду домой.", "I'm going home."),
    ("jönni", "jön", "jövök", "приходить", "to come", "Holnap jövök.", "Завтра приду.", "I'm coming tomorrow."),
    ("csinálni", "csinál", "csinálok", "делать", "to do", "Nem csinálok semmit.", "Я ничего не делаю.", "I'm not doing anything."),
    ("akarni", "akar", "akarok", "хотеть", "to want", "Kávét akarok.", "Я хочу кофе.", "I want a coffee."),
    ("tudni", "tud", "tudok", "уметь / мочь", "to be able to", "Tudok úszni.", "Я умею плавать.", "I can swim."),
    ("látni", "lát", "látok", "видеть", "to see", "Látok egy autót.", "Я вижу машину.", "I see a car."),
    ("mondani", "mond", "mondok", "сказать", "to say", "Mondok valamit.", "Я скажу кое-что.", "I'm telling you something."),
    ("adni", "ad", "adok", "давать", "to give", "Adok egy almát.", "Я дам яблоко.", "I'll give an apple."),
    ("venni", "vesz", "veszek", "брать / покупать", "to buy", "Kenyeret veszek.", "Я покупаю хлеб.", "I'm buying bread."),
    ("enni", "eszik", "eszem", "есть (еду)", "to eat", "Sajtot eszem.", "Я ем сыр.", "I'm eating cheese."),
    ("inni", "iszik", "iszom", "пить", "to drink", "Vizet iszom.", "Я пью воду.", "I'm drinking water."),
    # неделя 2: быт и разговор
    ("szeretni", "szeret", "szeretek", "любить", "to love / like", "Szeretek kávét inni.", "Я люблю пить кофе.", "I like drinking coffee."),
    ("kérni", "kér", "kérek", "просить", "to ask for", "Egy teát kérek.", "Мне чай, пожалуйста.", "A tea, please."),
    ("kapni", "kap", "kapok", "получать", "to get", "Levelet kapok.", "Я получаю письмо.", "I'm getting a letter."),
    ("keresni", "keres", "keresek", "искать", "to look for", "Kulcsot keresek.", "Я ищу ключ.", "I'm looking for a key."),
    ("várni", "vár", "várok", "ждать", "to wait", "Várok a buszra.", "Я жду автобус.", "I'm waiting for the bus."),
    ("nyitni", "nyit", "nyitok", "открывать", "to open", "Ajtót nyitok.", "Я открываю дверь.", "I'm opening the door."),
    ("fizetni", "fizet", "fizetek", "платить", "to pay", "Kártyával fizetek.", "Я плачу картой.", "I'm paying by card."),
    ("segíteni", "segít", "segítek", "помогать", "to help", "Segítek neked.", "Я помогу тебе.", "I'll help you."),
    ("beszélni", "beszél", "beszélek", "говорить", "to speak", "Magyarul beszélek.", "Я говорю по-венгерски.", "I speak Hungarian."),
    ("tanulni", "tanul", "tanulok", "учить / учиться", "to learn", "Magyarul tanulok.", "Я учу венгерский.", "I'm learning Hungarian."),
    ("dolgozni", "dolgozik", "dolgozom", "работать", "to work", "Itt dolgozom.", "Я здесь работаю.", "I work here."),
    ("lakni", "lakik", "lakom", "жить (где-то)", "to live (somewhere)", "Budapesten lakom.", "Я живу в Будапеште.", "I live in Budapest."),
    # неделя 3: повседневные действия
    ("olvasni", "olvas", "olvasok", "читать", "to read", "Könyvet olvasok.", "Я читаю книгу.", "I'm reading a book."),
    ("írni", "ír", "írok", "писать", "to write", "Levelet írok.", "Я пишу письмо.", "I'm writing a letter."),
    ("hallani", "hall", "hallok", "слышать", "to hear", "Zenét hallok.", "Я слышу музыку.", "I hear music."),
    ("nézni", "néz", "nézek", "смотреть", "to watch", "Filmet nézek.", "Я смотрю фильм.", "I'm watching a film."),
    ("hallgatni", "hallgat", "hallgatok", "слушать", "to listen", "Zenét hallgatok.", "Я слушаю музыку.", "I'm listening to music."),
    ("aludni", "alszik", "alszom", "спать", "to sleep", "Jól alszom.", "Я хорошо сплю.", "I sleep well."),
    ("főzni", "főz", "főzök", "готовить (еду)", "to cook", "Levest főzök.", "Я варю суп.", "I'm making soup."),
    ("futni", "fut", "futok", "бежать", "to run", "Reggel futok.", "Я бегаю по утрам.", "I run in the morning."),
    ("játszani", "játszik", "játszom", "играть", "to play", "Gitáron játszom.", "Я играю на гитаре.", "I play the guitar."),
    ("tenni", "tesz", "teszek", "класть / ставить", "to put", "Cukrot teszek a kávéba.", "Я кладу сахар в кофе.", "I'm putting sugar in my coffee."),
    ("hozni", "hoz", "hozok", "приносить", "to bring", "Vizet hozok.", "Я принесу воду.", "I'll bring water."),
    ("vinni", "visz", "viszek", "нести / везти", "to carry / take", "Kávét viszek.", "Я несу кофе.", "I'm carrying coffee."),
    # неделя 4: мысли, общение, движение
    ("gondolkodni", "gondolkodik", "gondolkodom", "размышлять", "to think (ponder)", "Most gondolkodom.", "Я сейчас думаю.", "I'm thinking now."),
    ("rajzolni", "rajzol", "rajzolok", "рисовать", "to draw", "Rajzolok egy házat.", "Я рисую дом.", "I'm drawing a house."),
    ("gépelni", "gépel", "gépelek", "печатать", "to type", "Gyorsan gépelek.", "Я быстро печатаю.", "I type fast."),
    ("találkozni", "találkozik", "találkozom", "встречаться", "to meet", "Holnap találkozom egy barátommal.", "Завтра я встречаюсь с другом.", "I'm meeting a friend tomorrow."),
    ("kezdeni", "kezd", "kezdek", "начинать", "to start", "Most kezdek.", "Я начинаю сейчас.", "I'm starting now."),
    ("kérdezni", "kérdez", "kérdezek", "спрашивать", "to ask", "Kérdezek valamit.", "Я спрошу кое-что.", "I'm asking something."),
    ("válaszolni", "válaszol", "válaszolok", "отвечать", "to answer", "Gyorsan válaszolok.", "Я быстро отвечаю.", "I answer quickly."),
    ("ülni", "ül", "ülök", "сидеть", "to sit", "Itt ülök.", "Я сижу здесь.", "I'm sitting here."),
    ("állni", "áll", "állok", "стоять", "to stand", "Az ajtónál állok.", "Я стою у двери.", "I'm standing at the door."),
    ("sétálni", "sétál", "sétálok", "гулять", "to walk", "Parkban sétálok.", "Я гуляю в парке.", "I'm walking in the park."),
    ("utazni", "utazik", "utazom", "путешествовать", "to travel", "Vonattal utazom.", "Я еду на поезде.", "I'm travelling by train."),
    ("vezetni", "vezet", "vezetek", "водить", "to drive", "Autót vezetek.", "Я вожу машину.", "I drive a car."),
    # неделя 5: ещё полезное
    ("táncolni", "táncol", "táncolok", "танцевать", "to dance", "Esténként táncolok.", "Я танцую по вечерам.", "I dance in the evenings."),
    ("tanítani", "tanít", "tanítok", "преподавать", "to teach", "Angolt tanítok.", "Я преподаю английский.", "I teach English."),
    ("használni", "használ", "használok", "использовать", "to use", "Telefont használok.", "Я пользуюсь телефоном.", "I'm using a phone."),
    ("hívni", "hív", "hívok", "звать / звонить", "to call", "Taxit hívok.", "Я вызываю такси.", "I'm calling a taxi."),
    ("mosni", "mos", "mosok", "мыть / стирать", "to wash", "Ruhát mosok.", "Я стираю одежду.", "I'm washing clothes."),
    ("ismerni", "ismer", "ismerek", "знать (кого, что)", "to know (a person, a place)", "Ismerek egy éttermet.", "Я знаю один ресторан.", "I know a restaurant."),
    ("érteni", "ért", "értek", "понимать", "to understand", "Értek magyarul.", "Я понимаю по-венгерски.", "I understand Hungarian."),
    ("gondolni", "gondol", "gondolok", "думать о", "to think of", "Rád gondolok.", "Я думаю о тебе.", "I'm thinking of you."),
    ("hinni", "hisz", "hiszek", "верить", "to believe", "Hiszek neked.", "Я верю тебе.", "I believe you."),
    ("félni", "fél", "félek", "бояться", "to be afraid", "Nem félek.", "Я не боюсь.", "I'm not afraid."),
    ("sietni", "siet", "sietek", "спешить", "to hurry", "Nagyon sietek.", "Я очень спешу.", "I'm in a big hurry."),
    ("maradni", "marad", "maradok", "оставаться", "to stay", "Itthon maradok.", "Я остаюсь дома.", "I'm staying home."),
]
N_VERBS = len(VERB_COURSE)
PACK = 12                 # глаголов в «неделе» по умолчанию (ориентир для карты)
CYCLE_DAYS = 6            # дней подачи новых глаголов, на 7-й день тест
PASS_RATIO = 0.75         # доля верных ответов в тесте, чтобы неделя считалась сданной
PACE_DEFAULT = 2          # новых глаголов в день
PACE_MIN, PACE_MAX = 1, 4
WINDOWS = {"early": (7, 19), "std": (9, 21), "late": (11, 23)}   # окно, в котором приходят сообщения
CATCHUP = 120             # если бот молчал, сообщение запоздало не больше чем на 120 минут: шлём, иначе пропускаем
BONUS_MAX = 4             # сколько глаголов, помеченных «знаю», проверяем в тесте
CREDIT_SAMPLE = 4         # сколько уже закрытых в течение недели глаголов всё же спрашиваем в тесте
MILESTONES = [(5, "🌱"), (10, "🥉"), (20, "🥈"), (30, "🥇"), (45, "💎"), (N_VERBS, "👑")]


def v_tr(lang, vid):
    v = VERB_COURSE[vid]
    return v[3] if lang in ("ru", "uk") else v[4]


def v_ex_tr(lang, vid):
    v = VERB_COURSE[vid]
    return v[6] if lang in ("ru", "uk") else v[7]


def v_blank(vid):
    """Фраза с пропуском на месте формы «я»."""
    v = VERB_COURSE[vid]
    return re.sub(r"(?<!\w)" + re.escape(v[2]) + r"(?!\w)", "___", v[5], count=1, flags=re.IGNORECASE)



# Этапы пути: каждый этап = неделя из 12 глаголов. Название и цель показываем в сообщениях и в /progress.
STAGES = [
    {"name": {"ru": "Основа", "uk": "Основа", "en": "Foundation"},
     "goal": {"ru": "самые нужные глаголы: быть, идти, хотеть, видеть, есть, пить",
              "uk": "найпотрібніші дієслова: бути, йти, хотіти, бачити, їсти, пити",
              "en": "the most essential verbs: to be, go, want, see, eat, drink"}},
    {"name": {"ru": "Быт и разговор", "uk": "Побут і розмова", "en": "Daily life & talk"},
     "goal": {"ru": "просить, платить, говорить, учить, работать, жить",
              "uk": "просити, платити, говорити, вчити, працювати, жити",
              "en": "ask for, pay, speak, learn, work, live"}},
    {"name": {"ru": "Повседневные действия", "uk": "Щоденні дії", "en": "Everyday actions"},
     "goal": {"ru": "читать, писать, слушать, смотреть, готовить, играть",
              "uk": "читати, писати, слухати, дивитись, готувати, грати",
              "en": "read, write, listen, watch, cook, play"}},
    {"name": {"ru": "Мысли и движение", "uk": "Думки і рух", "en": "Thinking & moving"},
     "goal": {"ru": "думать, встречаться, начинать, спрашивать, гулять, водить",
              "uk": "думати, зустрічатися, починати, питати, гуляти, водити",
              "en": "think, meet, start, ask, walk, drive"}},
    {"name": {"ru": "Ещё полезное", "uk": "Ще корисне", "en": "More essentials"},
     "goal": {"ru": "преподавать, звонить, понимать, верить, бояться, оставаться",
              "uk": "викладати, дзвонити, розуміти, вірити, боятися, залишатися",
              "en": "teach, call, understand, believe, fear, stay"}},
]
INTENSITY = {"calm": 5, "normal": 9, "dense": 13}   # сообщений в день (сколько глаголов — задаёт темп)


def user_lang(user_id):
    return active_trainings.get(user_id, {}).get("lang") or "ru"





# ---------- озвучка: венгерское произношение голосовым сообщением (кнопка 🔊)
TTS_VOICE = os.getenv("TTS_VOICE", "hu-HU-NoemiNeural")   # венгерский женский голос Microsoft
TTS_RATE = os.getenv("TTS_RATE", "-10%")                   # чуть медленнее обычного, чтобы разобрать на слух
AUDIO_DIR = os.path.join(DATA_DIR, "audio")
AUDIO_IDS_FILE = os.path.join(DATA_DIR, "audio_ids.json")
AUDIO_BTN = "🔊"
AUDIO_FAIL = {
    "ru": "Не получилось озвучить, попробуй позже",
    "uk": "Не вдалося озвучити, спробуй пізніше",
    "en": "Couldn't make the audio, try again later",
}
_tts_lock = threading.Lock()


def _load_audio_ids():
    try:
        with open(AUDIO_IDS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


_audio_ids = _load_audio_ids()   # {текст: file_id в Telegram}: повторно ничего не загружаем


def _save_audio_ids():
    try:
        with open(AUDIO_IDS_FILE, "w", encoding="utf-8") as f:
            json.dump(_audio_ids, f)
    except Exception as e:
        print(f"Не удалось сохранить audio_ids.json: {e}")


def speech_file(text):
    """Путь к mp3 с произношением. Каждый текст озвучивается один раз и лежит в кэше."""
    if edge_tts is None:
        return None
    os.makedirs(AUDIO_DIR, exist_ok=True)
    name = hashlib.sha1(f"{TTS_VOICE}|{TTS_RATE}|{text}".encode("utf-8")).hexdigest()[:16]
    path = os.path.join(AUDIO_DIR, f"{name}.mp3")
    with _tts_lock:
        if os.path.exists(path) and os.path.getsize(path) > 0:
            return path
        tmp = path + ".part"
        asyncio.run(edge_tts.Communicate(text, TTS_VOICE, rate=TTS_RATE).save(tmp))
        os.replace(tmp, path)
    return path


def send_speech(chat_id, text):
    """Присылает голосовое сообщение с произношением текста. True, если получилось."""
    text = text.strip()
    if not text:
        return False
    try:
        bot.send_chat_action(chat_id, "record_voice")
    except Exception:
        pass
    try:
        fid = _audio_ids.get(text)
        if fid:
            try:
                bot.send_voice(chat_id, fid)
                return True
            except Exception:
                _audio_ids.pop(text, None)     # file_id устарел: озвучим заново
        path = speech_file(text)
        if not path:
            return False
        with open(path, "rb") as f:
            sent = bot.send_voice(chat_id, f)
        info = getattr(sent, "voice", None) or getattr(sent, "audio", None)
        if info is not None and getattr(info, "file_id", None):
            _audio_ids[text] = info.file_id
            _save_audio_ids()
            try:
                os.remove(path)                    # файл больше не нужен: в Telegram есть file_id
            except OSError:
                pass
        return True
    except Exception as e:
        print(f"Ошибка озвучки «{text}»: {e}")
        return False


def _purge_audio_cache(max_age=6 * 3600):
    """Чистит папку с mp3: временные файлы не копятся."""
    try:
        now = time.time()
        for name in os.listdir(AUDIO_DIR):
            p = os.path.join(AUDIO_DIR, name)
            if os.path.isfile(p) and now - os.path.getmtime(p) > max_age:
                os.remove(p)
    except OSError:
        pass


_purge_audio_cache(0)


def audio_fail_text(lang):
    return AUDIO_FAIL.get(lang, AUDIO_FAIL["en"])




def budapest_now():
    return datetime.now(BUDAPEST_TZ)





# ---------------------------------------------------------------- хранилище прогресса
COURSE_FILE = os.path.join(DATA_DIR, "course.json")
_lock = threading.RLock()
_USER_DEFAULTS = {
    "pace": PACE_DEFAULT, "win": "std", "setup": None, "claimed": [], "learned": [],
    "cycle": None, "day": None, "test": None, "ach": [], "marked": [], "page": 0, "wkn": 0,
    "inten": "normal", "next_btn": True, "kb_sent": False, "tidy": True, "pin_id": None,
}


def _load_course():
    try:
        with open(COURSE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


_store = _load_course()   # {user_id: {...}}


def save_course():
    with _lock:
        try:
            tmp = COURSE_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(_store, f, ensure_ascii=False)
            os.replace(tmp, COURSE_FILE)
        except Exception as e:
            print(f"Не удалось сохранить course.json: {e}")


def U(uid):
    with _lock:
        u = _store.setdefault(str(uid), {})
        for k, d in _USER_DEFAULTS.items():
            if k not in u:
                u[k] = copy.deepcopy(d)
        return u


# ---------------------------------------------------------------- тексты
PT = {
    "ru": {
        "p_en": "я", "p_o": "он/она", "intro": "Глаголы дня", "example": "Фразы", "recall": "Вспомни",
        "quiz": "Мини-вопрос", "fill": "Вставь форму «я»:", "know": "✅ Знаю", "easy": "⏩ Слишком легко", "hard": "🐢 Слишком сложно",
        "pace_up": "Ок, глаголов в день: {n}. Со следующего дня.", "pace_down": "Ок, глаголов в день: {n}. Со следующего дня.",
        "know_ok": "Ок, проверю тебя в тесте. Вот следующий:", "stale": "Это сообщение уже устарело",
        "ob_hi": "{kao} Привет, я Réka! Каждый день я буду присылать пару венгерских глаголов: читай между делом, ничего открывать не нужно. "
                 "В конце недели короткий тест на пройденное.\n\nОтметь глаголы, которые ты уже знаешь. Если не знаешь ни одного, просто жми «Готово».",
        "ob_more": "▶️ Ещё глаголы", "ob_done": "✅ Готово", "ob_pace": "Сколько новых глаголов в день? Это можно поменять в /settings.",
        "pace_btn": "{n} в день", "pace_rec": "{n} в день · рекомендую", "ob_go": "Поехали! Первые глаголы уже летят 👇",
        "test_day": "🎯 Неделя пройдена: тест на {n} глаголов. Две минуты, один вопрос за раз.",
        "btn_test": "🎯 Начать тест", "recap": "Повторим неделю", "remind": "Тест всё ещё ждёт. Пока он не сдан, новых глаголов не будет: повторяем эту неделю.",
        "test_head": "🎯 Тест · вопрос {i} из {n}", "no_test": "Пока нечего проверять: глаголы ещё не приходили.",
        "pass": "✅ Тест сдан: {r} из {n}!", "fail": "❌ Тест не сдан: {r} из {n}, нужно {need}.", "wrong_list": "Эти глаголы вернутся:",
        "next_new": "Со следующего дня новые глаголы.", "next_repeat": "Повторяем их ещё раз ({n} шт.), потом снова тест.",
        "next_review": "Курс пройден, дальше повторение выученного.",
        "bonus_ok": "Знакомые глаголы подтвердились: {n}.", "bonus_bad": "Из «знаю» не подтвердились: {n}, они вернутся в программу.",
        "ach": "🏆 Достижение: выучено глаголов — {n} {e}",
        "progress": "📊 Твой путь", "learned": "Выучено глаголов: {n} из {t}", "week": "Неделя {n}: день {d} из {m}",
        "week_test": "Неделя {n}: пора на тест", "week_repeat": "Повторение: день {d} из {m}",
        "next_ach": "До следующей награды: {n}", "all_ach": "Все награды получены 👑", "map": "Карта:",
        "settings": "⚙️ Настройки\n\nГлаголов в день: {n}\nВремя сообщений: {a}:00–{b}:00",
        "win_early": "Рано", "win_std": "Днём", "win_late": "Поздно",
        "today_none": "Сегодня глаголов ещё нет. Загляну в {h}:00.", "today_test": "Сегодня день теста. Жми /test",
        "hint": "Всё приходит само, а «➡️ Дальше» ведёт по программе. Ещё: /progress, /settings, /test, /drill.",
        "drill_hint": "Выбери глагол для прописей:",
        "old_btn": "Бот обновился: теперь глаголы приходят сами. Команды: /progress, /settings, /test, /drill.",
        "stage_head": "📍 Этап {s} из {S}: «{name}»", "stage_line": "📍 Этап {s} из {S} «{name}» · день {d} из {m}",
        "stage_line_test": "📍 Этап {s} из {S} «{name}» · тест", "repeat_line": "🔁 Повтор этапа {s} · день {d} из {m}",
        "stage_goal": "Цель: {goal}.", "stage_learn": "Выучить ({n}):", "stage_how": "Как идём: {m} дней глаголы приходят сами, потом тест (нужно {p}% верных). Сдал, и этап пройден.",
        "stage_next": "Следующий этап: «{name}».", "stage_last": "Это последний этап.",
        "repeat_head": "🔁 Повторяем этап {s}: возвращаются глаголы ({n}):", "repeat_how": "Они придут ещё раз за {m} дн., потом снова тест.",
        "review_head": "🏁 Курс пройден! Дальше неделя повторения выученного ({n} глаголов).",
        "mix": "Вспомни прошлое", "day_recap": "Итог дня", "next_btn": "➡️ Дальше", "next_hint": "Внизу теперь кнопка «➡️ Дальше»: жми, когда захочешь продолжить, не дожидаясь сообщений. Убрать её можно в /settings.",
        "next_done": "На сегодня по плану всё ✅ Хочешь ещё? Держи вопрос:", "next_off": "Ок, убрал кнопку внизу.", "next_on": "Кнопка «➡️ Дальше» снова внизу.",
        "intensity": "Сообщений в день", "int_calm": "Спокойно", "int_normal": "Обычно", "int_dense": "Плотно", "btn_toggle_on": "Кнопка «Дальше»: вкл", "btn_toggle_off": "Кнопка «Дальше»: выкл",
        "test_in": "до теста: {n} дн.", "stage_left": "Осталось выучить: {n}", "tomorrow": "Завтра: новые глаголы.", "test_soon": "Дальше: тест. Жми «➡️ Дальше».",
        "go_test": "Погнали, тест!", "setup_first": "Сначала познакомимся:",
        "welcome_back": "{kao} Снова привет! Глаголы приходят сами. /progress покажет твой путь.",
    },
    "uk": {
        "p_en": "я", "p_o": "він/вона", "intro": "Дієслова дня", "example": "Фрази", "recall": "Згадай",
        "quiz": "Міні-питання", "fill": "Встав форму «я»:", "know": "✅ Знаю", "easy": "⏩ Занадто легко", "hard": "🐢 Занадто складно",
        "pace_up": "Ок, дієслів на день: {n}. З наступного дня.", "pace_down": "Ок, дієслів на день: {n}. З наступного дня.",
        "know_ok": "Ок, перевірю тебе в тесті. Ось наступне:", "stale": "Це повідомлення вже застаріло",
        "ob_hi": "{kao} Привіт, я Réka! Щодня я надсилатиму кілька угорських дієслів: читай між справами, нічого відкривати не треба. "
                 "Наприкінці тижня короткий тест на пройдене.\n\nПпознач дієслова, які ти вже знаєш. Якщо не знаєш жодного, просто тисни «Готово».",
        "ob_more": "▶️ Ще дієслова", "ob_done": "✅ Готово", "ob_pace": "Скільки нових дієслів на день? Це можна змінити в /settings.",
        "pace_btn": "{n} на день", "pace_rec": "{n} на день · раджу", "ob_go": "Поїхали! Перші дієслова вже летять 👇",
        "test_day": "🎯 Тиждень пройдено: тест на {n} дієслів. Дві хвилини, одне питання за раз.",
        "btn_test": "🎯 Почати тест", "recap": "Повторимо тиждень", "remind": "Тест досі чекає. Поки він не здано, нових дієслів не буде: повторюємо цей тиждень.",
        "test_head": "🎯 Тест · питання {i} з {n}", "no_test": "Поки нічого перевіряти: дієслова ще не надходили.",
        "pass": "✅ Тест здано: {r} з {n}!", "fail": "❌ Тест не здано: {r} з {n}, потрібно {need}.", "wrong_list": "Ці дієслова повернуться:",
        "next_new": "З наступного дня нові дієслова.", "next_repeat": "Повторюємо їх ще раз ({n} шт.), потім знову тест.",
        "next_review": "Курс пройдено, далі повторення вивченого.",
        "bonus_ok": "Знайомі дієслова підтвердилися: {n}.", "bonus_bad": "З «знаю» не підтвердилися: {n}, вони повернуться в програму.",
        "ach": "🏆 Досягнення: вивчено дієслів — {n} {e}",
        "progress": "📊 Твій шлях", "learned": "Вивчено дієслів: {n} з {t}", "week": "Тиждень {n}: день {d} з {m}",
        "week_test": "Тиждень {n}: час на тест", "week_repeat": "Повторення: день {d} з {m}",
        "next_ach": "До наступної нагороди: {n}", "all_ach": "Усі нагороди отримано 👑", "map": "Карта:",
        "settings": "⚙️ Налаштування\n\nДієслів на день: {n}\nЧас повідомлень: {a}:00–{b}:00",
        "win_early": "Рано", "win_std": "Вдень", "win_late": "Пізно",
        "today_none": "Сьогодні дієслів ще немає. Загляну о {h}:00.", "today_test": "Сьогодні день тесту. Тисни /test",
        "hint": "Усе приходить само, а «➡️ Далі» веде за програмою. Ще: /progress, /settings, /test, /drill.",
        "drill_hint": "Обери дієслово для прописів:",
        "old_btn": "Бот оновився: тепер дієслова приходять самі. Команди: /progress, /settings, /test, /drill.",
        "stage_head": "📍 Етап {s} з {S}: «{name}»", "stage_line": "📍 Етап {s} з {S} «{name}» · день {d} з {m}",
        "stage_line_test": "📍 Етап {s} з {S} «{name}» · тест", "repeat_line": "🔁 Повтор етапу {s} · день {d} з {m}",
        "stage_goal": "Мета: {goal}.", "stage_learn": "Вивчити ({n}):", "stage_how": "Як ідемо: {m} днів дієслова приходять самі, потім тест (потрібно {p}% вірних). Склав, і етап пройдено.",
        "stage_next": "Наступний етап: «{name}».", "stage_last": "Це останній етап.",
        "repeat_head": "🔁 Повторюємо етап {s}: повертаються дієслова ({n}):", "repeat_how": "Вони прийдуть ще раз за {m} дн., потім знову тест.",
        "review_head": "🏁 Курс пройдено! Далі тиждень повторення вивченого ({n} дієслів).",
        "mix": "Згадай минуле", "day_recap": "Підсумок дня", "next_btn": "➡️ Далі", "next_hint": "Внизу тепер кнопка «➡️ Далі»: тисни, коли захочеш продовжити, не чекаючи повідомлень. Прибрати її можна в /settings.",
        "next_done": "На сьогодні за планом усе ✅ Хочеш ще? Тримай питання:", "next_off": "Ок, прибрав кнопку внизу.", "next_on": "Кнопка «➡️ Далі» знову внизу.",
        "intensity": "Повідомлень на день", "int_calm": "Спокійно", "int_normal": "Звичайно", "int_dense": "Щільно", "btn_toggle_on": "Кнопка «Далі»: увімк", "btn_toggle_off": "Кнопка «Далі»: вимк",
        "test_in": "до тесту: {n} дн.", "stage_left": "Лишилось вивчити: {n}", "tomorrow": "Завтра: нові дієслова.", "test_soon": "Далі: тест. Тисни «➡️ Далі».",
        "go_test": "Поїхали, тест!", "setup_first": "Спочатку познайомимось:",
        "welcome_back": "{kao} Знову привіт! Дієслова приходять самі. /progress покаже твій шлях.",
    },
    "en": {
        "p_en": "I", "p_o": "he/she", "intro": "Verbs of the day", "example": "Phrases", "recall": "Recall",
        "quiz": "Quick question", "fill": "Fill in the “I” form:", "know": "✅ I know it", "easy": "⏩ Too easy", "hard": "🐢 Too hard",
        "pace_up": "Okay, verbs per day: {n}. From tomorrow.", "pace_down": "Okay, verbs per day: {n}. From tomorrow.",
        "know_ok": "Okay, I'll check you in the test. Here's the next one:", "stale": "This message is out of date",
        "ob_hi": "{kao} Hi, I'm Réka! Every day I'll send you a couple of Hungarian verbs: just read them whenever, nothing to open. "
                 "At the end of the week there's a short test.\n\nMark the verbs you already know. If you know none, just tap “Done”.",
        "ob_more": "▶️ More verbs", "ob_done": "✅ Done", "ob_pace": "How many new verbs per day? You can change it in /settings.",
        "pace_btn": "{n} a day", "pace_rec": "{n} a day · recommended", "ob_go": "Let's go! The first verbs are on the way 👇",
        "test_day": "🎯 Week complete: a test on {n} verbs. Two minutes, one question at a time.",
        "btn_test": "🎯 Start the test", "recap": "Week recap", "remind": "The test is still waiting. Until it's passed there are no new verbs: we repeat this week.",
        "test_head": "🎯 Test · question {i} of {n}", "no_test": "Nothing to test yet: no verbs have arrived.",
        "pass": "✅ Test passed: {r} of {n}!", "fail": "❌ Test failed: {r} of {n}, need {need}.", "wrong_list": "These verbs come back:",
        "next_new": "New verbs start tomorrow.", "next_repeat": "We repeat them once more ({n}), then test again.",
        "next_review": "Course complete, now we review what you learned.",
        "bonus_ok": "Verbs you said you know, confirmed: {n}.", "bonus_bad": "Not confirmed from “I know”: {n}, they return to the plan.",
        "ach": "🏆 Achievement: verbs learned — {n} {e}",
        "progress": "📊 Your path", "learned": "Verbs learned: {n} of {t}", "week": "Week {n}: day {d} of {m}",
        "week_test": "Week {n}: test time", "week_repeat": "Repeat: day {d} of {m}",
        "next_ach": "Next reward in: {n}", "all_ach": "All rewards unlocked 👑", "map": "Map:",
        "settings": "⚙️ Settings\n\nVerbs per day: {n}\nMessage window: {a}:00–{b}:00",
        "win_early": "Early", "win_std": "Daytime", "win_late": "Late",
        "today_none": "No verbs yet today. I'll be back at {h}:00.", "today_test": "Today is test day. Tap /test",
        "hint": "Everything arrives by itself, and “➡️ Next” walks you through the program. Also: /progress, /settings, /test, /drill.",
        "drill_hint": "Pick a verb to practice:",
        "old_btn": "The bot was updated: verbs now arrive by themselves. Commands: /progress, /settings, /test, /drill.",
        "stage_head": "📍 Stage {s} of {S}: “{name}”", "stage_line": "📍 Stage {s} of {S} “{name}” · day {d} of {m}",
        "stage_line_test": "📍 Stage {s} of {S} “{name}” · test", "repeat_line": "🔁 Stage {s} repeat · day {d} of {m}",
        "stage_goal": "Goal: {goal}.", "stage_learn": "To learn ({n}):", "stage_how": "How it goes: {m} days the verbs arrive on their own, then a test ({p}% correct needed). Pass it and the stage is done.",
        "stage_next": "Next stage: “{name}”.", "stage_last": "This is the last stage.",
        "repeat_head": "🔁 Repeating stage {s}: these verbs come back ({n}):", "repeat_how": "They arrive once more over {m} days, then another test.",
        "review_head": "🏁 Course complete! Next is a review week of what you learned ({n} verbs).",
        "mix": "Remember earlier", "day_recap": "Day recap", "next_btn": "➡️ Next", "next_hint": "There's now a “➡️ Next” button at the bottom: tap it whenever you want to continue without waiting. You can remove it in /settings.",
        "next_done": "That's everything planned for today ✅ Want more? Here's a question:", "next_off": "Okay, button removed.", "next_on": "The “➡️ Next” button is back.",
        "intensity": "Messages per day", "int_calm": "Calm", "int_normal": "Normal", "int_dense": "Dense", "btn_toggle_on": "“Next” button: on", "btn_toggle_off": "“Next” button: off",
        "test_in": "test in {n} d", "stage_left": "Left to learn: {n}", "tomorrow": "Tomorrow: new verbs.", "test_soon": "Next: the test. Tap “➡️ Next”.",
        "go_test": "Let's go, the test!", "setup_first": "Let's meet first:",
        "welcome_back": "{kao} Hi again! Verbs arrive by themselves. /progress shows your path.",
    },
}


PT["ru"].update({
    "step_head": "➡️ Шаг {k} из {n} {bar}", "stage_line": "Этап {s} из {S} «{name}»",
    "why_intro": "Что делаем: знакомимся с глаголами дня. Зачем: чтобы слова стали знакомыми.",
    "why_ex": "Что делаем: смотрим глагол в живой фразе. Зачем: так он запоминается легче, чем в списке.",
    "why_recall": "Что делаем: вспоминаем слова дня. Зачем: вспоминание закрепляет сильнее, чем перечитывание.",
    "why_quiz": "Что делаем: проверяем себя. Зачем: каждый верный ответ идёт в зачёт недельного теста.",
    "why_mix": "Что делаем: смешиваем с прошлыми глаголами. Зачем: чтобы старые не забывались.",
    "why_form": "Что делаем: ставим глагол в форму «я». Зачем: форма в предложении, а не слово в вакууме.",
    "why_recap": "Что делаем: итог дня. Зачем: увидеть всё выученное сегодня разом.",
    "why_testday": "Что делаем: день теста. Зачем: пока не сдашь, неделя повторяется.",
    "why_quizp": "Что делаем: разминка перед тестом.", "why_remind": "Что делаем: напоминаю про тест.",
    "bonus": "✅ План на сегодня выполнен. 🎲 Бонус {k} из {m}: ещё один вопрос по этой неделе.",
    "all_done": "Всё на сегодня ✅ Следующее сообщение придёт завтра с {a}:00. Я пишу сама, жать ничего не нужно.",
    "btn_tidy_on": "Чистый чат: вкл", "btn_tidy_off": "Чистый чат: выкл",
})
PT["uk"].update({
    "step_head": "➡️ Крок {k} з {n} {bar}", "stage_line": "Етап {s} з {S} «{name}»",
    "why_intro": "Що робимо: знайомимось із дієсловами дня. Навіщо: щоб слова стали знайомими.",
    "why_ex": "Що робимо: дивимось дієслово в живій фразі. Навіщо: так воно запам'ятовується легше, ніж у списку.",
    "why_recall": "Що робимо: згадуємо слова дня. Навіщо: згадування закріплює сильніше, ніж перечитування.",
    "why_quiz": "Що робимо: перевіряємо себе. Навіщо: кожна вірна відповідь іде в залік тижневого тесту.",
    "why_mix": "Що робимо: змішуємо з минулими дієсловами. Навіщо: щоб старі не забувались.",
    "why_form": "Що робимо: ставимо дієслово у форму «я». Навіщо: форма в реченні, а не слово саме по собі.",
    "why_recap": "Що робимо: підсумок дня. Навіщо: побачити все вивчене сьогодні разом.",
    "why_testday": "Що робимо: день тесту. Навіщо: поки не складеш, тиждень повторюється.",
    "why_quizp": "Що робимо: розминка перед тестом.", "why_remind": "Що робимо: нагадую про тест.",
    "bonus": "✅ План на сьогодні виконано. 🎲 Бонус {k} з {m}: ще одне питання за цим тижнем.",
    "all_done": "Усе на сьогодні ✅ Наступне повідомлення прийде завтра з {a}:00. Я пишу сама, тиснути нічого не треба.",
    "btn_tidy_on": "Чистий чат: увімк", "btn_tidy_off": "Чистий чат: вимк",
})
PT["en"].update({
    "step_head": "➡️ Step {k} of {n} {bar}", "stage_line": "Stage {s} of {S} “{name}”",
    "why_intro": "What: meeting today's verbs. Why: so the words feel familiar.",
    "why_ex": "What: a verb in a real phrase. Why: it sticks better than in a list.",
    "why_recall": "What: recalling today's words. Why: recalling beats rereading.",
    "why_quiz": "What: checking yourself. Why: every right answer counts toward the weekly test.",
    "why_mix": "What: mixing in earlier verbs. Why: so the old ones don't fade.",
    "why_form": "What: putting a verb into the “I” form. Why: a form in a sentence, not a word in a vacuum.",
    "why_recap": "What: today's recap. Why: see everything you learned today at once.",
    "why_testday": "What: test day. Why: until you pass, the week repeats.",
    "why_quizp": "What: a warm-up before the test.", "why_remind": "What: a reminder about the test.",
    "bonus": "✅ Today's plan is done. 🎲 Bonus {k} of {m}: one more question from this week.",
    "all_done": "That's all for today ✅ My next message comes tomorrow from {a}:00. I write by myself, no need to tap anything.",
    "btn_tidy_on": "Tidy chat: on", "btn_tidy_off": "Tidy chat: off",
})


def T(lang, key):
    return (PT.get(lang) or PT["en"]).get(key) or PT["en"][key]


def main_prompt(lang):
    return T(lang, "hint")


# ---------------------------------------------------------------- цикл недели
def queue(uid, exclude=()):
    u = U(uid)
    skip = set(u["learned"]) | set(u["claimed"]) | set(exclude)
    return [i for i in range(N_VERBS) if i not in skip]


def new_cycle(uid, carry=(), repeat=False):
    u = U(uid)
    pace = u["pace"]
    learned = set(u["learned"])
    carry = [i for i in carry if i not in learned]
    review = False
    if repeat:
        plan = list(carry)
    else:
        size = pace * CYCLE_DAYS
        carry = carry[:size]
        plan = carry + queue(uid, carry)[: max(0, size - len(carry))]
    if not plan and u["learned"]:
        plan = random.sample(u["learned"], min(pace * CYCLE_DAYS, len(u["learned"])))
        review = True
    if not plan and u["claimed"]:                       # всё «знаю»: сначала проверим это
        plan = list(u["claimed"])[: pace * CYCLE_DAYS]
        u["claimed"] = [i for i in u["claimed"] if i not in plan]
    max_days = max(2, math.ceil(len(plan) / pace)) if repeat else CYCLE_DAYS
    u["wkn"] = u.get("wkn", 0) + (0 if repeat else 1)
    u["cycle"] = {"plan": plan, "idx": 0, "days": 0, "max_days": max_days, "state": "deliver", "pack": [],
                  "credited": [], "review": review, "repeat": repeat, "closed": False, "n": u["wkn"]}
    save_course()
    return u["cycle"]


def window(uid):
    return WINDOWS.get(U(uid)["win"], WINDOWS["std"])


def _slot_minutes(uid, today, n):
    """n сообщений равномерно по окну дня; первое сразу в начале окна."""
    a, b = window(uid)
    span = (b - a) * 60
    rnd = random.Random(uid * 7919 + today.toordinal())
    return [a * 60 + int(span * 0.93 * k / max(1, n - 1)) + (0 if k == 0 else rnd.randint(-5, 5)) for k in range(n)] if n > 1 else [a * 60]


def older_verbs(uid, today_ids):
    u = U(uid)
    c = u["cycle"] or {"pack": []}
    return [v for v in c["pack"] if v not in today_ids] + [v for v in u["learned"] if v not in today_ids and v not in c["pack"]]


def day_frames(uid, ids):
    """Список кадров дня. Сколько их, зависит от «плотности» в настройках; порядок всегда один и тот же."""
    u = U(uid)
    n = INTENSITY.get(u["inten"], INTENSITY["normal"])
    ex = [f"ex:{v}" for v in ids]
    quiz = [f"quiz:{v}" for v in ids]
    form = [f"form:{v}" for v in ids]
    mix = ["mix"] if older_verbs(uid, ids) else []
    canon = ["stage"] * 0 + ["intro"] + ex + ["recall"] + quiz + mix + form + ["recap"]
    priority = ["intro", "recall", "recap"] + quiz + ex + mix + form
    chosen = set(priority[:n])
    return [f for f in canon if f in chosen]


def stage_index(c):
    if not c or c.get("review"):
        return None
    plan = sorted(c["plan"])
    base = (plan[len(plan) // 2] if plan else 0) // PACK       # этап по «середине» недели: знакомые глаголы его не сдвигают
    return min(len(STAGES) - 1, base)


def stage_name(s, lang):
    n = STAGES[s]["name"]
    return n.get(lang) or n["en"]


def stage_goal(s, lang):
    g = STAGES[s]["goal"]
    return g.get(lang) or g["en"]


def stage_line(uid):
    lang = user_lang(uid)
    c = U(uid)["cycle"]
    s = stage_index(c)
    if s is None:
        return T(lang, "review_head").split("!")[0] + "!"
    key = "stage_line_test" if c["state"] == "test" else ("repeat_line" if c["repeat"] else "stage_line")
    return T(lang, key).format(s=s + 1, S=len(STAGES), name=stage_name(s, lang), d=min(max(c["days"], 1), c["max_days"]), m=c["max_days"])


def stage_text(uid):
    """Объяснение этапа: цель, что выучить, как проходим, что дальше. Приходит в первый день этапа."""
    lang = user_lang(uid)
    c = U(uid)["cycle"]
    s = stage_index(c)
    verbs = "\n".join(f"• {VERB_COURSE[v][0]} — {v_tr(lang, v)}" for v in c["plan"])
    if s is None:
        return T(lang, "review_head").format(n=len(c["plan"])) + "\n\n" + verbs
    if c["repeat"]:
        return (T(lang, "repeat_head").format(s=s + 1, n=len(c["plan"])) + "\n\n" + verbs + "\n\n"
                + T(lang, "repeat_how").format(m=c["max_days"]))
    parts = [T(lang, "stage_head").format(s=s + 1, S=len(STAGES), name=stage_name(s, lang)),
             T(lang, "stage_goal").format(goal=stage_goal(s, lang)), "",
             T(lang, "stage_learn").format(n=len(c["plan"])), verbs, "",
             T(lang, "stage_how").format(m=c["max_days"], p=int(PASS_RATIO * 100))]
    parts.append(T(lang, "stage_next").format(name=stage_name(s + 1, lang)) if s + 1 < len(STAGES) else T(lang, "stage_last"))
    return "\n".join(parts)


def build_day(uid, today, _depth=0):
    """Создаёт расписание дня."""
    u = U(uid)
    if u["cycle"] is None:
        new_cycle(uid)
    c = u["cycle"]
    if c["state"] == "deliver" and c["closed"]:
        c["state"] = "test"
    ids = []
    if c["state"] == "deliver":
        claimed, learned = set(u["claimed"]), set(u["learned"])
        while len(ids) < u["pace"] and c["idx"] < len(c["plan"]):
            vid = c["plan"][c["idx"]]
            c["idx"] += 1
            if vid not in claimed and (vid not in learned or c["review"]):
                ids.append(vid)
        c["pack"] += ids
        c["days"] += 1
        if c["idx"] >= len(c["plan"]) or c["days"] >= c["max_days"]:
            c["closed"] = True
        if not ids:
            c["state"] = "test"
    if c["state"] == "test" and not c["pack"] and _depth < 3:    # проверять нечего: начинаем следующую неделю
        new_cycle(uid)
        save_course()
        return build_day(uid, today, _depth + 1)
    if c["state"] == "deliver":
        names = day_frames(uid, ids)
        if c["days"] == 1:
            names = ["stage"] + names            # в первый день этапа объясняем, где мы и что надо выучить
    else:
        names = ["testday", "recap", "quizp", "remind"]
    mins = _slot_minutes(uid, today, len(names))
    u["day"] = {"date": today.isoformat(), "state": c["state"], "ids": ids, "frames": [[n, m] for n, m in zip(names, mins)],
                "sent": [], "q": {}, "extra": 0}
    save_course()
    return u["day"]


# ---------------------------------------------------------------- карточки глаголов
def card_line(lang, vid, i=None):
    v = VERB_COURSE[vid]
    head = f"{i}. " if i else ""
    return f"{head}{v[0]} — {v_tr(lang, vid)}\n   {T(lang, 'p_en')} — {v[2]} · {T(lang, 'p_o')} — {v[1]}"


def audio_button(kind, vid, label=None):
    return InlineKeyboardButton(label or AUDIO_BTN, callback_data=f"au:{kind}:{vid}")


def audio_markup_v(vid):
    if edge_tts is None:
        return None
    kb = InlineKeyboardMarkup()
    kb.row(audio_button("v", vid))
    return kb


def intro_text(uid):
    lang = user_lang(uid)
    ids = U(uid)["day"]["ids"]
    body = "\n\n".join(card_line(lang, vid, i + 1) for i, vid in enumerate(ids))
    names = ", ".join(VERB_COURSE[vid][0] for vid in ids)
    return f"{random.choice(KAO_HAPPY)} {T(lang, 'intro')}: {names}\n{stage_line(uid)}\n\n{body}"


def intro_markup(uid):
    lang = user_lang(uid)
    ids = U(uid)["day"]["ids"]
    kb = InlineKeyboardMarkup()
    for vid in ids:
        row = []
        if edge_tts is not None:
            row.append(audio_button("v", vid, f"🔊 {VERB_COURSE[vid][0]}"))
        row.append(InlineKeyboardButton(T(lang, "know"), callback_data=f"kn:{vid}"))
        kb.row(*row)
    kb.row(InlineKeyboardButton(T(lang, "easy"), callback_data="pc:up"),
           InlineKeyboardButton(T(lang, "hard"), callback_data="pc:down"))
    return kb


def send_intro(uid):
    bot.send_message(uid, intro_text(uid), reply_markup=intro_markup(uid))


def send_example(uid):
    lang = user_lang(uid)
    ids = U(uid)["day"]["ids"]
    lines = [f"💬 {T(lang, 'example')}", ""]
    kb = InlineKeyboardMarkup()
    row = []
    for i, vid in enumerate(ids):
        v = VERB_COURSE[vid]
        lines.append(f"{i + 1}. {v[5]}\n   {v_ex_tr(lang, vid)}")
        if edge_tts is not None:
            row.append(audio_button("e", vid, f"🔊 {i + 1}"))
    if row:
        kb.row(*row)
    bot.send_message(uid, "\n".join(lines), reply_markup=kb if row else None)


def _spoiler_lines(lang, vids):
    plain, md = [], []
    for vid in vids:
        v = VERB_COURSE[vid]
        tr = v_tr(lang, vid)
        plain.append(f"{v[0]} — {tr}")
        md.append(f"{escape_markdown_v2(v[0])} — ||{escape_markdown_v2(tr)}||")
    return plain, md


def send_spoilers(uid, title, vids):
    lang = user_lang(uid)
    plain, md = _spoiler_lines(lang, vids)
    try:
        bot.send_message(uid, f"🧠 {escape_markdown_v2(title)}\n\n" + "\n".join(md), parse_mode="MarkdownV2")
    except Exception as e:
        print(f"Ошибка спойлера: {e}")
        bot.send_message(uid, f"🧠 {title}\n\n" + "\n".join(plain))


def send_ex(uid, vid):
    lang = user_lang(uid)
    v = VERB_COURSE[vid]
    kb = None
    if edge_tts is not None:
        kb = InlineKeyboardMarkup()
        kb.row(audio_button("e", vid))
    bot.send_message(uid, f"💬 {v[0]}\n\n{v[5]}\n{v_ex_tr(lang, vid)}", reply_markup=kb)


def send_mix(uid):
    u = U(uid)
    older = older_verbs(uid, u["day"]["ids"])
    if older:
        send_spoilers(uid, T(user_lang(uid), "mix"), random.sample(older, min(4, len(older))))


def send_day_recap(uid):
    lang = user_lang(uid)
    ids = U(uid)["day"]["ids"]
    lines = [f"📌 {T(lang, 'day_recap')}", ""]
    for vid in ids:
        v = VERB_COURSE[vid]
        lines.append(f"{card_line(lang, vid)}\n   {v[5]} — {v_ex_tr(lang, vid)}")
        lines.append("")
    bot.send_message(uid, "\n".join(lines).strip())


def send_form(uid, vid):
    send_quiz(uid, vid, qtype=2)


def send_quizp(uid):
    c = U(uid)["cycle"]
    pool = [v for v in c["pack"] if v not in c["credited"]] or list(c["pack"])
    if pool:
        send_quiz(uid, random.choice(pool))


def send_stage(uid):
    """Сообщение об этапе не исчезает и закрепляется сверху: всегда видно, где мы."""
    u = U(uid)
    old = u.get("pin_id")
    sent = bot.send_message(uid, stage_text(uid), _keep=True)
    mid = getattr(sent, "message_id", None)
    try:
        if old:
            bot.delete_message(uid, old)
        if mid:
            bot.pin_chat_message(uid, mid, disable_notification=True)
    except Exception as e:
        print(f"Не удалось закрепить этап: {e}")
    u["pin_id"] = mid
    save_course()


def send_recall(uid):
    u = U(uid)
    c = u["cycle"]
    today_ids = list(u["day"]["ids"])
    older = [v for v in c["pack"] if v not in today_ids]
    vids = today_ids + random.sample(older, min(2, len(older)))
    send_spoilers(uid, T(user_lang(uid), "recall"), vids)


def send_recap(uid):
    c = U(uid)["cycle"]
    send_spoilers(uid, T(user_lang(uid), "recap"), list(c["pack"]))


# ---------------------------------------------------------------- вопросы
def make_q(uid, vid, qtype, lang):
    """Вопрос по глаголу. Тип 0: венгерский → перевод, 1: перевод → венгерский, 2: вставь форму «я»."""
    v = VERB_COURSE[vid]
    u = U(uid)
    seen = [i for i in set(u["learned"]) | set(u["claimed"]) | set((u["cycle"] or {}).get("pack", [])) if i != vid]
    others = [i for i in range(N_VERBS) if i != vid and i not in seen]
    random.shuffle(seen)
    random.shuffle(others)
    pool = seen + others
    if qtype == 2:
        correct = v[2]
        opts = [v[2], v[1], v[0]]
        prompt = f"{T(lang, 'fill')}\n\n{v_blank(vid)}\n({v_ex_tr(lang, vid)})"
    else:
        texts = []
        correct = v_tr(lang, vid) if qtype == 0 else v[0]
        prompt = f"{v[0]} — ?" if qtype == 0 else f"{v_tr(lang, vid)} — ?"
        for j in pool:
            t = v_tr(lang, j) if qtype == 0 else VERB_COURSE[j][0]
            if t != correct and t not in texts:
                texts.append(t)
            if len(texts) == 2:
                break
        opts = texts + [correct]
    random.shuffle(opts)
    return {"id": vid, "t": qtype, "prompt": prompt, "opts": opts, "ans": opts.index(correct), "done": False}


def send_quiz(uid, vid, qtype=None):
    lang = user_lang(uid)
    u = U(uid)
    q = make_q(uid, vid, random.choice((0, 1, 2)) if qtype is None else qtype, lang)
    u["day"]["q"][str(vid)] = q
    save_course()
    kb = InlineKeyboardMarkup()
    for k, o in enumerate(q["opts"]):
        kb.row(InlineKeyboardButton(o, callback_data=f"qz:{vid}:{k}"))
    bot.send_message(uid, f"🎯 {T(lang, 'quiz')}\n\n{q['prompt']}", reply_markup=kb)


def day_message(uid, frame):
    u = U(uid)
    lang = user_lang(uid)
    if frame == "intro":
        send_intro(uid)
    elif frame == "stage":
        send_stage(uid)
    elif frame.startswith("ex:"):
        send_ex(uid, int(frame.split(":")[1]))
    elif frame == "mix":
        send_mix(uid)
    elif frame == "recap" and u["day"]["state"] == "deliver":
        send_day_recap(uid)
    elif frame.startswith("form:"):
        send_form(uid, int(frame.split(":")[1]))
    elif frame == "quizp":
        send_quizp(uid)
    elif frame == "example":
        send_example(uid)
    elif frame == "recall":
        send_recall(uid)
    elif frame.startswith("quiz:"):
        send_quiz(uid, int(frame.split(":")[1]))
    elif frame == "testday":
        send_test_invite(uid)
    elif frame == "recap":
        send_recap(uid)
    elif frame == "remind":
        bot.send_message(uid, T(lang, "remind"), reply_markup=test_invite_markup(lang))


def test_invite_markup(lang):
    kb = InlineKeyboardMarkup()
    kb.row(InlineKeyboardButton(T(lang, "btn_test"), callback_data="ts:go"))
    return kb


def send_test_invite(uid):
    lang = user_lang(uid)
    c = U(uid)["cycle"]
    bot.send_message(uid, T(lang, "test_day").format(n=len(c["pack"])), reply_markup=test_invite_markup(lang))


# ---------------------------------------------------------------- кнопка «➡️ Дальше»
NEXT_NAMES = {"ru": "➡️ Дальше", "uk": "➡️ Далі", "en": "➡️ Next"}


def next_label(lang):
    return NEXT_NAMES.get(lang) or NEXT_NAMES["en"]


NEXT_BTNS = {v.replace("\ufe0f", "") for v in NEXT_NAMES.values()}


def next_keyboard(lang):
    try:
        kb = ReplyKeyboardMarkup(resize_keyboard=True, is_persistent=True)
    except TypeError:                                   # старая версия библиотеки без is_persistent
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton(text=next_label(lang)))
    return kb


def step_prefix(uid, day, frame):
    """Шапка шага: номер, этап и «что делаем и зачем»."""
    lang = user_lang(uid)
    names = [n for n, _m in day["frames"] if n != "stage"]
    if frame not in names:
        return ""
    k, n = names.index(frame) + 1, len(names)
    head = T(lang, "step_head").format(k=k, n=n, bar="▰" * k + "▱" * (n - k))
    c = U(uid)["cycle"]
    st = stage_index(c) if c else None
    lines = [head]
    if st is not None and not c.get("review"):
        lines.append(T(lang, "stage_line").format(s=st + 1, S=len(STAGES), name=stage_name(st, lang)))
    key = "why_" + frame.split(":")[0]
    if key in PT["en"]:
        lines.append(T(lang, key))
    return "\n".join(lines)


BONUS_MAX_DAY = 3


def go_next(uid, chat_id):
    """«Дальше»: следующий шаг программы прямо сейчас, с пояснением что и зачем."""
    lang = user_lang(uid)
    u = U(uid)
    if u["setup"] != "ready":
        start_onboarding(uid, chat_id)
        return
    if u["test"]:
        text, kb = test_view(uid)
        bot.send_message(chat_id, text, reply_markup=kb)
        return
    now = budapest_now()
    day = u["day"]
    if not day or day["date"] != now.date().isoformat():
        day = build_day(uid, now.date())
    if day["state"] == "test":
        _prefix[chat_id] = T(lang, "go_test")
        reason = start_test(uid, chat_id)
        if reason:
            _prefix.pop(chat_id, None)
            bot.send_message(chat_id, reason)
        return
    if day["state"] == "done":
        bot.send_message(chat_id, T(lang, "tomorrow"))
        return
    skip = day.setdefault("skip", [])
    pending = [n for n, _m in day["frames"] if n not in day["sent"] or n in skip]
    if pending:
        name = pending[0]
        if name not in day["sent"]:
            day["sent"].append(name)
        if name in skip:
            skip.remove(name)
        save_course()
        pre = step_prefix(uid, day, name)
        if pre:
            _prefix[chat_id] = pre
        day_message(uid, name)
        return
    day["extra"] = day.get("extra", 0) + 1
    save_course()
    c = u["cycle"]
    pool = [v for v in (c["pack"] if c else []) if v not in c["credited"]] or list(c["pack"] if c else []) or list(u["learned"])
    if day["extra"] > BONUS_MAX_DAY or not pool:
        bot.send_message(chat_id, T(lang, "all_done").format(a=window(uid)[0]))
        return
    _prefix[chat_id] = T(lang, "bonus").format(k=day["extra"], m=BONUS_MAX_DAY)
    send_quiz(uid, random.choice(pool))


# ---------------------------------------------------------------- чистый чат
TIDY_VOICE_TTL = 240          # голосовое живёт 4 минуты и удаляется
_tidy = {}                    # chat_id -> [(message_id, время, вид)]
_prefix = {}                  # chat_id -> шапка для следующего сообщения
_tidy_lock = threading.Lock()


def tidy_on(chat_id):
    try:
        return chat_id > 0 and bool(U(chat_id)["tidy"])
    except Exception:
        return False


def tidy_track(chat_id, mid, kind="card"):
    if mid is None:
        return
    if kind != "voice" and not tidy_on(chat_id):
        return
    with _tidy_lock:
        _tidy.setdefault(chat_id, []).append((mid, time.time(), kind))


def _tidy_delete(chat_id, mids):
    for mid in mids:
        try:
            bot.delete_message(chat_id, mid)
        except Exception:
            pass


def tidy_sweep_voices():
    now = time.time()
    drops = []
    with _tidy_lock:
        for chat_id, items in _tidy.items():
            old = [it for it in items if it[2] == "voice" and now - it[1] > TIDY_VOICE_TTL]
            if old:
                _tidy[chat_id] = [it for it in items if it not in old]
                drops.append((chat_id, [it[0] for it in old]))
    for chat_id, mids in drops:
        _tidy_delete(chat_id, mids)


_raw_send_message = bot.send_message
_raw_send_voice = bot.send_voice


def _send_message(chat_id, text=None, *a, **kw):
    keep = kw.pop("_keep", False)
    pre = None
    if not keep and isinstance(text, str):
        pre = _prefix.pop(chat_id, None)
        if pre:
            if kw.get("parse_mode") == "MarkdownV2":
                text = escape_markdown_v2(pre) + "\n\n" + text
            else:
                text = pre + "\n\n" + text
    try:
        sent = _raw_send_message(chat_id, text, *a, **kw)
    except Exception:
        if pre:
            _prefix[chat_id] = pre
        raise
    if tidy_on(chat_id):
        with _tidy_lock:
            old = [it[0] for it in _tidy.get(chat_id, [])]
            _tidy[chat_id] = []
        _tidy_delete(chat_id, old)
        if not keep:
            tidy_track(chat_id, getattr(sent, "message_id", None), "card")
    return sent


def _send_voice(chat_id, *a, **kw):
    sent = _raw_send_voice(chat_id, *a, **kw)
    tidy_track(chat_id, getattr(sent, "message_id", None), "voice")
    return sent


bot.send_message = _send_message
bot.send_voice = _send_voice


# ---------------------------------------------------------------- тест
def start_test(uid, chat_id):
    """Начинает тест по неделе. Возвращает текст причины, если начать нельзя."""
    lang = user_lang(uid)
    u = U(uid)
    c = u["cycle"]
    if not c or (not c["pack"]):
        return T(lang, "no_test")
    pack = list(c["pack"])
    credited = [v for v in pack if v in c["credited"]]
    unc = [v for v in pack if v not in c["credited"]]
    sample = random.sample(credited, min(CREDIT_SAMPLE, len(credited)))
    bonus = random.sample(u["claimed"], min(BONUS_MAX, len(u["claimed"])))
    asked = unc + sample
    random.shuffle(asked)
    qs = []
    for vid in asked + bonus:
        q = make_q(uid, vid, random.choice((0, 1, 2)), lang)
        q["kind"] = "bonus" if vid in bonus and vid not in asked else "pack"
        qs.append(q)
    u["test"] = {"qs": qs, "i": 0, "right": [], "wrong": [], "rest": [v for v in credited if v not in sample]}
    save_course()
    text, kb = test_view(uid)
    bot.send_message(chat_id, text, reply_markup=kb)
    return None


def test_view(uid, prefix=""):
    lang = user_lang(uid)
    t = U(uid)["test"]
    q = t["qs"][t["i"]]
    text = f"{T(lang, 'test_head').format(i=t['i'] + 1, n=len(t['qs']))}\n\n{q['prompt']}"
    if prefix:
        text = f"{prefix}\n\n{text}"
    kb = InlineKeyboardMarkup()
    for k, o in enumerate(q["opts"]):
        kb.row(InlineKeyboardButton(o, callback_data=f"ta:{t['i']}:{k}"))
    return text, kb


def check_achievements(uid):
    u = U(uid)
    total = len(u["learned"])
    new = [(n, e) for n, e in MILESTONES if total >= n and f"v{n}" not in u["ach"]]
    for n, _ in new:
        u["ach"].append(f"v{n}")
    if new:
        save_course()
    return new


def finish_test(uid, chat_id):
    lang = user_lang(uid)
    u = U(uid)
    t = u["test"]
    u["test"] = None
    c = u["cycle"]
    right = set(t["right"])
    pack_q = [q for q in t["qs"] if q["kind"] == "pack"]
    bonus_q = [q for q in t["qs"] if q["kind"] == "bonus"]
    pack_right = [q["id"] for q in pack_q if q["id"] in right]
    pack_wrong = [q["id"] for q in pack_q if q["id"] not in right]
    n, r = len(pack_q), len(pack_right)
    need = max(1, math.ceil(PASS_RATIO * n)) if n else 0
    passed = r >= need
    learned = [i for i in u["learned"] if i not in pack_wrong]       # в повторении «не вспомнил» = забыл
    for vid in pack_right + t["rest"]:
        if vid not in learned:
            learned.append(vid)
    # «знаю»: подтверждённые идут в выученные, неподтверждённые возвращаются в программу
    bonus_ids = {q["id"] for q in bonus_q}
    bonus_right = [i for i in bonus_ids if i in right]
    bonus_bad = [i for i in bonus_ids if i not in right]
    for vid in u["claimed"]:
        if vid in bonus_ids and vid in bonus_bad:
            continue
        if vid not in learned:
            learned.append(vid)
    u["claimed"] = []
    u["learned"] = sorted(learned)
    lines = [T(lang, "pass" if passed else "fail").format(r=r, n=n, need=need)]
    if bonus_q:
        lines.append(T(lang, "bonus_ok").format(n=len(bonus_right)))
        if bonus_bad:
            lines.append(T(lang, "bonus_bad").format(n=len(bonus_bad)))
    if pack_wrong:
        lines.append(T(lang, "wrong_list"))
        lines += [f"• {VERB_COURSE[i][0]} — {v_tr(lang, i)}" for i in pack_wrong]
    if c and c.get("review"):
        new_cycle(uid)
        lines.append(T(lang, "next_review"))
    elif passed:
        new_cycle(uid, carry=pack_wrong)
        lines.append(T(lang, "next_review" if u["cycle"]["review"] else "next_new"))
    else:
        new_cycle(uid, carry=pack_wrong, repeat=True)
        lines.append(T(lang, "next_repeat").format(n=len(pack_wrong)))
    if u["day"]:
        u["day"]["frames"] = []                         # сегодня больше ничего не шлём
        u["day"]["state"] = "done"
    save_course()
    bot.send_message(chat_id, "\n".join(lines))
    for n_v, emoji in check_achievements(uid):
        bot.send_message(chat_id, T(lang, "ach").format(n=n_v, e=emoji))


# ---------------------------------------------------------------- прогресс, настройки, онбординг
def progress_text(uid):
    lang = user_lang(uid)
    u = U(uid)
    learned = set(u["learned"])
    c = u["cycle"]
    lines = [T(lang, "progress"), ""]
    if c:
        s = stage_index(c)
        if s is not None:
            lines.append(stage_line(uid))
            lines.append(T(lang, "stage_goal").format(goal=stage_goal(s, lang)))
            left = [v for v in c["plan"] if v not in learned]
            lines.append(T(lang, "stage_left").format(n=len(left)))
            if c["state"] == "test":
                lines.append(T(lang, "test_soon"))
            else:
                lines.append(T(lang, "test_in").format(n=max(1, c["max_days"] - c["days"] + 1)).capitalize())
            if s + 1 < len(STAGES):
                lines.append(T(lang, "stage_next").format(name=stage_name(s + 1, lang)))
            else:
                lines.append(T(lang, "stage_last"))
        else:
            lines.append(stage_line(uid))
    lines += ["", T(lang, "learned").format(n=len(learned), t=N_VERBS)]
    nxt = next((m for m, _ in MILESTONES if m > len(learned)), None)
    lines.append(T(lang, "next_ach").format(n=nxt - len(learned)) if nxt else T(lang, "all_ach"))
    lines += ["", T(lang, "map")]
    cur = stage_index(c) if c else 0
    for si, st in enumerate(STAGES):
        ids = range(si * PACK, min(N_VERBS, (si + 1) * PACK))
        k = sum(1 for i in ids if i in learned)
        if k == len(ids):
            mark = "✅"
        elif cur is None or si == cur:
            mark = "📍"
        else:
            mark = "🔒" if si > (cur or 0) else "📍"
        lines.append(f"{mark} {si + 1}. {stage_name(si, lang)}: {k}/{len(ids)}")
    got = [e for m, e in MILESTONES if len(learned) >= m]
    if got:
        lines += ["", " ".join(got)]
    return "\n".join(lines)


def settings_view(uid):
    lang = user_lang(uid)
    u = U(uid)
    a, b = window(uid)
    text = T(lang, "settings").format(n=u["pace"], a=a, b=b) + f"\n{T(lang, 'intensity')}: {INTENSITY.get(u['inten'], 9)}"
    kb = InlineKeyboardMarkup()
    kb.row(*[InlineKeyboardButton(("• " if u["pace"] == n else "") + T(lang, "pace_btn").format(n=n),
                                  callback_data=f"st:pace:{n}") for n in range(PACE_MIN, PACE_MAX + 1)])
    kb.row(*[InlineKeyboardButton(("• " if u["win"] == k else "") + f"{T(lang, 'win_' + k)} {w[0]}–{w[1]}",
                                  callback_data=f"st:win:{k}") for k, w in WINDOWS.items()])
    kb.row(*[InlineKeyboardButton(("• " if u["inten"] == k else "") + T(lang, "int_" + k),
                                  callback_data=f"st:int:{k}") for k in INTENSITY])
    kb.row(InlineKeyboardButton(T(lang, "btn_toggle_on" if u["next_btn"] else "btn_toggle_off"), callback_data="st:btn:x"))
    kb.row(InlineKeyboardButton(T(lang, "btn_tidy_on" if u["tidy"] else "btn_tidy_off"), callback_data="st:tidy:x"))
    return text, kb


def ob_markup(uid):
    lang = user_lang(uid)
    u = U(uid)
    p = u["page"]
    ids = list(range(p * PACK, min(N_VERBS, (p + 1) * PACK)))
    kb = InlineKeyboardMarkup()
    for i in range(0, len(ids), 2):
        kb.row(*[InlineKeyboardButton(("✅ " if vid in u["marked"] else "") + VERB_COURSE[vid][0],
                                      callback_data=f"ob:t:{vid}") for vid in ids[i:i + 2]])
    row = []
    if (p + 1) * PACK < N_VERBS:
        row.append(InlineKeyboardButton(T(lang, "ob_more"), callback_data="ob:pg"))
    row.append(InlineKeyboardButton(T(lang, "ob_done"), callback_data="ob:done"))
    kb.row(*row)
    return kb


def start_onboarding(uid, chat_id=None):
    lang = user_lang(uid)
    u = U(uid)
    u["setup"], u["marked"], u["page"] = "onb", [], 0
    save_course()
    bot.send_message(chat_id or uid, T(lang, "ob_hi").format(kao=random.choice(KAO_HAPPY)), reply_markup=ob_markup(uid))


def pace_markup(lang, prefix):
    kb = InlineKeyboardMarkup()
    kb.row(*[InlineKeyboardButton(T(lang, "pace_rec" if n == PACE_DEFAULT else "pace_btn").format(n=n),
                                  callback_data=f"{prefix}:{n}") for n in range(PACE_MIN, PACE_MAX + 1)])
    return kb


def finish_setup(uid, pace):
    """Конец знакомства: создаём первую неделю и сразу присылаем первые глаголы."""
    lang = user_lang(uid)
    u = U(uid)
    u["pace"] = pace
    u["claimed"] = sorted(set(u["marked"]))
    u["setup"] = "ready"
    u["cycle"] = None
    save_course()
    new_cycle(uid)
    now = budapest_now()
    day = build_day(uid, now.date())
    now_min = now.hour * 60 + now.minute
    late = [n for n, m in day["frames"] if m <= now_min and n not in ("intro", "stage")]
    day["sent"] = late + ["intro", "stage"]
    day["skip"] = late                                 # эти шаги не пропадут: их отдаст «Дальше»
    save_course()
    u["kb_sent"] = True
    bot.send_message(uid, T(lang, "ob_go"), reply_markup=next_keyboard(lang) if u["next_btn"] else None)
    if day["frames"] and day["frames"][0][0] == "stage":
        send_stage(uid)
    send_intro(uid)


# ---------------------------------------------------------------- обработчики кнопок
@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("ob:"))
def on_onboarding(call):
    uid = call.from_user.id
    lang = user_lang(uid)
    try:
        u = U(uid)
        if u["setup"] != "onb":
            bot.answer_callback_query(call.id, T(lang, "stale"))
            return
        parts = call.data.split(":")
        chat_id, mid = call.message.chat.id, call.message.message_id
        if parts[1] == "t":
            vid = int(parts[2])
            if vid in u["marked"]:
                u["marked"].remove(vid)
            else:
                u["marked"].append(vid)
            save_course()
            bot.edit_message_reply_markup(chat_id, mid, reply_markup=ob_markup(uid))
        elif parts[1] == "pg":
            u["page"] += 1
            save_course()
            bot.edit_message_reply_markup(chat_id, mid, reply_markup=ob_markup(uid))
        elif parts[1] == "done":
            bot.edit_message_reply_markup(chat_id, mid, reply_markup=None)
            bot.send_message(chat_id, T(lang, "ob_pace"), reply_markup=pace_markup(lang, "ob:pace"))
        elif parts[1] == "pace":
            bot.edit_message_reply_markup(chat_id, mid, reply_markup=None)
            finish_setup(uid, max(PACE_MIN, min(PACE_MAX, int(parts[2]))))
        bot.answer_callback_query(call.id)
    except Exception as e:
        print(f"Ошибка знакомства: {e}")
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass


@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("kn:"))
def on_know(call):
    """«Знаю»: глагол уходит из рассылки (проверим в тесте), на его место приходит следующий."""
    uid = call.from_user.id
    lang = user_lang(uid)
    try:
        u = U(uid)
        vid = int(call.data.split(":")[1])
        day, c = u["day"], u["cycle"]
        if not day or day["date"] != budapest_now().date().isoformat() or vid not in day["ids"]:
            bot.answer_callback_query(call.id, T(lang, "stale"))
            return
        pos = day["ids"].index(vid)
        if vid not in u["claimed"]:
            u["claimed"].append(vid)
        if c and vid in c["pack"]:
            c["pack"].remove(vid)
        taken = set(day["ids"]) | set(c["pack"] if c else []) | set(c["plan"] if c else [])
        repl = next((i for i in queue(uid) if i not in taken), None)
        if repl is not None and c is not None:
            day["ids"][pos] = repl
            c["pack"].append(repl)
        else:
            day["ids"].remove(vid)
        save_course()
        bot.answer_callback_query(call.id, T(lang, "know_ok"))
        if day["ids"]:
            bot.edit_message_text(intro_text(uid), call.message.chat.id, call.message.message_id,
                                  reply_markup=intro_markup(uid))
    except Exception as e:
        print(f"Ошибка «знаю»: {e}")
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass


@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("pc:"))
def on_pace(call):
    uid = call.from_user.id
    lang = user_lang(uid)
    try:
        u = U(uid)
        u["pace"] = max(PACE_MIN, min(PACE_MAX, u["pace"] + (1 if call.data == "pc:up" else -1)))
        save_course()
        bot.answer_callback_query(call.id, T(lang, "pace_up").format(n=u["pace"]))
    except Exception as e:
        print(f"Ошибка темпа: {e}")


@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("qz:"))
def on_quiz(call):
    uid = call.from_user.id
    lang = user_lang(uid)
    try:
        u = U(uid)
        _, vid_s, k_s = call.data.split(":")
        vid, k = int(vid_s), int(k_s)
        q = ((u["day"] or {}).get("q") or {}).get(str(vid))
        if not q or q["done"] or not 0 <= k < len(q["opts"]):
            bot.answer_callback_query(call.id, T(lang, "stale"))
            return
        q["done"] = True
        right = k == q["ans"]
        c = u["cycle"]
        if right and c and vid in c["pack"] and vid not in c["credited"]:
            c["credited"].append(vid)
        save_course()
        correct = q["opts"][q["ans"]]
        head = f"✅ {correct}" if right else f"❌ {q['opts'][k]} → ✅ {correct}"
        bot.answer_callback_query(call.id, "✅" if right else "❌")
        bot.edit_message_text(f"{head}\n\n{card_line(lang, vid)}", call.message.chat.id, call.message.message_id,
                              reply_markup=audio_markup_v(vid))
    except Exception as e:
        print(f"Ошибка мини-вопроса: {e}")
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass


@bot.callback_query_handler(func=lambda c: c.data == "ts:go")
def on_test_go(call):
    uid = call.from_user.id
    try:
        all_users.add(uid)
        reason = start_test(uid, call.message.chat.id)
        bot.answer_callback_query(call.id, reason, show_alert=bool(reason))
    except Exception as e:
        print(f"Ошибка запуска теста: {e}")


@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("ta:"))
def on_test_answer(call):
    uid = call.from_user.id
    lang = user_lang(uid)
    try:
        u = U(uid)
        _, i_s, k_s = call.data.split(":")
        i, k = int(i_s), int(k_s)
        t = u["test"]
        if not t or t["i"] != i or not 0 <= k < len(t["qs"][i]["opts"]):
            bot.answer_callback_query(call.id, T(lang, "stale"))
            return
        q = t["qs"][i]
        right = k == q["ans"]
        (t["right"] if right else t["wrong"]).append(q["id"])
        t["i"] += 1
        correct = q["opts"][q["ans"]]
        line = f"✅ {correct}" if right else f"❌ {q['opts'][k]} → ✅ {correct}"
        save_course()
        bot.answer_callback_query(call.id, "✅" if right else "❌")
        chat_id, mid = call.message.chat.id, call.message.message_id
        if t["i"] >= len(t["qs"]):
            bot.edit_message_text(line, chat_id, mid)
            finish_test(uid, chat_id)
        else:
            text, kb = test_view(uid, line)
            bot.edit_message_text(text, chat_id, mid, reply_markup=kb)
    except Exception as e:
        print(f"Ошибка ответа в тесте: {e}")
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass


@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("st:"))
def on_settings(call):
    uid = call.from_user.id
    try:
        u = U(uid)
        _, kind, val = call.data.split(":")
        if kind == "pace":
            u["pace"] = max(PACE_MIN, min(PACE_MAX, int(val)))
        elif kind == "win" and val in WINDOWS:
            u["win"] = val
        elif kind == "int" and val in INTENSITY:
            u["inten"] = val
        elif kind == "tidy":
            u["tidy"] = not u["tidy"]
        elif kind == "btn":
            u["next_btn"] = not u["next_btn"]
            lang = user_lang(uid)
            if u["next_btn"]:
                bot.send_message(call.message.chat.id, T(lang, "next_on"), reply_markup=next_keyboard(lang))
            else:
                bot.send_message(call.message.chat.id, T(lang, "next_off"), reply_markup=ReplyKeyboardRemove())
        save_course()
        text, kb = settings_view(uid)
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=kb)
        bot.answer_callback_query(call.id)
    except Exception as e:
        print(f"Ошибка настроек: {e}")
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass


@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("au:"))
def on_audio(call):
    try:
        _, tag, idx = call.data.split(":")
        v = VERB_COURSE[int(idx)]
        text = {"v": f"{v[0]}. {v[1]}. {v[2]}.", "e": v[5]}.get(tag)
        if text is None:
            bot.answer_callback_query(call.id)
        elif send_speech(call.message.chat.id, text):
            bot.answer_callback_query(call.id)
        else:
            bot.answer_callback_query(call.id, audio_fail_text(user_lang(call.from_user.id)))
    except Exception as e:
        print(f"Ошибка озвучки: {e}")
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass


_OLD_PREFIXES = ("wq:", "nq:", "ls:", "rs:", "rv:", "tt:", "tq:", "md:")


@bot.callback_query_handler(func=lambda c: c.data in ("wn", "nn", "pf") or (c.data or "").startswith(_OLD_PREFIXES))
def on_old_buttons(call):
    """Кнопки из сообщений прежних версий бота."""
    try:
        bot.answer_callback_query(call.id, T(user_lang(call.from_user.id), "old_btn"), show_alert=True)
    except Exception:
        pass


# ---------------------------------------------------------------- команды
@bot.message_handler(commands=["progress"])
def cmd_progress(message):
    uid = message.from_user.id
    all_users.add(uid)
    bot.send_message(message.chat.id, progress_text(uid))


@bot.message_handler(commands=["settings", "modes"])
def cmd_settings(message):
    uid = message.from_user.id
    all_users.add(uid)
    text, kb = settings_view(uid)
    bot.send_message(message.chat.id, text, reply_markup=kb)


@bot.message_handler(commands=["test"])
def cmd_test(message):
    uid = message.from_user.id
    all_users.add(uid)
    reason = start_test(uid, message.chat.id)
    if reason:
        bot.send_message(message.chat.id, reason)


@bot.message_handler(commands=["today"])
def cmd_today(message):
    uid = message.from_user.id
    all_users.add(uid)
    lang = user_lang(uid)
    day = U(uid)["day"]
    if day and day["date"] == budapest_now().date().isoformat() and day["state"] == "deliver" and day["ids"]:
        send_intro(uid)
    elif day and day["state"] in ("test",):
        bot.send_message(uid, T(lang, "today_test"))
    else:
        bot.send_message(uid, T(lang, "today_none").format(h=window(uid)[0]))


@bot.message_handler(commands=["drill"])
def cmd_drill(message):
    uid = message.from_user.id
    all_users.add(uid)
    data = active_trainings.get(uid)
    if not data or data.get("lang") not in LANGUAGES:
        cmd_start(message)
        return
    lang = data["lang"]
    bot.send_message(message.chat.id, T(lang, "drill_hint"), reply_markup=get_verbs_keyboard(lang, data.get("recent", [])))


# ---------------------------------------------------------------- расписание
def tick_user(uid, now):
    lang = user_lang(uid)
    u = U(uid)
    today = now.date()
    now_min = now.hour * 60 + now.minute
    if u["setup"] is None:
        if active_trainings.get(uid, {}).get("lang") and not u.get("prompted") and now_min >= 9 * 60:
            u["prompted"] = True
            start_onboarding(uid)
        return
    if u["setup"] != "ready":
        return
    if u["test"]:
        return                                    # идёт тест: карточки дня его не перебивают
    if u["next_btn"] and not u["kb_sent"] and now_min >= 9 * 60:
        u["kb_sent"] = True
        save_course()
        bot.send_message(uid, T(lang, "next_hint"), reply_markup=next_keyboard(lang))
    a, _b = window(uid)
    day = u["day"]
    if (not day or day["date"] != today.isoformat()) and now_min >= a * 60:
        day = build_day(uid, today)
    if not day:
        return
    for name, minute in list(day["frames"]):
        if name in day["sent"] or now_min < minute:
            continue
        day["sent"].append(name)
        save_course()
        if now_min - minute > CATCHUP and name not in ("intro", "testday"):
            day.setdefault("skip", []).append(name)   # опоздавшее не сыплем, но «Дальше» его отдаст
            continue
        day_message(uid, name)


def scheduler_tick(now):
    tidy_sweep_voices()
    for uid in list(all_users):
        try:
            tick_user(uid, now)
        except Exception as e:
            print(f"Ошибка расписания {uid}: {e}")
        time.sleep(0.02)


def daily_reminders_loop():
    while True:
        try:
            scheduler_tick(budapest_now())
        except Exception as e:
            print(f"Ошибка планировщика: {e}")
        time.sleep(20)


# обработчик «всё остальное» обязан быть последним: telebot берёт первый подходящий
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

        new_state(user_id, selected_lang)
        start_onboarding(user_id, message.chat.id)
        return

    data = active_trainings[user_id]
    lang = data["lang"]
    l_data = LANGUAGES.get(lang, LANGUAGES["ru"])
    recent = data.setdefault("recent", [])

    # --- кнопка выхода
    if text in EXIT_BTNS:
        exit_to_menu(message.chat.id, user_id)
        return

    # --- кнопка «Дальше»
    if text.replace("\ufe0f", "") in NEXT_BTNS and "verb" not in data:
        go_next(user_id, message.chat.id)
        return

    # --- игра с картинками
    if text == CARDS_BTN:
        start_cards(message.chat.id, user_id)
        return

    # --- выбор глагола
    if "verb" not in data:
        found = find_verb(text)
        if not found:
            send_reka_ai(
                message.chat.id, user_id, text, lang,
                reply_markup=main_keyboard(lang, user_id),
            )
            return

        data["verb"] = found
        data["steps"] = build_steps(found[0], l_data)
        data["step"] = 1
        question = make_question(l_data, lang, data["steps"], 1, found)
        hint = hint_for(data["steps"][0], found[0], found[3])
        send_reply(message.chat.id, question, hint, exit_keyboard(lang))
        return

    # --- проверка ответа
    verb = data["verb"]
    hu, ru, en, inf = verb
    steps = data["steps"]
    step = data["step"]
    key = steps[step - 1]

    # --- кнопка 🔊: произносим текущий ответ (тот же, что под спойлером)
    if text == AUDIO_BTN:
        if not send_speech(message.chat.id, hint_for(key, hu, inf)):
            bot.send_message(message.chat.id, audio_fail_text(lang))
        return

    answers = answers_for(key, hu, inf)

    user_text = norm(text)
    if key != "q":
        user_text = strip_pronoun(user_text)

    if user_text in [norm(a) for a in answers]:
        step += 1
        data["step"] = step

        if step > len(steps):
            # глагол пройден целиком
            data.pop("verb", None)
            data.pop("steps", None)
            data["step"] = 0
            recent.append(hu)
            data["recent"] = recent[-RECENT_LIMIT:]
            send_reka_chat(message.chat.id, lang)
            time.sleep(1.0)
            bot.send_message(
                message.chat.id,
                f"{random.choice(KAO_DONE)} {l_data['finish']}",
                reply_markup=get_verbs_keyboard(lang, data["recent"]),
            )
        else:
            if step % 2 == 0:
                praise = f"{l_data['correct']} {random.choice(KAO_HAPPY)}"
            else:
                praise = f"{l_data['fire']} {random.choice(KAO_GREAT)}"
            question = make_question(l_data, lang, steps, step, verb)
            hint = hint_for(steps[step - 1], hu, inf)
            send_reply(message.chat.id, f"{praise}\n\n{question}", hint, exit_keyboard(lang))
    else:
        retry_text = (
            f"{random.choice(KAO_SAD)} "
            + l_data["retry"].format(v=verb_name(lang, ru, en))
        )
        send_reply(message.chat.id, retry_text, hint_for(key, hu, inf), exit_keyboard(lang))


try:   # меню команд (кнопка «/» рядом с полем ввода)
    from telebot.types import BotCommand
    bot.set_my_commands([
        BotCommand("today", "Глаголы дня"),
        BotCommand("progress", "Мой путь и награды"),
        BotCommand("test", "Тест недели"),
        BotCommand("settings", "Темп и время"),
        BotCommand("drill", "Прописи: глагол по формам"),
        BotCommand("cards", "Игра с картинками"),
    ])
except Exception as e:
    print(f"Не удалось задать меню команд: {e}")

threading.Thread(target=daily_reminders_loop, daemon=True).start()

print("Река запущена...")

while True:
    try:
        bot.infinity_polling(timeout=60, long_polling_timeout=60)
    except Exception as e:
        print(f"Ошибка: {e}")
        time.sleep(5)

