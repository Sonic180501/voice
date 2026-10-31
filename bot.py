import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
import google.generativeai as genai

# Переменные окружения (задаются на Render.com)
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY")
WEB_APP_URL = os.getenv("WEB_APP_URL", "https://your-domain.vercel.app")

genai.configure(api_key=GEMINI_API_KEY)

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def start_handler(message: types.Message):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎙️ Открыть Web App",
                    web_app=WebAppInfo(url=WEB_APP_URL)
                )
            ]
        ]
    )
    await message.answer(
        "👋 **Добро пожаловать в SpeechToText AI Bot!**\n\n"
        "1️⃣ Нажмите **«Открыть Web App»** для быстрой работы с короткими файлами.\n"
        "2️⃣ Или **отправьте длинный аудиофайл / голосовое** прямо в этот чат (до 2 ГБ)!",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

@dp.message(F.voice | F.audio | F.document)
async def handle_audio_file(message: types.Message):
    status_msg = await message.answer("📥 Загрузка файла...")
    
    file_id = None
    if message.voice:
        file_id = message.voice.file_id
    elif message.audio:
        file_id = message.audio.file_id
    elif message.document and (message.document.mime_type or '').startswith(('audio/', 'video/')):
        file_id = message.document.file_id
    
    if not file_id:
        await status_msg.edit_text("❌ Пожалуйста, отправьте аудиофайл.")
        return

    try:
        file_info = await bot.get_file(file_id)
        os.makedirs("downloads", exist_ok=True)
        file_path = f"downloads/{file_id}_{os.path.basename(file_info.file_path)}"
        
        await bot.download_file(file_info.file_path, file_path)
        await status_msg.edit_text("⚡ Транскрибация речи через Gemini AI...")

        uploaded_file = genai.upload_file(file_path)
        
        candidate_models = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash-latest"]
        response = None
        
        for model_name in candidate_models:
            try:
                model = genai.GenerativeModel(model_name)
                prompt = (
                    "Транскрибируй следующее аудио точно и без ошибок. "
                    "Распознавай узбекский и русский языки. Разделяй спикеров по репликам."
                )
                response = model.generate_content([prompt, uploaded_file])
                if response and response.text:
                    break
            except Exception:
                continue

        if os.path.exists(file_path):
            os.remove(file_path)
        genai.delete_file(uploaded_file.name)

        if not response or not response.text:
            await status_msg.edit_text("❌ Не удалось получить расшифровку от Gemini API.")
            return

        text = response.text
        if len(text) > 4000:
            with open("transcription.txt", "w", encoding="utf-8") as f:
                f.write(text)
            await message.answer_document(
                types.FSInputFile("transcription.txt"),
                caption="📝 Текст расшифровки:"
            )
            os.remove("transcription.txt")
        else:
            await message.answer(f"📝 **Результат расшифровки:**\n\n{text}", parse_mode="Markdown")
            
        await status_msg.delete()

    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка при обработке: {str(e)}")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
