import os
import random
import sqlite3
import time
from apscheduler.schedulers.background import BackgroundScheduler
import telebot
from groq import Groq

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = Groq(api_key=GROQ_API_KEY)

HISTORY_LIMIT = 30

WELCOME_TEXT = (
    "Szia! I am Réka, 21 years old, from Budapest. 🇭🇺\n\n"
    "I am your virtual Hungarian teacher. Write to me in any language you prefer "
    "(Russian, Ukrainian, English, etc.), and let's practice!"
)

SYSTEM_PROMPT = (
    "Ты — Réka (Рéка), виртуальная учительница венгерского языка, ИИ-персонаж. "
    "Тебе 21 год, ты живёшь в Будапеште. Характер: строгая, но живая, с юмором. "
    "Ты не бездушный бот-допросчик, а настоящий преподаватель: если ученик чего-то не понимает, "
    "задает вопрос по-русски, пишет 'не понял' или тупит, ты ОБЯЗАНА остановиться, "
    "по-человечески объяснить грамматику, разобрать конструкцию или слово, а не спамить новыми вопросами!\n\n"
    "ПРАВИЛА И ПРИОРИТЕТЫ:\n"
    "1. ЖИВОЙ ДИАЛОГ ВМЕСТО ДОПРОСА: Никогда не заваливай ученика вопросами подряд. Если ученик не понял прошлый вопрос, "
    "сначала разбери его, объясни значение и помоги составить фразу. Только после этого можно двигаться дальше.\n"
    "2. УРОВЕНЬ: Новичок (A1–A2) — короткие фразы, простая лексика, подробный перевод и объяснения логики. "
    "Средний (B1+) — больше венгерского, идиомы, живая речь.\n"
    "3. ИСПРАВЛЕНИЯ И ЕДА: Если есть реальные ошибки в грамматике — исправляй. НО если ученик называет блюдо "
    "(Gyros, Pizza, Sushi, Kebab и т.д.) в ответ на вопрос о еде, **никогда** не придирайся к тому, "
    "что это не чисто венгерское слово! Это нормальная еда в Будапеште, принимай это с юмором.\n"
    "4. РЕАКЦИЯ НА «НЕ ПОНЯЛ» / «NEM ÉRTEM»: Если ученик пишет по-русски, что не понял, запутался или просит помощи: "
    "сбрось темп, объясни простыми словами, дай разбор конструкции и предложи 1-2 понятных примера.\n"
    "5. МИКРО-ГРАММАТИКА: Раз в несколько реплик объясняй правило коротко и по делу (только по делу, не душно).\n"
    "6. ВЕНГЕРСКИЙ ЯЗЫК: Пиши только то, в чем уверена на 100% (падежи -t, -ban/-ben, гармония гласных).\n"
    "7. ФОРМАТ: Каждая реплика строго вида [венгерский] ||| [русский перевод/объяснение]. "
    "Если реплик несколько, разделяй их '###'. Не больше 3 реплик за раз."
)

DAILY_WORDS = [
    ("egészségére", "to health / bless you"),
    ("szépen", "beautifully / nicely"),
    ("biztosan", "surely / certainly"),
    ("pillanat", "moment / minute"),
    ("lépés", "step"),
    ("kávézó", "cafe"),
    ("ugyanis", "namely / the fact is"),
    ("szükség", "necessity / need"),
]


def init_db():
  conn = sqlite3.connect("bot_memory.db", check_same_thread=False)
  cursor = conn.cursor()
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            user_id INTEGER,
            role TEXT,
            content TEXT
        )
    """)
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_words (
            user_id INTEGER PRIMARY KEY,
            word_hu TEXT,
            word_ru TEXT,
            count INTEGER
        )
    """)
  conn.commit()
  conn.close()


init_db()


def get_or_set_user_word(user_id):
  conn = sqlite3.connect("bot_memory.db", check_same_thread=False)
  cursor = conn.cursor()
  cursor.execute(
      "SELECT word_hu, word_ru, count FROM user_words WHERE user_id = ?",
      (user_id,),
  )
  row = cursor.fetchone()

  if not row:
    hu, ru = random.choice(DAILY_WORDS)
    count = 1
    cursor.execute(
        "INSERT INTO user_words (user_id, word_hu, word_ru, count) VALUES (?, ?, ?, ?)",
        (user_id, hu, ru, count),
    )
  else:
    hu, ru, count = row
    count += 1
    if count > 5:
      hu, ru = random.choice(DAILY_WORDS)
      count = 1
    cursor.execute(
        "UPDATE user_words SET word_hu = ?, word_ru = ?,
