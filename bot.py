import asyncio
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
)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
bot = telebot.TeleBot(TELEGRAM_TOKEN)

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


def get_verbs_keyboard(lang="ru", exclude=(), uid=None):
    """До 3 глаголов на выбор. С uid: только открытые на карте (глаголы текущего уровня)."""
    if uid is not None:
        ids = VTRACK.pending_ids(uid) or VTRACK.seen_ids(uid) or list(range(len(VERBS_DATABASE)))
        pool = [VERBS_DATABASE[i] for i in ids if VERBS_DATABASE[i][0] not in exclude] or [VERBS_DATABASE[i] for i in ids]
    else:
        pool = [v for v in VERBS_DATABASE if v[0] not in exclude]
        if len(pool) < 3:
            pool = VERBS_DATABASE
    selected = random.sample(pool, min(3, len(pool)))
    markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    for hu, ru, en, inf in selected:
        markup.add(KeyboardButton(text=f"{hu} ({verb_name(lang, ru, en)})"))
    markup.add(KeyboardButton(text=exit_label(lang)))
    return markup


def find_verb(text, uid=None):
    """Ищем глагол по нажатой кнопке «hall (слышать)» или по точному слову."""
    t = text.lower().strip()
    head = t.split(" (")[0].strip()
    for verb in VERBS_DATABASE:
        hu, ru, en, inf = verb
        if head in (hu, inf) or t in (ru.lower(), en.lower()):
            if uid is not None and not VTRACK.allowed(uid, VERBS_DATABASE.index(verb)):
                return "locked"
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


def main_keyboard(lang):
    """Главное меню: «Глаголы», «Cards» и «Режимы» (что присылать в течение дня)."""
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    row = [KeyboardButton(text=verbs_label(lang))]
    if available_cards():
        row.append(KeyboardButton(text=CARDS_BTN))
    kb.row(*row)
    kb.row(KeyboardButton(text=modes_label(lang)))
    kb.row(KeyboardButton(text=map_label(lang)), KeyboardButton(text=profile_label(lang)))
    return kb


def main_prompt(lang):
    return f"{random.choice(KAO_HAPPY)} {menu_txt(lang)['main']}"


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
        f"{random.choice(KAO_DONE)} {menu_txt(lang)['main']}",
        reply_markup=main_keyboard(lang),
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
        data = new_state(user_id, current_lang)
        bot.send_message(
            message.chat.id,
            main_prompt(current_lang),
            reply_markup=main_keyboard(current_lang),
        )
    else:
        new_state(user_id, None)
        bot.send_message(
            message.chat.id,
            f"{K_LANG} Выберите язык интерфейса / Choose your language:",
            reply_markup=get_language_keyboard(),
        )


# ---------------------------------------------------------- слово дня
# (венгерский, русский, украинский, английский)
WORDS = [
    ("éhes", "голодный", "голодний", "hungry"),
    ("szomjas", "жаждущий", "спраглий", "thirsty"),
    ("meleg", "тёплый", "теплий", "warm"),
    ("hideg", "холодный", "холодний", "cold"),
    ("forró", "горячий", "гарячий", "hot"),
    ("hűvös", "прохладный", "прохолодний", "cool"),
    ("nagy", "большой", "великий", "big"),
    ("kicsi", "маленький", "маленький", "small"),
    ("szép", "красивый", "гарний", "beautiful"),
    ("csúnya", "некрасивый", "негарний", "ugly"),
    ("jó", "хороший", "добрий", "good"),
    ("rossz", "плохой", "поганий", "bad"),
    ("új", "новый", "новий", "new"),
    ("régi", "старый (давний)", "старий (давній)", "old (of things)"),
    ("gyors", "быстрый", "швидкий", "fast"),
    ("lassú", "медленный", "повільний", "slow"),
    ("magas", "высокий", "високий", "tall"),
    ("alacsony", "низкий", "низький", "short / low"),
    ("hosszú", "длинный", "довгий", "long"),
    ("rövid", "короткий", "короткий", "short"),
    ("vastag", "толстый", "товстий", "thick"),
    ("vékony", "тонкий", "тонкий", "thin"),
    ("olcsó", "дешёвый", "дешевий", "cheap"),
    ("drága", "дорогой", "дорогий", "expensive"),
    ("könnyű", "лёгкий", "легкий", "easy / light"),
    ("nehéz", "тяжёлый / трудный", "важкий / складний", "heavy / difficult"),
    ("boldog", "счастливый", "щасливий", "happy"),
    ("szomorú", "грустный", "сумний", "sad"),
    ("fáradt", "усталый", "втомлений", "tired"),
    ("vidám", "весёлый", "веселий", "cheerful"),
    ("okos", "умный", "розумний", "smart"),
    ("buta", "глупый", "дурний", "stupid"),
    ("erős", "сильный", "сильний", "strong"),
    ("gyenge", "слабый", "слабкий", "weak"),
    ("tiszta", "чистый", "чистий", "clean"),
    ("piszkos", "грязный", "брудний", "dirty"),
    ("nyitott", "открытый", "відкритий", "open"),
    ("zárt", "закрытый", "закритий", "closed"),
    ("üres", "пустой", "порожній", "empty"),
    ("tele", "полный", "повний", "full"),
    ("fiatal", "молодой", "молодий", "young"),
    ("öreg", "старый (о человеке)", "старий (про людину)", "old (of people)"),
    ("gazdag", "богатый", "багатий", "rich"),
    ("szegény", "бедный", "бідний", "poor"),
    ("édes", "сладкий", "солодкий", "sweet"),
    ("savanyú", "кислый", "кислий", "sour"),
    ("finom", "вкусный", "смачний", "tasty"),
    ("csendes", "тихий", "тихий", "quiet"),
    ("hangos", "громкий", "гучний", "loud"),
    ("sötét", "тёмный", "темний", "dark"),
    ("világos", "светлый", "світлий", "light / bright"),
    ("puha", "мягкий", "м'який", "soft"),
    ("kemény", "твёрдый", "твердий", "hard"),
    ("száraz", "сухой", "сухий", "dry"),
    ("nedves", "мокрый", "мокрий", "wet"),
    ("egészséges", "здоровый", "здоровий", "healthy"),
    ("beteg", "больной", "хворий", "sick"),
    ("szabad", "свободный", "вільний", "free"),
    ("elfoglalt", "занятой", "зайнятий", "busy"),
    ("kedves", "милый / добрый", "милий / добрий", "kind / sweet"),
    ("bátor", "смелый", "сміливий", "brave"),
    ("mérges", "злой / сердитый", "злий / сердитий", "angry"),
    ("kíváncsi", "любопытный", "допитливий", "curious"),
    ("unalmas", "скучный", "нудний", "boring"),
    ("érdekes", "интересный", "цікавий", "interesting"),
    ("fontos", "важный", "важливий", "important"),
    ("veszélyes", "опасный", "небезпечний", "dangerous"),
    ("biztonságos", "безопасный", "безпечний", "safe"),
    ("mély", "глубокий", "глибокий", "deep"),
    ("széles", "широкий", "широкий", "wide"),
    ("keskeny", "узкий", "вузький", "narrow"),
]
# Режимы «слова дня» (колоды). У каждого режима свой список, свои сообщения в течение дня
# и своя память «знаю» у каждого пользователя. Режимов можно включить несколько сразу.
WORDS_PER_DAY = 14            # прилагательные: сколько сообщений в день (меняй как хочешь)
NUMBERS_PER_DAY = 10          # числа: сколько сообщений в день
WORD_START = 8 * 60           # с 08:00 (минуты от полуночи)
WORD_END = 22 * 60 + 30       # до 22:30
WORD_MIN_GAP = 25             # минимум минут между сообщениями одного режима
MODES_MIN_GAP = 8             # минимум минут между сообщениями РАЗНЫХ режимов
# вес формата: обычное «hu — tr» самое частое
WORD_FORMATS = [("plain", 6), ("spoiler", 2), ("quiz", 2), ("example", 2), ("big", 1.5), ("old", 1.5)]
OLD_LABELS = {
    1: {"ru": "вчера", "uk": "вчора", "en": "yesterday"},
    3: {"ru": "3 дня назад", "uk": "3 дні тому", "en": "3 days ago"},
    7: {"ru": "неделю назад", "uk": "тиждень тому", "en": "a week ago"},
}
QUIZ_RIGHT = {"ru": "верно", "uk": "вірно", "en": "correct"}
DEFAULT_MODES = ["adj"]       # у кого режимы не настроены, всё как раньше: только прилагательные


