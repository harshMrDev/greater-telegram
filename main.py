import os
import re
import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode
import yt_dlp

API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")

YOUTUBE_REGEX = re.compile(
    r'(https?://(?:www\.)?(?:youtube\.com/(?:watch\?v=|shorts/)|youtu\.be/)[\w\-\_\?&=]+)'
)

def extract_youtube_links(text):
    return YOUTUBE_REGEX.findall(text or "")

def sanitize_filename(name):
    return re.sub(r'[^a-zA-Z0-9_\-\.]', '_', name)

def make_sexy_progress_bar(downloaded, total, speed=None, eta=None, bar_length=18):
    """Return a visually-appealing progress bar string for Telegram."""
    if total == 0:
        return "🟡 Starting..."
    percent = downloaded / total
    filled_len = int(bar_length * percent)
    bar = "🟩" * filled_len + "⬜" * (bar_length - filled_len)
    percent_text = f"{percent*100:5.1f}%"
    size_text = f"{downloaded/1048576:.1f}MB / {total/1048576:.1f}MB"
    speed_text = f"🚀 {speed/1048576:.2f}MB/s" if speed else ""
    eta_text = f"⏳ {int(eta)}s left" if eta else ""
    extras = "  ".join(x for x in [speed_text, eta_text] if x)
    fun = "🔥" if speed and speed > 2*1048576 else ""
    return (
        f"*Downloading:*\n"
        f"{bar} `{percent_text}` {fun}\n"
        f"`{size_text}`\n"
        f"{extras}"
    )

async def download_youtube(link, mode, cookies_file=None, progress_callback=None):
    def get_stream():
        outtmpl = "/tmp/%(title).60s.%(ext)s"
        ydl_opts = {
            "progress_hooks": [progress_callback] if progress_callback else [],
        }
        if mode == 'audio':
            ydl_opts.update({
                'format': 'bestaudio/best',
                'outtmpl': outtmpl,
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            })
        elif mode == 'video_360':
            ydl_opts.update({
                'format': 'bestvideo[height<=360]+bestaudio/best[height<=360]/best[height<=360]',
                'outtmpl': outtmpl,
                'merge_output_format': 'mp4',
            })
        elif mode == 'video_480':
            ydl_opts.update({
                'format': 'bestvideo[height<=480]+bestaudio/best[height<=480]/best[height<=480]',
                'outtmpl': outtmpl,
                'merge_output_format': 'mp4',
            })
        elif mode == 'video_1080':
            ydl_opts.update({
                'format': 'bestvideo[height<=1080]+bestaudio/best[height<=1080]/best[height<=1080]',
                'outtmpl': outtmpl,
                'merge_output_format': 'mp4',
            })
        else:
            raise Exception("Invalid mode")
        if cookies_file and os.path.exists(cookies_file):
            ydl_opts['cookiefile'] = cookies_file
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(link, download=True)
            if mode == 'audio':
                filename = ydl.prepare_filename(info).rsplit('.', 1)[0] + '.mp3'
            else:
                ext = 'mp4'
                filename = ydl.prepare_filename(info).rsplit('.', 1)[0] + f'.{ext}'
            safe_filename = '/tmp/' + sanitize_filename(os.path.basename(filename))
            if filename != safe_filename and os.path.exists(filename):
                os.rename(filename, safe_filename)
            return safe_filename if os.path.exists(safe_filename) else filename
    return await asyncio.to_thread(get_stream)

app = Client(
    "youtube_downloader_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
)

user_sessions = {}

@app.on_message(filters.command("start"))
async def start(client, message: Message):
    await message.reply(
        "🎉 *YouTube Downloader Bot*\n\n"
        "Send a YouTube link (or a .txt file with links).\n"
        "I'll ask for Audio/Video and, if video, ask for quality.\n"
        "Files up to 4GB supported.",
        parse_mode=ParseMode.MARKDOWN
    )

@app.on_message(filters.command("help"))
async def help_command(client, message: Message):
    await message.reply(
        "Send a YouTube link (or a .txt file with links).\n"
        "I'll ask if you want audio or video, then for video: the quality (360p/480p/1080p).\n"
        "Files up to 4GB are supported.",
        parse_mode=ParseMode.MARKDOWN
    )

