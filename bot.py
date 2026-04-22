import telebot
import os
import json
import time
import re
from google import genai
from google.cloud import discoveryengine_v1 as discoveryengine
from google.cloud import storage

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
ENGINE_ID  = os.environ.get("ENGINE_ID")

# ⚠️  Set this to your Cloud Storage bucket name (the one with your PDFs)
KB_BUCKET  = os.environ.get("KB_BUCKET_NAME", "YOUR_BUCKET_NAME_HERE")

# =========================
# GOOGLE CLIENTS
# =========================
gemini_client = genai.Client(
    vertexai=True,
    project=PROJECT_ID,
    location="us-central1"
)

search_client = discoveryengine.SearchServiceClient()
SERVING_CONFIG = f"{ENGINE_ID}/servingConfigs/default_config"

storage_client = storage.Client()

# =========================
# TELEGRAM
# =========================
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)

ADMIN_ID = 693749347

# pending_questions maps:  alert_message_id → { user_id, question }
# This lets us match admin replies to the right user
pending_questions = {}


# =========================
# SMALL TALK DETECTION
# Gemini decides if the message is casual chat (not a KB question)
# =========================
def is_small_talk(text):
    prompt = f"""
You are a classifier. Decide if this message is SMALL TALK or a REAL QUESTION.

SMALL TALK = greetings, thanks, goodbye, feelings, compliments, casual chat
REAL QUESTION = asks for specific info, facts, procedures, services, products

Reply with ONE word only: SMALLTALK or QUESTION

Message: "{text}"
"""
    try:
        r = gemini_client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt
        )
        result = r.text.strip().upper()
        print(f"[CLASSIFIER] '{text}' → {result}", flush=True)
        return "SMALLTALK" in result
    except Exception as e:
        print("[CLASSIFIER ERROR]", e, flush=True)
        return False  # if unsure, treat as real question


# =========================
# SMALL TALK REPLY
# Ahmad responds naturally, mirrors user's language
# =========================
def reply_small_talk(text):
    prompt = f"""
You are Ahmad, a friendly and helpful AI assistant for a digital business platform.
Your personality: warm, casual, a little witty, never robotic.

Rules:
- Mirror the user's language (if they write Malay, reply Malay; English → English; mix → mix)
- Keep it short (1–3 sentences max)
- Never mention you're an AI unless directly asked
- If they ask what you can do, say you help answer questions about the platform, registration, domains, digital tools, etc.

User said: "{text}"

Reply naturally:
"""
    try:
        r = gemini_client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt
        )
        return r.text.strip()
    except Exception as e:
        print("[SMALLTALK ERROR]", e, flush=True)
        return "Eh, ada masalah sikit. Cuba lagi ya! 😅"


# =========================
# VERTEX AI SEARCH
# =========================
def search_vertex(question):
    try:
        request = discoveryengine.SearchRequest(
            serving_config=SERVING_CONFIG,
            query=question,
            page_size=5,
            content_search_spec=discoveryengine.SearchRequest.ContentSearchSpec(
                snippet_spec=discoveryengine.SearchRequest.ContentSearchSpec.SnippetSpec(
                    return_snippet=True
                ),
                extractive_content_spec=discoveryengine.SearchRequest.ContentSearchSpec.ExtractiveContentSpec(
                    max_extractive_answer_count=3,
                    max_extractive_segment_count=5
                )
            )
        )

        response = search_client.search(request)
        results = []

        for r in response.results:
            if r.document:
                data = r.document.derived_struct_data
                if data:
                    for s in data.get("snippets", []):
                        if "snippet" in s:
                            results.append(s["snippet"])
                    for e in data.get("extractive_answers", []):
                        if "content" in e:
                            results.append(e["content"])

        print(f"[VERTEX] {len(results)} chunks found", flush=True)
        return results

    except Exception as e:
        print("[VERTEX ERROR]", e, flush=True)
        return []


# =========================
# GEMINI — ANSWER FROM KB
# =========================
def ask_ai(context, question):
    if not context:
        return None

    context_text = "\n\n".join(context)

    prompt = f"""
You are Ahmad, a helpful AI assistant.

RULES:
- Answer ONLY using the info below
- Mirror the user's language (Malay → Malay, English → English, mix → mix)
- Be friendly and casual, not robotic
- If the info is not enough to answer, reply exactly: INSUFFICIENT
- Never add facts from outside the provided info

--- INFO ---
{context_text}
--- END INFO ---

Question: {question}
"""

    try:
        r = gemini_client.models.generate_content(
            model="gemini-2.5-pro",
            contents=prompt
        )
        if hasattr(r, "text") and r.text:
            return r.text.strip()
    except Exception as e:
        print("[AI ERROR]", e, flush=True)

    return None