def _num(n, hu):
    """Число в том же виде, что и слово: (венгерский, ru, uk, en). Перевод везде один: цифры."""
    return (hu, str(n), str(n), str(n))


# Числа идут по порядку: сначала десятки, потом сотни и цены в форинтах.
NUMBERS = [
    _num(10, "tíz"), _num(20, "húsz"), _num(30, "harminc"), _num(40, "negyven"), _num(50, "ötven"),
    _num(60, "hatvan"), _num(70, "hetven"), _num(80, "nyolcvan"), _num(90, "kilencven"),
    _num(100, "száz"), _num(200, "kétszáz"), _num(300, "háromszáz"), _num(500, "ötszáz"),
    _num(1000, "ezer"), _num(2000, "kétezer"), _num(5000, "ötezer"),
]


# ---------------------------------------------------------------- прогресс: карта, уровни, тесты
# Каждая дорожка (прилагательные, числа, глаголы) разбита на уровни по несколько слов.
# Слова уровня идут по одному в день, в конце контрольный тест: сдал, открывается следующий
# уровень; не сдал, повторяем то, что не получилось, а новые слова закрыты.
PROGRESS_FILE = os.path.join(DATA_DIR, "progress.json")
LEVEL_SIZE = {"adj": 5, "num": 4, "verbs": 3}   # сколько слов (чисел, глаголов) в одном уровне карты
PASS_RATIO = 0.75                               # доля верных ответов, нужная для сдачи теста
TEST_COOLDOWN = 30 * 60                         # после неудачи пересдача через 30 минут (секунды)
TEST_OPTIONS = 3                                # вариантов ответа на вопрос теста
_prog_lock = threading.RLock()


