import telebot
import os
import json
import time
import random
from google import genai

# =========================
# CONFIG
# =========================
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

bot = telebot.TeleBot(BOT_TOKEN)
client = genai.Client(api_key=GEMINI_API_KEY)

ADMIN_ID = 693749347

pending_questions = {}

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
# PERSONALITY
# =========================
openers = [
    "*Nice question* 👍",
    "*Soalan yang bagus* 😄",
    "*Menarik ni* 👀",
]

closers = [
    "_Kalau nak, saya boleh explain lagi_ 👍",
    "_Nak detail lagi pun boleh_ 😊",
]

# =========================
# GEMINI CALL (RETRY)
# =========================
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

# =========================
# INTENT CLASSIFICATION
# =========================
def classify_intent(text):
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"""
Klasifikasikan ayat ini kepada salah satu sahaja:

1. SMALL_TALK
2. QUESTION

Jawab satu perkataan sahaja.

Ayat:
{text}
"""
        )

        result = response.text.strip().upper()

        if "SMALL_TALK" in result:
            return "SMALL_TALK"
        else:
            return "QUESTION"

    except:
        return "QUESTION"

# =========================
# USER HANDLER
# =========================
@bot.message_handler(func=lambda message: True)
def handle_user(message):
    try:
        user_id = message.chat.id
        question = message.text

        opening = random.choice(openers)
        closing = random.choice(closers)

        # detect intent
        if len(question) < 10:
            intent = "SMALL_TALK"
        else:
            intent = classify_intent(question)

        # =========================
        # SMALL TALK
        # =========================
        if intent == "SMALL_TALK":
            prompt = f"""
Anda AI mesra.

User cakap:
{question}

Balas secara santai, friendly dan pendek.

Gunakan format Telegram:
- Bold guna *text*
- Jangan guna **
"""
            ai_response = ask_gemini(prompt)

            if ai_response:
                bot.send_message(user_id, ai_response, parse_mode="Markdown")
            else:
                bot.send_message(user_id, "Hi! 😊 Ada apa yang saya boleh bantu?", parse_mode="Markdown")

            return

        # =========================
        # FACTUAL (USE KB)
        # =========================
        context = search_kb(question)

        if context:
            prompt = f"""
Anda AI Tutor untuk usahawan Malaysia.

Gunakan maklumat ini sahaja:
{context}

Jawab secara:
- Santai
- Mudah faham
- Beri contoh

Jika berkaitan domain:
- Cadangkan guna *domain .my* atau *.com.my*
- Tekankan kelebihan local branding Malaysia

Gunakan format Telegram:
- Bold guna *text*
- Jangan guna **

Soalan:
{question}
"""
            ai_response = ask_gemini(prompt)

            if ai_response:
                reply = f"{opening}\n\n{ai_response}\n\n{closing}"
                bot.send_message(user_id, reply, parse_mode="Markdown")
                return

        # =========================
        # FALLBACK ADMIN
        # =========================
        pending_questions[user_id] = question

        bot.send_message(
            ADMIN_ID,
            f"User ID: {user_id}\nSoalan: {question}"
        )

        bot.send_message(
            user_id,
            "Soalan ni menarik 🤔 saya pass ke admin ya 👍",
            parse_mode="Markdown"
        )

    except Exception as e:
        print("[USER ERROR]:", e)

# =========================
# ADMIN REPLY
# =========================
@bot.message_handler(func=lambda m: m.reply_to_message is not None)
def handle_admin_reply(message):
    try:
        original = message.reply_to_message.text

        if "User ID:" in original:
            user_id = int(original.split("\n")[0].replace("User ID: ", ""))
            bot.send_message(user_id, message.text, parse_mode="Markdown")

    except Exception as e:
        print("[ADMIN ERROR]:", e)

# =========================
# START BOT
# =========================
print("Bot running...")

bot.remove_webhook()
time.sleep(2)

bot.infinity_polling(timeout=20, long_polling_timeout=20)
