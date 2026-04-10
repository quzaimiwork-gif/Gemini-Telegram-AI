import telebot
import os
from google import genai

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

bot = telebot.TeleBot(BOT_TOKEN)
client = genai.Client(api_key=GEMINI_API_KEY)

@bot.message_handler(func=lambda message: True)
def reply(message):
    response = client.models.generate_content(
        model="gemini-1.5-flash",
        contents=message.text
    )

    bot.reply_to(message, response.text)

print("Bot running...")
bot.polling()
