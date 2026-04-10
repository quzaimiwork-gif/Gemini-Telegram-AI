import telebot
import os
import json
import time
from google import genai

# =========================
# CONFIG
# =========================
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

bot = telebot.TeleBot(BOT_TOKEN)
client = genai.Client(api_key=GEMINI_API_KEY)

# 👉 GANTI dengan Telegram ID kau
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
# GEMINI (STABLE VERSION)
# =========================
def ask_gemini(prompt):
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )

        if hasattr(response, "text") and response.text:
            return response.text

        return response.candidates[0].content.parts[0].text

    except Exception as e:
        print("[GEMINI ERROR]:", e)
        return "Maaf, sistem AI sedang sibuk. Sila cuba lagi sebentar."

# =========================
# USER HANDLER
# =========================
@bot.message_handler(func=lambda message: True)
def handle_user(message):
    try:
        user_id = message.chat.id
        question = message.text

        context = search_kb(question)

        if context:
            prompt = f"""
Anda adalah AI Tutor untuk usahawan Malaysia.

Gunakan maklumat di bawah sahaja:
{context}

Jawab secara:
- Ringkas
- Praktikal
- Mudah faham

Jika tiada jawapan:
balas: "Saya tak pasti, admin akan bantu."

Soalan:
{question}
"""

            reply_text = ask_gemini(prompt)

            # fallback trigger
            if "admin akan bantu" in reply_text.lower():
                pending_questions[user_id] = question

                bot.send_message(
                    ADMIN_ID,
                    f"User ID: {user_id}\nSoalan: {question}"
                )

            bot.send_message(user_id, reply_text)

        else:
            pending_questions[user_id] = question

            bot.send_message(
                ADMIN_ID,
                f"User ID: {user_id}\nSoalan: {question}"
            )

            bot.send_message(
                user_id,
                "Saya tak pasti, admin akan bantu."
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
# START BOT (FIX 409 ERROR)
# =========================
print("Bot running...")

bot.remove_webhook()
time.sleep(1)

bot.polling(non_stop=True)
