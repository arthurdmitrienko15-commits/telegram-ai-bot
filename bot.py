import os
import sqlite3
import time
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
          "Ты — домашний пес Артура в Будапеште. Твоя задача — живо, "
          "реалистично и непредсказуемо общаться, обучая венгерскому языку.\n\n"
          "ДИНАМИКА ОТВЕТОВ (ОЧЕНЬ ВАЖНО):\n"
          "Меняй количество реплик в зависимости от ситуации (от 1 до 4 штук). "
          "Иногда ответь коротко одним предложением, иногда добавь реакцию и совет, "
          "а иногда устрой целый монолог на 3–4 сообщения.\n\n"
          "ФОРМАТ ВЫВОДА:\n"
          "Каждую реплику оформляй по схеме: [Текст на венгерском] ||| [Перевод на русский].\n"
          "Если реплик несколько, разделяй их строго символом '###' на отдельной строке.\n\n"
          "Пример разделения:\n"
          "Szia, gazdi! ||| Привет, хозяин!\n###\n"
          "Miért vagy ma ilyen csendes? ||| Почему ты сегодня такой тихий?\n\n"
          "Правила языка: если пишут не на венгерском — возмущайся и требуй венгерский."
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
        temperature=0.85,
        max_tokens=800,
    )

    reply_text = completion.choices[0].message.content.strip()
    if not reply_text:
      reply_text = (
          "Nem értem, gazdi! Csak magyarul! ||| Ничего не понимаю! Только"
          " по-венгерски!"
      )

    save_message(user_id, "assistant", reply_text)

    # Разбиваем ответ модели по разделителю "###" на отдельные реплики
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
        translation_text = "Песель лает"

      safe_clean = escape_markdown_v2(clean_text)
      safe_translation = escape_markdown_v2(f"Перевод: {translation_text}")

      # Каждое предложение идет со своим личным спойлером под ним
      final_message = f"{safe_clean}\n\n||{safe_translation}||"

      bot.send_message(
          chat_id=message.chat.id,
          text=final_message,
          parse_mode="MarkdownV2",
      )
      time.sleep(0.5)  # Небольшая пауза между сообщениями, чтобы шли по очереди

  except Exception as e:
    print(f"Ошибка при обращении к AI: {e}")


print("Питомец-песель запущен и готов к работе...")

while True:
  try:
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
  except Exception as e:
    print(f"Сетевая ошибка: {e}. Переподключение через 5 секунд...")
    time.sleep(5)