def _load_progress():
    try:
        with open(PROGRESS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


_progress = _load_progress()   # {user_id: {"tracks": {...}, "ach": [...], "test": {...} или None}}


def save_progress():
    with _prog_lock:
        try:
            tmp = PROGRESS_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(_progress, f, ensure_ascii=False)
            os.replace(tmp, PROGRESS_FILE)
        except Exception as e:
            print(f"Не удалось сохранить progress.json: {e}")


def prog(user_id):
    with _prog_lock:
        u = _progress.setdefault(str(user_id), {})
        u.setdefault("tracks", {})
        u.setdefault("ach", [])
        u.setdefault("test", None)
        return u


def make_levels(n_items, size):
    return [list(range(i, min(i + size, n_items))) for i in range(0, n_items, size)]


class Track:
    """Дорожка на карте: уровни по несколько слов. Следующий уровень открывается только после теста."""

    def __init__(self, key, items):
        self.key = key
        self.items = items
        self.levels = make_levels(len(items), LEVEL_SIZE[key])

    def index(self, item):
        return self.items.index(item)

    def st(self, uid):
        with _prog_lock:
            t = prog(uid)["tracks"].setdefault(self.key, {})
            for k, v in (("passed", 0), ("missed", []), ("last_try", 0), ("tries", 0)):
                t.setdefault(k, v)
            return t

    def passed(self, uid):
        return self.st(uid)["passed"]

    def finished(self, uid):
        return self.passed(uid) >= len(self.levels)

    def current_ids(self, uid):
        p = self.passed(uid)
        return self.levels[p] if p < len(self.levels) else []

    def learned_ids(self, uid):
        return [i for lvl in self.levels[: self.passed(uid)] for i in lvl]

    def seen_ids(self, uid):
        """Всё, что пользователь уже видел: выученные слова и слова текущего уровня."""
        return self.learned_ids(uid) + list(self.current_ids(uid))

    def test_ready(self, uid):
        raise NotImplementedError

    def wait_left(self, uid):
        """Сколько секунд ждать до пересдачи (0, если можно сдавать)."""
        s = self.st(uid)
        if s["tries"] <= 0:
            return 0
        return max(0, int(s["last_try"] + TEST_COOLDOWN - time.time()))

    def _reset_level(self, s):
        pass

    def _after_fail(self, s):
        pass

    def pass_level(self, uid):
        with _prog_lock:
            s = self.st(uid)
            s["passed"] += 1
            s["missed"], s["tries"], s["last_try"] = [], 0, 0
            self._reset_level(s)
            save_progress()

    def fail_level(self, uid, wrong_ids):
        with _prog_lock:
            s = self.st(uid)
            s["missed"] = sorted(set(wrong_ids))
            s["tries"] += 1
            s["last_try"] = time.time()
            self._after_fail(s)
            save_progress()


class Deck(Track):
    """Режим «слова дня»: слова уровня идут по одному в день, повторяются весь день в разных форматах."""

    def __init__(self, key, tag, items, per_day, slot_seed=0, fmt_seed=0):
        super().__init__(key, items)
        self.tag = tag            # "w" / "n": начало callback_data и ключ отправленных слотов
        self.per_day = per_day
        self.slot_seed = slot_seed
        self.fmt_seed = fmt_seed

    def _reset_level(self, s):
        # новый уровень начинается сегодня же, с его первого слова
        s["pos"], s["date"] = 0, budapest_now().date().isoformat()

    def _day_state(self, uid, day):
        """Каждый новый день показываем следующее слово уровня."""
        s = self.st(uid)
        iso = day.isoformat()
        s.setdefault("pos", 0)
        if s.get("date") != iso:
            if s.get("date") is not None and s["pos"] < len(self.current_ids(uid)):
                s["pos"] += 1
            s["date"] = iso
            save_progress()
        return s

    def test_ready(self, uid):
        ids = self.current_ids(uid)
        return bool(ids) and self.st(uid).get("pos", 0) >= len(ids)

    def user_item(self, uid, day):
        """Слово дня. Когда слова уровня кончились, повторяем их (сначала те, что не получились)."""
        with _prog_lock:
            ids = self.current_ids(uid)
            if not ids:                       # все уровни пройдены: любое слово для повторения
                return random.choice(self.items)
            s = self._day_state(uid, day)
            if s["pos"] < len(ids):
                return self.items[ids[s["pos"]]]
            pool = [i for i in s["missed"] if i in ids] or ids
            return self.items[random.choice(pool)]

    def skip(self, uid, day):
        """«Знаю это слово»: к следующему слову уровня. None, если слова кончились и пора на тест."""
        with _prog_lock:
            ids = self.current_ids(uid)
            if not ids:
                return random.choice(self.items)
            s = self._day_state(uid, day)
            if s["pos"] < len(ids):
                s["pos"] += 1
                save_progress()
            if s["pos"] >= len(ids):
                return None
            return self.items[ids[s["pos"]]]

    def review_item(self, uid):
        ids = self.learned_ids(uid)
        return self.items[random.choice(ids)] if ids else None

    def base_slots(self, day):
        """Время сообщений на день: случайное, но одинаковое после перезапуска. Минуты от полуночи."""
        rnd = random.Random(day.toordinal() * 7919 + self.slot_seed)
        span = WORD_END - WORD_START
        n = self.per_day
        free = span - (n - 1) * WORD_MIN_GAP
        cuts = sorted(rnd.randint(0, free) for _ in range(n))
        return [WORD_START + c + i * WORD_MIN_GAP for i, c in enumerate(cuts)]

    def fmt(self, day, i):
        rnd = random.Random(day.toordinal() * 104729 + i + self.fmt_seed)
        names = [f for f, _ in WORD_FORMATS]
        weights = [w for _, w in WORD_FORMATS]
        return rnd.choices(names, weights)[0]


class VerbTrack(Track):
    """Глаголы: уровень = несколько глаголов. Их проходят в тренировке, потом контрольный тест."""

    def st(self, uid):
        s = super().st(uid)
        s.setdefault("done", [])
        return s

    def pending_ids(self, uid):
        done = set(self.st(uid)["done"])
        return [i for i in self.current_ids(uid) if i not in done]

    def test_ready(self, uid):
        return bool(self.current_ids(uid)) and not self.pending_ids(uid)

    def mark_done(self, uid, idx):
        with _prog_lock:
            s = self.st(uid)
            if idx in self.current_ids(uid) and idx not in s["done"]:
                s["done"].append(idx)
                save_progress()

    def allowed(self, uid, idx):
        return self.finished(uid) or idx in self.seen_ids(uid)

    def _reset_level(self, s):
        s["done"] = []

    def _after_fail(self, s):
        # глаголы, в которых ошибся, снова нужно пройти
        s["done"] = [d for d in s["done"] if d not in s["missed"]]


ADJ = Deck("adj", "w", WORDS, WORDS_PER_DAY)
NUM = Deck("num", "n", NUMBERS, NUMBERS_PER_DAY, slot_seed=31337, fmt_seed=5000)
VTRACK = VerbTrack("verbs", VERBS_DATABASE)
DECKS = {"adj": ADJ, "num": NUM}                  # порядок = порядок кнопок в настройках
DECK_BY_TAG = {d.tag: d for d in DECKS.values()}
TRACKS = {"adj": ADJ, "num": NUM, "verbs": VTRACK}
TRACK_ORDER = ["adj", "num", "verbs"]
TOTAL_WORDS = sum(len(t.items) for t in TRACKS.values())


# ---------- выученные слова и достижения
MILESTONES = [(n, e) for n, e in ((10, "🌱"), (25, "🥉"), (50, "🥈"), (75, "🥇"), (100, "💎"), (TOTAL_WORDS, "👑"))
              if n <= TOTAL_WORDS]


def learned_counts(uid):
    return {k: len(t.learned_ids(uid)) for k, t in TRACKS.items()}


def learned_total(uid):
    return sum(learned_counts(uid).values())


def check_achievements(uid):
    """Открывает новые достижения за выученные слова. Возвращает [(число слов, эмодзи), ...]."""
    with _prog_lock:
        total = learned_total(uid)
        have = set(prog(uid)["ach"])
        new = [(n, e) for n, e in MILESTONES if total >= n and f"w{n}" not in have]
        if new:
            prog(uid)["ach"] += [f"w{n}" for n, _ in new]
            save_progress()
        return new


# ---------- тексты (ru, uk, en; остальные языки получают английский)
PT = {
    "ru": {
        "map_title": "🗺 Карта Réka", "level": "уровень {n} из {t}", "today": "Сегодня: слово {n} из {t}",
        "verbs_progress": "Пройдено глаголов: {n} из {t}", "test_ready": "🎯 Пора на контрольную!",
        "track_done": "🏁 все уровни пройдены", "learned": "📚 Выучено слов: {n} из {t}",
        "next_ach": "🏆 До следующей награды: {n}", "all_ach": "🏆 Все награды получены",
        "profile_title": "🏆 Профиль", "ach_title": "Достижения:", "words_noun": "слов",
        "ach_all": "Все {n} слов выучены",
        "invite": "🎯 Контрольная: {name}, уровень {n}\n\nСдашь — откроются новые слова. "
                  "Не сдашь — повторим то, что не получилось.",
        "btn_test": "🎯 Пройти тест", "test_menu": "Какой тест пройдём?", "test_head": "🎯 {name} · уровень {n}",
        "q_of": "Вопрос {i} из {n}", "wait": "Пересдача через {m} мин. Пока повтори слова.",
        "no_test": "Тестов пока нет: все уровни пройдены 🏁", "stale": "Этот вопрос уже неактуален",
        "pass": "✅ Тест сдан: {s} из {n}! Уровень {l} пройден.",
        "pass_words": "Открыт уровень {l}: новые слова скоро появятся.",
        "pass_verbs": "Новые глаголы уже ждут в разделе «Глаголы».",
        "pass_last": "🏁 Это был последний уровень!",
        "fail": "❌ Тест не сдан: {s} из {n}, нужно {need}. Повторим то, что не получилось:",
        "fail_words": "Эти слова пришлю ещё раз в течение дня.",
        "fail_verbs": "Эти глаголы снова открыты в разделе «Глаголы».",
        "retry_in": "Пересдать можно через {m} мин.", "ach_unlock": "🏆 Новое достижение: {title}!",
        "locked_verb": "🔒 Этот глагол пока закрыт. Пройди глаголы текущего уровня и сдай тест.",
        "verbs_done": "Глаголы уровня пройдены!",
        "verbs_ready": "🎯 Контрольная по глаголам готова. Сдашь — откроются новые.",
        "review": "Повторим",
    },
    "uk": {
        "map_title": "🗺 Карта Réka", "level": "рівень {n} з {t}", "today": "Сьогодні: слово {n} з {t}",
        "verbs_progress": "Пройдено дієслів: {n} з {t}", "test_ready": "🎯 Час на контрольну!",
        "track_done": "🏁 усі рівні пройдено", "learned": "📚 Вивчено слів: {n} з {t}",
        "next_ach": "🏆 До наступної нагороди: {n}", "all_ach": "🏆 Усі нагороди отримано",
        "profile_title": "🏆 Профіль", "ach_title": "Досягнення:", "words_noun": "слів",
        "ach_all": "Усі {n} слів вивчено",
        "invite": "🎯 Контрольна: {name}, рівень {n}\n\nЗдаси — відкриються нові слова. "
                  "Не здаси — повторимо те, що не вийшло.",
        "btn_test": "🎯 Пройти тест", "test_menu": "Який тест пройдемо?", "test_head": "🎯 {name} · рівень {n}",
        "q_of": "Питання {i} з {n}", "wait": "Перездача через {m} хв. Поки повтори слова.",
        "no_test": "Тестів поки немає: усі рівні пройдено 🏁", "stale": "Це питання вже неактуальне",
        "pass": "✅ Тест здано: {s} з {n}! Рівень {l} пройдено.",
        "pass_words": "Відкрито рівень {l}: нові слова скоро з'являться.",
        "pass_verbs": "Нові дієслова вже чекають у розділі «Дієслова».",
        "pass_last": "🏁 Це був останній рівень!",
        "fail": "❌ Тест не здано: {s} з {n}, потрібно {need}. Повторимо те, що не вийшло:",
        "fail_words": "Ці слова надішлю ще раз протягом дня.",
        "fail_verbs": "Ці дієслова знову відкриті в розділі «Дієслова».",
        "retry_in": "Перездати можна через {m} хв.", "ach_unlock": "🏆 Нове досягнення: {title}!",
        "locked_verb": "🔒 Це дієслово поки закрите. Пройди дієслова поточного рівня й здай тест.",
        "verbs_done": "Дієслова рівня пройдено!",
        "verbs_ready": "🎯 Контрольна з дієслів готова. Здаси — відкриються нові.",
        "review": "Повторимо",
    },
    "en": {
        "map_title": "🗺 Réka's map", "level": "level {n} of {t}", "today": "Today: word {n} of {t}",
        "verbs_progress": "Verbs done: {n} of {t}", "test_ready": "🎯 Time for the test!",
        "track_done": "🏁 all levels done", "learned": "📚 Words learned: {n} of {t}",
        "next_ach": "🏆 Next reward in: {n}", "all_ach": "🏆 All rewards unlocked",
        "profile_title": "🏆 Profile", "ach_title": "Achievements:", "words_noun": "words",
        "ach_all": "All {n} words learned",
        "invite": "🎯 Test: {name}, level {n}\n\nPass it and new words unlock. "
                  "Fail and we repeat what went wrong.",
        "btn_test": "🎯 Take the test", "test_menu": "Which test shall we take?", "test_head": "🎯 {name} · level {n}",
        "q_of": "Question {i} of {n}", "wait": "Retake in {m} min. Review the words meanwhile.",
        "no_test": "No tests right now: all levels are done 🏁", "stale": "This question is no longer active",
        "pass": "✅ Test passed: {s} of {n}! Level {l} complete.",
        "pass_words": "Level {l} is open: new words are coming soon.",
        "pass_verbs": "New verbs are waiting in the Verbs section.",
        "pass_last": "🏁 That was the last level!",
        "fail": "❌ Test failed: {s} of {n}, need {need}. Let's repeat what went wrong:",
        "fail_words": "I'll send these words again during the day.",
        "fail_verbs": "These verbs are open again in the Verbs section.",
        "retry_in": "You can retake it in {m} min.", "ach_unlock": "🏆 New achievement: {title}!",
        "locked_verb": "🔒 This verb is still locked. Finish this level's verbs and pass the test.",
        "verbs_done": "Level verbs done!",
        "verbs_ready": "🎯 The verbs test is ready. Pass it to unlock new ones.",
        "review": "Review",
    },
}
TRACK_NAMES = {
    "adj": {"ru": "Прилагательные", "uk": "Прикметники", "en": "Adjectives"},
    "num": {"ru": "Числа", "uk": "Числа", "en": "Numbers"},
    "verbs": {"ru": "Глаголы", "uk": "Дієслова", "en": "Verbs"},
}
TRACK_ICONS = {"adj": "🌿", "num": "🔢", "verbs": "🏃"}
MAP_NAMES = {"ru": "Карта", "uk": "Карта", "en": "Map"}
PROFILE_NAMES = {"ru": "Профиль", "uk": "Профіль", "en": "Profile"}


def TXT(lang, key):
    return (PT.get(lang) or PT["en"]).get(key) or PT["en"][key]


def track_name(key, lang):
    return TRACK_NAMES[key].get(lang) or TRACK_NAMES[key]["en"]


def _label(prefix, names, lang):
    return f"{prefix} {names.get(lang) or names['en']}"


def map_label(lang):
    return _label("🗺", MAP_NAMES, lang)


def profile_label(lang):
    return _label("🏆", PROFILE_NAMES, lang)


# в сравнении убираем невидимый знак эмодзи (U+FE0F): Telegram может его потерять
MAP_BTNS = {map_label(lg).replace("️", "") for lg in MENU_TXT}
PROFILE_BTNS = {profile_label(lg).replace("️", "") for lg in MENU_TXT}


# ---------- экран карты и профиля
def test_markup(lang, key):
    kb = InlineKeyboardMarkup()
    kb.row(InlineKeyboardButton(TXT(lang, "btn_test"), callback_data=f"tt:{key}"))
    return kb


def map_text(uid, lang):
    lines = [TXT(lang, "map_title"), ""]
    for key in TRACK_ORDER:
        tr = TRACKS[key]
        p, n = tr.passed(uid), len(tr.levels)
        status = TXT(lang, "track_done") if tr.finished(uid) else TXT(lang, "level").format(n=p + 1, t=n)
        lines.append(f"{TRACK_ICONS[key]} {track_name(key, lang)}: {status}")
        lines.append("".join("✅" if i < p else ("📍" if i == p else "🔒") for i in range(n)))
        if not tr.finished(uid):
            size = len(tr.current_ids(uid))
            if tr.test_ready(uid):
                lines.append(TXT(lang, "test_ready"))
            elif key == "verbs":
                lines.append(TXT(lang, "verbs_progress").format(n=len(tr.st(uid)["done"]), t=size))
            else:
                lines.append(TXT(lang, "today").format(n=min(tr.st(uid).get("pos", 0), size - 1) + 1, t=size))
        lines.append("")
    total = learned_total(uid)
    lines.append(TXT(lang, "learned").format(n=total, t=TOTAL_WORDS))
    nxt = next((n for n, _ in MILESTONES if n > total), None)
    lines.append(TXT(lang, "next_ach").format(n=nxt - total) if nxt else TXT(lang, "all_ach"))
    return "\n".join(lines)


def map_markup(uid, lang):
    kb = InlineKeyboardMarkup()
    for key in TRACK_ORDER:
        tr = TRACKS[key]
        if not tr.finished(uid) and tr.test_ready(uid):
            kb.row(InlineKeyboardButton(f"🎯 {track_name(key, lang)}", callback_data=f"tt:{key}"))
    kb.row(InlineKeyboardButton(profile_label(lang), callback_data="pf"))
    return kb


def show_map(chat_id, uid, lang):
    bot.send_message(chat_id, map_text(uid, lang), reply_markup=map_markup(uid, lang))


def achievement_title(n, lang):
    return TXT(lang, "ach_all").format(n=n) if n == TOTAL_WORDS else f"{n} {TXT(lang, 'words_noun')}"


def profile_text(uid, lang):
    total = learned_total(uid)
    counts = learned_counts(uid)
    lines = [TXT(lang, "profile_title"), "", TXT(lang, "learned").format(n=total, t=TOTAL_WORDS)]
    for key in TRACK_ORDER:
        lines.append(f"   {TRACK_ICONS[key]} {track_name(key, lang)}: {counts[key]}/{len(TRACKS[key].items)}")
    lines += ["", TXT(lang, "ach_title")]
    for n, e in MILESTONES:
        lines.append(f"{e} {achievement_title(n, lang)}" if total >= n else f"🔒 {achievement_title(n, lang)}")
    return "\n".join(lines)


def show_profile(chat_id, uid, lang):
    bot.send_message(chat_id, profile_text(uid, lang))


def send_test_invite(uid, key):
    lang = user_lang(uid)
    tr = TRACKS[key]
    bot.send_message(
        uid, TXT(lang, "invite").format(name=track_name(key, lang), n=tr.passed(uid) + 1),
        reply_markup=test_markup(lang, key),
    )


# ---------- контрольные тесты
VERB_TEST_GROUPS = [["ő", "én", "te", "mi", "ők"], ["past", "past_te"], ["f_ő", "f_én", "f_te", "f_ők"]]
VERB_TEST_KEYS = ["ő", "én", "te", "mi", "ők", "past", "f_én", "f_ők"]   # из них выбираем вопросы


def _word_questions(uid, deck, lang):
    seen = deck.seen_ids(uid)
    qs = []
    for i in deck.current_ids(uid):
        w = deck.items[i]
        to_hu = random.random() < 0.5            # то перевод -> слово, то слово -> перевод
        correct = w[0] if to_hu else tr_of(lang, w)
        prompt = f"{tr_of(lang, w)} — ?" if to_hu else f"{w[0]} — ?"
        cand = [j for j in seen if j != i]
        random.shuffle(cand)
        cand += [j for j in range(len(deck.items)) if j not in seen]    # запасной вариант: любые слова
        texts = []
        for j in cand:
            t = deck.items[j][0] if to_hu else tr_of(lang, deck.items[j])
            if t != correct and t not in texts:
                texts.append(t)
            if len(texts) == TEST_OPTIONS - 1:
                break
        opts = texts + [correct]
        random.shuffle(opts)
        qs.append({"id": i, "q": prompt, "opts": opts, "ans": opts.index(correct)})
    return qs


def _verb_questions(uid, lang):
    l_data = LANGUAGES.get(lang, LANGUAGES["ru"])
    cut = len(l_data["step"].format(n=1, t=1))
    qs = []
    for i in VTRACK.current_ids(uid):
        verb = VERBS_DATABASE[i]
        hu, inf = verb[0], verb[3]
        for key in random.sample(VERB_TEST_KEYS, 2):
            correct = answers_for(key, hu, inf)[0]
            group = next(g for g in VERB_TEST_GROUPS if key in g)
            same = [k for k in group if k != key]
            other = [k for g in VERB_TEST_GROUPS for k in g if k not in group]
            random.shuffle(same)
            random.shuffle(other)
            texts = []
            for k in same + other:                 # сначала формы из той же группы (время), потом любые
                a = answers_for(k, hu, inf)[0]
                if a != correct and a not in texts:
                    texts.append(a)
                if len(texts) == TEST_OPTIONS - 1:
                    break
            opts = texts + [correct]
            random.shuffle(opts)
            q = make_question(l_data, lang, [key], 1, verb)[cut:]
            qs.append({"id": i, "q": q, "opts": opts, "ans": opts.index(correct)})
    return qs


def _question_view(uid, test, prefix=""):
    lang = user_lang(uid)
    tr = TRACKS[test["track"]]
    i, qs = test["i"], test["qs"]
    head = TXT(lang, "test_head").format(name=track_name(test["track"], lang), n=tr.passed(uid) + 1)
    text = f"{head}\n{TXT(lang, 'q_of').format(i=i + 1, n=len(qs))}\n\n{qs[i]['q']}"
    if prefix:
        text = f"{prefix}\n\n{text}"
    kb = InlineKeyboardMarkup()
    for oi, o in enumerate(qs[i]["opts"]):
        kb.row(InlineKeyboardButton(o, callback_data=f"tq:{i}:{oi}"))
    return text, kb


def start_test(uid, chat_id, key):
    """Запускает тест по дорожке. Возвращает причину отказа текстом или None, если тест начат."""
    lang = user_lang(uid)
    tr = TRACKS.get(key)
    if tr is None:
        return TXT(lang, "stale")
    with _prog_lock:
        if tr.finished(uid):
            return TXT(lang, "no_test")
        left = tr.wait_left(uid)
        if left > 0:
            return TXT(lang, "wait").format(m=max(1, (left + 59) // 60))
        qs = _verb_questions(uid, lang) if key == "verbs" else _word_questions(uid, tr, lang)
        if not qs:
            return TXT(lang, "no_test")
        test = {"track": key, "qs": qs, "i": 0, "score": 0, "wrong": []}
        prog(uid)["test"] = test          # незавершённый прежний тест просто заменяется
        save_progress()
        text, kb = _question_view(uid, test)
    bot.send_message(chat_id, text, reply_markup=kb)
    return None


def _item_label(key, idx, lang):
    if key == "verbs":
        hu, ru, en, inf = VERBS_DATABASE[idx]
        return f"{inf} — {verb_name(lang, ru, en)}"
    return word_text(lang, TRACKS[key].items[idx])


def finish_test(uid, chat_id):
    lang = user_lang(uid)
    with _prog_lock:
        test = prog(uid)["test"]
        if not test:
            return
        prog(uid)["test"] = None
        key = test["track"]
        tr = TRACKS[key]
        n, s = len(test["qs"]), test["score"]
        need = max(1, math.ceil(PASS_RATIO * n))
        ok = s >= need
        level = tr.passed(uid) + 1
        missed = sorted(set(test["wrong"]))
        if ok:
            tr.pass_level(uid)
            new_ach = check_achievements(uid)
        else:
            tr.fail_level(uid, missed)
            new_ach = []
        last = tr.finished(uid)
    if ok:
        parts = [TXT(lang, "pass").format(s=s, n=n, l=level)]
        if last:
            parts.append(TXT(lang, "pass_last"))
        elif key == "verbs":
            parts.append(TXT(lang, "pass_verbs"))
        else:
            parts.append(TXT(lang, "pass_words").format(l=level + 1))
    else:
        parts = [TXT(lang, "fail").format(s=s, n=n, need=need)]
        parts += [f"• {_item_label(key, i, lang)}" for i in missed]
        parts.append(TXT(lang, "fail_verbs" if key == "verbs" else "fail_words"))
        parts.append(TXT(lang, "retry_in").format(m=TEST_COOLDOWN // 60))
    bot.send_message(chat_id, "\n".join(parts))
    for n_words, emoji in new_ach:
        bot.send_message(chat_id, TXT(lang, "ach_unlock").format(title=f"{emoji} {achievement_title(n_words, lang)}"))


@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("tt:"))
def on_test_start(call):
    try:
        uid = call.from_user.id
        all_users.add(uid)
        reason = start_test(uid, call.message.chat.id, call.data[3:])
        bot.answer_callback_query(call.id, reason, show_alert=bool(reason))
    except Exception as e:
        print(f"Ошибка запуска теста: {e}")
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass


@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("tq:"))
def on_test_answer(call):
    uid = call.from_user.id
    lang = user_lang(uid)
    try:
        _, i_s, o_s = call.data.split(":")
        i, o = int(i_s), int(o_s)
        with _prog_lock:
            test = prog(uid)["test"]
            if not test or test["i"] != i or not 0 <= o < len(test["qs"][i]["opts"]):
                bot.answer_callback_query(call.id, TXT(lang, "stale"))
                return
            q = test["qs"][i]
            right = o == q["ans"]
            if right:
                test["score"] += 1
            else:
                test["wrong"].append(q["id"])
            test["i"] += 1
            correct = q["opts"][q["ans"]]
            line = f"✅ {correct}" if right else f"❌ {q['opts'][o]} → ✅ {correct}"
            done = test["i"] >= len(test["qs"])
            save_progress()
            view = None if done else _question_view(uid, test, line)
        bot.answer_callback_query(call.id, "✅" if right else "❌")
        chat_id, mid = call.message.chat.id, call.message.message_id
        if view:
            bot.edit_message_text(view[0], chat_id, mid, reply_markup=view[1])
        else:
            bot.edit_message_text(line, chat_id, mid)     # убираем кнопки у последнего вопроса
            finish_test(uid, chat_id)
    except Exception as e:
        print(f"Ошибка ответа на тест: {e}")
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass


@bot.message_handler(commands=["test"])
def cmd_test(message):
    uid = message.from_user.id
    all_users.add(uid)
    lang = user_lang(uid)
    kb = InlineKeyboardMarkup()
    for key in TRACK_ORDER:
        tr = TRACKS[key]
        if not tr.finished(uid):
            kb.row(InlineKeyboardButton(
                f"🎯 {track_name(key, lang)} · {TXT(lang, 'level').format(n=tr.passed(uid) + 1, t=len(tr.levels))}",
                callback_data=f"tt:{key}"))
    if kb.keyboard:
        bot.send_message(message.chat.id, TXT(lang, "test_menu"), reply_markup=kb)
    else:
        bot.send_message(message.chat.id, TXT(lang, "no_test"))


@bot.message_handler(commands=["map"])
def cmd_map(message):
    uid = message.from_user.id
    all_users.add(uid)
    show_map(message.chat.id, uid, user_lang(uid))


@bot.message_handler(commands=["profile"])
def cmd_profile(message):
    uid = message.from_user.id
    all_users.add(uid)
    show_profile(message.chat.id, uid, user_lang(uid))


@bot.callback_query_handler(func=lambda c: c.data == "pf")
def on_profile_button(call):
    try:
        uid = call.from_user.id
        show_profile(call.message.chat.id, uid, user_lang(uid))
        bot.answer_callback_query(call.id)
    except Exception as e:
        print(f"Ошибка профиля: {e}")


def day_slots(day):
    """Расписание на день по режимам: {ключ режима: [минуты от полуночи]}.
    Сообщения разных режимов не стоят вплотную: второй режим сдвигается от первого."""
    result, taken = {}, []
    for key, deck in DECKS.items():
        slots = []
        for m in deck.base_slots(day):
            for _ in range(MODES_MIN_GAP * 2):
                if all(abs(m - t) >= MODES_MIN_GAP for t in taken):
                    break
                m += 1
            slots.append(m)
        result[key] = slots
        taken += slots
    return result


# ---------- какие режимы включены у пользователя (можно несколько сразу)
MODES_FILE = os.path.join(DATA_DIR, "modes.json")


def _load_modes():
    try:
        with open(MODES_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


_user_modes = _load_modes()   # {user_id: ["adj", "num"]}


def _save_modes():
    try:
        with open(MODES_FILE, "w", encoding="utf-8") as f:
            json.dump(_user_modes, f)
    except Exception as e:
        print(f"Не удалось сохранить modes.json: {e}")


def user_modes(user_id):
    return set(_user_modes.get(str(user_id), DEFAULT_MODES)) & set(DECKS)


def toggle_mode(user_id, key):
    """Включает или выключает режим. Возвращает True, если теперь он включён."""
    modes = user_modes(user_id)
    if key in modes:
        modes.discard(key)
    else:
        modes.add(key)
    _user_modes[str(user_id)] = [k for k in DECKS if k in modes]
    _save_modes()
    return key in modes


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
        return True
    except Exception as e:
        print(f"Ошибка озвучки «{text}»: {e}")
        return False


def audio_fail_text(lang):
    return AUDIO_FAIL.get(lang, AUDIO_FAIL["en"])


def audio_button(deck, w):
    return InlineKeyboardButton(AUDIO_BTN, callback_data=f"au:{deck.tag}:{deck.index(w)}")


def audio_markup(deck, w):
    """Клавиатура только с кнопкой 🔊 (или None, если озвучка не подключена)."""
    if edge_tts is None:
        return None
    kb = InlineKeyboardMarkup()
    kb.row(audio_button(deck, w))
    return kb


CHANGE_BTN = {
    "w": {"ru": "🔄 Знаю, другое слово", "uk": "🔄 Знаю, інше слово", "en": "🔄 I know it, next word"},
    "n": {"ru": "🔄 Знаю, другое число", "uk": "🔄 Знаю, інше число", "en": "🔄 I know it, next number"},
}


def change_markup(lang, deck=ADJ, w=None):
    """Кнопки под словом: 🔊 (если передано слово и озвучка подключена) и «Знаю, другое»."""
    kb = InlineKeyboardMarkup()
    if w is not None and edge_tts is not None:
        kb.row(audio_button(deck, w))
    btn = CHANGE_BTN[deck.tag]
    kb.row(InlineKeyboardButton(btn.get(lang, btn["en"]), callback_data=f"{deck.tag}n"))
    return kb


def tr_of(lang, w):
    return w[1] if lang == "ru" else (w[2] if lang == "uk" else w[3])


def short_tr(lang, w):
    """Перевод без скобок и вариантов после « / » (для примеров)."""
    return tr_of(lang, w).split(" (")[0].split(" / ")[0]


def word_text(lang, w):
    return f"{w[0]} — {tr_of(lang, w)}"


def number_example(lang, w):
    """Фраза с числом: возраст для чисел до 100, цена в форинтах для остальных."""
    n = int(w[1])
    hu = w[0]
    if n <= 100:
        tr = {"ru": f"Мне {n} лет.", "uk": f"Мені {n} років.", "en": f"I'm {n} years old."}
        return f"{hu[:1].upper()}{hu[1:]} éves vagyok.", tr.get(lang, tr["en"])
    tr = {"ru": f"Это {n} форинтов.", "uk": f"Це {n} форинтів.", "en": f"This is {n} forints."}
    return f"Ez {hu} forint.", tr.get(lang, tr["en"])


MODE_LABELS = {
    "adj": {"ru": "Прилагательные", "uk": "Прикметники", "en": "Adjectives"},
    "num": {"ru": "Числа (20, 30, 50…)", "uk": "Числа (20, 30, 50…)", "en": "Numbers (20, 30, 50…)"},
}
MODES_HEAD = {
    "ru": "Что присылать в течение дня? Можно включить оба режима сразу.\n✅ включено, ⬜ выключено",
    "uk": "Що надсилати протягом дня? Можна увімкнути обидва режими одразу.\n✅ увімкнено, ⬜ вимкнено",
    "en": "What should I send during the day? You can turn on both modes at once.\n✅ on, ⬜ off",
}


def mode_label(key, lang):
    labels = MODE_LABELS[key]
    return labels.get(lang, labels["en"])


def modes_markup(user_id, lang):
    on = user_modes(user_id)
    kb = InlineKeyboardMarkup()
    for key in DECKS:
        mark = "✅" if key in on else "⬜"
        kb.row(InlineKeyboardButton(f"{mark} {mode_label(key, lang)}", callback_data=f"md:{key}"))
    return kb


def show_modes(chat_id, user_id, lang):
    bot.send_message(chat_id, MODES_HEAD.get(lang, MODES_HEAD["en"]), reply_markup=modes_markup(user_id, lang))


def budapest_now():
    return datetime.now(BUDAPEST_TZ)


@bot.message_handler(commands=["word"])
def cmd_word(message):
    uid = message.from_user.id
    all_users.add(uid)
    lang = user_lang(uid)
    today = budapest_now().date()
    modes = user_modes(uid) or {"adj"}   # по прямой просьбе показываем слово, даже если всё выключено
    for key, deck in DECKS.items():
        if key in modes:
            w = deck.user_item(uid, today)
            bot.send_message(message.chat.id, word_text(lang, w), reply_markup=change_markup(lang, deck, w))


@bot.message_handler(commands=["newword"])
def cmd_newword(message):
    uid = message.from_user.id
    all_users.add(uid)
    lang = user_lang(uid)
    w = ADJ.skip(uid, budapest_now().date())
    if w is None:
        send_test_invite(uid, "adj")
        return
    bot.send_message(message.chat.id, word_text(lang, w), reply_markup=change_markup(lang, ADJ, w))


@bot.message_handler(commands=["modes"])
def cmd_modes(message):
    uid = message.from_user.id
    all_users.add(uid)
    show_modes(message.chat.id, uid, user_lang(uid))


@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("md:"))
def on_modes_callback(call):
    try:
        uid = call.from_user.id
        key = call.data.split(":", 1)[1]
        if key not in DECKS:
            bot.answer_callback_query(call.id)
            return
        all_users.add(uid)
        lang = user_lang(uid)
        now_on = toggle_mode(uid, key)
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id,
                                      reply_markup=modes_markup(uid, lang))
        bot.answer_callback_query(call.id, f"{'✅' if now_on else '⬜'} {mode_label(key, lang)}")
        if now_on:   # сразу показываем первое слово (число), чтобы было видно, что режим работает
            deck = DECKS[key]
            w = deck.user_item(uid, budapest_now().date())
            bot.send_message(call.message.chat.id, word_text(lang, w), reply_markup=change_markup(lang, deck, w))
    except Exception as e:
        print(f"Ошибка переключения режима: {e}")
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass


# ---------------------------------------------------------- напоминания
REMIND_HOURS = {9: "morning", 14: "day", 20: "evening"}
_sent = set()


def send_reminder(user_id, time_key):
    state = active_trainings.get(user_id, {})
    user_lang = state.get("lang") or "ru"
    l_data = LANGUAGES.get(user_lang, LANGUAGES["ru"])
    # сбрасываем незаконченную тренировку, чтобы кнопки работали
    state.pop("verb", None)
    state.pop("steps", None)
    state["step"] = 0
    state.setdefault("lang", user_lang)
    state.setdefault("recent", [])
    active_trainings[user_id] = state
    try:
        bot.send_message(
            user_id, reka_chat(user_lang), parse_mode="MarkdownV2",
            reply_markup=main_keyboard(user_lang),
        )
    except Exception:
        bot.send_message(
            user_id, f"{l_data[time_key]} {random.choice(KAO_TIME[time_key])}",
            reply_markup=main_keyboard(user_lang),
        )


def send_word(user_id, w, fmt="plain", day=None, deck=ADJ):
    """Сообщение со словом (числом) дня. Без disable_notification: звук включён.
    Клавиатура и тренировка не трогаются."""
    lang = user_lang(user_id)
    hu = w[0]
    markup = change_markup(lang, deck, w)
    if fmt == "spoiler":
        bot.send_message(
            user_id, f"{escape_markdown_v2(hu)} — ||{escape_markdown_v2(tr_of(lang, w))}||",
            parse_mode="MarkdownV2", reply_markup=markup)
    elif fmt == "quiz":
        pool = [deck.items[i] for i in deck.seen_ids(user_id) if deck.items[i] != w]
        pool += [x for x in deck.items if x != w and x not in pool]
        others = pool[:2] if len(deck.seen_ids(user_id)) <= 2 else random.sample(pool[:max(2, len(deck.seen_ids(user_id)) - 1)], 2)
        opts = others + [w]
        random.shuffle(opts)
        kb = InlineKeyboardMarkup()
        kb.row(*[InlineKeyboardButton(o[0], callback_data=f"{deck.tag}q:{deck.index(w)}:{deck.index(o)}")
                 for o in opts])
        btn = CHANGE_BTN[deck.tag]
        kb.row(InlineKeyboardButton(btn.get(lang, btn["en"]), callback_data=f"{deck.tag}n"))
        bot.send_message(user_id, f"{tr_of(lang, w)} — ?", reply_markup=kb)
    elif fmt == "example":
        if deck.key == "num":
            sent_hu, sent_tr = number_example(lang, w)
            text = f"{hu} — {sent_hu}\n({sent_tr})"
        else:
            sent_hu = f"Nagyon {hu}."
            pre = {"ru": "Очень", "uk": "Дуже", "en": "Very"}.get(lang, "Very")
            text = f"{hu} — {sent_hu}\n({pre} {short_tr(lang, w)})"
        bot.send_message(user_id, text, reply_markup=markup)
    elif fmt == "big":
        bot.send_message(user_id, f"*{escape_markdown_v2(hu.upper())}*", parse_mode="MarkdownV2",
                         reply_markup=markup)
    elif fmt == "old" and day is not None:
        n = random.choice([1, 3, 7])
        old = deck.review_item(user_id)
        if old is None or old == w:
            bot.send_message(user_id, word_text(lang, w), reply_markup=markup)
        else:
            label = TXT(lang, "review")
            bot.send_message(user_id, f"{label}: {word_text(lang, old)}",
                             reply_markup=change_markup(lang, deck, old))
    else:
        bot.send_message(user_id, word_text(lang, w), reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data in ("wn", "nn"))
def on_word_change(call):
    try:
        uid = call.from_user.id
        deck = DECK_BY_TAG[call.data[0]]
        lang = user_lang(uid)
        new = deck.skip(uid, budapest_now().date())
        if new is None:       # слова уровня закончились: пора на контрольную
            bot.answer_callback_query(call.id, "🎯")
            send_test_invite(uid, deck.key)
            return
        bot.edit_message_text(word_text(lang, new), call.message.chat.id, call.message.message_id,
                              reply_markup=change_markup(lang, deck, new))
        bot.answer_callback_query(call.id, "🔄")
    except Exception as e:
        print(f"Ошибка смены слова: {e}")
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass


@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith(("wq:", "nq:")))
def on_word_quiz(call):
    try:
        deck = DECK_BY_TAG[call.data[0]]
        _, wi, oi = call.data.split(":")
        w, o = deck.items[int(wi)], deck.items[int(oi)]
        lang = user_lang(call.from_user.id)
        if w == o:
            bot.edit_message_text(f"✅ {word_text(lang, w)}", call.message.chat.id, call.message.message_id,
                                  reply_markup=audio_markup(deck, w))
            bot.answer_callback_query(call.id, "✅")
        else:
            kb = InlineKeyboardMarkup()
            for r in call.message.reply_markup.keyboard:
                row = [b for b in r if b.callback_data != call.data]
                if row:
                    kb.row(*row)
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=kb)
            bot.answer_callback_query(call.id, "❌")
    except Exception as e:
        print(f"Ошибка quiz слова: {e}")
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass


