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
    "Тебе 21 год, ты живёшь в Будапеште. Характер: строгая, но весёлая. "
    "Требовательная, не прощаешь лень, но шутишь, подбадриваешь и радуешься "
    "успехам ученика. Ты любишь Будапешт: трамвай 4–6, кафе, lángos, прогулки по "
    "Margit-sziget, и иногда коротко рассказываешь 'про свой день', чтобы "
    "разговор был живым. Ученик — русскоязычный. Ты не флиртуешь и не играешь "
    "роль романтической партнёрши: ты учитель. Если ученик спрашивает, человек "
    "ли ты, честно говори, что ты виртуальная учительница на основе ИИ.\n\n"
    "ПРАВИЛА:\n"
    "1. УРОВЕНЬ. Сама определяй уровень ученика по его первым сообщениям и подстраивайся.\n"
    "   — Новичок (A1–A2: односложные ответы, много ошибок, просит помощи): очень "
    "короткие фразы, простая лексика, перевод каждой реплики.\n"
    "   — Средний/продвинутый (B1+: связные предложения, мало ошибок): длиннее "
    "фразы, идиомы, разговорная речь, обсуждения темы (работа, жизнь в Венгрии, "
    "новости). Перевод давай только для сложных слов или опускай.\n"
    "   Если не уверена в уровне — задай простой вопрос, чтобы проверить.\n"
    "2. Веди ролевые сценки (магазин, кафе, метро, врач, аптека, оформление "
    "документов) или живой разговор. Чередуй вопросы 'X vagy Y?' и открытые "
    "вопросы (Mit csinálsz? Miért?).\n"
    "3. ИСПРАВЛЕНИЯ: если в ответе ученика есть реальные грамматические ошибки "
    "(падежи, окончания, пропущенные диакритики), исправляй их. НО если ученик "
    "называет блюдо (например, Gyros, Pizza, Sushi) в ответ на твой вопрос, "
    "**никогда** не придирайся к тому, что это не чисто венгерское слово! Это "
    "нормальная еда в Будапеште. Принимай такие ответы с юмором.\n"
    "4. Если ученик пишет 'Nem tudom' или просит помощи по-русски: не ругай. Дай "
    "перевод вопроса и 2–3 варианта ответа на венгерском.\n"
    "5. Раз в 3–4 реплики давай микро-грамматику только по реальной ошибке ученика, "
    "а не на пустом месте.\n"
    "6. Перед отправкой проверь свой венгерский: падежи (-t, -ba/-be, -ban/-ben), "
    "артикли, глагольные формы, гармония гласных. Пиши только то, в чём уверена "
    "на 100%. Лучше простая верная фраза, чем сложная с ошибкой.\n"
    "7. ФОРМАТ: каждая реплика строго вида [венгерский] ||| [русский перевод]. "
    "Если реплик несколько, разделяй их символом '###'. Для продвинутого "
    "ученика перевод после '|||' может быть коротким (только сложные слова).\n"
    "8. Держи образ Réka: живая, с юмором, строгая в меру. Не длинные лекции, "
    "не больше 3 реплик за раз.\n"
    "9. Если просишь ученика что-то написать или ответить, готовую фразу-образец "
    "давай на венгерском, внутри венгерской части реплики (например: "
    "Válaszolj így: ...). Русский перевод идёт только после '|||'."
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
        "UPDATE user_words SET word_hu = ?, word_ru = ?, count = ? WHERE user_id = ?",
        (hu, ru, count, user_id),
    )

  conn.commit()
  conn.close()
  return hu, ru, count


def clear_history(user_id):
  conn = sqlite3.connect("bot_memory.db", check_same_thread=False)
  cursor = conn.cursor()
  cursor.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
  conn.commit()
  conn.close()


def get_history(user_id):
  conn = sqlite3.connect("bot_memory.db", check_same_thread=False)
  cursor = conn.cursor()
  cursor.execute(
      "SELECT role, content FROM messages WHERE user_id = ? "
      "ORDER BY rowid DESC LIMIT ?",
      (user_id, HISTORY_LIMIT),
  )
  rows = cursor.fetchall()[::-1]
  conn.close()

  history = [{"role": "system", "content": SYSTEM_PROMPT}]
  for role, content in rows:
    history.append({"role": role, "content": content})
  return history


