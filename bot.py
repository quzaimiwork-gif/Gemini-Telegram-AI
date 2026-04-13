import telebot
import os
import json
import time
import random
import re
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
# PERSONA AHMAD
# =========================
PERSONA = """
Nama anda Ahmad.

Anda AI Tutor untuk usahawan Malaysia.

Kepakaran:
- Web Builder
- Digital Marketing
- SEO
- Social Media
- Branding & Website

Gaya:
- Santai macam borak
- Bahasa Melayu mudah + sedikit English

Peraturan:
- Jawab dalam bidang ini sahaja
- Jika luar bidang, maklumkan dan pass ke admin

Domain:
- Cadangkan .my hanya bila relevan
- Contoh: ali.my, bisnesku.com.my
"""

# =========================
# LOAD KB
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
# GEMINI ULTRA STABLE
# =========================
def ask_gemini(prompt):

    # 🔥 anti-spike delay
    time.sleep(random.uniform(0.5, 1.5))

    models = [
        "gemini-2.5-flash",
        "gemini-1.5-flash"
    ]

    for model in models:
        for i in range(2):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt
                )

                if hasattr(response, "text") and response.text:
                    return response.text

                if hasattr(response, "candidates"):
                    return response.candidates[0].content.parts[0].text

            except Exception as e:
                print(f"[{model} RETRY {i+1} ERROR]:", e)
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
Klasifikasikan ayat ini:

SMALL_TALK atau QUESTION sahaja.

Ayat:
{text}
"""
        )
        result = response.text.strip().upper()
        return "SMALL_TALK" if "SMALL_TALK" in result else "QUESTION"
    except:
        return "QUESTION"

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
    try:
        text = message.text

        # Reply mode
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

                bot.send_message(ADMIN_ID, "✅ Saved to KB")
                return

        # ID parsing mode
        numbers = re.findall(r'\b\d{6,}\b', text)

        for num in numbers:
            user_id = int(num)

            if user_id in pending_questions:
                clean_text = text.replace(num, "").strip()

                bot.send_message(user_id, clean_text, parse_mode="Markdown")

                question = pending_questions.get(user_id)

                if question:
                    with open("knowledge.json", "r+") as f:
                        data = json.load(f)
                        data.append({
                            "id": f"auto_{len(data)+1}",
                            "keywords": question.lower().split(),
                            "content": clean_text
                        })
                        f.seek(0)
                        json.dump(data, f, indent=2)

                bot.send_message(ADMIN_ID, f"✅ Sent to {user_id}")
                return

        # Admin tanya AI
        prompt = f"{PERSONA}\n\nSoalan:\n{text}"
        ai = ask_gemini(prompt)

        if ai:
            bot.send_message(ADMIN_ID, ai, parse_mode="Markdown")
        else:
            bot.send_message(ADMIN_ID, "Line busy 😅 cuba lagi")

    except Exception as e:
        print("[ADMIN ERROR]:", e)

# =========================
# USER HANDLER
# =========================
@bot.message_handler(func=lambda message: True)
def handle_user(message):
    try:
        user_id = message.chat.id
        question = message.text

        # Identity
        if is_identity_question(question):
            bot.send_message(
                user_id,
                "Hi! Saya *Ahmad* 😊\nSaya bantu usahawan dalam digital & bisnes online.",
                parse_mode="Markdown"
            )
            return

        # Intent
        intent = "SMALL_TALK" if len(question) < 10 else classify_intent(question)

        # Small talk
        if intent == "SMALL_TALK":
            prompt = f"{PERSONA}\nUser: {question}"
            reply = ask_gemini(prompt) or "Hi! 😊"
            bot.send_message(user_id, reply, parse_mode="Markdown")
            return

        # KB
        context = search_kb(question)

        if context:
            prompt = f"{PERSONA}\nContext:\n{context}\n\nSoalan:\n{question}"
            ai = ask_gemini(prompt)

            if ai:
                bot.send_message(user_id, ai, parse_mode="Markdown")
                return

        # Smart retry UX
        bot.send_message(user_id, "Saya tengah fikir 🤔 tunggu sikit ya...")

        retry = ask_gemini(f"{PERSONA}\nSoalan:\n{question}")

        if retry:
            bot.send_message(user_id, retry, parse_mode="Markdown")
        else:
            pending_questions[user_id] = question

            bot.send_message(
                ADMIN_ID,
                f"[ADMIN_ALERT]\nUser ID: {user_id}\nSoalan: {question}"
            )

            bot.send_message(
                user_id,
                "Line agak busy 😅 saya pass ke admin ya",
                parse_mode="Markdown"
            )

    except Exception as e:
        print("[USER ERROR]:", e)

# =========================
# START
# =========================
print("Bot running...")

bot.remove_webhook()
time.sleep(2)

bot.infinity_polling(timeout=20, long_polling_timeout=20)
