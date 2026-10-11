from datetime import datetime
import os
import random
import re
import threading
import time
import unicodedata
from zoneinfo import ZoneInfo

from groq import Groq
import telebot
from telebot.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

BUDAPEST_TZ = ZoneInfo("Europe/Budapest")
RECENT_LIMIT = 6

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
    "gondolkodik": (
        "gondolkodom",
        "gondolkodsz",
        "gondolkodunk",
        "gondolkodnak",
        "gondolkodott",
    ),
    "gépel": ("gépelek", "gépelsz", "gépelünk", "gépelnek", "gépelt"),
    "rajzol": ("rajzolok", "rajzolsz", "rajzolunk", "rajzolnak", "rajzolt"),
}

FOG = {"ő": "fog", "én": "fogok", "te": "fogsz", "ők": "fognak"}

PAST_TE = {
    "csinál": "csináltál",
    "olvas": "olvastál",
    "ír": "írtál",
    "eszik": "ettél",
    "iszik": "ittál",
    "lát": "láttál",
    "hall": "hallottál",
    "vesz": "vettél",
    "kér": "kértél",
    "tanul": "tanultál",
    "dolgozik": "dolgoztál",
    "lakik": "laktál",
    "beszél": "beszéltél",
    "tud": "tudtál",
    "akar": "akartál",
    "megy": "mentél",
    "jön": "jöttél",
    "alszik": "aludtál",
    "főz": "főztél",
    "szeret": "szerettél",
    "ad": "adtál",
    "kap": "kaptál",
    "fut": "futottál",
    "nyit": "nyitottál",
    "vár": "vártál",
    "keres": "kerestél",
    "játszik": "játszottál",
    "fizet": "fizettél",
    "segít": "segítettél",
    "tesz": "tettél",
    "gondolkodik": "gondolkodtál",
    "gépel": "gépeltél",
    "rajzol": "rajzoltál",
}

QUESTION_KEYS = {"te", "past_te", "f_te"}
ALT_TE = {"lakik": ["lakol"], "gondolkodik": ["gondolkodol"]}

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

WH_HU = {
    "mit": "mit",
    "hol": "hol",
    "kit": "kit",
    "melyik": "melyiket",
    "hova": "hova",
}

WH_LABELS = {
    "ru": {
        "mit": "что",
        "hol": "где",
        "kit": "кого",
        "melyik": "какой",
        "hova": "куда",
    },
    "en": {
        "mit": "what",
        "hol": "where",
        "kit": "who",
        "melyik": "which one",
        "hova": "where to",
    },
    "es": {
        "mit": "qué",
        "hol": "dónde",
        "kit": "a quién",
        "melyik": "cuál",
        "hova": "adónde",
    },
    "fr": {
        "mit": "quoi",
        "hol": "où",
        "kit": "qui",
        "melyik": "lequel",
        "hova": "vers où",
    },
    "de": {
        "mit": "was",
        "hol": "wo",
        "kit": "wen",
        "melyik": "welchen",
        "hova": "wohin",
    },
    "it": {
        "mit": "cosa",
        "hol": "dove",
        "kit": "chi",
        "melyik": "quale",
        "hova": "verso dove",
    },
    "pl": {
        "mit": "co",
        "hol": "gdzie",
        "kit": "kogo",
        "melyik": "który",
        "hova": "dokąd",
    },
    "uk": {
        "mit": "що",
        "hol": "де",
        "kit": "кого",
        "melyik": "який",
        "hova": "куди",
    },
    "zh": {
        "mit": "什么",
        "hol": "哪里",
        "kit": "谁",
        "melyik": "哪个",
        "hova": "去哪里",
    },
    "pt": {
        "mit": "o que",
        "hol": "onde",
        "kit": "quem",
        "melyik": "qual",
        "hova": "para onde",
    },
}


def is_question(key):
  return key in QUESTION_KEYS or key.startswith("wh_")


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

