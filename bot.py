import telebot
import os
import json
import time
import re
import threading
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
KB_BUCKET  = os.environ.get("KB_BUCKET_NAME", "telegram_kb")

# =========================
# GOOGLE CLIENTS
# =========================
gemini_client = genai.Client(
    vertexai=True,
    project=PROJECT_ID,
    location="us-central1"
)

search_client = discoveryengine.SearchServiceClient()
SERVING_CONFIG = (
    f"projects/{PROJECT_ID}/locations/global/collections/default_collection"
    f"/engines/{ENGINE_ID}/servingConfigs/default_search"
)

storage_client = storage.Client()

# =========================
# TELEGRAM
# =========================
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)

ADMIN_ID = 693749347
pending_questions = {}

# =========================
# MESSAGE BATCHING
# Collects multiple messages from same user,
# waits 10s of silence, then processes as one
# =========================
BATCH_WAIT = 10  # seconds to wait after last message
user_batches = {}       # user_id → list of messages
user_timers = {}        # user_id → threading.Timer


# =========================
# SMALL TALK DETECTION
# =========================
def is_small_talk(text):
    prompt = f"""
You are a classifier for a Malay/English chatbot. Decide if this message is SMALL TALK or a REAL QUESTION.

SMALL TALK includes:
- Pure greetings with no question attached: "hi", "hello", "hai", "hey", "assalamualaikum", "selamat pagi", "apa khabar"
- "hai?" alone is still a greeting/small talk
- Asking who/what the bot is: "awak ni siapa", "kau ni apa", "who are you", "siapa kau", "bot ke"
- Thanks: terima kasih, thanks, tq, ok thanks
- Goodbye: bye, selamat tinggal, ok bye
- Reactions: best, ok je, haha, wah, bagus, pandai, hebat

REAL QUESTION includes:
- Questions about specific services, products, prices, procedures
- Questions about MYNIC, domain, registration, digital business
- How to do something specific
- "Hai, apa tu MYNIC?" — greeting combined with a real question = QUESTION

Reply with ONE word only: SMALLTALK or QUESTION

Message: "{text}"
"""
    try:
        r = gemini_client.models.generate_content(
            model="gemini-2.5-pro",
            contents=prompt
        )
        result = r.text.strip().upper()
        print(f"[CLASSIFIER] '{text}' → {result}", flush=True)
        return "SMALLTALK" in result
    except Exception as e:
        print("[CLASSIFIER ERROR]", e, flush=True)
        return False


# =========================
# THINKING MESSAGE
# Ahmad generates natural "looking it up" message
# =========================
def get_thinking_message(question):
    prompt = f"""
You are Ahmad, a friendly Malay/English assistant (not a robot).
The user just asked you something. Reply with ONE short casual sentence that shows you're engaged and about to help.

Rules:
- Max 8 words
- Sound like a real person, not an AI assistant
- Mirror their language (Malay → Malay, English → English, mix → mix)
- Use phrases like: "Menarik soalan tu!", "Saya boleh cuba bantu!", "Oh, bagus soalan!", "Let me check that for you!", "Okay, biar saya tengok..."
- Do NOT say "saya check", "saya semak", "looking it up" — too robotic
- Vary the phrase, don't repeat

User question: "{question}"

Reply with just the short engaging message:
"""
    try:
        r = gemini_client.models.generate_content(
            model="gemini-2.5-pro",
            contents=prompt
        )
        return r.text.strip()
    except Exception as e:
        print("[THINKING ERROR]", e, flush=True)
        return "Menarik soalan tu! 😊"


