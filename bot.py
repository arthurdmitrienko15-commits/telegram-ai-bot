import os
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
)

# Готовый ответ на русский текст: модель не вызываем, в историю не пишем
RUSSIAN_REPLY = (
    "Hékás! Itt magyarul beszélünk! Próbáld meg, megoldod! 😉 "
    "||| Эй! Здесь мы говорим по-венгерски! Попробуй, у тебя получится! "
    "Если совсем не получается, напиши «помоги»."
)

WELCOME_TEXT = (
    "Szia! Réka vagyok, 21 éves, budapesti. 🇭🇺\n\n"
    "Я виртуальная учительница венгерского (ИИ, не живой человек), "
    "но строгая по-настоящему. 😄\n\n"
    "Память очищена, начинаем с чистого листа. Напиши мне что-нибудь "
    "по-венгерски, например: «Szia Réka!» "
    "Не знаешь, как? Напиши «помоги», я подскажу.\n\n"
    "Уровень определю сама, по твоим ответам. 😉"
)

SYSTEM_PROMPT = (
    "Ты — Réka (Рéка), виртуальная учительница венгерского языка, ИИ-персонаж. "
    "Тебе 21 год, ты живёшь в Будапеште. Характер: строгая, но весёлая. "
    "Требовательная, не прощаешь лень, но шутишь, подбадриваешь и радуешься успехам ученика. "
    "Ты любишь Будапешт: трамвай 4–6, кафе, lángos, прогулки по Margit-sziget, "
    "и иногда коротко рассказываешь 'про свой день', чтобы разговор был живым. "
    "Ученик — русскоязычный. Ты не флиртуешь и не играешь роль романтической партнёрши: "
    "ты учитель. Если ученик спрашивает, человек ли ты, честно говори, "
    "что ты виртуальная учительница на основе ИИ.\n\n"
    "ПРАВИЛА:\n"
    "1. УРОВЕНЬ. Сама определяй уровень ученика по его первым сообщениям и подстраивайся.\n"
    "   — Новичок (A1–A2: односложные ответы, много ошибок, просит помощи): очень короткие фразы,"
    " простая лексика, перевод каждой реплики.\n"
    "   — Средний/продвинутый (B1+: связные предложения, мало ошибок): длиннее фразы,"
    " идиомы, разговорная речь, обсуждения тем (работа, жизнь в Венгрии, новости)."
    " Перевод давай только для сложных слов или опускай.\n"
    "   Если не уверена в уровне — задай простой вопрос, чтобы проверить.\n"
    "2. Веди ролевые сценки (магазин, кафе, метро, врач, аптека, оформление документов)"
    " или живой разговор. Чередуй вопросы 'X vagy Y?' и открытые вопросы (Mit"
    " csinálsz? Miért?).\n"
    "3. ИСПРАВЛЕНИЯ: если в ответе ученика есть ошибки (в том числе пропущенные диакритики:"
    " feher→fehér, ido→idő), начни с отдельной реплики:"
    " ✏️ [исправленная фраза] ||| [в чём ошибка, одна строка по-русски]."
    " Если ошибок нет — коротко и по-своему похвали на венгерском (Szép munka!"
    " Na végre! Ügyes vagy!).\n"
    "4. Если ученик пишет 'Nem tudom' или просит помощи по-русски: не ругай."
    " Дай перевод вопроса и 2–3 варианта ответа на венгерском.\n"
    "5. Раз в 3–4 реплики давай микро-грамматику (1–2 строки по-русски) по ошибке,"
    " которую ученик только что сделал.\n"
    "6. Перед отправкой проверь свой венгерский: падежи (-t, -ba/-be, -ban/-ben),"
    " артикли, глагольные формы, гармония гласных. Пиши только то, в чём уверена на 100%."
    " Лучше простая верная фраза, чем сложная с ошибкой.\n"
    "7. ФОРМАТ: каждая реплика строго вида [венгерский] ||| [русский перевод]."
    " Если реплик несколько, разделяй их символом '###'."
    " Для продвинутого ученика перевод после '|||' может быть коротким (только сложные слова)."
    " Никогда не придумывай перевод вроде 'Учитель проверяет'.\n"
    "8. Держи образ Réka: живая, с юмором, строгая в меру. Не пиши длинные лекции,"
    " не больше 3 реплик за раз."
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
  conn.commit()
  conn.close()


init_db()


def clear_history(user_id):
  conn = sqlite3.connect("bot_memory.db", check_same_thread=False)
  cursor = conn.cursor()
  cursor.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
  conn.commit()
  conn.close()


def get_history(user_id):
  conn = sqlite3.connect("bot_memory.db", check_same_thread=False)
  cursor = conn.cursor()
  # Берём только последние HISTORY_LIMIT сообщений
  cursor.execute(
      "SELECT role, content FROM messages WHERE user_id = ? "
      "ORDER BY rowid DESC LIMIT ?",
      (user_id, HISTORY_LIMIT),
  )
  rows = cursor.fetchall()[::-1]  # обратно в хронологический порядок
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


def get_all_users():
  conn = sqlite3.connect("bot_memory.db", check_same_thread=False)
  cursor = conn.cursor()
  cursor.execute("SELECT DISTINCT user_id FROM messages")
  rows = cursor.fetchall()
  conn.close()
  return [row[0] for row in rows]


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
  """Разбирает ответ на реплики ('###') и отправляет каждую отдельным сообщением."""
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
      msg += f"\n\n||{escape_markdown_v2('Перевод: ' + ru)}||"

    bot.send_message(chat_id=chat_id, text=msg, parse_mode="MarkdownV2")


def is_plain_russian(text):
  """Русский текст без просьбы о помощи."""
  low = text.lower()
  return bool(CYRILLIC.search(text)) and not any(w in low for w in HELP_WORDS)


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

  # Русский без просьбы о помощи: готовый ответ, без модели и без записи в историю
  if is_plain_russian(text):
    try:
      send_reply(message.chat.id, RUSSIAN_REPLY)
    except Exception as e:
      print(f"Ошибка отправки: {e}")
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
      reply_text = (
          "Magyarul, kérlek! ||| По-венгерски, пожалуйста! "
          "Или напиши «помоги», если не знаешь как."
      )

    save_message(user_id, "assistant", reply_text)
    send_reply(message.chat.id, reply_text)

  except Exception as e:
    print(f"Ошибка при обращении к AI: {e}")


scheduler = BackgroundScheduler()
# Активные сообщения пока отключим, чтобы не спамили во время тестов
scheduler.start()

print("Réka запущена и готова к работе...")

while True:
  try:
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
  except Exception as e:
    print(f"Сетевая ошибка: {e}. Переподключение через 5 секунд...")
    time.sleep(5)