RU_PAST = {
    "csinál": "делал(а)",
    "olvas": "читал(а)",
    "ír": "писал(а)",
    "eszik": "ел(а)",
    "iszik": "пил(а)",
    "lát": "видел(а)",
    "hall": "слышал(а)",
    "vesz": "покупал(а)",
    "kér": "просил(а)",
    "tanul": "учил(а)",
    "dolgozik": "работал(а)",
    "lakik": "жил(а)",
    "beszél": "говорил(а)",
    "tud": "знал(а)",
    "akar": "хотел(а)",
    "megy": "шёл(шла)",
    "jön": "приходил(а)",
    "alszik": "спал(а)",
    "főz": "готовил(а)",
    "szeret": "любил(а)",
    "ad": "давал(а)",
    "kap": "получал(а)",
    "fut": "бежал(а)",
    "nyit": "открывал(а)",
    "vár": "ждал(а)",
    "keres": "искал(а)",
    "játszik": "играл(а)",
    "fizet": "платил(а)",
    "segít": "помогал(а)",
    "tesz": "клал(а)",
    "gondolkodik": "думал(а)",
    "gépel": "печатал(а)",
    "rajzol": "рисовал(а)",
}

EN_PAST = {
    "csinál": "did",
    "olvas": "read",
    "ír": "wrote",
    "eszik": "ate",
    "iszik": "drank",
    "lát": "saw",
    "hall": "heard",
    "vesz": "bought",
    "kér": "asked for",
    "tanul": "learned",
    "dolgozik": "worked",
    "lakik": "lived",
    "beszél": "spoke",
    "tud": "knew",
    "akar": "wanted",
    "megy": "went",
    "jön": "came",
    "alszik": "slept",
    "főz": "cooked",
    "szeret": "loved",
    "ad": "gave",
    "kap": "got",
    "fut": "ran",
    "nyit": "opened",
    "vár": "waited",
    "keres": "looked for",
    "játszik": "played",
    "fizet": "paid",
    "segít": "helped",
    "tesz": "put",
    "gondolkodik": "thought",
    "gépel": "typed",
    "rajzol": "drew",
}

_RU_PRON = {"én": "я", "te": "ты", "mi": "мы", "ők": "они"}
_RU_BUDU = {
    "én": "я буду",
    "te": "ты будешь",
    "ő": "он / она будет",
    "mi": "мы будем",
    "ők": "они будут",
}
_PRES_IDX = {"én": 0, "te": 1, "mi": 2, "ők": 3}
_EN_PRON = {"én": "I", "te": "you", "mi": "we", "ők": "they"}


def _cap(s):
  return s[:1].upper() + s[1:]


def ru_natural(key, hu, ru, en, l_data):
  if key.startswith("wh_"):
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
  else:
    s = f"{_RU_BUDU[key[2:]]} {ru}"
  if is_question(key):
    s += "?"
  return _cap(s)


def en_natural(key, hu, ru, en, l_data):
  bare = en[3:] if en.startswith("to ") else en
  if key.startswith("wh_"):
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
  else:
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


NATURAL = {"ru": ru_natural, "en": en_natural}


def hint_for(key, hu, inf):
  a = answers_for(key, hu, inf)[0]
  if is_question(key) and not a.endswith("?"):
    a += "?"
  return a


ORDER = ["csinál", "olvas", "ír", "eszik", "iszik", "lát", "hall", "vesz"]


def L(forms, phrases):
  return dict(zip(ORDER, forms)), dict(zip(ORDER, phrases))


