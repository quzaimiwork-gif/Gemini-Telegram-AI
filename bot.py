import telebot
import os
import json
import time
import random
from google import genai

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

bot = telebot.TeleBot(BOT_TOKEN)
client = genai.Client(api_key=GEMINI_API_KEY)

ADMIN_ID = 693749347

pending_questions = {}

with open("knowledge.json") as f:
    KB = json.load(f)

def search_kb(question):
    results = []
    for chunk in KB:
        for keyword in chunk["keywords"]:
            if keyword.lower() in question.lower():
                results.append(chunk["content"])
    return results[:3]

openers = ["Soalan yang bagus 😄", "Nice question 👍", "Menarik ni 👀"]
closers = ["Nak detail lagi pun boleh 😊", "Tanya je lagi kalau nak 👍"]

def ask_gemini(prompt):
    for i in range(3):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt
            )

            if hasattr(response, "text") and response.text:
                return response.text

            return response.candidates[0].content.parts[0].text

        except Exception as e:
            print(f"[RETRY {i+1} ERROR]:", e)
            time.sleep(2)

    return None

@bot.message_handler(func=lambda message: True)
def handle_user(message):
    try:
        user_id = message.chat.id
        question = message.text

        opening = random.choice(openers)
        closing = random.choice(closers)

        context = search_kb(question)

        if context:
            prompt = f"""
Anda AI Tutor santai untuk usahawan Malaysia.

Jawab secara santai, mudah faham dan beri contoh.

Context:
{context}

Soalan:
{question}
"""

            ai_response = ask_gemini(prompt)

            if ai_response:
                bot.send_message(user_id, f"{opening}\n\n{ai_response}\n\n{closing}")
            else:
                bot.send_message(user_id, "Saya tengah fikir 😅 tunggu kejap ya...")

                retry = ask_gemini(prompt)

                if retry:
                    bot.send_message(user_id, f"Okay dah dapat 👇\n\n{retry}")
                else:
                    pending_questions[user_id] = question

                    bot.send_message(
                        ADMIN_ID,
                        f"User ID: {user_id}\nSoalan: {question}"
                    )

                    bot.send_message(user_id, "Line slow sikit 😅 saya pass ke admin ya 👍")

        else:
            pending_questions[user_id] = question

            bot.send_message(
                ADMIN_ID,
                f"User ID: {user_id}\nSoalan: {question}"
            )

            bot.send_message(user_id, "Soalan ni menarik 🤔 saya pass ke admin ya 👍")

    except Exception as e:
        print("[USER ERROR]:", e)

@bot.message_handler(func=lambda m: m.reply_to_message is not None)
def handle_admin_reply(message):
    try:
        original = message.reply_to_message.text

        if "User ID:" in original:
            user_id = int(original.split("\n")[0].replace("User ID: ", ""))
            bot.send_message(user_id, message.text)

    except Exception as e:
        print("[ADMIN ERROR]:", e)

print("Bot running...")

bot.remove_webhook()
time.sleep(2)

bot.infinity_polling(timeout=20, long_polling_timeout=20)