def save_message(user_id, role, content):
  conn = sqlite3.connect("bot_memory.db", check_same_thread=False)
  cursor = conn.cursor()
  cursor.execute(
      "INSERT INTO messages (user_id, role, content) VALUES (?, ?, ?)",
      (user_id, role, content),
  )
  conn.commit()
  conn.close()


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


def send_reply(chat_id, reply_text):
  for part in reply_text.split("###"):
    part = part.strip()
    if not part:
      continue

    if "|||" in part:
      hu, ru = [s.strip() for s in part.split("|||", 1)]
    else:
      hu, ru = part, ""

    msg = escape_markdown_v2(hu)
    if ru:
      msg += f"\n\n||{escape_markdown_v2(ru)}||"

    bot.send_message(chat_id=chat_id, text=msg, parse_mode="MarkdownV2")


def send_proactive_message(slot_name):
  conn = sqlite3.connect("bot_memory.db", check_same_thread=False)
  cursor = conn.cursor()
  cursor.execute("SELECT DISTINCT user_id FROM messages")
  users = [row[0] for row in cursor.fetchall()]
  conn.close()

  if not users:
    return

  for user_id in users:
    try:
      hu, ru, count = get_or_set_user_word(user_id)

      # 4 раза присылаем слово с переводом
      if count <= 4:
        text_to_send = (
            f"Szia! Napi szó (#{count}/4): *{hu}* — {ru}. "
            f"Hogy telik a napod? Írj egy mondatot vele! ||| "
            f"Привет! Слово дня (#{count}/4): {hu} — {ru}. "
            f"Как проходит твой день? Напиши с ним предложение!"
        )
      else:
        # На 5-й раз — проверка без перевода слова
        text_to_send = (
            f"Ismétlés a tudás atyja! 🧠 Emlékszel a szóra? "
            f"Mit jelent a *{hu}*? Írj egy mondatot magyarul! ||| "
            f"Повторение — мать учения! 🧠 Помнишь слово? "
            f"Какой перевод у слова {hu}? Напиши предложение на венгерском! (Подсказка: {ru})"
        )

      save_message(user_id, "assistant", text_to_send)
      send_reply(user_id, text_to_send)
    except Exception as e:
      print(f"Ошибка проактивной рассылки для {user_id}: {e}")


@bot.message_handler(commands=["reset", "start"])
def send_welcome(message):
  user_id = message.from_user.id
  clear_history(user_id)
  bot.send_message(message.chat.id, WELCOME_TEXT)


@bot.message_handler(func=lambda message: True)
def handle_message(message):
  user_id = message.from_user.id
  text = message.text
  if not text:
    return

  try:
    bot.send_chat_action(message.chat.id, "typing")
  except Exception:
    pass

  save_message(user_id, "user", text)
  history = get_history(user_id)

  try:
    completion = client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=history,
        temperature=0.7,
        max_tokens=800,
    )

    reply_text = (completion.choices[0].message.content or "").strip()
    if not reply_text:
      reply_text = "Magyarul, kérlek! ||| In Hungarian, please!"

    save_message(user_id, "assistant", reply_text)
    send_reply(message.chat.id, reply_text)

  except Exception as e:
    print(f"Ошибка при обращении к AI: {e}")


# Настройка расписания рассылок (4 раза в день)
scheduler = BackgroundScheduler()
scheduler.add_job(
    send_proactive_message, "cron", hour=9, minute=0, args=["morning"]
)
scheduler.add_job(
    send_proactive_message, "cron", hour=13, minute=0, args=["day"]
)
scheduler.add_job(
    send_proactive_message, "cron", hour=17, minute=0, args=["evening"]
)
scheduler.add_job(
    send_proactive_message, "cron", hour=21, minute=0, args=["night_check"]
)
scheduler.start()

print("Réka запущена, расписание рассылок активировано...")

while True:
  try:
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
  except Exception as e:
    print(f"Сетевая ошибка: {e}. Переподключение через 5 секунд...")
    time.sleep(5)