_ru_forms, _ru_phr = L(
    ["делает", "читает", "пишет", "ест", "пьёт", "видит", "слышит", "покупает"],
    [
        "Что ты делаешь?",
        "Что ты читаешь?",
        "Что ты пишешь?",
        "Что ты ешь?",
        "Что ты пьёшь?",
        "Что ты видишь?",
        "Что ты слышишь?",
        "Что ты покупаешь?",
    ],
)
_ru_forms.update({
    "kér": "просит",
    "tanul": "учит",
    "dolgozik": "работает",
    "lakik": "живёт",
    "beszél": "говорит",
    "tud": "знает / умеет",
    "akar": "хочет",
    "megy": "идёт / едет",
    "jön": "приходит",
    "alszik": "спит",
    "főz": "готовит",
    "szeret": "любит",
    "ad": "даёт",
    "kap": "получает",
    "fut": "бежит",
    "nyit": "открывает",
    "vár": "ждёт",
    "keres": "ищет",
    "játszik": "играет",
    "fizet": "платит",
    "segít": "помогает",
    "tesz": "кладёт / ставит",
    "gondolkodik": "думает",
    "gépel": "печатает",
    "rajzol": "рисует",
})
_uk_forms, _uk_phr = L(
    ["робить", "читає", "пише", "їсть", "п'є", "бачить", "чує", "купує"],
    [
        "Що ти робиш?",
        "Що ти читаєш?",
        "Що ти пишеш?",
        "Що ти їси?",
        "Що ти п'єш?",
        "Що ти бачиш?",
        "Що ти чуєш?",
        "Що ти купуєш?",
    ],
)
_uk_forms.update({
    "kér": "просить",
    "tanul": "вчить",
    "dolgozik": "працює",
    "lakik": "живе",
    "beszél": "говорить",
    "tud": "знає / вміє",
    "akar": "хоче",
    "megy": "йде / їде",
    "jön": "приходить",
    "alszik": "спить",
    "főz": "готує",
    "szeret": "любить",
    "ad": "дає",
    "kap": "отримує",
    "fut": "біжить",
    "nyit": "відкриває",
    "vár": "чекає",
    "keres": "шукає",
    "játszik": "грає",
    "fizet": "платить",
    "segít": "допомагає",
    "tesz": "кладе / ставить",
    "gondolkodik": "думає",
    "gépel": "друкує",
    "rajzol": "малює",
})
_en_forms, _en_phr = L(
    ["does", "reads", "writes", "eats", "drinks", "sees", "hears", "buys"],
    [
        "What are you doing?",
        "What are you reading?",
        "What are you writing?",
        "What are you eating?",
        "What are you drinking?",
        "What do you see?",
        "What do you hear?",
        "What are you buying?",
    ],
)
_en_forms.update({
    "kér": "asks for",
    "tanul": "learns",
    "dolgozik": "works",
    "lakik": "lives",
    "beszél": "speaks",
    "tud": "knows",
    "akar": "wants",
    "megy": "goes",
    "jön": "comes",
    "alszik": "sleeps",
    "főz": "cooks",
    "szeret": "loves",
    "ad": "gives",
    "kap": "gets",
    "fut": "runs",
    "nyit": "opens",
    "vár": "waits",
    "keres": "looks for",
    "játszik": "plays",
    "fizet": "pays",
    "segít": "helps",
    "tesz": "puts",
    "gondolkodik": "thinks",
    "gépel": "types",
    "rajzol": "draws",
})
_es_forms, _es_phr = L(
    ["hace", "lee", "escribe", "come", "bebe", "ve", "oye", "compra"],
    [
        "¿Qué haces?",
        "¿Qué lees?",
        "¿Qué escribes?",
        "¿Qué comes?",
        "¿Qué bebes?",
        "¿Qué ves?",
        "¿Qué oyes?",
        "¿Qué compras?",
    ],
)
_fr_forms, _fr_phr = L(
    ["fait", "lit", "écrit", "mange", "boit", "voit", "entend", "achète"],
    [
        "Qu'est-ce que tu fais ?",
        "Qu'est-ce que tu lis ?",
        "Qu'est-ce que tu écris ?",
        "Qu'est-ce que tu manges ?",
        "Qu'est-ce que tu bois ?",
        "Qu'est-ce que tu vois ?",
        "Qu'est-ce que tu entends ?",
        "Qu'est-ce que tu achètes ?",
    ],
)
_de_forms, _de_phr = L(
    ["macht", "liest", "schreibt", "isst", "trinkt", "sieht", "hört", "kauft"],
    [
        "Was machst du?",
        "Was liest du?",
        "Was schreibst du?",
        "Was isst du?",
        "Was trinkst du?",
        "Was siehst du?",
        "Was hörst du?",
        "Was kaufst du?",
    ],
)
_it_forms, _it_phr = L(
    ["fa", "legge", "scrive", "mangia", "beve", "vede", "sente", "compra"],
    [
        "Cosa fai?",
        "Cosa leggi?",
        "Cosa scrivi?",
        "Cosa mangi?",
        "Cosa bevi?",
        "Cosa vedi?",
        "Cosa senti?",
        "Cosa compri?",
    ],
)
_pl_forms, _pl_phr = L(
    ["robi", "czyta", "pisze", "je", "pije", "widzi", "słyszy", "kupuje"],
    [
        "Co robisz?",
        "Co czytasz?",
        "Co piszesz?",
        "Co jesz?",
        "Co pijesz?",
        "Co widzisz?",
        "Co słyszysz?",
        "Co kupujesz?",
    ],
)
_zh_forms, _zh_phr = L(
    ["做", "读", "写", "吃", "喝", "看见", "听见", "买"],
    [
        "你在做什么？",
        "你在读什么？",
        "你在写什么？",
        "你在吃什么？",
        "你在喝什么？",
        "你看到了什么？",
        "你听到了什么？",
        "你在买什么？",
    ],
)
_pt_forms, _pt_phr = L(
    ["faz", "lê", "escreve", "come", "bebe", "vê", "ouve", "compra"],
    [
        "O que você está fazendo?",
        "O que você está lendo?",
        "O que você está escrevendo?",
        "O que você está comendo?",
        "O que você está bebendo?",
        "O que você vê?",
        "O que você ouve?",
        "O que você está comprando?",
    ],
)

