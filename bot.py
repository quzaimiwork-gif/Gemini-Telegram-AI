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

ADMIN_ID = 123456789  # 👉 GANTI dengan ID kau

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
# RANDOM PERSONALITY
# =========================
openers = [
    "Soalan yang bagus tu 😄",
    "Nice question ni 👍",
    "Ramai juga confuse benda ni",
    "Good one!",
    "Okay ini menarik 👀",
    "Best soalan ni actually",
]

closers = [
    "Kalau nak, saya boleh bagi contoh lagi 👍",
    "Nak saya explain lagi detail pun boleh 😊",
    "Kalau kau nak, kita boleh breakdown lagi step-by-step",
    "Kalau masih blur, tanya je lagi ya 😄",
    "Boleh je kalau nak saya bantu lebih detail",
]

# =========================
# GEMINI (STABLE)
# =========================
def ask_gemini(prompt):
    try:
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt
        )

        if hasattr(response, "text") and response.text:
            return response.text

        return response.candidates[0].content.parts[0].text

    except Exception as e:
        print("[GEMINI ERROR]:", e)
        return None

# =========================
# USER HANDLER
# =========================
@bot.message_handler(func=lambda message: True)
def handle_user(message):
    try:
        user_id = message.chat.id
        question = message.text

        context = search_kb(question)

        opening = random.choice(openers)
        closing = random.choice(closers)

        # =========================
        # ADA CONTEXT → AI JAWAB
        # =========================
        if context:
            prompt = f"""
Anda adalah AI Tutor mesra untuk usahawan Malaysia.

Gaya:
- Santai, macam bercakap dengan kawan
- Bahasa Melayu mudah + sedikit English
- Jangan terlalu formal atau skema

Struktur:
- Mulakan dengan ayat engaging
- Terangkan ringkas
- Boleh beri contoh mudah
- Akhiri dengan ayat friendly

Gunakan maklumat ini sahaja:
{context}

Soalan:
{question}
"""

            ai_response = ask_gemini(prompt)

            if ai_response:
                reply_text = f"{opening}\n\n{ai_response}\n\n{closing}"
            else:
                reply_text = "Maaf, sistem AI tengah sibuk sikit. Cuba lagi kejap ya 🙏"

            # fallback trigger
            if "tak pasti" in reply_text.lower():
                pending_questions[user_id] = question

                bot.send_message(
                    ADMIN_ID,
                    f"User ID: {user_id}\nSoalan: {question}"
                )

            bot.send_message(user_id, reply_text)

        # =========================
        # TAK ADA CONTEXT → ADMIN
        # =========================
        else:
            pending_questions[user_id] = question

            bot.send_message(
                ADMIN_ID,
                f"User ID: {user_id}\nSoalan: {question}"
            )

            bot.send_message(
                user_id,
                "Soalan ni menarik 🤔 tapi saya tak pasti. Saya pass dekat admin ya 👍"
            )

    except Exception as e:
        print("[USER ERROR]:", e)
        bot.send_message(
            message.chat.id,
            "Maaf, sistem tengah ada gangguan."
        )

# =========================
# ADMIN REPLY
# =========================
@bot.message_handler(func=lambda m: m.reply_to_message is not None)
def handle_admin_reply(message):
    try:
        original = message.reply_to_message.text

        if "User ID:" in original:
            user_id = int(original.split("\n")[0].replace("User ID: ", ""))

            bot.send_message(user_id, message.text)

            # auto learning
            question = pending_questions.get(user_id)

            if question:
                with open("knowledge.json", "r+") as f:
                    data = json.load(f)

                    data.append({
                        "id": f"auto_{len(data)+1}",
                        "keywords": [question.lower()],
                        "content": message.text
                    })

                    f.seek(0)
                    json.dump(data, f, indent=2)

    except Exception as e:
        print("[ADMIN ERROR]:", e)

# =========================
# START BOT
# =========================
print("Bot running...")

bot.remove_webhook()
time.sleep(1)

bot.polling(non_stop=True)
