import os, glob, shutil, subprocess, logging, math, re
import requests
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)

logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
WORK_DIR = "/tmp/videobot"
WAITING_SECONDS, WAITING_LINK = range(2)

def extract_gdrive_id(url):
    patterns = [r'/file/d/([a-zA-Z0-9_-]+)', r'id=([a-zA-Z0-9_-]+)']
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None

def download_gdrive(file_id, dest_path):
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    session = requests.Session()
    url = f"https://drive.google.com/uc?export=download&id={file_id}&confirm=t"
    response = session.get(url, stream=True)
    for key, value in response.cookies.items():
        if key.startswith("download_warning"):
            url = f"https://drive.google.com/uc?export=download&id={file_id}&confirm={value}"
            response = session.get(url, stream=True)
            break
    with open(dest_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=32768):
            if chunk:
                f.write(chunk)
    return dest_path

def get_duration(path):
    result = subprocess.run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", path
    ], capture_output=True, text=True)
    return float(result.stdout.strip())

def split_video(input_path, output_dir, segment_sec):
    os.makedirs(output_dir, exist_ok=True)
    pattern = os.path.join(output_dir, "part_%03d.mp4")
    subprocess.run([
        "ffmpeg", "-i", input_path,
        "-c", "copy", "-map", "0",
        "-segment_time", str(segment_sec),
        "-f", "segment",
        "-reset_timestamps", "1",
        pattern, "-y"
    ], check=True, capture_output=True)
    return sorted(glob.glob(os.path.join(output_dir, "part_*.mp4")))

def compress_if_needed(path, max_mb=45):
    size_mb = os.path.getsize(path) / (1024 * 1024)
    if size_mb <= max_mb:
        return path
    duration = get_duration(path)
    target_bitrate = int((max_mb * 8 * 1024) / duration * 0.95)
    video_bitrate = target_bitrate - 128
    compressed = path.replace(".mp4", "_c.mp4")
    subprocess.run([
        "ffmpeg", "-i", path,
        "-b:v", f"{video_bitrate}k", "-b:a", "128k",
        "-c:v", "libx264", "-c:a", "aac",
        compressed, "-y"
    ], check=True, capture_output=True)
    os.remove(path)
    return compressed

async def start(update, context):
    await update.message.reply_text(
        "✂️ *Видео-нарезчик*\n\n"
        "Режу видео на равные части.\n\n"
        "Как пользоваться:\n"
        "1. Загрузи видео на Google Drive\n"
        "2. Открой доступ по ссылке\n"
        "3. Отправь ссылку боту через /cut\n\n"
        "/cut — начать",
        parse_mode="Markdown"
    )

async def cut_start(update, context):
    await update.message.reply_text(
        "⏱ На сколько секунд резать?\n"
        "Отправь число, например `60`",
        parse_mode="Markdown"
    )
    return WAITING_SECONDS

async def receive_seconds(update, context):
    text = update.message.text.strip()
    if not text.isdigit() or int(text) < 5:
        await update.message.reply_text("⚠️ Введи число от 5 и выше")
        return WAITING_SECONDS
    context.user_data["seconds"] = int(text)
    await update.message.reply_text(
        f"✅ Буду резать по *{text} сек*\n\n"
        "🔗 Отправь ссылку на видео с Google Drive\n\n"
        "_(Файл → Поделиться → Все у кого есть ссылка)_",
        parse_mode="Markdown"
    )
    return WAITING_LINK

async def receive_link(update, context):
    url = update.message.text.strip()
    file_id = extract_gdrive_id(url)

    if not file_id:
        await update.message.reply_text(
            "❌ Не могу распознать ссылку Google Drive\n"
            "Пример правильной ссылки:\n"
            "`https://drive.google.com/file/d/XXXXX/view`",
            parse_mode="Markdown"
        )
        return WAITING_LINK

    seconds = context.user_data.get("seconds", 60)
    user_id = update.effective_user.id
    work_dir = os.path.join(WORK_DIR, str(user_id))
    video_path = os.path.join(work_dir, "download", "input.mp4")
    out_dir = os.path.join(work_dir, "output")

    msg = await update.message.reply_text("⬇️ Скачиваю видео с Google Drive...")

    try:
        download_gdrive(file_id, video_path)
        duration = get_duration(video_path)
        parts_count = math.ceil(duration / seconds)

        await msg.edit_text(f"✂️ Режу на {parts_count} частей по {seconds} сек...")
        parts = split_video(video_path, out_dir, seconds)

        for i, part in enumerate(parts, 1):
            part = compress_if_needed(part)
            await msg.edit_text(f"📤 Отправляю {i}/{len(parts)}...")
            with open(part, "rb") as f:
                await update.message.reply_video(
                    video=f,
                    caption=f"Часть {i}/{len(parts)}",
                    supports_streaming=True
                )

        await msg.edit_text(f"✅ Готово! Отправил {len(parts)} видео.")

    except Exception as e:
        logging.error(e)
        await msg.edit_text(
            "❌ Ошибка. Проверь:\n"
            "• Доступ к файлу открыт для всех\n"
            "• Ссылка именно на файл, не на папку\n\n"
            "Попробуй /cut снова"
        )
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    return ConversationHandler.END

async def cancel(update, context):
    await update.message.reply_text("❌ Отменено. /cut — начать заново")
    return ConversationHandler.END

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("cut", cut_start)],
        states={
            WAITING_SECONDS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_seconds)],
            WAITING_LINK:    [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link)],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv)
    app.run_polling()

if __name__ == "__main__":
    main()