LANGUAGES = {
    "ru": {
        "name": "🇷🇺 Русский",
        "welcome": (
            "Отлично! Выбери глагол для тренировки с помощью кнопок внизу:"
        ),
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
        "pron": {
            "én": "я",
            "te": "ты",
            "ő": "он / она",
            "mi": "мы",
            "ők": "они",
        },
        "past": "прошедшее",
        "future": "будущее",
        "forms": _ru_forms,
        "phrases": _ru_phr,
        "morning": "☀️ Jó reggelt! ✨ mit csinálsz ma? Gyere gyakoroljunk kicsit! ☕️",
        "day": (
            "☕️ Sziia! Amúgy hogy vagy? 🌸 csinálunk egy kis magyar igét? ✨"
        ),
        "evening": (
            "🌙 Jó éjt! 🌙 szép álmokat! ne felejtsd el az igéket! 💤"
        ),
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
        "pron": {
            "én": "I",
            "te": "you",
            "ő": "he / she",
            "mi": "we",
            "ők": "they",
        },
        "past": "past",
        "future": "future",
        "forms": _en_forms,
        "phrases": _en_phr,
        "morning": (
            "☀️ Good morning! ✨ What are u up to today? Let's practice! ☕️"
        ),
        "day": "☕️ Heyyy! How's your day going? 🌸 Wanna practice a verb? ✨",
        "evening": "🌙 Good night!! 🌙 sweet dreams! don't forget verbs! 💤",
    },
}

KAO_HAPPY = [
    "ʕ•ᴥ•ʔ",
    "(≧◡≦)",
    "(๑>ᴗ<๑)",
    "(o˘◡˘o)",
    "(｡•ㅅ•｡)♡",
    "( ´ ω ` )♡",
    "(づᴗ_ᴗ)づ♡",
    "(=^･ω･^=)",
    "ʕっ•ᴥ•ʔっ",
    "ฅ^•ﻌ•^ฅ",
]
KAO_GREAT = [
    "ʕ≧ᴥ≦ʔ",
    "(>ᴗ<)",
    "(=`ω´=)",
    "(≧◡≦)♡",
    "ʕっ•ᴥ•ʔっ",
    "(๑>ᴗ<๑)",
]
KAO_DONE = ["ʕっ•ᴥ•ʔっ♡", "(づᴗ_ᴗ)づ♡", "(๑>ᴗ<๑)♡", "ʕ≧ᴥ≦ʔ♡"]
KAO_SAD = ["ʕ´•ᴥ•`ʔ", "(´･ω･`)", "(´• ω •`)"]
KAO_TIME = {
    "morning": ["(≧◡≦)♡", "ʕ•ᴥ•ʔ", "(o˘◡˘o)"],
    "day": ["(=^･ω･^=)", "ฅ^•ﻌ•^ฅ", "(｡•ㅅ•｡)♡"],
    "evening": ["(˘ω˘)zzZ", "ʕ-ᴥ-ʔ♡", "( ´ ω ` )♡"],
}
K_LANG = "(=^･ω･^=)"
CARDS_BTN = "Cards (=^･ω･^=)"

_EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF☀-➿️‍]+")


def _strip_emoji(s):
  return _EMOJI_RE.sub("", s).strip()


for _l in LANGUAGES.values():
  for _k in ("correct", "fire", "finish", "morning", "day", "evening"):
    _l[_k] = _strip_emoji(_l[_k])


def verb_name(lang, ru, en):
  return ru if lang in ("ru", "uk") else en


def norm(text):
  text = unicodedata.normalize("NFD", text.lower())
  text = "".join(c for c in text if unicodedata.category(c) != "Mn")
  for ch in "?!.,":
    text = text.replace(ch, "")
  return " ".join(text.split())


_PRON_NORM = {"en", "te", "o", "mi", "ti", "ok"}