# =========================
# SMALL TALK REPLY
# =========================
def reply_small_talk(text):
    prompt = f"""
You are Ahmad, a friendly AI assistant for MYNIC — Malaysia's domain registry.
Your personality: warm, casual, helpful, a little witty, never robotic.

Rules:
- Mirror the user's language (Malay → Malay, English → English, mix → mix)
- Keep it short (1-3 sentences max)
- If the user greeted with "hai", "hi", "hello" etc, you CAN reply with a greeting back — it is natural
- If the user did NOT greet, do NOT open with a greeting word
- If asked who you are: say you are Ahmad, a virtual assistant for MYNIC, here to help with domain registration, digital services, and related questions
- If asked what you can do: say you can answer questions about MYNIC services, domain registration (.my domains), and digital business topics
- Never say you are ChatGPT or any other AI brand

User said: "{text}"

Reply naturally:
"""
    try:
        r = gemini_client.models.generate_content(
            model="gemini-2.5-pro",
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
            page_size=10,
            content_search_spec=discoveryengine.SearchRequest.ContentSearchSpec(
                snippet_spec=discoveryengine.SearchRequest.ContentSearchSpec.SnippetSpec(
                    return_snippet=True,
                    max_snippet_count=5
                ),
                extractive_content_spec=discoveryengine.SearchRequest.ContentSearchSpec.ExtractiveContentSpec(
                    max_extractive_answer_count=5,
                    max_extractive_segment_count=10
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
You are Ahmad, a helpful AI assistant for MYNIC — Malaysia's domain registry.

RULES:
- Answer ONLY using the info below
- Mirror the user's language (Malay → Malay, English → English, mix → mix)
- Be friendly and casual, not robotic
- Do NOT open with "Hai", "Hello" or any greeting — just answer directly
- Give a COMPLETE answer based on what the question asks — if the question asks for an overview of a topic, cover all relevant parts; if it asks about one specific thing, focus on that
- Use **double asterisks** around important terms or key points for bold e.g. **MYNIC**
- When the answer has multiple sections or points, separate each COMPLETE section with exactly this on its own line: ---
- Each section must be complete before the --- separator
- Short answers (1-2 sentences) do not need separators
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
            contents=prompt,
            config={"max_output_tokens": 8192}
        )
        if hasattr(r, "text") and r.text:
            return r.text.strip()
    except Exception as e:
        print("[AI ERROR]", e, flush=True)

    return None


# =========================
# AUTO-LEARN: SAVE Q&A TO BUCKET
# =========================
def save_to_kb(question, answer):
    try:
        bucket = storage_client.bucket(KB_BUCKET)
        safe_name = re.sub(r"[^a-zA-Z0-9]", "_", question[:60]).strip("_")
        filename  = f"learned_qa/{safe_name}_{int(time.time())}.txt"
        content   = f"Soalan: {question}\n\nJawapan: {answer}"
        blob = bucket.blob(filename)
        blob.upload_from_string(content, content_type="text/plain")
        print(f"[KB SAVED] {filename}", flush=True)
        return True
    except Exception as e:
        print("[KB SAVE ERROR]", e, flush=True)
        return False


# =========================
# HTML FORMATTER
# Converts **bold** markdown to Telegram HTML <b>bold</b>
# =========================
def to_html(text):
    # Fix smart quotes
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    # Convert **bold** to <b>bold</b> BEFORE bullet fix
    text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
    # Convert ### headings to bold
    text = re.sub(r"### (.*?)\n", r"<b>\1</b>\n", text)
    # Convert markdown bullet points (* item) to dash (- item)
    text = re.sub(r"^\* ", "• ", text, flags=re.MULTILINE)
    text = re.sub(r"^- ", "• ", text, flags=re.MULTILINE)
    # Escape HTML special chars but preserve our <b> tags
    text = text.replace("&", "&amp;")
    text = text.replace("<b>", "BOLD_OPEN").replace("</b>", "BOLD_CLOSE")
    text = text.replace("<", "&lt;").replace(">", "&gt;")
    text = text.replace("BOLD_OPEN", "<b>").replace("BOLD_CLOSE", "</b>")
    return text


# =========================
# SPLIT LONG MESSAGES INTO BUBBLES
# Gemini uses --- to mark end of each complete section
# =========================
def send_in_bubbles(chat_id, text):
    # Split by --- separator (each section is a complete point)
    sections = [s.strip() for s in re.split(r"\n---\n|\n---$|^---\n", text) if s.strip()]

    # If no --- found or only one section, send as single bubble
    if len(sections) <= 1:
        formatted = to_html(text.strip())
        # Telegram max is 4096 chars per message — split only if exceeded
        if len(formatted) <= 4096:
            bot.send_message(chat_id, formatted, parse_mode="HTML")
        else:
            # Very long single section — split at sentence level
            chunks = [formatted[i:i+4000] for i in range(0, len(formatted), 4000)]
            for chunk in chunks:
                bot.send_message(chat_id, chunk, parse_mode="HTML")
                time.sleep(0.4)
        return

    # Send each complete section as its own bubble
    for section in sections:
        if section.strip():
            formatted = to_html(section.strip())
            bot.send_message(chat_id, formatted, parse_mode="HTML")
            time.sleep(0.4)  # small delay so bubbles arrive in order


# =========================
# PROCESS COMPILED MESSAGE
# Called after 10s silence — processes all batched messages as one
# =========================
def process_batch(user_id):
    try:
        messages = user_batches.pop(user_id, [])
        user_timers.pop(user_id, None)

        if not messages:
            return

        # Compile all messages into one
        text = " ".join(messages)
        print(f"\n📦 BATCH FROM {user_id}: {text}", flush=True)

        # ─────────────────────────────
        # USER: small talk
        # ─────────────────────────────
        if is_small_talk(text):
            reply = reply_small_talk(text)
            bot.send_message(user_id, to_html(reply), parse_mode="HTML")
            return

        # ─────────────────────────────
        # USER: real question → KB search
        # ─────────────────────────────
        thinking = get_thinking_message(text)
        bot.send_message(user_id, thinking)

        context = search_vertex(text)
        ai      = ask_ai(context, text) if context else None

        if ai and "INSUFFICIENT" not in ai.upper():
            send_in_bubbles(user_id, ai)
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

        pending_questions[alert.message_id] = {
            "user_id": user_id,
            "question": text
        }

        bot.send_message(
            user_id,
            "Yang ni saya tak jumpa dalam rekod saya 😅\nSaya dah forwardkan ke admin — nanti ada jawapan saya bagitahu ya! 👍"
        )

    except Exception as e:
        print("[BATCH ERROR]", e, flush=True)


# =========================
# VOICE NOTE HANDLER
# Download audio → send to Gemini as base64 → transcribe → add to batch
# =========================
def handle_voice(message):
    user_id = message.chat.id
    try:
        print(f"\n🎤 VOICE FROM {user_id}", flush=True)

        # Download voice file from Telegram
        file_info = bot.get_file(message.voice.file_id)
        downloaded = bot.download_file(file_info.file_path)

        # Convert to base64
        import base64
        audio_b64 = base64.b64encode(downloaded).decode("utf-8")

        # Send inline to Gemini (Vertex AI compatible)
        from google.genai import types as genai_types
        response = gemini_client.models.generate_content(
            model="gemini-2.5-pro",
            contents=[
                genai_types.Part.from_bytes(
                    data=base64.b64decode(audio_b64),
                    mime_type="audio/ogg"
                ),
                "Transcribe this audio exactly as spoken. Return ONLY the transcribed text, nothing else."
            ]
        )

        transcribed = response.text.strip()
        print(f"[VOICE] Transcribed: {transcribed}", flush=True)

        # Add transcribed text to batch (same flow as text messages)
        if user_id in user_timers:
            user_timers[user_id].cancel()

        if user_id not in user_batches:
            user_batches[user_id] = []
        user_batches[user_id].append(transcribed)

        timer = threading.Timer(BATCH_WAIT, process_batch, args=[user_id])
        user_timers[user_id] = timer
        timer.start()

        print(f"[BATCH] Voice queued for {user_id}", flush=True)

    except Exception as e:
        print("[VOICE ERROR]", e, flush=True)
        bot.send_message(user_id, "Alamak, ada masalah nak proses voice note tu. Cuba hantar dalam bentuk teks ya! 😅")


# =========================
# IMAGE HANDLER
# Download image → Gemini vision understands doc/screenshot → answer
# =========================
def handle_image(message):
    user_id = message.chat.id
    try:
        print(f"\n🖼️ IMAGE FROM {user_id}", flush=True)

        caption = (message.caption or "").strip()

        # Download highest resolution photo
        photo = message.photo[-1]
        file_info = bot.get_file(photo.file_id)
        downloaded = bot.download_file(file_info.file_path)

        # Build prompt — always treat as document/screenshot
        if caption:
            image_prompt = f"""The user sent a document or screenshot with this question: "{caption}"
Read the content in the image carefully and answer their question based on what you see.
If you cannot read the image clearly, say so.
Reply in the same language as the caption."""
        else:
            image_prompt = """The user sent a document or screenshot without any question.
Read and summarise what you see in the image.
If it contains text, extract the key information.
Ask the user what they need help with regarding this document.
Reply in Malay by default."""

        # Send inline as base64 (Vertex AI compatible)
        from google.genai import types as genai_types
        response = gemini_client.models.generate_content(
            model="gemini-2.5-pro",
            contents=[
                genai_types.Part.from_bytes(
                    data=downloaded,
                    mime_type="image/jpeg"
                ),
                image_prompt
            ]
        )

        reply = response.text.strip()
        print(f"[IMAGE] Reply: {reply[:100]}...", flush=True)
        send_in_bubbles(user_id, reply)

    except Exception as e:
        print("[IMAGE ERROR]", e, flush=True)
        bot.send_message(user_id, "Alamak, ada masalah nak proses gambar tu. Cuba hantar dalam bentuk teks ya! 😅")


# =========================
# MAIN MESSAGE HANDLER
# =========================
@bot.message_handler(func=lambda m: True)
def handle_all(message):
    try:
        user_id = message.chat.id
        text    = (message.text or "").strip()

        print(f"\n📩 FROM {user_id}: {text}", flush=True)

        # ─────────────────────────────
        # ADMIN: reply to alert message → send to user
        # ─────────────────────────────
        if user_id == ADMIN_ID and message.reply_to_message:
            replied_msg_id = message.reply_to_message.message_id

            if replied_msg_id in pending_questions:
                entry    = pending_questions.pop(replied_msg_id)
                target   = entry["user_id"]
                question = entry["question"]
                answer   = text

                bot.send_message(target, to_html(answer), parse_mode="HTML")

                saved  = save_to_kb(question, answer)
                status = "✅ Saved to KB" if saved else "⚠️ KB save failed (check bucket name)"
                bot.send_message(ADMIN_ID, f"✅ Answer sent to user.\n{status}")
                return

        # ─────────────────────────────
        # ADMIN: plain message reminder
        # ─────────────────────────────
        if user_id == ADMIN_ID and not message.reply_to_message:
            bot.send_message(ADMIN_ID, "💡 To answer a user, use Telegram's Reply feature on the alert message.")
            return

        # ─────────────────────────────
        # USER: batch text messages
        # Add to batch, reset 10s timer
        # ─────────────────────────────

        # Cancel existing timer if any
        if user_id in user_timers:
            user_timers[user_id].cancel()

        # Add message to batch
        if user_id not in user_batches:
            user_batches[user_id] = []
        user_batches[user_id].append(text)

        # Start new 10s timer
        timer = threading.Timer(BATCH_WAIT, process_batch, args=[user_id])
        user_timers[user_id] = timer
        timer.start()

        print(f"[BATCH] Queued for {user_id}, {len(user_batches[user_id])} msg(s) so far", flush=True)

    except Exception as e:
        print("[ERROR]", e, flush=True)


# =========================
# START
# =========================
bot.remove_webhook()
time.sleep(2)

# Explicit handlers for voice and photo (must be before infinity_polling)
@bot.message_handler(content_types=["voice"])
def route_voice(message):
    if message.chat.id != ADMIN_ID:
        handle_voice(message)

@bot.message_handler(content_types=["photo"])
def route_photo(message):
    if message.chat.id != ADMIN_ID:
        handle_image(message)

print("🚀 Ahmad is running...", flush=True)
bot.infinity_polling(skip_pending=True)