@app.on_message(filters.text | filters.document)
async def handle_message(client, message: Message):
    links = []
    if message.document and message.document.mime_type == "text/plain":
        file = await client.download_media(message.document)
        with open(file, "r") as f:
            for line in f:
                links += extract_youtube_links(line.strip())
        os.remove(file)
    elif message.text:
        links = extract_youtube_links(message.text)

    if not links:
        await message.reply("No YouTube links found.")
        return

    user_sessions[message.from_user.id] = {"pending_links": links}
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎵 Audio", callback_data="choose_audio"),
         InlineKeyboardButton("📺 Video", callback_data="choose_video")],
        [InlineKeyboardButton("❌ Cancel", callback_data="choose_cancel")]
    ])
    await message.reply("Choose format:", reply_markup=keyboard)

@app.on_callback_query()
async def inline_callback(client, callback_query):
    user_id = callback_query.from_user.id
    session = user_sessions.get(user_id, {})
    links = session.get("pending_links", [])
    data = callback_query.data

    if data == 'choose_audio':
        await callback_query.edit_message_text("Downloading audio...")
        await process_and_send(client, callback_query.message, links, 'audio')
        user_sessions.pop(user_id, None)
    elif data == 'choose_video':
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📺 360p", callback_data='video_360'),
             InlineKeyboardButton("📺 480p", callback_data='video_480'),
             InlineKeyboardButton("📺 1080p", callback_data='video_1080')],
            [InlineKeyboardButton("❌ Cancel", callback_data='choose_cancel')]
        ])
        await callback_query.edit_message_text("Choose video quality:", reply_markup=keyboard)
        session["awaiting_quality"] = True
    elif data in ['video_360', 'video_480', 'video_1080']:
        quality_label = data.replace("video_", "")
        await callback_query.edit_message_text(f"Downloading {quality_label} ...")
        await process_and_send(client, callback_query.message, links, data)
        user_sessions.pop(user_id, None)
    elif data == 'choose_cancel':
        await callback_query.edit_message_text("Cancelled.")
        user_sessions.pop(user_id, None)
    else:
        await callback_query.edit_message_text("Unknown action.")

async def process_and_send(client, message, links, mode):
    cookies_file = 'cookies.txt' if os.path.exists('cookies.txt') else None
    for link in links:
        try:
            progress_msg = await message.reply(f"🎯 Processing: {link}")
            last_percent = -1  # To avoid unnecessary edits

            async def edit_progress(d):
                if d['status'] == 'downloading':
                    total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                    downloaded = d.get('downloaded_bytes', 0)
                    speed = d.get('speed')
                    eta = d.get('eta')
                    if total and downloaded:
                        percent = int(100 * downloaded / total)
                        nonlocal last_percent
                        if percent != last_percent:
                            last_percent = percent
                            bar = make_sexy_progress_bar(downloaded, total, speed, eta)
                            await progress_msg.edit_text(
                                bar + f"\n[`{link}`]",
                                parse_mode=ParseMode.MARKDOWN,
                                disable_web_page_preview=True
                            )

            def progress_hook(d):
                asyncio.run_coroutine_threadsafe(edit_progress(d), client.loop)

            file_path = await download_youtube(link, mode, cookies_file, progress_hook)
            if not os.path.exists(file_path):
                await message.reply("❌ Download failed, file not found!")
                continue
            size = os.path.getsize(file_path)
            if size == 0:
                await message.reply("❌ File is empty. Download failed!")
                os.remove(file_path)
                continue
            if size > 4 * 1024 * 1024 * 1024:
                await message.reply("❌ File too large! Max 4GB allowed.")
                os.remove(file_path)
                continue
            await progress_msg.edit_text("✅ Uploading to Telegram...", parse_mode=ParseMode.MARKDOWN)
            await message.reply_document(file_path)
            os.remove(file_path)
            await progress_msg.delete()
        except Exception as e:
            await message.reply(
                f"❌ Failed for {link}:\n`{str(e)}`", parse_mode=ParseMode.MARKDOWN
            )

if __name__ == "__main__":
    app.run()