def strip_pronoun(text):
  parts = text.split(" ", 1)
  if len(parts) == 2 and parts[0] in _PRON_NORM and parts[1]:
    return parts[1]
  return text


def build_steps(hu, l_data):
  steps = ["inf", "ő", "én", "te", "mi", "ők"]
  for w in WH.get(hu, []):
    steps += [f"wh_{w}_te", f"wh_{w}_én"]
  steps += ["past", "past_te", "f_ő", "f_én", "f_te", "f_ők"]
  return steps


def answers_for(key, hu, inf):
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
  pool = [v for v in VERBS_DATABASE if v[0] not in exclude]
  if len(pool) < 3:
    pool = VERBS_DATABASE
  selected = random.sample(pool, 3)
  markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
  for hu, ru, en, inf in selected:
    markup.add(KeyboardButton(text=f"{hu} ({verb_name(lang, ru, en)})"))
  if available_cards():
    markup.add(KeyboardButton(text=CARDS_BTN))
  return markup


def find_verb(text):
  t = text.lower().strip()
  head = t.split(" (")[0].strip()
  for verb in VERBS_DATABASE:
    hu, ru, en, inf = verb
    if head in (hu, inf) or t in (ru.lower(), en.lower()):
      return verb
  return None


def escape_markdown_v2(text):
  text = text.replace("\\", "\\\\")
  special_chars = "_*[]()~`>#+-=|{}.!"
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


def new_state(user_id, lang):
  recent = active_trainings.get(user_id, {}).get("recent", [])
  active_trainings[user_id] = {"lang": lang, "step": 0, "recent": recent}
  return active_trainings[user_id]


CARDS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cards")

CARD_FILES = {
    "ad": "ad.jpg",
    "gondolkodik": "gondolkodik.jpg",
    "fut": "fut.jpg",
    "ír": "ir.jpg",
    "dolgozik": "dolgozik.jpg",
    "rajzol": "rajzol.jpg",
    "tanul": "tanul.jpg",
}

CARD_CONFLICTS = {
    "ad": {"kér", "tesz", "vesz", "kap", "eszik"},
    "gondolkodik": {"tanul", "tud", "akar"},
    "fut": {"megy", "jön"},
    "ír": {"gépel", "rajzol", "tanul", "dolgozik", "olvas"},
    "dolgozik": {"gépel", "ír", "tanul", "olvas"},
    "rajzol": {"ír", "játszik", "dolgozik"},
    "tanul": {"olvas", "ír", "gondolkodik", "dolgozik"},
}

CARD_FILE_IDS = {}
VERB_INDEX = {v[0]: i for i, v in enumerate(VERBS_DATABASE)}

NO_CARDS_MSG = "Нет картинок. Положи папку cards рядом с bot.py"

CARDS_TXT = {
    "ru": {
        "q": "Что делает Réka?",
        "no": "Не то, попробуй ещё",
        "next": "Дальше",
        "score": "Счёт",
    },
    "en": {
        "q": "What is Réka doing?",
        "no": "Not that one, try again",
        "next": "Next",
        "score": "Score",
    },
    "es": {
        "q": "¿Qué hace Réka?",
        "no": "Esa no, prueba otra",
        "next": "Siguiente",
        "score": "Puntos",
    },
    "fr": {
        "q": "Que fait Réka ?",
        "no": "Pas celle-là, réessaie",
        "next": "Suivant",
        "score": "Score",
    },
    "de": {
        "q": "Was macht Réka?",
        "no": "Nicht das, versuch's nochmal",
        "next": "Weiter",
        "score": "Punkte",
    },
    "it": {
        "q": "Cosa fa Réka?",
        "no": "Non quella, riprova",
        "next": "Avanti",
        "score": "Punti",
    },
    "pl": {
        "q": "Co robi Réka?",
        "no": "Nie to, spróbuj jeszcze raz",
        "next": "Dalej",
        "score": "Wynik",
    },
    "uk": {
        "q": "Що робить Réka?",
        "no": "Не те, спробуй ще",
        "next": "Далі",
        "score": "Рахунок",
    },
    "zh": {
        "q": "Réka在做什么？",
        "no": "不是这个，再试试",
        "next": "下一张",
        "score": "得分",
    },
    "pt": {
        "no": "Não é essa, tente de novo",
        "next": "Próxima",
        "q": "O que a Réka está fazendo?",
        "score": "Pontos",
    },
}