# =========================
# AUTO-LEARN: SAVE Q&A TO BUCKET
# Vertex will re-index this file automatically
# =========================
def save_to_kb(question, answer):
    try:
        bucket = storage_client.bucket(KB_BUCKET)
        # Safe filename from question
        safe_name = re.sub(r"[^a-zA-Z0-9]", "_", question[:60]).strip("_")
        filename  = f"learned_qa/{safe_name}_{int(time.time())}.txt"

        content = f"Soalan: {question}\n\nJawapan: {answer}"
        blob = bucket.blob(filename)
        blob.upload_from_string(content, content_type="text/plain")

        print(f"[KB SAVED] {filename}", flush=True)
        return True
    except Exception as e:
        print("[KB SAVE ERROR]", e, flush=True)
        return False


# =========================
# HTML FORMATTER
# =========================
def to_html(text):
    # Fix smart quotes
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    # Convert ### headings to bold
    text = re.sub(r"### (.*?)\n", r"<b>\1</b>\n", text)
    # Escape HTML (AFTER bold replacement)
    text = text.replace("&", "&amp;")
    text = text.replace("<b>", "BOLD_OPEN").replace("</b>", "BOLD_CLOSE")
    text = text.replace("<", "&lt;").replace(">", "&gt;")
    text = text.replace("BOLD_OPEN", "<b>").replace("BOLD_CLOSE", "</b>")
    return text


# =========================
# MAIN MESSAGE HANDLER
# =========================
@bot.message_handler(func=lambda m: True)
def handle_all(message):
    try:
        user_id   = message.chat.id
        text      = message.text or ""
        text      = text.strip()

        print(f"\n📩 FROM {user_id}: {text}", flush=True)

        # ─────────────────────────────
        # ADMIN: handle replies to alert messages
        # ─────────────────────────────
        if user_id == ADMIN_ID and message.reply_to_message:
            replied_msg_id = message.reply_to_message.message_id

            if replied_msg_id in pending_questions:
                entry    = pending_questions.pop(replied_msg_id)
                target   = entry["user_id"]
                question = entry["question"]
                answer   = text

                # Send answer to user
                bot.send_message(
                    target,
                    to_html(answer),
                    parse_mode="HTML"
                )

                # Save to KB for future
                saved = save_to_kb(question, answer)
                status = "✅ Saved to KB" if saved else "⚠️ Saved to KB failed (check bucket name)"
                bot.send_message(ADMIN_ID, f"✅ Answer sent to user.\n{status}")
                return

        # ─────────────────────────────
        # ADMIN: plain message (not a reply) — skip normal flow
        # ─────────────────────────────
        if user_id == ADMIN_ID and not message.reply_to_message:
            bot.send_message(ADMIN_ID, "💡 To answer a user, use Telegram's Reply feature on the alert message.")
            return

        # ─────────────────────────────
        # USER: small talk check
        # ─────────────────────────────
        if is_small_talk(text):
            reply = reply_small_talk(text)
            bot.send_message(user_id, to_html(reply), parse_mode="HTML")
            return

        # ─────────────────────────────
        # USER: real question → search KB
        # ─────────────────────────────
        bot.send_message(user_id, "Sekejap ya, saya check 🤔...")

        context = search_vertex(text)
        ai      = ask_ai(context, text) if context else None

        if ai and "INSUFFICIENT" not in ai.upper():
            bot.send_message(user_id, to_html(ai), parse_mode="HTML")
            return

        # ─────────────────────────────
        # FALLBACK: escalate to admin
        # ─────────────────────────────
        print("[FALLBACK] Escalating to admin", flush=True)

        alert = bot.send_message(
            ADMIN_ID,
            f"🔔 <b>[SOALAN BARU]</b>\n\n"
            f"👤 User ID: <code>{user_id}</code>\n"
            f"❓ Soalan: {text}\n\n"
            f"<i>Reply mesej ini untuk jawab user secara terus.</i>",
            parse_mode="HTML"
        )

        # Store by alert message ID so we can match admin's reply
        pending_questions[alert.message_id] = {
            "user_id": user_id,
            "question": text
        }

        bot.send_message(
            user_id,
            "Hmm, yang ni saya tak jumpa lagi 😅\nSaya dah forward ke admin — nanti ada jawapan, saya bagitahu ya! 👍"
        )

    except Exception as e:
        print("[ERROR]", e, flush=True)


# =========================
# START
# =========================
bot.remove_webhook()
time.sleep(2)

print("🚀 Ahmad is running...", flush=True)
bot.infinity_polling(skip_pending=True)
