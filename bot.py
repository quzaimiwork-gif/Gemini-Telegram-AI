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
# GEMINI (VERTEX MODE)
# =========================
client = genai.Client(
    vertexai=True,
    project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
    location="us-central1"
)

# =========================
# TELEGRAM CONFIG
# =========================
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)

ADMIN_ID = 693749347
pending_questions = {}

# =========================
# PERSONA
# =========================
SYSTEM_RULE = """
Nama anda Ahmad.
Anda AI Assistant untuk usahawan Malaysia.

Fokus:
- Website
- SEO
- Digital Marketing
- Social Media
- Domain

Gaya santai, friendly, ringkas & jelas.
"""

# =========================
# LOAD KB
# =========================
with open("knowledge.json") as f:
    KB = json.load(f)

# =========================
# STRICT KB SEARCH + DEBUG
# =========================
def search_kb(question):
    results = []
    question_words = set(question.lower().split())

    print("\n[DEBUG] Question words:", question_words)

    for chunk in KB:
        keyword_set = set(k.lower() for k in chunk["keywords"])
        match = question_words & keyword_set

        print("[DEBUG] Checking:", keyword_set)
        print("[DEBUG] Match:", match)

        # 🔥 STRICT: minimum 2 keyword match
        if len(match) >= 2:
            print("[DEBUG] ✅ MATCHED:", chunk["content"][:60])
            results.append(chunk["content"])

    print("[DEBUG] Final context:", results)
    return results[:3]

# =========================
# HTML FORMAT
# =========================
def to_html(text):
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")

    text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\*(.*?)\*", r"<b>\1</b>", text)

    return text

# =========================
# AI FUNCTION
# =========================
def ask_ai(prompt):
    for i in range(3):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-pro",
                contents=f"{SYSTEM_RULE}\n\n{prompt}"
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
    keywords = ["siapa awak", "nama awak", "who are you"]
    return any(k in text.lower() for k in keywords)

# =========================
# ADMIN HANDLER
# =========================
@bot.message_handler(func=lambda message: message.chat.id == ADMIN_ID)
def handle_admin(message):
    try:
        text = message.text

        # Reply to user → save to KB
        if message.reply_to_message:
            original = message.reply_to_message.text

            if "[ADMIN_ALERT]" in original:
                user_id = int(original.split("\n")[1].replace("User ID: ", ""))

                bot.send_message(user_id, to_html(text), parse_mode="HTML")

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
        ai = ask_ai(text)

        if ai:
            bot.send_message(ADMIN_ID, to_html(ai), parse_mode="HTML")
        else:
            bot.send_message(ADMIN_ID, "AI busy 😅")

    except Exception as e:
        print("[ADMIN ERROR]:", e)

# =========================
# USER HANDLER (STRICT KB)
# =========================
@bot.message_handler(func=lambda message: True)
def handle_user(message):
    try:
        user_id = message.chat.id
        question = message.text

        print("\n==============================")
        print("[USER QUESTION]:", question)

        # Identity
        if is_identity_question(question):
            bot.send_message(user_id, "Hi! Saya Ahmad 😊")
            return

        bot.send_message(user_id, "Saya tengah fikir 🤔...")

        # 🔥 STRICT KB MATCH
        context = search_kb(question)

        # 1. Ada KB → jawab
        if context:
            ai = ask_ai(f"{context}\n\nSoalan: {question}")
            if ai:
                bot.send_message(user_id, to_html(ai), parse_mode="HTML")
                return

        # 2. Tak cukup match → PASS ADMIN
        pending_questions[user_id] = question

        bot.send_message(
            ADMIN_ID,
            f"[ADMIN_ALERT]\nUser ID: {user_id}\nSoalan: {question}"
        )

        bot.send_message(
            user_id,
            "Soalan ni belum ada dalam sistem saya 🤔 saya pass ke admin ya"
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