def available_cards():
  return [
      hu
      for hu, fn in CARD_FILES.items()
      if os.path.exists(os.path.join(CARDS_DIR, fn))
  ]


def send_card(chat_id, user_id):
  state = active_trainings.setdefault(
      user_id, {"lang": None, "step": 0, "recent": []}
  )
  lang = state.get("lang") or "ru"
  t = CARDS_TXT.get(lang, CARDS_TXT["ru"])

  cards = available_cards()
  if not cards:
    bot.send_message(chat_id, NO_CARDS_MSG)
    return

  pool = [c for c in cards if c != state.get("last_card")] or cards
  correct = random.choice(pool)
  wrong_pool = [
      v[0]
      for v in VERBS_DATABASE
      if v[0] != correct and v[0] not in CARD_CONFLICTS.get(correct, ())
  ]
  options = random.sample(wrong_pool, 3) + [correct]
  random.shuffle(options)

  markup = InlineKeyboardMarkup(row_width=2)
  markup.add(*[
      InlineKeyboardButton(
          text=o, callback_data=f"cd:{VERB_INDEX[o]}:{VERB_INDEX[correct]}"
      )
      for o in options
  ])

  state["last_card"] = correct
  state["card_missed"] = False
  caption = f"{t['q']} {random.choice(KAO_HAPPY)}"

  file_id = CARD_FILE_IDS.get(correct)
  if file_id:
    bot.send_photo(chat_id, file_id, caption=caption, reply_markup=markup)
  else:
    path = os.path.join(CARDS_DIR, CARD_FILES[correct])
    with open(path, "rb") as f:
      msg = bot.send_photo(chat_id, f, caption=caption, reply_markup=markup)
    CARD_FILE_IDS[correct] = msg.photo[-1].file_id


@bot.message_handler(commands=["cards"])
def cmd_cards(message):
  all_users.add(message.from_user.id)
  send_card(message.chat.id, message.from_user.id)


@bot.callback_query_handler(
    func=lambda call: call.data in ("cn", "cx") or call.data.startswith("cd:")
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

  if call.data == "cx":
    bot.answer_callback_query(call.id)
    return

  if call.data == "cn":
    bot.answer_callback_query(call.id)
    try:
      bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=None)
    except Exception:
      pass
    send_card(chat_id, user_id)
    return

  _, chosen, correct = call.data.split(":")

  if chosen == correct:
    hu, ru, en, inf = VERBS_DATABASE[int(correct)]
    state["card_total"] = state.get("card_total", 0) + 1
    if not state.get("card_missed"):
      state["card_ok"] = state.get("card_ok", 0) + 1
    caption = (
        f"{hu} ({inf}) — {verb_name(lang, ru, en)}\n"
        f"{t['score']}: {state.get('card_ok', 0)}/{state['card_total']} "
        f"{random.choice(KAO_HAPPY)}"
    )
    old_kb = (
        call.message.reply_markup.keyboard if call.message.reply_markup else []
    )
    chosen_text = next(
        (b.text for row in old_kb for b in row if b.callback_data == call.data),
        hu,
    )
    green = InlineKeyboardMarkup()
    green.add(InlineKeyboardButton(text=f"✅ {chosen_text}", callback_data="cx"))
    bot.answer_callback_query(call.id, text=random.choice(KAO_GREAT))
    try:
      bot.edit_message_caption(
          caption=caption,
          chat_id=chat_id,
          message_id=msg_id,
          reply_markup=green,
      )
    except Exception:
      pass
    time.sleep(1.2)
    send_card(chat_id, user_id)
  else:
    state["card_missed"] = True
    bot.answer_callback_query(
        call.id, text=f"{random.choice(KAO_SAD)} {t['no']}"
    )
    old = (
        call.message.reply_markup.keyboard if call.message.reply_markup else []
    )
    left = [b for row in old for b in row if b.callback_data != call.data]
    new_markup = InlineKeyboardMarkup(row_width=2)
    new_markup.add(*left)
    bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=new_markup)


