import telebot
import os
import json
import time
import re
from google import genai
from google.cloud import discoveryengine_v1 as discoveryengine

# =========================
# GOOGLE CREDENTIALS
# =========================
if "GOOGLE_CREDENTIALS" in os.environ:
    creds = json.loads(os.environ["GOOGLE_CREDENTIALS"])
    with open("service-account.json", "w") as f:
        json.dump(creds, f)
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "service-account.json"

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT")
LOCATION = "global"
DATA_STORE_ID = os.environ.get("DATA_STORE_ID")

# =========================
# GEMINI
# =========================
client = genai.Client(
    vertexai=True,
    project=PROJECT_ID,
    location="us-central1"
)

# =========================
# VERTEX SEARCH CLIENT
# =========================
search_client = discoveryengine.SearchServiceClient()

serving_config = f"projects/{PROJECT_ID}/locations/{LOCATION}/collections/default_collection/dataStores/{DATA_STORE_ID}/servingConfigs/default_config"

# =========================
# TELEGRAM
# =========================
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)

ADMIN_ID = 693749347
pending_questions = {}

# =========================
# SEARCH FROM PDF
# =========================
def search_vertex(question):
    try:
        request = discoveryengine.SearchRequest(
            serving_config=serving_config,
            query=question,
            page_size=3
        )

        response = search_client.search(request)

        results = []

        for res in response.results:
            if res.document and res.document.derived_struct_data:
                text = res.document.derived_struct_data.get("text", "")
                if text:
                    results.append(text)

        print("[DEBUG] Found:", len(results), flush=True)
        return results

    except Exception as e:
        print("[VERTEX ERROR]:", e, flush=True)
        return []

# =========================
# FORMAT OUTPUT
# =========================
def to_html(text):
    text = text.replace("‘", "'").replace("’", "'")
    text = text.replace("“", '"').replace("”", '"')

    text = re.sub(r"### (.*?)\n", r"<b>\1</b>\n", text)

    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")

    return text

# =========================
# AI FUNCTION (STRICT)
# =========================
def ask_ai(context, question):

    if not context:
        return None

    context_text = "\n\n".join(context)

    prompt = f"""
Jawab hanya berdasarkan maklumat ini sahaja.

Gaya santai, macam sembang biasa.

DILARANG:
- guna pengetahuan luar
- tambah fakta sendiri

Jika maklumat tak cukup, jawab:
"tak cukup info"

-----------------------
{context_text}
-----------------------

Soalan:
{question}
"""

    try:
        response = client.models.generate_content(
            model="gemini-2.5-pro",
            contents=prompt
        )

        if hasattr(response, "text") and response.text:
            return response.text.strip()

    except Exception as e:
        print("[AI ERROR]:", e, flush=True)

    return None

# =========================
# ADMIN HANDLER
# =========================
@bot.message_handler(func=lambda m: m.chat.id == ADMIN_ID)
def handle_admin(message):
    try:
        if message.reply_to_message:
            original = message.reply_to_message.text

            if "[ADMIN_ALERT]" in original:
                user_id = int(original.split("\n")[1].replace("User ID: ", ""))

                bot.send_message(user_id, to_html(message.text), parse_mode="HTML")
                bot.send_message(ADMIN_ID, "✅ Sent to user")

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

        bot.send_message(user_id, "Sekejap ya, saya check 🤔...")

        # 🔥 SEARCH PDF KB
        context = search_vertex(question)

        # 🔥 AI ANSWER
        if context:
            ai = ask_ai(context, question)

            if ai and "tak cukup info" not in ai.lower():
                bot.send_message(user_id, to_html(ai), parse_mode="HTML")
                return

        # 🔥 FALLBACK → ADMIN
        print("[DEBUG] SEND TO ADMIN", flush=True)

        pending_questions[user_id] = question

        bot.send_message(
            ADMIN_ID,
            f"[ADMIN_ALERT]\nUser ID: {user_id}\nSoalan: {question}"
        )

        bot.send_message(
            user_id,
            "Hmm yang ni saya tak jumpa lagi 😅\nSaya pass dekat admin ya 👍"
        )

    except Exception as e:
        print("[USER ERROR]", e, flush=True)

# =========================
# START
# =========================
print("Bot running (Vertex Search mode)...", flush=True)

bot.remove_webhook()
time.sleep(2)

bot.infinity_polling(skip_pending=True)
