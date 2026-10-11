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

# Сколько последних выученных глаголов не показывать на кнопках
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
}

# Шаги, которые подаются как вопрос (со знаком «?» в подсказке)
QUESTION_KEYS = {"te", "past_te", "f_te"}

# Допустимые разговорные варианты формы «te»
ALT_TE = {"lakik": ["lakol"]}

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
    """3 случайных глагола, кроме недавно выученных."""
    pool = [v for v in VERBS_DATABASE if v[0] not in exclude]
    if len(pool) < 3:
        pool = VERBS_DATABASE
    selected = random.sample(pool, 3)
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


def new_state(user_id, lang):
    recent = active_trainings.get(user_id, {}).get("recent", [])
    active_trainings[user_id] = {"lang": lang, "step": 0, "recent": recent}
    return active_trainings[user_id]


# --------------------------------------------------------------- handlers

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

    # --- выбор глагола
    if "verb" not in data:
        found = find_verb(text)
        if not found:
            bot.send_message(
                message.chat.id,
                l_data["choose_btn"],
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

    # --- проверка ответа
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
            # глагол пройден целиком
            data.pop("verb", None)
            data.pop("steps", None)
            data["step"] = 0
            recent.append(hu)
            data["recent"] = recent[-RECENT_LIMIT:]
            bot.send_message(
                message.chat.id,
                l_data["finish"],
                reply_markup=get_verbs_keyboard(lang, data["recent"]),
            )
        else:
            praise = l_data["correct"] if step % 2 == 0 else l_data["fire"]
            question = make_question(l_data, lang, steps, step, verb)
            hint = hint_for(steps[step - 1], hu, inf)
            send_reply(message.chat.id, f"{praise}\n\n{question}", hint)
    else:
        retry_text = l_data["retry"].format(v=verb_name(lang, ru, en))
        send_reply(message.chat.id, retry_text, hint_for(key, hu, inf))


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
                    state.pop("steps", None)
                    state["step"] = 0
                    state.setdefault("lang", user_lang)
                    state.setdefault("recent", [])
                    active_trainings[user_id] = state
                    bot.send_message(
                        user_id,
                        l_data[time_key],
                        reply_markup=get_verbs_keyboard(user_lang, state["recent"]),
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