def generate_teen_ai_chat(user_text, user_lang):
  """Генерирует живой венгерский разговорный ответ в стиле подростка (teen/Gen-Z text style)."""
  if not client:
    return "sziia! 💕 hogy vagy? akarod gyakorolni az igéket? ✨"

  prompt = (
      "You are Réka, a cool Hungarian teenage girl texting your friend on Instagram/DM. "
      "Style: Gen-Z / teen texting vibe, casual, short, cute, expressive, uses emojis (✨, 😂, 🥺, 💀, ❤️), "
      "uses teen slang/fillers ('amúgy', 'tbh', 'hahaha', 'vagy mi', 'szerintem', 'jól vagy?'). "
      f"User wrote to you: '{user_text}'. "
      "Reply naturally IN HUNGARIAN like a teenage girl texting a friend. Keep it short (1-3 sentences)."
  )

  try:
    completion = client.chat.completions.create(
        model="llama3-8b-8192",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.8,
        max_tokens=150,
    )
    return completion.choices[0].message.content.strip()
  except Exception as e:
    print(f"Groq API error: {e}")
    return "sziia! ✨ hogy vagy amúgy? csinálunk egy kis igét? 💕"


@bot.message_handler(commands=["start", "reset", "verbs"])
def cmd_start(message):
  user_id = message.from_user.id
  all_users.add(user_id)

  current_lang = active_trainings.get(user_id, {}).get("lang")

  if current_lang in LANGUAGES:
    data = new_state(user_id, current_lang)
    bot.send_message(
        message.chat.id,
        LANGUAGES[current_lang]["welcome"],
        reply_markup=get_verbs_keyboard(current_lang, data["recent"]),
    )
  else:
    new_state(user_id, None)
    bot.send_message(
        message.chat.id,
        f"{K_LANG} Выберите язык интерфейса / Choose your language:",
        reply_markup=get_language_keyboard(),
    )


@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
  if not message.text:
    return

  user_id = message.from_user.id
  all_users.add(user_id)
  text = message.text.strip()

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
        LANGUAGES[selected_lang]["welcome"],
        reply_markup=get_verbs_keyboard(selected_lang, data["recent"]),
    )
    return

  data = active_trainings[user_id]
  lang = data["lang"]
  l_data = LANGUAGES.get(lang, LANGUAGES["ru"])
  recent = data.setdefault("recent", [])

  if text == CARDS_BTN:
    send_card(message.chat.id, user_id)
    return

  # --- выбор глагола
  if "verb" not in data:
    found = find_verb(text)
    if not found:
      # Если сообщение не совпало с глаголом — Réka общается как живая подруга на венгерском!
      ai_chat = generate_teen_ai_chat(text, lang)
      bot.send_message(
          message.chat.id,
          ai_chat,
          reply_markup=get_verbs_keyboard(lang, recent),
      )
      return

    data["verb"] = found
    data["steps"] = build_steps(found[0], l_data)
    data["step"] = 1
    question = make_question(l_data, lang, data["steps"], 1, found)
    hint = hint_for(data["steps"][0], found[0], found[3])
    send_reply(message.chat.id, question, hint)
    return

  # --- проверка ответа в процессе тренировки
  verb = data["verb"]
  hu, ru, en, inf = verb
  steps = data["steps"]
  step = data["step"]
  key = steps[step - 1]
  answers = answers_for(key, hu, inf)

  user_text = norm(text)
  if key != "q":
    user_text = strip_pronoun(user_text)

  if user_text in [norm(a) for a in answers]:
    step += 1
    data["step"] = step

    if step > len(steps):
      data.pop("verb", None)
      data.pop("steps", None)
      data["step"] = 0
      recent.append(hu)
      data["recent"] = recent[-RECENT_LIMIT:]
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
      send_reply(message.chat.id, f"{praise}\n\n{question}", hint)
  else:
    retry_text = (
        f"{random.choice(KAO_SAD)} "
        + l_data["retry"].format(v=verb_name(lang, ru, en))
    )
    send_reply(message.chat.id, retry_text, hint_for(key, hu, inf))


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
          state.pop("verb", None)
          state.pop("steps", None)
          state["step"] = 0
          state.setdefault("lang", user_lang)
          state.setdefault("recent", [])
          active_trainings[user_id] = state
          bot.send_message(
              user_id,
              f"{l_data[time_key]} {random.choice(KAO_TIME[time_key])}",
              reply_markup=get_verbs_keyboard(user_lang, state["recent"]),
          )
        except Exception as e:
          print(f"Ошибка отправки напоминания пользователю {user_id}: {e}")
      time.sleep(3700)
    else:
      time.sleep(600)


threading.Thread(target=daily_reminders_loop, daemon=True).start()

print("Réka запущенa как собеседник с венгерским vibe...")

while True:
  try:
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
  except Exception as e:
    print(f"Ошибка: {e}")
    time.sleep(5)
