import telebot
import os
import json
from google import genai

# =========================
# CONFIG
# =========================
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

bot = telebot.TeleBot(BOT_TOKEN)
client = genai.Client(api_key=GEMINI_API_KEY)

# 👉 GANTI dengan Telegram ID kau nanti
ADMIN_ID = 123456789  

# simpan soalan pending
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
# USER MESSAGE HANDLER
# =========================
@bot.message_handler(func=lambda message: True)
def handle_user(message):
    try:
        user_id = message.chat.id
        question = message.text

        context = search_kb(question)

        # ✅ IF ADA KNOWLEDGE
        if context:
            prompt = f"""
Anda adalah AI Tutor untuk usahawan Malaysia.

Gunakan maklumat di bawah sahaja:
{context}

Jawab secara:
- Ringkas
- Praktikal
- Mudah faham

Jika tiada jawapan dalam konteks:
balas: "Saya tak pasti, admin akan bantu."

Soalan:
{question}
"""

            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt
            )

            reply_text = response.text

            # 🚨 detect kalau AI tak tahu
            if "admin akan bantu" in reply_text.lower():
                pending_questions[user_id] = question

                bot.send_message(
                    ADMIN_ID,
                    f"User ID: {user_id}\nSoalan: {question}"
                )

            bot.send_message(user_id, reply_text)

        # ❌ TAK ADA KNOWLEDGE → fallback
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
        print("ERROR:", e)
        bot.send_message(
            message.chat.id,
            "Maaf, sistem tengah ada gangguan."
        )


# =========================
# ADMIN REPLY HANDLER
# =========================
@bot.message_handler(func=lambda m: m.reply_to_message is not None)
def handle_admin_reply(message):
    try:
        original = message.reply_to_message.text

        if "User ID:" in original:
            user_id = int(original.split("\n")[0].replace("User ID: ", ""))

            # hantar jawapan admin ke user
            bot.send_message(user_id, message.text)

            # OPTIONAL: auto learn
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
        print("ADMIN ERROR:", e)


# =========================
# START BOT
# =========================
print("Bot running...")
bot.polling()
