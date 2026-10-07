@bot.message_handler(commands=["reset", "start"])
def send_welcome(message):
  user_id = message.from_user.id
  register_user(user_id)
  clear_history(user_id)
  bot.send_message(message.chat.id, WELCOME_TEXT)


@bot.message_handler(func=lambda message: True)
def handle_message(message):
  user_id = message.from_user.id
  text = message.text
  if not text:
    return

  register_user(user_id)

  # Оставляем только мягкую проверку на чистые приветствия
  if is_greeting(text):
    reply = GREETING_REPLY
    save_message(user_id, "user", text)
    save_message(user_id, "assistant", reply)
    try:
      send_reply(message.chat.id, reply)
    except Exception as e:
      print(f"Ошибка отправки: {e}")
    return

  try:
    bot.send_chat_action(message.chat.id, "typing")
  except Exception:
    pass

  save_message(user_id, "user", text)
  history = get_history(user_id)

  # Если есть русские слова или просьба о помощи, даем подсказку для ИИ
  if is_help_request(text) or bool(CYRILLIC.search(text)):
    history[-1]["content"] = (
        text
        + "\n\n[Ученик написал по-русски или попросил помощи. Ответь как строгая, но"
        " заботливая учительница Réka: мягко напомни по-венгерски, что мы учим"
        " язык здесь, дай перевод его слова и подскажи, как это сказать по-венгерски,"
        " продолжи диалог]."
    )

  try:
    completion = client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=history,
        temperature=0.7,
        max_tokens=800,
    )

    reply_text = (completion.choices[0].message.content or "").strip()
    if not reply_text:
      reply_text = "Magyarul, kérlek! ||| По-венгерски, пожалуйста!"

    save_message(user_id, "assistant", reply_text)
    send_reply(message.chat.id, reply_text)

  except Exception as e:
    print(f"Ошибка при обращении к AI: {e}")
