import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from google import genai
from aiohttp import web

# --- НАСТРОЙКИ ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
RAW_GEMINI_KEY = os.getenv("GEMINI_API_KEY", "").strip()
WEB_APP_URL = os.getenv("WEB_APP_URL", "https://your-web-app-url.vercel.app")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Инициализация нового клиента Gemini API
ai_client = None
if RAW_GEMINI_KEY:
    ai_client = genai.Client(api_key=RAW_GEMINI_KEY)

@dp.message(CommandStart())
async def start_handler(message: types.Message):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎙️ Открыть Web App (для файлов >20 МБ)",
                    web_app=WebAppInfo(url=WEB_APP_URL)
                )
            ]
        ]
    )
    await message.answer(
        "👋 **Добро пожаловать в SpeechToText AI Bot!**\n\n"
        "📌 **Как отправить аудио:**\n"
        "• **До 20 МБ**: Просто отправьте голосовое или файл прямо в этот чат.\n"
        "• **Больше 20 МБ (до 2 ГБ)**: Нажмите кнопку **«Открыть Web App»** ниже!",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

@dp.message(F.voice | F.audio | F.document)
async def handle_audio_file(message: types.Message):
    if not ai_client:
        await message.answer("❌ Ошибка: GEMINI_API_KEY не установлен или недействителен.")
        return

    file_size = 0
    file_id = None
    
    if message.voice:
        file_id = message.voice.file_id
        file_size = message.voice.file_size or 0
    elif message.audio:
        file_id = message.audio.file_id
        file_size = message.audio.file_size or 0
    elif message.document and (message.document.mime_type or '').startswith(('audio/', 'video/')):
        file_id = message.document.file_id
        file_size = message.document.file_size or 0
    
    if not file_id:
        await message.answer("❌ Пожалуйста, отправьте аудиофайл.")
        return

    # Ограничение Telegram Bot API (20 MB)
    if file_size > 20 * 1024 * 1024:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🎙️ Открыть Web App", web_app=WebAppInfo(url=WEB_APP_URL))]
            ]
        )
        await message.answer(
            "⚠️ **Этот файл больше 20 МБ!**\n\n"
            "Telegram Bot API не позволяет ботам скачивать файлы больше 20 МБ в чате.\n\n"
            "👇 Нажмите **«Открыть Web App»** — там можно легко расшифровать файлы любого размера (до 2 ГБ)!",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        return

    status_msg = await message.answer("📥 Загрузка файла...")

    try:
        file_info = await bot.get_file(file_id)
        file_path = f"downloads/{file_id}_{os.path.basename(file_info.file_path)}"
        os.makedirs("downloads", exist_ok=True)
        
        await bot.download_file(file_info.file_path, file_path)
        await status_msg.edit_text("⚡ Расшифровка через Gemini 3 Flash (Узбекский / Русский)...")

        # Загрузка файла в Gemini Files API
        uploaded_file = ai_client.files.upload(file=file_path)
        
        prompt = (
            "Транскрибируй следующее аудио максимально точно и подробно. "
            "Распознавай узбекский и русский языки, включая смешанные реплики. "
            "Разделяй спикеров по строкам (Спикер 1, Спикер 2)."
        )

        # Вызов новейшей модели Gemini 3 Flash
        response = ai_client.models.generate_content(
            model='gemini-3-flash-preview',
            contents=[prompt, uploaded_file]
        )

        if os.path.exists(file_path):
            os.remove(file_path)
        try:
            ai_client.files.delete(name=uploaded_file.name)
        except Exception:
            pass

        if not response or not response.text:
            await status_msg.edit_text("❌ Не удалось получить расшифровку от Gemini API.")
            return

        text = response.text
        if len(text) > 4000:
            with open("transcription.txt", "w", encoding="utf-8") as f:
                f.write(text)
            await message.answer_document(
                types.FSInputFile("transcription.txt"),
                caption="📝 Текст расшифровки (Gemini 3 Flash):"
            )
            os.remove("transcription.txt")
        else:
            await message.answer(f"📝 **Результат расшифровки (Gemini 3 Flash):**\n\n{text}", parse_mode="Markdown")
            
        await status_msg.delete()

    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка при обработке: {str(e)}")

async def handle_ping(request):
    return web.Response(text="Bot is running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_ping)
    app.router.add_get('/health', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

async def main():
    await start_web_server()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())