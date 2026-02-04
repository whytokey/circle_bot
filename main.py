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

MAX_QUEUE_SIZE = 10
WORKERS_COUNT = 2
MAX_VIDEO_SIZE = 100_000_000

TEMP_DIR = "/tmp/video_notes"
os.makedirs(TEMP_DIR, exist_ok=True)

app = Client(
    "circle_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workdir="/tmp" # Храним сессию во временной папке
)

queue = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)


# ================== FFMPEG ==================

async def make_circle_async(input_path: str, output_path: str):
    cmd = [
        "ffmpeg",
        "-y",
        "-i", input_path,
        "-t", "60",
        "-vf", "crop=min(iw\\,ih):min(iw\\,ih),scale=512:512",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-profile:v", "baseline",
        "-level", "3.0",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-c:a", "aac",
        "-b:a", "128k",
        output_path
    ]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE
    )

    try:
        await asyncio.wait_for(process.communicate(), timeout=120)
    except asyncio.TimeoutError:
        process.kill()
        raise RuntimeError("ffmpeg timeout")

    if process.returncode != 0:
        raise RuntimeError("ffmpeg error")


# ================== WORKER ==================

async def worker(worker_id: int):
    while True:
        message, input_path = await queue.get()
        output_path = f"{TEMP_DIR}/circle_{message.id}.mp4"

        try:
            await make_circle_async(input_path, output_path)
            await message.reply_video_note(output_path)

        except Exception as e:
            await message.reply(f"❌ Ошибка обработки: {e}")

        finally:
            for f in (input_path, output_path):
                if f and os.path.exists(f):
                    os.remove(f)

            queue.task_done()


# ================== HANDLER ==================

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

@app.on_message(filters.video)
async def handle_video(_, message):
    if message.video.file_size > MAX_VIDEO_SIZE:
        await message.reply("⚠️ Видео слишком большое (макс. 20 МБ)")
        return

    if queue.full():
        await message.reply("⏳ Бот сейчас перегружен, попробуйте позже")
        return

    status = await message.reply("📥 Видео принято, ставлю в очередь...")

    try:
        input_path = await message.download(
            file_name=f"{TEMP_DIR}/{message.id}.mp4"
        )
        await queue.put((message, input_path))
        await status.edit("⏳ Видео в очереди на обработку")

    except Exception as e:
        await status.edit(f"❌ Ошибка загрузки: {e}")


# ================== RUN ==================

if __name__ == "__main__":
    loop = asyncio.get_event_loop()

    # 🔥 Запускаем воркеры ДО старта бота
    for i in range(WORKERS_COUNT):
        loop.create_task(worker(i))

    print(f"🤖 Бот запущен | воркеров: {WORKERS_COUNT}")
    app.run()
