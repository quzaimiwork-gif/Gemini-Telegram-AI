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
# SIMPLE KB MATCH
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
# AI FUNCTION (ROBUST)
# =========================
def ask_ai(context, question):

    context_text = "\n\n".join(context).strip()

    if not context_text:
        print("[DEBUG] Empty context → skip AI", flush=True)
        return None

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

        # normal case
        if hasattr(response, "text") and response.text:
            return response.text.strip()

        # fallback (Vertex weird format)
        if hasattr(response, "candidates"):
            try:
                return response.candidates[0].content.parts[0].text.strip()
            except:
                pass

        print("[DEBUG] AI returned empty", flush=True)

    except Exception as e:
        print("[AI ERROR]", e, flush=True)

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
        ai = ask_ai([text], text)

        if ai:
            bot.send_message(ADMIN_ID, to_html(ai), parse_mode="HTML")
        else:
            bot.send_message(ADMIN_ID, "AI busy 😅")

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

        # Identity
        if is_identity_question(question):
            bot.send_message(user_id, "Hi! Saya Ahmad 😊")
            return

        bot.send_message(user_id, "Saya tengah fikir 🤔...")

        context = search_kb(question)

        # ✅ ADA KB → AI jawab
        if context:
            ai = ask_ai(context, question)

            if ai:
                bot.send_message(user_id, to_html(ai), parse_mode="HTML")
                return

        # 🔥 FALLBACK → ADMIN
        print("[DEBUG] ❌ SEND TO ADMIN", flush=True)

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
