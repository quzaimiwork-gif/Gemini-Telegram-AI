import telebot
import os
import json
import time
import re
from google import genai

# =========================
# DEBUG START
# =========================
print("🔥 BOT STARTED", flush=True)

# =========================
# TELEGRAM SETUP
# =========================
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

if not BOT_TOKEN:
    print("❌ BOT TOKEN MISSING", flush=True)

bot = telebot.TeleBot(BOT_TOKEN)

# =========================
# FORCE RESET WEBHOOK
# =========================
try:
    bot.remove_webhook()
    print("✅ Webhook removed", flush=True)
except Exception as e:
    print("❌ Webhook error:", e, flush=True)

time.sleep(2)

print("🔥 READY FOR MESSAGE", flush=True)

# =========================
# DEBUG HANDLER (CATCH ALL)
# =========================
@bot.message_handler(func=lambda m: True)
def debug_all(message):
    try:
        print("📩 MESSAGE MASUK:", message.text, flush=True)

        bot.reply_to(message, "OK masuk bro 🔥")

    except Exception as e:
        print("❌ ERROR HANDLE MESSAGE:", e, flush=True)

# =========================
# START POLLING
# =========================
print("🚀 Polling started...", flush=True)

bot.infinity_polling(skip_pending=True, timeout=20, long_polling_timeout=20)
