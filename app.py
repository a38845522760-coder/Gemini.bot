import asyncio
import io
import logging
import os
import threading
from google import genai
from google.genai import types
import gradio as gr
from PIL import Image
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# تنظیمات لاگینگ
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# خواندن توکن‌ها به صورت امن از متغیرهای محیطی سیستم
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
  raise ValueError(
      "لطفاً متغیرهای محیطی TELEGRAM_TOKEN و GEMINI_API_KEY را تنظیم کنید!"
  )

# مقداردهی کلاینت جمینی
client = genai.Client(api_key=GEMINI_API_KEY)

# حافظه چت کاربران
user_chats = {}

# لیست کامل مدل‌ها (از ۳.۱ تا ۳.۸)
AVAILABLE_MODELS = {
    "gemini-3.5-flash": "⚡ 3.5 Flash",
    "gemini-3.6-flash": "⚡ 3.6 Flash",
    "gemini-3.7-flash": "⚡ 3.7 Flash",
    "gemini-3.8-flash": "⚡ 3.8 Flash",
    "gemini-3.1-pro": "🧠 3.1 Pro",
    "gemini-3.1-flash-lite": "💡 3.1 Lite",
    "gemini-3.5-flash-lite": "💡 3.5 Lite",
}

DEFAULT_MODEL = "gemini-3.5-flash"

SYSTEM_INSTRUCTION = """
نام تو علی است. تو یک دستیار هوشمند، بسیار صمیمی، رفیقانه و خفن هستی.
همیشه پاسخ‌های دقیق، کاملاً فارسی و روان بده.
اگر کاربر عکسی فرستاد، آن را با دقت آنالیز کن و توضیح بده.
"""


def get_user_model(user_id):
  if user_id in user_chats:
    return user_chats[user_id].get("model", DEFAULT_MODEL)
  return DEFAULT_MODEL


def get_chat(user_id, model_name=None):
  if model_name is None:
    model_name = get_user_model(user_id)

  if (
      user_id not in user_chats
      or user_chats[user_id].get("model") != model_name
      or "chat" not in user_chats[user_id]
  ):
    chat = client.chats.create(
        model=model_name,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            temperature=0.7,
        ),
    )
    user_chats[user_id] = {"chat": chat, "model": model_name}
  return user_chats[user_id]["chat"]


def build_main_keyboard(current_model):
  keyboard = []
  model_buttons = []

  for model_key, model_label in AVAILABLE_MODELS.items():
    label = f"✅ {model_label}" if model_key == current_model else model_label
    model_buttons.append(
        InlineKeyboardButton(label, callback_data=f"model_{model_key}")
    )

  for i in range(0, len(model_buttons), 2):
    keyboard.append(model_buttons[i : i + 2])

  keyboard.append([
      InlineKeyboardButton("🗑 پاکسازی حافظه", callback_data="action_clear"),
      InlineKeyboardButton("❓ راهنما", callback_data="action_help"),
  ])

  return InlineKeyboardMarkup(keyboard)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
  user_id = update.effective_user.id
  current_model = get_user_model(user_id)
  get_chat(user_id, current_model)

  markup = build_main_keyboard(current_model)
  await update.message.reply_text(
      f"سلام رفیق! من علی هستم. 🤖\n\n"
      f"هر سوالی داری بپرس یا عکس بفرست تا آنالیزش کنم.\n"
      f"مدل فعال فعلی: `{AVAILABLE_MODELS.get(current_model, current_model)}`",
      reply_markup=markup,
      parse_mode="Markdown",
  )


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
  user_id = update.effective_user.id
  current_model = get_user_model(user_id)
  if user_id in user_chats:
    del user_chats[user_id]
  get_chat(user_id, current_model)
  await update.message.reply_text("🧹 حافظه چت با موفقیت پاک شد!")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
  user_id = update.effective_user.id
  text = update.message.text
  chat = get_chat(user_id)

  await context.bot.send_chat_action(
      chat_id=update.effective_chat.id, action="typing"
  )

  try:
    response = chat.send_message(text)
    await update.message.reply_text(response.text)
  except Exception as e:
    await update.message.reply_text(f"❌ خطایی رخ داد: {str(e)}")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
  user_id = update.effective_user.id
  model_name = get_user_model(user_id)

  await context.bot.send_chat_action(
      chat_id=update.effective_chat.id, action="typing"
  )

  try:
    photo_file = await update.message.photo[-1].get_file()
    photo_bytes = await photo_file.download_as_bytearray()
    image = Image.open(io.BytesIO(photo_bytes))

    caption = (
        update.message.caption or "این تصویر رو تحلیل کن و توضیحات کامل بده."
    )

    response = client.models.generate_content(
        model=model_name, contents=[image, caption]
    )

    await update.message.reply_text(response.text)
  except Exception as e:
    await update.message.reply_text(
        f"❌ خطایی در پردازش عکس رخ داد: {str(e)}"
    )


async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
  query = update.callback_query
  await query.answer()
  user_id = query.from_user.id

  if query.data.startswith("model_"):
    selected_model = query.data.replace("model_", "")
    get_chat(user_id, model_name=selected_model)
    markup = build_main_keyboard(selected_model)
    model_title = AVAILABLE_MODELS.get(selected_model, selected_model)
    await query.edit_message_text(
        f"✅ مدل هوش مصنوعی تغییر کرد به: `{model_title}`",
        reply_markup=markup,
        parse_mode="Markdown",
    )
  elif query.data == "action_clear":
    if user_id in user_chats:
      del user_chats[user_id]
    current_model = get_user_model(user_id)
    get_chat(user_id, current_model)
    await query.message.reply_text("🧹 حافظه گفتگو ریست شد.")
  elif query.data == "action_help":
    await query.message.reply_text(
        "📌 راهنمای استفاده:\n"
        "• متن بفرست تا جوابت رو بدم.\n"
        "• عکس بفرست تا برات آنالیز کنم.\n"
        "• با دکمه‌های منو می‌تونی مدل‌ها رو عوض کنی.\n"
        "• دستور /clear حافظه رو پاک می‌کنه."
    )


async def run_bot_async():
  app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

  app.add_handler(CommandHandler("start", start))
  app.add_handler(CommandHandler("clear", clear_command))
  app.add_handler(CallbackQueryHandler(button_click))
  app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
  app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

  await app.initialize()
  await app.start()
  await app.updater.start_polling(drop_pending_updates=True)

  while True:
    await asyncio.sleep(3600)


def start_bot_thread():
  loop = asyncio.new_event_loop()
  asyncio.set_event_loop(loop)
  loop.run_until_complete(run_bot_async())


bot_thread = threading.Thread(target=start_bot_thread, daemon=True)
bot_thread.start()

with gr.Blocks() as demo:
  gr.Markdown("# 🤖 ربات هوش مصنوعی علی")
  gr.Markdown("میزبانی پایدار در Render.")

if __name__ == "__main__":
  port = int(os.getenv("PORT", 7860))
  demo.launch(server_name="0.0.0.0", server_port=port)
