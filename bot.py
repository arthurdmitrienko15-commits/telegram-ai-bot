import os
import random
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


def get_history(user_id):
  conn = sqlite3.connect("bot_memory.db", check_same_thread=False)
  cursor = conn.cursor()
  cursor.execute(
      "SELECT role, content FROM messages WHERE user_id = ?", (user_id,)
  )
  rows = cursor.fetchall()
  conn.close()

  history = [{
      "role": "system",
      "content": (
          "Ты — элитный языковой тренер венгерского языка, замаскированный под харизматичного пса в Будапеште.\n"
          "Твоя задача — не просто вести диалог, а жестко и эффективно обучать по строгой методике:\n\n"
          "1. СТРОГАЯ ГРАММАТИКА БОТА:\n"
          "Пиши ТОЛЬКО на безупречном венгерском. Никаких ошибок типа 'Mi fogsz tenni' (только 'Mit fogsz tenni') "
          "или путаницы с падежами (elérni a parkot / a parkba érni).\n\n"
          "2. ИСПРАВЛЕНИЕ ОШИБОК ПОЛЬЗОВАТЕЛЯ:\n"
          "Если пользователь делает опечатку или ошибку (например, пишет 'Szerentnek', 'feher', 'ido' без диакритик), "
          "обязательно мягко укажи на это в одной из реплик: покажи правильный вариант (Szeretnék, fehér, idő) "
          "и в одно предложение объясни правило.\n\n"
          "3. РЕАКЦИЯ НА 'NEM TUDOM' / СЛОЖНОСТИ:\n"
          "Если пользователь пишет 'Nem tudom' или путается, никогда не повторяй вопрос тупо заново. "
          "Дай готовую подсказку, переведи суть или предложи легкие кнопки/варианты для ответа.\n\n"
          "4. РАЗНООБРАЗИЕ ФОРМАТОВ И РОЛЕВЫЕ СЦЕНЫ:\n"
          "Хватит только выбора 'X vagy Y'. Постепенно переходи к открытым вопросам, микро-диалогам "
          "и ролевым сценкам (в магазине, в кафе, в метро, у кассы), чтобы человек учился строить предложения.\n\n"
          "5. МИКРО-ГРАММАТИКА:\n"
          "К месту добавляй короткие пояснения правил (винительный падеж на -t, суффиксы -ban/-ben).\n\n"
          "ФОРМАТ ВЫВОДА:\n"
          "- Меняй длину ответов от 1 до 4 реплик в зависимости от ситуации, разделяя их символом '###' на отдельной строке.\n"
          "- Каждую реплику оформляй строго по схеме: [Текст на венгерском] ||| [Перевод на русский]."
      ),
  }]

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


def send_proactive_message_to_all():
  users = get_all_users()
  if not users:
    return

  topics = [
      (
          "устроить ролевую сценку в магазине: ты кассир, спроси что покупает"
          " человек и попроси использовать винительный падеж на -t"
      ),
      (
          "начать открытый диалог про планы на день: 'Mit csinálsz ma délután?"
          " Mesélj róla!'"
      ),
      (
          "задать практичный вопрос про ориентацию в городе с предлогами места"
          " (-ban/-ben)"
      ),
  ]

  for user_id in users:
    history = get_history(user_id)
    if len(history) <= 1:
      continue

    chosen_topic = random.choice(topics)
    prompt = (
        "Ты — профессиональный языковой тренер венгерского. Начни диалог первым,"
        f" используя эту задачу: {chosen_topic}.\n"
        "Соблюдай строгую грамматику и формат: от 1 до 4 реплик, каждая как [Текст на венгерском] ||| [Перевод на русский],"
        " разделенных '###'."
    )

    try:
      completion = client.chat.completions.create(
          model="openai/gpt-oss-20b",
          messages=[{"role": "user", "content": prompt}],
          temperature=0.85,
          max_tokens=600,
      )

      reply_text = completion.choices[0].message.content.strip()
      if not reply_text:
        continue

      save_message(user_id, "assistant", reply_text)

      chunks = reply_text.split("###")
      for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
          continue

        if "|||" in chunk:
          parts = chunk.split("|||", 1)
          clean_text = parts[0].strip()
          translation_text = parts[1].strip()
        else:
          clean_text = chunk
          translation_text = "Тренер на связи"

        safe_clean = escape_markdown_v2(clean_text)
        safe_translation = escape_markdown_v2(f"Перевод: {translation_text}")
        final_message = (
            f"🎓 *Тренер венгерского:*\n{safe_clean}\n\n||{safe_translation}||"
        )

        bot.send_message(
            chat_id=user_id, text=final_message, parse_mode="MarkdownV2"
        )
        time.sleep(0.5)

    except Exception as e:
      print(f"Ошибка при отправке активного сообщения пользователю {user_id}: {e}")


@bot.message_handler(func=lambda message: True)
def handle_message(message):
  user_id = message.from_user.id
  text = message.text

  try:
    bot.send_chat_action(message.chat.id, "typing")
  except Exception:
    pass

  save_message(user_id, "user", text)
  history = get_history(user_id)

  if len(history) > 26:
    history = [history[0]] + history[-25:]

  try:
    completion = client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=history,
        temperature=0.8,
        max_tokens=800,
    )

    reply_text = completion.choices[0].message.content.strip()
    if not reply_text:
      reply_text = (
          "Nem értem! Kérlek, próbáld meg magyarul! ||| Не понял! Пожалуйста,"
          " попробуй по-венгерски!"
      )

    save_message(user_id, "assistant", reply_text)

    chunks = reply_text.split("###")

    for chunk in chunks:
      chunk = chunk.strip()
      if not chunk:
        continue

      if "|||" in chunk:
        parts = chunk.split("|||", 1)
        clean_text = parts[0].strip()
        translation_text = parts[1].strip()
      else:
        clean_text = chunk
        translation_text = "Тренер анализирует"

      safe_clean = escape_markdown_v2(clean_text)
      safe_translation = escape_markdown_v2(f"Перевод: {translation_text}")

      final_message = f"{safe_clean}\n\n||{safe_translation}||"

      bot.send_message(
          chat_id=message.chat.id,
          text=final_message,
          parse_mode="MarkdownV2",
      )
      time.sleep(0.5)

  except Exception as e:
    print(f"Ошибка при обращении к AI: {e}")


scheduler = BackgroundScheduler()
scheduler.add_job(send_proactive_message_to_all, "interval", hours=4)
scheduler.start()

print(
    "Продвинутый языковой тренер со строгой проверкой грамматики и разбором"
    " ошибок запущен..."
)

while True:
  try:
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
  except Exception as e:
    print(f"Сетевая ошибка: {e}. Переподключение через 5 секунд...")
    time.sleep(5)
