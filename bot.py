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
# LOAD KB
# =========================
with open("knowledge.json") as f:
    KB = json.load(f)

# =========================
# SIMPLE KB MATCH (MACAM DULU)
# =========================
def search_kb(question):
    results = []
    q = question.lower()

    print("\n[DEBUG] Question:", question, flush=True)

    for chunk in KB:
        for keyword in chunk["keywords"]:
            if keyword.lower() in q:
                print("[DEBUG] MATCH:", keyword, flush=True)
                results.append(chunk["content"])
                break

    print("[DEBUG] Context:", results, flush=True)
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
# AI FUNCTION (FIXED)
# =========================
def ask_ai(context, question):

    context_text = "\n\n".join(context)  # 🔥 CRITICAL FIX

    prompt = f"""
Jawab soalan berdasarkan maklumat berikut.

Maklumat:
{context_text}

Soalan:
{question}
"""

    try:
        response = client.models.generate_content(
            model="gemini-2.5-pro",
            contents=prompt
        )

        if response.text:
            return response.text.strip()

    except Exception as e:
        print("[AI ERROR]", e, flush=True)

    return None

# =========================
# ADMIN HANDLER
# =========================
@bot.message_handler(func=lambda m: m.chat.id == ADMIN_ID)
def handle_admin(message):
    try:
        text = message.text

        # Reply mode (IMPORTANT)
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

        bot.send_message(user_id, "Saya tengah fikir 🤔...")

        context = search_kb(question)

        # ✅ ADA KB → AI jawab
        if context:
            ai = ask_ai(context, question)

            if ai:
                bot.send_message(user_id, to_html(ai), parse_mode="HTML")
                return
            else:
                print("[DEBUG] AI empty", flush=True)

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
