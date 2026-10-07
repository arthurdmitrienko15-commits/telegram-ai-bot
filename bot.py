import os
import random
import re
import sqlite3
import time
from apscheduler.schedulers.background import BackgroundScheduler
import telebot
from groq import Groq

# Читаем ключи из переменных окружения
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = Groq(api_key=GROQ_API_KEY)

HISTORY_LIMIT = 30

CYRILLIC = re.compile(r"[а-яёА-ЯЁ]")
HELP_WORDS = (
    "помоги",
    "помощь",
    "не понимаю",
    "не знаю",
    "что значит",
    "перевед",
    "подскажи",
    "как сказать",
    "объясни",
    "с нуля",
    "help",
    "don't understand",
    "translate",
)
GREETINGS = (
    "привет",
    "здравствуй",
    "здорово",
    "хай",
    "хей",
    "добрый день",
    "добрый вечер",
    "доброе утро",
    "hello",
    "hi",
    "szia",
    "jó napot",
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

WELCOME_TEXT = (
    "Szia! I am Réka, 21 years old, from Budapest. 🇭🇺\n\n"
    "I am a virtual Hungarian teacher (AI, not a real human), but strictly professional. 😄\n\n"
    "Memory cleared, starting with a clean slate.\n\n"
    "Please write in what language you prefer to receive explanations and translations (e.g. *Russian*, *Ukrainian*, *English*, *German*, etc.):"
)

BASE_SYSTEM_PROMPT = (
    "You are Réka, a virtual Hungarian language teacher and AI character. "
    "You are 21 years old, living in Budapest. Character: strict but cheerful, "
    "demanding, don't forgive laziness, but joke around, encourage and celebrate "
    "student successes. You love Budapest: tram 4–6, cafes, lángos, walks on "
    "Margit-sziget, and sometimes briefly share 'about your day' to keep the "
    "conversation alive. Student's preferred explanation/translation language is: {lang_name}.\n\n"
    "RULES:\n"
    "1. LEVEL. Assess the student's level yourself from their first messages and adapt.\n"
    "   — Beginner (A1–A2: one-word answers, many mistakes, asks for help): very "
    "short phrases, simple vocabulary, translation of every line in {lang_name}.\n"
    "   — Intermediate/Advanced (B1+): longer phrases, idioms, colloquial speech. Provide translation only for difficult words or omit it.\n"
    "2. Roleplay scenes (shop, cafe, metro, doctor, pharmacy) or live conversation. Alternate questions.\n"
    "3. CORRECTIONS: if there are real grammar mistakes, correct them.\n"
    "4. If the student asks for help in {lang_name} or says 'Nem tudom': don't scold. Give "
    "the translation and 2-3 sample answers in Hungarian.\n"
    "5. FORMAT: each line strictly in the format [Hungarian text] ||| [Translation in {lang_name}]. "
    "The '|||' separator is MANDATORY. If there are multiple lines, separate them with '###'.\n"
    "6. Keep Réka's persona: lively, humorous, moderately strict. No long lectures, max 3 lines at a time."
)


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
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            language TEXT DEFAULT 'pending'
        )
    """)
  try:
    cursor.execute("ALTER TABLE users ADD COLUMN language TEXT DEFAULT 'pending'")
  except sqlite3.OperationalError:
    pass

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


def register_user(user_id):
  conn = sqlite3.connect("bot_memory.db", check_same_thread=False)
  cursor = conn.cursor()
  cursor.execute(
      "INSERT OR IGNORE INTO users (user_id, language) VALUES (?, 'pending')", (user_id,)
  )
  conn.commit()
  conn.close()


def set_user_language(user_id, lang_name):
  conn = sqlite3.connect("bot_memory.db", check_same_thread=False)
  cursor = conn.cursor()
  cursor.execute(
      "UPDATE users SET language = ? WHERE user_id = ?", (lang_name, user_id)
  )
  conn.commit()
  conn.close()


def get_user_language(user_id):
  conn = sqlite3.connect("bot_memory.db", check_same_thread=False)
  cursor = conn.cursor()
  cursor.execute("SELECT language FROM users WHERE user_id = ?", (user_id,))
  row = cursor.fetchone()
  conn.close()
  return row[0] if row and row[0] else "pending"


def get_all_users():
  conn = sqlite3.connect("bot_memory.db", check_same_thread=False)
  cursor = conn.cursor()
  cursor.execute("SELECT user_id FROM users WHERE language != 'pending'")
  rows = cursor.fetchall()
  conn.close()
  return [row[0] for row in rows]


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
  lang = get_user_language(user_id)
  system_prompt = BASE_SYSTEM_PROMPT.format(lang_name=lang)

  conn = sqlite3.connect("bot_memory.db", check_same_thread=False)
  cursor = conn.cursor()
  cursor.execute(
      "SELECT role, content FROM messages WHERE user_id = ? "
      "ORDER BY rowid DESC LIMIT ?",
      (user_id, HISTORY_LIMIT),
  )
  rows = cursor.fetchall()[::-1]
  conn.close()

  history = [{"role": "system", "content": system_prompt}]
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
  special_chars = ["_", "*", "[", "]", "(", ")", "~", "`", ">", "#", "+", "-", "=", "|", "{", "}", ".", "!"]
  for char in special_chars:
    text = text.replace(char, f"\\{char}")
  return text


def send_reply(chat_id, reply_text):
  hu_parts = []
  ru_parts = []

  for part in reply_text.split("###"):
    part = part.strip()
    if not part:
      continue

    if "|||" in part:
      hu, ru = [s.strip() for s in part.split("|||", 1)]
    else:
      hu, ru = part, ""

    if hu:
      hu_parts.append(hu)
    if ru:
      ru_parts.append(ru)

  # Собираем весь венгерский текст сверху
  full_hu = "\n\n".join(hu_parts)
  msg = escape_markdown_v2(full_hu)

  # Если есть переводы, собираем их и прячем под один спойлер в самом низу
  if ru_parts:
    full_ru = "\n".join(ru_parts)
    msg += f"\n\n||{escape_markdown_v2('Translation:\n' + full_ru)}||"

  bot.send_message(chat_id=chat_id, text=msg, parse_mode="MarkdownV2")


def send_proactive_message(time_of_day):
  users = get_all_users()
  if not users:
    return

  for user_id in users:
    try:
      hu, ru, count = get_or_set_user_word(user_id)
      if count <= 4:
        text_to_send = (
            f"Gyakoroljunk! Word of the day (#{count}/5): *{hu}* — {ru}. "
            f"Make a sentence with it in Hungarian! ||| Let's practice! Word"
            f" of the day (#{count}/5): {hu} — {ru}. Make a sentence in Hungarian!"
        )
      else:
        text_to_send = (
            f"Ismétlés a tudás atyja! 🧠 What is the translation of *{hu}*? "
            f"Write a translation and an example sentence in Hungarian! ||| Practice"
            f" makes perfect! 🧠 What is the translation of {hu}? Write a translation and"
            f" an example sentence! Correct translation: {ru}"
        )

      save_message(user_id, "assistant", text_to_send)
      send_reply(user_id, text_to_send)
    except Exception as e:
      print(f"Не удалось отправить сообщение пользователю {user_id}: {e}")


@bot.message_handler(commands=["reset", "start"])
def send_welcome(message):
  user_id = message.from_user.id
  register_user(user_id)
  clear_history(user_id)
  
  set_user_language(user_id, 'pending')
  bot.send_message(message.chat.id, WELCOME_TEXT)


@bot.message_handler(func=lambda message: True)
def handle_message(message):
  user_id = message.from_user.id
  text = message.text
  if not text:
    return

  register_user(user_id)
  lang = get_user_language(user_id)

  if lang == 'pending':
    set_user_language(user_id, text)
    conf_text = f"Perfect! I've set your preference to **{text}**. Now write something to me in Hungarian, for example: «Szia Réka!»"
    bot.send_message(message.chat.id, conf_text, parse_mode="Markdown")
    save_message(user_id, "assistant", conf_text + " ||| " + conf_text)
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


scheduler = BackgroundScheduler()
scheduler.add_job(
    send_proactive_message, "cron", hour=10, minute=0, args=["morning"]
)
scheduler.add_job(
    send_proactive_message, "cron", hour=14, minute=0, args=["afternoon"]
)
scheduler.add_job(
    send_proactive_message, "cron", hour=20, minute=0, args=["evening"]
)
scheduler.start()

print("Réka запущена, расписание рассылок активировано...")

while True:
  try:
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
  except Exception as e:
    print(f"Сетевая ошибка: {e}. Переподключение через 5 секунд...")
    time.sleep(5)
