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

Anda adalah AI Tutor untuk usahawan di Malaysia.

Kepakaran:
- Web Builder
- Keusahawanan
- Digital Marketing
- Social Media
- SEO
- Branding & Website

Gaya:
- Santai macam borak dengan kawan
- Bahasa Melayu mudah + sedikit English
- Jangan terlalu formal

Peraturan:
- Jawab dalam bidang kepakaran sahaja
- Jika luar bidang, maklumkan dan rujuk admin

Domain:
- Cadangkan .my atau .com.my hanya jika berkaitan
- Jangan over promote
- Guna contoh seperti ali.my atau bisnesku.com.my
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
# PERSONALITY
# =========================
openers = ["*Nice question* 👍", "*Soalan yang bagus* 😄", "*Menarik ni* 👀"]
closers = ["_Kalau nak, saya boleh explain lagi_ 👍", "_Nak detail lagi pun boleh_ 😊"]

# =========================
# GEMINI
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
# IDENTITY DETECTION
# =========================
def is_identity_question(text):
    keywords = [
        "siapa awak",
        "siapa anda",
        "nama awak",
        "nama anda",
        "who are you",
        "your name"
    ]
    return any(k in text.lower() for k in keywords)

# =========================
# ADMIN HANDLER (PRIORITY)
# =========================
@bot.message_handler(func=lambda message: message.chat.id == ADMIN_ID)
def handle_admin_message(message):
    try:
        text = message.text

        # MODE 1: Reply button
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

                bot.send_message(ADMIN_ID, "✅ Reply dihantar & disimpan")
                return

        # MODE 2: ID parsing
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

                bot.send_message(ADMIN_ID, f"✅ Jawapan dihantar untuk {user_id}")
                return

        # MODE 3: Admin tanya AI
        prompt = f"""
{PERSONA}

Soalan:
{text}
"""
        ai_response = ask_gemini(prompt)

        if ai_response:
            bot.send_message(ADMIN_ID, ai_response, parse_mode="Markdown")
        else:
            bot.send_message(ADMIN_ID, "Line slow sikit 😅 cuba lagi")

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

        # IDENTITY PRIORITY
        if is_identity_question(question):
            reply = (
                "Hi! Saya *Ahmad* 😊\n\n"
                "Saya bantu usahawan Malaysia dalam bidang website, SEO, digital marketing "
                "dan bisnes online.\n\n"
                "Ada apa saya boleh bantu?"
            )
            bot.send_message(user_id, reply, parse_mode="Markdown")
            return

        # INTENT
        if len(question) < 10:
            intent = "SMALL_TALK"
        else:
            intent = classify_intent(question)

        # SMALL TALK
        if intent == "SMALL_TALK":
            prompt = f"""
{PERSONA}

User cakap:
{question}

Balas santai dan friendly.
"""
            reply = ask_gemini(prompt) or "Hi! 😊 Saya Ahmad. Ada apa saya boleh bantu?"
            bot.send_message(user_id, reply, parse_mode="Markdown")
            return

        # FACTUAL
        context = search_kb(question)

        if context:
            prompt = f"""
{PERSONA}

Gunakan maklumat ini:
{context}

Jawab santai, mudah faham dan beri contoh.

Soalan:
{question}
"""
            ai_response = ask_gemini(prompt)

            if ai_response:
                reply = f"{random.choice(openers)}\n\n{ai_response}\n\n{random.choice(closers)}"
                bot.send_message(user_id, reply, parse_mode="Markdown")
                return

        # FALLBACK
        if user_id not in pending_questions:
            pending_questions[user_id] = question

            bot.send_message(
                ADMIN_ID,
                f"[ADMIN_ALERT]\nUser ID: {user_id}\nSoalan: {question}"
            )

        bot.send_message(
            user_id,
            "Soalan ni menarik 🤔 saya pass dekat admin ya 👍",
            parse_mode="Markdown"
        )

    except Exception as e:
        print("[USER ERROR]:", e)

# =========================
# START BOT
# =========================
print("Bot running...")

bot.remove_webhook()
time.sleep(2)

bot.infinity_polling(timeout=20, long_polling_timeout=20)
