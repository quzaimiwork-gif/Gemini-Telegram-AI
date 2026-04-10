import telebot
import os
import google.generativeai as genai

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

bot = telebot.TeleBot(BOT_TOKEN)

genai.configure(api_key=GEMINI_API_KEY)

model = genai.GenerativeModel("gemini-1.5-flash")

@bot.message_handler(func=lambda message: True)
def reply(message):
    response = model.generate_content(message.text)
    bot.reply_to(message, response.text)

print("Bot running...")
bot.polling()
