import telebot
import os
import json
import time
import random
import re
from google import genai

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

bot = telebot.TeleBot(BOT_TOKEN)
client = genai.Client(api_key=GEMINI_API_KEY)

ADMIN_ID = 693749347
pending_questions = {}

PERSONA = """
Nama anda Ahmad.
Anda AI Tutor untuk usahawan Malaysia.

Gaya santai, mudah faham.
Fokus pada web, marketing, SEO dan bisnes digital.
"""

with open("knowledge.json") as f:
    KB = json.load(f)

def search_kb(question):
    results = []
    for chunk in KB:
        for keyword in chunk["keywords"]:
            if keyword.lower() in question.lower():
                results.append(chunk["content"])
    return results[:3]

# =========================
# GEMINI (FINAL CLEAN)
# =========================
def ask_gemini(prompt):

    for i in range(5):  # lebih retry
        try:
            time.sleep(random.uniform(0.5, 1.5))

            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt
            )

            if hasattr(response, "text") and response.text:
                return response.text

            if hasattr(response, "candidates"):
                parts = response.candidates[0].content.parts
                if parts and hasattr(parts[0], "text"):
                    return parts[0].text

        except Exception as e:
            print(f"[RETRY {i+1} ERROR]:", e)
            time.sleep(2)

    return None

# =========================
# ADMIN HANDLER
# =========================
@bot.message_handler(func=lambda message: message.chat.id == ADMIN_ID)
def handle_admin(message):
    text = message.text

    if message.reply_to_message:
        original = message.reply_to_message.text

        if "[ADMIN_ALERT]" in original:
            user_id = int(original.split("\n")[1].replace("User ID: ", ""))

            bot.send_message(user_id, text, parse_mode="Markdown")

            question = pending_questions.get(user_id)

            if question:
                with open("knowledge.json", "r+") as f:
                    data = json.load(f)
                    data.append({
                        "id": f"auto_{len(data)+1}",
                        "keywords": question.lower().split(),
                        "content": text
                    })
                    f.seek(0)
                    json.dump(data, f, indent=2)

            bot.send_message(ADMIN_ID, "✅ Saved")
            return

    # admin tanya AI
    ai = ask_gemini(f"{PERSONA}\n{text}")

    if ai:
        bot.send_message(ADMIN_ID, ai, parse_mode="Markdown")
    else:
        bot.send_message(ADMIN_ID, "AI busy 😅 cuba lagi")

# =========================
# USER HANDLER
# =========================
@bot.message_handler(func=lambda message: True)
def handle_user(message):

    user_id = message.chat.id
    question = message.text

    bot.send_message(user_id, "Saya tengah fikir 🤔...")

    ai = ask_gemini(f"{PERSONA}\n{question}")

    if ai:
        bot.send_message(user_id, ai, parse_mode="Markdown")
    else:
        pending_questions[user_id] = question

        bot.send_message(
            ADMIN_ID,
            f"[ADMIN_ALERT]\nUser ID: {user_id}\nSoalan: {question}"
        )

        bot.send_message(
            user_id,
            "Line busy 😅 saya pass ke admin ya"
        )

# =========================
# START
# =========================
print("Bot running...")

bot.remove_webhook()
time.sleep(2)

bot.infinity_polling(timeout=20, long_polling_timeout=20)
