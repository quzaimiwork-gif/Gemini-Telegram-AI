import telebot
import os
import json
import time
import re
from google import genai

# =========================
# GOOGLE CREDENTIALS (ENV → FILE)
# =========================
if "GOOGLE_CREDENTIALS" in os.environ:
    creds = json.loads(os.environ["GOOGLE_CREDENTIALS"])
    with open("service-account.json", "w") as f:
        json.dump(creds, f)

    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "service-account.json"

# =========================
# GEMINI (VERTEX MODE - NEW SDK)
# =========================
client = genai.Client(
    vertexai=True,
    project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
    location="us-central1"  # 🔥 IMPORTANT for Gemini 2.5 Pro
)

# =========================
# TELEGRAM CONFIG
# =========================
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)

ADMIN_ID = 693749347
pending_questions = {}

# =========================
# PERSONA AHMAD
# =========================
PERSONA = """
Nama anda Ahmad.
Anda AI Assistant untuk usahawan Malaysia.

Gaya:
- Santai, friendly, macam borak
- Melayu + English sikit
- Jawapan ringkas & jelas

Fokus:
- Website
- Digital Marketing
- SEO
- Social Media

Kalau sesuai, cadangkan domain .my secara natural.
"""

# =========================
# LOAD KNOWLEDGE BASE
# =========================
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
# AI FUNCTION (GEMINI 2.5 PRO)
# =========================
def ask_ai(prompt):

    for i in range(3):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-pro",
                contents=prompt
            )

            if response.text:
                return response.text

        except Exception as e:
            print(f"[RETRY {i+1} ERROR]:", e)
            time.sleep(2)

    return None

# =========================
# IDENTITY CHECK
# =========================
def is_identity_question(text):
    keywords = [
        "siapa awak", "nama awak",
        "who are you", "your name"
    ]
    return any(k in text.lower() for k in keywords)

# =========================
# ADMIN HANDLER
# =========================
@bot.message_handler(func=lambda message: message.chat.id == ADMIN_ID)
def handle_admin(message):
    text = message.text

    # Reply mode (answer user)
    if message.reply_to_message:
        original = message.reply_to_message.text

        if "[ADMIN_ALERT]" in original:
            user_id = int(original.split("\n")[1].replace("User ID: ", ""))

            bot.send_message(user_id, text)

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

            bot.send_message(ADMIN_ID, "✅ Saved to KB")
            return

    # Admin ask AI
    ai = ask_ai(f"{PERSONA}\n{text}")

    if ai:
        bot.send_message(ADMIN_ID, ai)
    else:
        bot.send_message(ADMIN_ID, "AI busy 😅")

# =========================
# USER HANDLER
# =========================
@bot.message_handler(func=lambda message: True)
def handle_user(message):

    user_id = message.chat.id
    question = message.text

    # Identity question
    if is_identity_question(question):
        bot.send_message(user_id, "Hi! Saya Ahmad 😊")
        return

    bot.send_message(user_id, "Saya tengah fikir 🤔...")

    # KB first
    context = search_kb(question)

    if context:
        ai = ask_ai(f"{PERSONA}\n{context}\n{question}")
        if ai:
            bot.send_message(user_id, ai)
            return

    # Direct AI
    ai = ask_ai(f"{PERSONA}\n{question}")

    if ai:
        bot.send_message(user_id, ai)
    else:
        pending_questions[user_id] = question

        bot.send_message(
            ADMIN_ID,
            f"[ADMIN_ALERT]\nUser ID: {user_id}\nSoalan: {question}"
        )

        bot.send_message(user_id, "Line busy 😅 saya pass ke admin")

# =========================
# START BOT
# =========================
print("Bot running...")

bot.remove_webhook()
time.sleep(2)

bot.infinity_polling(timeout=20, long_polling_timeout=20)