@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("au:"))
def on_audio(call):
    try:
        _, tag, idx = call.data.split(":")
        w = DECK_BY_TAG[tag].items[int(idx)]
        if send_speech(call.message.chat.id, w[0]):
            bot.answer_callback_query(call.id)
        else:
            bot.answer_callback_query(call.id, audio_fail_text(user_lang(call.from_user.id)))
    except Exception as e:
        print(f"Ошибка озвучки слова: {e}")
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass


def scheduler_tick(now):
    today = now.date()
    for k in [k for k in _sent if k[0] != today]:
        _sent.discard(k)

    # обычные напоминания (утро, день, вечер)
    h = now.hour
    if h in REMIND_HOURS and now.minute < 30 and (today, "r", h) not in _sent:
        _sent.add((today, "r", h))
        for user_id in list(all_users):
            try:
                send_reminder(user_id, REMIND_HOURS[h])
            except Exception as e:
                print(f"Ошибка напоминания {user_id}: {e}")
            time.sleep(0.05)

    # слово дня: каждый режим крутится весь день (одно слово или число), форматы чередуются.
    # Сообщения получают только те, у кого этот режим включён: можно включить оба сразу.
    now_min = now.hour * 60 + now.minute
    for key, slots in day_slots(today).items():
        deck = DECKS[key]
        for i, m in enumerate(slots):
            if 0 <= now_min - m < 20 and (today, deck.tag, i) not in _sent:
                _sent.add((today, deck.tag, i))
                fmt = deck.fmt(today, i)
                for user_id in list(all_users):
                    if key not in user_modes(user_id):
                        continue
                    try:
                        send_word(user_id, deck.user_item(user_id, today), fmt, today, deck)
                    except Exception as e:
                        print(f"Ошибка слова дня ({key}) {user_id}: {e}")
                    time.sleep(0.05)

    # приглашение на контрольную: раз в день после 12:00, если все слова уровня показаны
    if now_min >= 12 * 60:
        for user_id in list(all_users):
            for key in TRACK_ORDER:
                tr = TRACKS[key]
                if key in DECKS and key not in user_modes(user_id):
                    continue
                if key == "verbs" and "verbs" not in prog(user_id)["tracks"]:
                    continue
                if tr.finished(user_id) or not tr.test_ready(user_id) or (today, "ti", key, user_id) in _sent:
                    continue
                _sent.add((today, "ti", key, user_id))
                try:
                    send_test_invite(user_id, key)
                except Exception as e:
                    print(f"Ошибка приглашения на тест {user_id}: {e}")


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

        data = new_state(user_id, selected_lang)
        bot.send_message(
            message.chat.id,
            main_prompt(selected_lang),
            reply_markup=main_keyboard(selected_lang),
        )
        return

    data = active_trainings[user_id]
    lang = data["lang"]
    l_data = LANGUAGES.get(lang, LANGUAGES["ru"])
    recent = data.setdefault("recent", [])

    # --- кнопка выхода
    if text in EXIT_BTNS:
        exit_to_menu(message.chat.id, user_id)
        return

    # --- режимы слова дня
    if text.replace("\ufe0f", "") in MODES_BTNS and "verb" not in data:
        show_modes(message.chat.id, user_id, lang)
        return

    # --- раздел «Глаголы»
    if text in VERBS_BTNS and "verb" not in data:
        bot.send_message(
            message.chat.id,
            l_data["choose_btn"],
            reply_markup=get_verbs_keyboard(lang, recent, user_id),
        )
        return

    # --- карта и профиль
    if text.replace("\ufe0f", "") in MAP_BTNS and "verb" not in data:
        show_map(message.chat.id, user_id, lang)
        return
    if text.replace("\ufe0f", "") in PROFILE_BTNS and "verb" not in data:
        show_profile(message.chat.id, user_id, lang)
        return

    # --- игра с картинками
    if text == CARDS_BTN:
        start_cards(message.chat.id, user_id)
        return

    # --- выбор глагола
    if "verb" not in data:
        found = find_verb(text, user_id)
        if found == "locked":
            bot.send_message(message.chat.id, TXT(lang, "locked_verb"),
                             reply_markup=get_verbs_keyboard(lang, recent, user_id))
            return
        if not found:
            send_reka_ai(
                message.chat.id, user_id, text, lang,
                reply_markup=main_keyboard(lang),
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
            VTRACK.mark_done(user_id, VERBS_DATABASE.index(verb))
            prog(user_id)["tracks"].setdefault("verbs", {})
            data["recent"] = recent[-RECENT_LIMIT:]
            send_reka_chat(message.chat.id, lang)
            time.sleep(1.0)
            bot.send_message(
                message.chat.id,
                f"{random.choice(KAO_DONE)} {l_data['finish']}",
                reply_markup=get_verbs_keyboard(lang, data["recent"], user_id),
            )
            if VTRACK.test_ready(user_id) and not VTRACK.finished(user_id):
                bot.send_message(message.chat.id, TXT(lang, "verbs_ready"), reply_markup=test_markup(lang, "verbs"))
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
        BotCommand("word", "Слово дня"),
        BotCommand("newword", "Другое слово дня"),
        BotCommand("modes", "Режимы: прилагательные и числа"),
        BotCommand("map", "Карта прогресса"),
        BotCommand("test", "Контрольный тест"),
        BotCommand("profile", "Профиль и достижения"),
        BotCommand("menu", "Главное меню"),
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
