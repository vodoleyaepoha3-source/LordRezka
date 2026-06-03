import os, glob, shutil, subprocess, logging, math
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
WORK_DIR = "/tmp/videobot"

WAITING_SECONDS, WAITING_LINK = range(2)

def get_duration(path):
    result = subprocess.run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path
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
    audio_bitrate = 128
    video_bitrate = target_bitrate - audio_bitrate
    compressed = path.replace(".mp4", "_compressed.mp4")
    subprocess.run([
        "ffmpeg", "-i", path,
        "-b:v", f"{video_bitrate}k",
        "-b:a", f"{audio_bitrate}k",
        "-c:v", "libx264", "-c:a", "aac",
        compressed, "-y"
    ], check=True, capture_output=True)
    os.remove(path)
    return compressed

def download_video(url, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    out_template = os.path.join(out_dir, "input.%(ext)s")
    subprocess.run([
        "yt-dlp", "--no-playlist",
        "-o", out_template, url
    ], check=True)
    files = glob.glob(os.path.join(out_dir, "input.*"))
    if not files:
        raise FileNotFoundError("Видео не скачалось")
    return files[0]

async def start(update, context):
    await update.message.reply_text(
        "✂️ *Видео-нарезчик*\n\n"
        "Режу видео на равные части.\n\n"
        "Поддерживаю:\n"
        "• Google Drive\n"
        "• YouTube\n\n"
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
        "🔗 Отправь ссылку на видео\n_(Google Drive или YouTube)_",
        parse_mode="Markdown"
    )
    return WAITING_LINK

async def receive_link(update, context):
    url = update.message.text.strip()
    user_id = update.effective_user.id
    seconds = context.user_data.get("seconds", 60)
    work_dir = os.path.join(WORK_DIR, str(user_id))
    dl_dir = os.path.join(work_dir, "download")
    out_dir = os.path.join(work_dir, "output")
    msg = await update.message.reply_text("⬇️ Скачиваю видео...")
    try:
        video_path = download_video(url, dl_dir)
        duration = get_duration(video_path)
        parts_count = math.ceil(duration / seconds)
        await msg.edit_text(f"✂️ Режу на {parts_count} частей по {seconds} сек...")
        parts = split_video(video_path, out_dir, seconds)
        await msg.edit_text(f"📤 Отправляю {len(parts)} файлов...")
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
            "• Ссылка открыта для всех\n"
            "• Видео доступно\n\n"
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
