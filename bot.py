import telebot
import os
import json
import time
import re
from google import genai
from google.cloud import discoveryengine_v1 as discoveryengine

print("🔥 BOT STARTED", flush=True)

# =========================
# GOOGLE CREDS
# =========================
if "GOOGLE_CREDENTIALS" in os.environ:
    creds = json.loads(os.environ["GOOGLE_CREDENTIALS"])
    with open("service-account.json", "w") as f:
        json.dump(creds, f)
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "service-account.json"

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT")
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
# VERTEX SEARCH
# =========================
search_client = discoveryengine.SearchServiceClient()

serving_config = f"projects/{PROJECT_ID}/locations/global/collections/default_collection/dataStores/{DATA_STORE_ID}/servingConfigs/default_config"

# =========================
# TELEGRAM
# =========================
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)

ADMIN_ID = 693749347
pending_questions = {}

# =========================
# SEARCH
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

        for r in response.results:
            if r.document and r.document.derived_struct_data:
                text = r.document.derived_struct_data.get("text", "")
                if text:
                    results.append(text)

        print("[DEBUG] Vertex:", len(results), flush=True)
        return results

    except Exception as e:
        print("[VERTEX ERROR]", e, flush=True)
        return []

# =========================
# FORMAT
# =========================
def to_html(text):
    text = text.replace("‘", "'").replace("’", "'")
    text = text.replace("“", '"').replace("”", '"')
    text = re.sub(r"### (.*?)\n", r"<b>\1</b>\n", text)
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return text

# =========================
# AI
# =========================
def ask_ai(context, question):

    if not context:
        return None

    prompt = f"""
Jawab hanya berdasarkan maklumat ini sahaja.

Jika tak cukup, jawab:
"tak cukup info"

-----------------------
{chr(10).join(context)}
-----------------------

Soalan:
{question}
"""

    try:
        r = client.models.generate_content(
            model="gemini-2.5-pro",
            contents=prompt
        )

        if hasattr(r, "text"):
            return r.text.strip()

    except Exception as e:
        print("[AI ERROR]", e, flush=True)

    return None

# =========================
# SINGLE HANDLER (FIX)
# =========================
@bot.message_handler(func=lambda m: True)
def handle_all(message):
    try:
        user_id = message.chat.id
        text = message.text

        print("\n📩 MESSAGE:", text, flush=True)

        # ================= ADMIN =================
        if user_id == ADMIN_ID:

            if message.reply_to_message:
                original = message.reply_to_message.text

                if "[ADMIN_ALERT]" in original:
                    target = int(original.split("\n")[1].replace("User ID: ", ""))

                    bot.send_message(target, to_html(text), parse_mode="HTML")
                    bot.send_message(ADMIN_ID, "✅ Sent to user")
                    return

        # ================= USER =================
        bot.send_message(user_id, "Sekejap ya, saya check 🤔...")

        context = search_vertex(text)

        if context:
            ai = ask_ai(context, text)

            if ai and "tak cukup info" not in ai.lower():
                bot.send_message(user_id, to_html(ai), parse_mode="HTML")
                return

        # ================= FALLBACK =================
        pending_questions[user_id] = text

        bot.send_message(
            ADMIN_ID,
            f"[ADMIN_ALERT]\nUser ID: {user_id}\nSoalan: {text}"
        )

        bot.send_message(
            user_id,
            "Hmm yang ni saya tak jumpa lagi 😅\nSaya pass dekat admin ya 👍"
        )

    except Exception as e:
        print("[ERROR]", e, flush=True)

# =========================
# START
# =========================
bot.remove_webhook()
time.sleep(2)

print("🚀 Bot running FINAL...", flush=True)

bot.infinity_polling(skip_pending=True)
