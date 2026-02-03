import os
import asyncio
import logging
from pyrogram import Client, filters, idle
from pyrogram.enums import ParseMode
from dotenv import load_dotenv
from aiohttp import web

# Загружаем переменные из .env (для локального теста)
load_dotenv()

# ================== НАСТРОЙКИ ==================
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

MAX_QUEUE_SIZE = 5
WORKERS_COUNT = 1  # На бесплатных хостингах лучше оставить 1, чтобы не превышать лимиты CPU
MAX_VIDEO_SIZE = 100 * 1024 * 1024  # 100 MB
TEMP_DIR = "/tmp/circle_bot"

os.makedirs(TEMP_DIR, exist_ok=True)
logging.basicConfig(level=logging.INFO)

# ================== КЛИЕНТ ==================
app = Client(
    "circle_bot_session",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workdir=TEMP_DIR,
    ipv6=False,  # Оставляем False для надежности
    proxy=dict(
        hostname="193.233.254.8",
        port=1080,
        scheme="socks5"
    )
)

queue = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)

# ================== FFMPEG ==================
async def make_circle_async(input_path: str, output_path: str):
    # Telegram требует: 1:1 соотношение сторон, формат mp4, обычно до 640x640
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-t", "60", # Обрезаем до 1 минуты (лимит Telegram)
        "-vf", "crop=min(iw\\,ih):min(iw\\,ih),scale=512:512",
        "-c:v", "libx264",
        "-preset", "ultrafast", # Быстрая обработка для слабых CPU
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-c:a", "aac", "-b:a", "128k",
        output_path
    ]
    
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE
    )
    
    try:
        await asyncio.wait_for(process.communicate(), timeout=180)
    except asyncio.TimeoutError:
        process.kill()
        raise RuntimeError("FFmpeg: время обработки истекло")
    
    if process.returncode != 0:
        raise RuntimeError("FFmpeg: ошибка конвертации")

# ================== WORKER ==================
async def worker():
    logging.info("Worker started")
    while True:
        message, input_path = await queue.get()
        output_path = os.path.join(TEMP_DIR, f"circle_{message.id}.mp4")
        
        status = await message.reply("⚙️ Обрабатываю видео...")
        
        try:
            await make_circle_async(input_path, output_path)
            await message.reply_video_note(video_note=output_path)
            await status.delete()
        except Exception as e:
            logging.error(f"Error processing: {e}")
            await status.edit(f"❌ Ошибка: {e}")
        finally:
            # Чистим за собой
            for f in (input_path, output_path):
                if os.path.exists(f):
                    os.remove(f)
            queue.task_done()

# ================== HANDLERS ==================
@app.on_message(filters.command("start"))
async def start(_, msg):
    gif_url = "https://media3.giphy.com/media/v1.Y2lkPTc5MGI3NjExY3JicWZ0ZXpna2N2N2FmbjMwZnRmZDE0bnRqZXlzMGx0emdubTU0cCZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/ACeIDlMpgc4yOf1Lyt/giphy.gif"

    text = (
        "👋 <b>Привет!</b>\n\n"
        "Я помогу превратить любое видео в <b>видеокружок</b> для Telegram ⭕\n\n"
        "📤 <b>Просто отправь мне видео</b> — я всё сделаю сам.\n\n"
        "✨ <b>Возможности:</b>\n"
        "• Максимальный размер видео — <b>100 МБ</b>\n"
        "• Автоматическое приведение к нужному формату\n"
        "• Автоматическая обрезка длительности видео\n"
        "• Оптимизация под требования Telegram\n\n"
        "⚡ Быстро, просто и без лишних настроек "
        "<a href='https://t.me/@ClipGetBot'>@ClipGetBot</a>"
    )

    await msg.reply_animation(
        animation=gif_url,
        caption=text,
        parse_mode=ParseMode.HTML
    )


@app.on_message(filters.video | filters.document)
async def handle_video(client, message):
    # Проверка на тип файла, если это документ
    if message.document and not message.document.mime_type.startswith("video/"):
        return

    if queue.full():
        await message.reply("⏳ Очередь переполнена. Попробуйте через минуту.")
        return

    # Защита от слишком больших файлов
    file_size = message.video.file_size if message.video else message.document.file_size
    if file_size > MAX_VIDEO_SIZE:
        await message.reply("⚠️ Файл слишком большой (макс. 100 МБ).")
        return

    wait_msg = await message.reply("📥 Скачиваю видео...")
    
    try:
        input_path = os.path.join(TEMP_DIR, f"input_{message.id}.mp4")
        await message.download(file_name=input_path)
        
        await queue.put((message, input_path))
        await wait_msg.edit("✅ Видео добавлено в очередь.")
    except Exception as e:
        await wait_msg.edit(f"❌ Ошибка загрузки: {e}")

# ================== RUN ==================
async def keep_alive():
    async def handle(request):
        return web.Response(text="Bot is alive!")
    
    app_web = web.Application()
    app_web.router.add_get("/", handle)
    runner = web.AppRunner(app_web)
    await runner.setup()
    # Hugging Face всегда ищет порт 7860
    site = web.TCPSite(runner, "0.0.0.0", 7860)
    await site.start()
    logging.info("Keep-alive server started on port 7860")

# === ОБНОВЛЕННЫЙ RUN ===
async def main():
    await app.start()
    logging.info("--- BOT STARTED ---")
    
    # Запускаем веб-сервер, чтобы Hugging Face нас не убил
    await keep_alive()
    
    for _ in range(WORKERS_COUNT):
        asyncio.create_task(worker())
        
    await idle()
    await app.stop()

if __name__ == "__main__":
    import asyncio
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        pass