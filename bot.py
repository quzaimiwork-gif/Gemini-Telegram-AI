import telebot
import os
import json
import time
import re
from google import genai

# =========================
# GOOGLE CREDENTIALS
# =========================
if "GOOGLE_CREDENTIALS" in os.environ:
    creds = json.loads(os.environ["GOOGLE_CREDENTIALS"])
    with open("service-account.json", "w") as f:
        json.dump(creds, f)
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "service-account.json"

# =========================
# GEMINI (VERTEX)
# =========================
client = genai.Client(
    vertexai=True,
    project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
    location="us-central1"
)

# =========================
# TELEGRAM
# =========================
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)

ADMIN_ID = 693749347
pending_questions = {}

# =========================
# PERSONA (NORMAL, NOT STRICT)
# =========================
SYSTEM_RULE = """
Nama anda Ahmad.
Anda AI Assistant untuk usahawan Malaysia.

Jawab secara santai, jelas dan mudah faham.
"""

# =========================
# LOAD KB
# =========================
with open("knowledge.json") as f:
    KB = json.load(f)

# =========================
# SIMPLE KB SEARCH (MACAM HARITU)
# =========================
def search_kb(question):
    results = []

    q = question.lower()

    print("\n====================", flush=True)
    print("[DEBUG] Question:", question, flush=True)

    for chunk in KB:
        for keyword in chunk["keywords"]:
            if keyword.lower() in q:
                print("[DEBUG] MATCH:", keyword, flush=True)
                results.append(chunk["content"])
                break  # avoid duplicate

    print("[DEBUG] Final context:", results, flush=True)
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
            print("[ERROR]", e, flush=True)
            time.sleep(2)

    return None

# =========================
# IDENTITY
# =========================
def is_identity_question(text):
    keywords = ["siapa awak", "nama awak", "who are you"]
    return any(k in text.lower() for k in keywords)

# =========================
# ADMIN HANDLER
# =========================
@bot.message_handler(func=lambda m: m.chat.id == ADMIN_ID)
def handle_admin(message):
    try:
        text = message.text

        # Reply mode
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

    except Exception as e:
        print("[ADMIN ERROR]", e, flush=True)

# =========================
# USER HANDLER
# =========================
@bot.message_handler(func=lambda m: True)
def handle_user(message):
    try:
        user_id = message.chat.id
        question = message.text

        print("\n[USER]:", question, flush=True)

        if is_identity_question(question):
            bot.send_message(user_id, "Hi! Saya Ahmad 😊")
            return

        bot.send_message(user_id, "Saya tengah fikir 🤔...")

        context = search_kb(question)

        # ✅ ADA KB → jawab
        if context:
            ai = ask_ai(f"{context}\n\nSoalan: {question}")

            if ai:
                bot.send_message(user_id, to_html(ai), parse_mode="HTML")
                return

        # ❌ TAK ADA KB → ADMIN
        print("[DEBUG] ❌ NO KB → ADMIN", flush=True)

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
        print("[USER ERROR]", e, flush=True)

# =========================
# START
# =========================
print("Bot running...", flush=True)

bot.remove_webhook()
time.sleep(2)

bot.infinity_polling(timeout=20, long_polling_timeout=20)
