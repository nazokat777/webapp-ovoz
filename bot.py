import sys
# Windows konsolida emoji chop etish uchun UTF-8 ga o'tkazish
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import logging
import os
import json
import time
import base64
import tempfile
import subprocess
import math
import shutil
import requests
import re
import asyncio
import threading
from telegram import (
    Update, KeyboardButton, ReplyKeyboardMarkup, WebAppInfo,
)
from fpdf import FPDF
from fpdf.enums import XPos, YPos
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes,
)
from aiohttp import web

BOT_TOKEN   = os.getenv("BOT_TOKEN", "8502384684:AAETKbx4YBtiQ9W7PRTWUeVumwwnG-lH9R8")
MUXLISA_KEY = os.getenv("MUXLISA_KEY", "UYaezERZPBO7pkJj4wzttq5eV90cGdFrI8XxGyCl")

# Web App URL — ngrok yoki o'z serveringiz URL'ini kiriting
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://botch-engaging-mustang.ngrok-free.dev")
HTTP_PORT  = int(os.getenv("HTTP_PORT", 8000))

MUXLISA_URL   = "https://service.muxlisa.uz/api/v2/stt"
# Muxlisa cheklovi: 60 sek davomiylik. Xavfsizlik buferi bilan 50 sek bo'laklar.
# 1 soatlik audio = ~72 bo'lak. Har biri Muxlisa'ga alohida yuboriladi.
CHUNK_SECONDS = 50

HERE       = os.path.dirname(os.path.abspath(__file__))
INDEX_HTML = os.path.join(HERE, "index.html")

bot_app = None

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

URL_PATTERN = re.compile(r'https?://\S+')


def extract_url(text):
    if not text:
        return None
    m = URL_PATTERN.search(text)
    return m.group(0).rstrip('.,;:!?)') if m else None


def have_cmd(cmd):
    return shutil.which(cmd) is not None


def cors_headers():
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, OPTIONS, GET",
        "Access-Control-Allow-Headers": "Content-Type",
    }


# ── AUDIO/VIDEO UTILS ───────────────────────────────────────────────────────

def convert_to_wav(input_path):
    if not have_cmd("ffmpeg"):
        raise Exception("ffmpeg topilmadi. Iltimos ffmpeg o'rnating va PATH ga qo'shing.")
    wav_path = input_path + ".wav"
    result = subprocess.run([
        "ffmpeg", "-y", "-i", input_path,
        "-vn", "-ar", "16000", "-ac", "1",
        "-acodec", "pcm_s16le", "-f", "wav", wav_path
    ], capture_output=True)
    if result.returncode != 0:
        result = subprocess.run([
            "ffmpeg", "-y", "-i", input_path,
            "-map", "0:a:0", "-ar", "16000", "-ac", "1",
            "-acodec", "pcm_s16le", "-f", "wav", wav_path
        ], capture_output=True)
        if result.returncode != 0:
            stderr = (result.stderr or b"").decode(errors="ignore")[:300]
            raise Exception(f"ffmpeg konvertatsiya xatosi: {stderr}")
    return wav_path


def download_audio_from_url(url):
    if not have_cmd("yt-dlp"):
        raise Exception("yt-dlp o'rnatilmagan. Terminalda: pip install -U yt-dlp")
    if not have_cmd("ffmpeg"):
        raise Exception("ffmpeg topilmadi. yt-dlp ga audio konvertatsiya kerak.")

    tmp_dir = tempfile.mkdtemp()
    output_template = os.path.join(tmp_dir, "audio.%(ext)s")
    try:
        result = subprocess.run([
            "yt-dlp", "-x",
            "--audio-format", "wav",
            "--no-playlist",
            "--no-warnings",
            "-o", output_template, url
        ], capture_output=True, text=True)

        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            low = stderr.lower()
            if "instagram" in url.lower():
                if "login" in low or "rate" in low or "cookies" in low or "private" in low:
                    raise Exception(
                        "Instagram bu havolaga login yoki cookies talab qilyapti. "
                        "Iltimos public post yuboring (yoki yt-dlp uchun cookies sozlang)."
                    )
                if "unsupported url" in low:
                    raise Exception("Instagram havolasi tan olinmadi. Public post URL yuboring.")
            if "login" in low or "private" in low:
                raise Exception("Bu video private yoki login talab qiladi.")
            if "unsupported url" in low:
                raise Exception("Bu havola turi qo'llab-quvvatlanmaydi.")
            if "http error 403" in low or "forbidden" in low:
                raise Exception("Manba 403 qaytardi. yt-dlp ni yangilang: pip install -U yt-dlp")
            err_msg = stderr[:300] or "noma'lum xato"
            raise Exception(f"yt-dlp xatosi: {err_msg}")

        downloaded = None
        for f in sorted(os.listdir(tmp_dir)):
            if f.startswith("audio."):
                downloaded = os.path.join(tmp_dir, f)
                break
        if not downloaded:
            raise Exception("Yuklab olingan fayl topilmadi.")

        if downloaded.lower().endswith(".wav"):
            return downloaded

        wav_path = os.path.join(tmp_dir, "audio_converted.wav")
        subprocess.run([
            "ffmpeg", "-y", "-i", downloaded,
            "-vn", "-ar", "16000", "-ac", "1",
            "-acodec", "pcm_s16le", wav_path
        ], check=True, capture_output=True)
        return wav_path
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise


def get_duration(path):
    try:
        result = subprocess.run([
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", path
        ], capture_output=True, text=True)
        info = json.loads(result.stdout)
        return float(info["format"]["duration"])
    except Exception:
        return 0


def split_audio(wav_path):
    duration = get_duration(wav_path)
    if duration <= CHUNK_SECONDS:
        return [wav_path]
    chunks = []
    n_chunks = math.ceil(duration / CHUNK_SECONDS)
    for i in range(n_chunks):
        chunk_path = wav_path + f"_part{i}.wav"
        start = i * CHUNK_SECONDS
        subprocess.run([
            "ffmpeg", "-y", "-i", wav_path,
            "-ss", str(start), "-t", str(CHUNK_SECONDS),
            "-ar", "16000", "-ac", "1",
            "-acodec", "pcm_s16le", chunk_path
        ], check=True, capture_output=True)
        chunks.append(chunk_path)
    return chunks


def transcribe_chunk(path):
    # Bo'lak 50 sek audio — Muxlisa odatda 5-15 sekundda javob beradi.
    # 90 sek timeout: agar shuncha vaqtda javob bo'lmasa, server osilgan, keyingisiga o'tamiz.
    with open(path, "rb") as f:
        response = requests.post(
            MUXLISA_URL,
            headers={"x-api-key": MUXLISA_KEY},
            files=[("audio", ("audio.wav", f, "audio/wav"))],
            data={},
            timeout=90,
        )
    if response.status_code == 200:
        return response.json().get("text", "").strip()
    raise Exception(f"Muxlisa xatosi: {response.status_code} - {response.text[:200]}")


FATAL_KEYWORDS = ("balance", "insufficient", "credit", "payment", "quota",
                  "limit reach", "unauthorized", "forbidden", "401", "402", "403")


def _is_fatal_error(err_str):
    s = err_str.lower()
    return any(k in s for k in FATAL_KEYWORDS)


def transcribe(file_path, progress_cb=None):
    """progress_cb(stage, current, total) — sync callback. stage: 'convert','split','chunk'."""
    if progress_cb:
        try: progress_cb('convert', 0, 0)
        except Exception: pass
    wav_path = convert_to_wav(file_path)

    if progress_cb:
        try: progress_cb('split', 0, 0)
        except Exception: pass
    chunks = split_audio(wav_path)
    total = len(chunks)
    results = []
    error_count = 0
    consecutive_errors = 0
    fatal_msg = None
    last_processed = 0
    try:
        for i, chunk in enumerate(chunks):
            last_processed = i
            if progress_cb:
                try: progress_cb('chunk', i + 1, total)
                except Exception: pass
            try:
                text = transcribe_chunk(chunk)
                if text:
                    results.append(text)
                consecutive_errors = 0
            except Exception as e:
                logging.error(f"Bo'lak {i+1} xatosi: {e}")
                error_count += 1
                consecutive_errors += 1
                err_str = str(e)
                if _is_fatal_error(err_str):
                    fatal_msg = (
                        "Muxlisa hisobingizdagi balans tugagan yoki API kalit muammoli. "
                        "Iltimos service.muxlisa.uz hisobingizni to'ldirib qayta urinib ko'ring."
                    )
                    break
                if consecutive_errors >= 3:
                    fatal_msg = "Ketma-ket 3 ta bo'lak xato qaytardi — to'xtatildi."
                    break
            finally:
                if chunk != wav_path and os.path.exists(chunk):
                    os.remove(chunk)
        # Agar erta to'xtagan bo'lsak, qolgan vaqtinchalik bo'laklarni tozalash
        if fatal_msg:
            for j in range(last_processed + 1, total):
                rest = chunks[j]
                if rest != wav_path and os.path.exists(rest):
                    try: os.remove(rest)
                    except Exception: pass
    finally:
        if wav_path != file_path and os.path.exists(wav_path):
            os.remove(wav_path)

    text_part = " ".join(results) if results else ""
    if fatal_msg:
        if text_part:
            return f"{text_part}\n\n⚠️ {fatal_msg}\n(Matn {last_processed + 1 - error_count}/{total} bo'lakdan olindi.)"
        return f"⚠️ {fatal_msg}"
    if not text_part:
        return "Matn aniqlanmadi."
    if error_count:
        return f"{text_part}\n\nℹ️ {error_count}/{total} bo'lak xato bo'ldi."
    return text_part


FONT_CANDIDATES = [
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
    r"/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    r"/Library/Fonts/Arial.ttf",
]


def _find_font():
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def make_pdf(text, title="SesTon — Matn"):
    """Matnni PDF qiladi va vaqtinchalik fayl yo'lini qaytaradi."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_title(title)
    font_path = _find_font()
    if font_path:
        pdf.add_font("Body", "", font_path)
        pdf.set_font("Body", size=14)
        pdf.cell(0, 12, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
        pdf.ln(4)
        pdf.set_font("Body", size=11)
    else:
        pdf.set_font("Helvetica", size=14)
        pdf.cell(0, 12, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
        pdf.ln(4)
        pdf.set_font("Helvetica", size=11)
    # multi_cell uzun matnni avtomatik o'rab beradi
    pdf.multi_cell(0, 7, text)
    out_path = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False).name
    pdf.output(out_path)
    return out_path


def save_base64_audio(data, suffix='.webm'):
    if data.startswith('data:'):
        data = data.split(',', 1)[1]
    try:
        decoded = base64.b64decode(data)
    except Exception as e:
        raise Exception(f"Base64 audio o'qib bo'lmadi: {e}")
    if not suffix.startswith('.'):
        suffix = '.' + suffix
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(decoded)
        return tmp.name


# ── BOT HELPERS ─────────────────────────────────────────────────────────────

async def send_result(update, msg, text):
    if not text:
        await msg.edit_text("Matn aniqlanmadi.")
        return
    # Matnni xabarda yuborish
    if len(text) <= 4000:
        await msg.edit_text(f"📝 Matn:\n\n{text}")
    else:
        await msg.edit_text("✅ Tayyor! Qismlarga bo'lib yuborilmoqda...")
        parts = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for i, part in enumerate(parts):
            await update.message.reply_text(f"📄 Qism {i+1}/{len(parts)}:\n\n{part}")
    # PDF qilib yuborish (bonus — saqlash qulay)
    pdf_path = None
    try:
        pdf_path = await asyncio.to_thread(make_pdf, text)
        with open(pdf_path, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename="seston-matn.pdf",
                caption="📎 Matn PDF formatda"
            )
    except Exception as e:
        logging.error(f"PDF yaratish xatosi: {e}")
    finally:
        if pdf_path and os.path.exists(pdf_path):
            try: os.remove(pdf_path)
            except Exception: pass


def make_progress_cb(loop, msg, base_label="🎙 Tanilmoqda"):
    """Sync callback yaratadi — Telegram xabarini async edit qiladi (rate-limited)."""
    state = {"last": 0.0}
    def cb(stage, current, total):
        now = time.time()
        if now - state["last"] < 4 and stage == "chunk":
            return  # juda tez bosqichlarni o'tkazib yuborish (Telegram rate limit)
        state["last"] = now
        if stage == "convert":
            text = f"{base_label}...\n🔄 Audio konvertatsiya qilinmoqda..."
        elif stage == "split":
            text = f"{base_label}...\n✂️ Bo'laklarga bo'linmoqda..."
        elif stage == "chunk":
            if total > 1:
                text = f"{base_label}...\n📊 {current}/{total} bo'lak qayta ishlanmoqda..."
            else:
                text = f"{base_label}...\n🎙 Tanilmoqda..."
        else:
            return
        try:
            asyncio.run_coroutine_threadsafe(msg.edit_text(text), loop)
        except Exception:
            pass
    return cb


async def process_local_audio(update, context, file_path, duration=0):
    est = f"{duration // 60} daqiqa {duration % 60} soniya" if duration else "noma'lum"
    msg = await update.message.reply_text(
        f"🎙 Tanilmoqda...\n⏱ Davomiyligi: {est}\n\nBiroz sabr qiling..."
    )
    try:
        loop = asyncio.get_running_loop()
        cb = make_progress_cb(loop, msg)
        text = await asyncio.to_thread(transcribe, file_path, cb)
        await send_result(update, msg, text)
    except Exception as e:
        logging.error(f"Xato: {e}")
        await msg.edit_text(f"❌ Xato: {str(e)[:300]}")


async def process_file(update, context, file_id, suffix, duration=0):
    est = f"{duration // 60} daqiqa {duration % 60} soniya" if duration else "noma'lum"
    msg = await update.message.reply_text(
        f"🎙 Tanilmoqda...\n⏱ Davomiyligi: {est}\n\nBiroz sabr qiling..."
    )
    tmp_path = None
    try:
        file = await context.bot.get_file(file_id)
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp_path = tmp.name
        await file.download_to_drive(tmp_path)

        loop = asyncio.get_running_loop()
        cb = make_progress_cb(loop, msg)
        text = await asyncio.to_thread(transcribe, tmp_path, cb)
        await send_result(update, msg, text)
    except Exception as e:
        logging.error(f"Xato: {e}")
        await msg.edit_text(f"❌ Xato: {str(e)[:300]}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try: os.remove(tmp_path)
            except Exception: pass


async def process_url(update, context, url):
    msg = await update.message.reply_text(
        f"📥 Video yuklanmoqda...\n🔗 {url[:50]}\n\nBiroz sabr qiling..."
    )
    audio_path = None
    try:
        audio_path = await asyncio.to_thread(download_audio_from_url, url)
        await msg.edit_text("✅ Yuklanidi! 🎙 Matn tanilmoqda...")

        loop = asyncio.get_running_loop()
        cb = make_progress_cb(loop, msg)
        text = await asyncio.to_thread(transcribe, audio_path, cb)
        await send_result(update, msg, text)
    except Exception as e:
        logging.error(f"URL xato: {e}")
        await msg.edit_text(f"❌ Xato: {str(e)[:300]}")
    finally:
        if audio_path:
            shutil.rmtree(os.path.dirname(audio_path), ignore_errors=True)


def webapp_keyboard(chat_id=None):
    # Cache buster + chat_id (iMe va boshqa Telegram fork'lari uchun fallback)
    sep = "&" if "?" in WEBAPP_URL else "?"
    parts = [f"v={int(time.time())}"]
    if chat_id is not None:
        parts.append(f"user={chat_id}")
    url = f"{WEBAPP_URL}{sep}{'&'.join(parts)}"
    return ReplyKeyboardMarkup(
        [[KeyboardButton(text="🎙 Web ilovani ochish", web_app=WebAppInfo(url=url))]],
        resize_keyboard=True,
    )


# ── BOT HANDLERS ────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Assalomu alaykum, *{}*!\n\n"
        "🎧 Men audio, video va hatto krugli videolarni matnga aylantirib beradigan aqlli bot.\n\n"
        "📌 *Nima yuborsa bo'ladi:*\n"
        "• 🎤 Ovozli xabar\n"
        "• 🎵 Audio fayl (MP3, WAV, OGG...)\n"
        "• 🎬 Video fayl (MP4, MKV...)\n"
        "• 💬 Dumaloq video xabar\n"
        "• 🔗 YouTube / TikTok / Instagram havolasi\n\n"
        "Yoki quyidagi tugma orqali *Web ilovani* oching 👇".format(
            update.effective_user.first_name
        ),
        parse_mode="Markdown",
        reply_markup=webapp_keyboard(chat_id=update.effective_user.id),
    )


async def handle_web_app_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Web App dan json ma'lumot kelganda ishlaydi (faqat KeyboardButton orqali)."""
    try:
        data = json.loads(update.message.web_app_data.data)
        file_type = data.get("type", "")
        url = data.get("url", "")

        if file_type == "url" and url:
            url = extract_url(url) or url
            await process_url(update, context, url)
            return

        if file_type == "webapp_voice" and data.get("audio"):
            await update.message.reply_text("🎙 Web ilovadan audio qabul qilindi. Matniga aylantirilmoqda...")
            audio_data = data["audio"]
            fmt = data.get("format", "")
            if not fmt and isinstance(audio_data, str) and audio_data.startswith('data:'):
                fmt = audio_data.split(';', 1)[0].split(':', 1)[1]
            ext = fmt.split("/")[-1] if "/" in fmt else fmt or "webm"
            ext = ext.split(";")[0]
            if not ext.startswith('.'):
                ext = '.' + ext
            tmp_path = save_base64_audio(audio_data, ext)
            try:
                await process_local_audio(update, context, tmp_path, data.get("duration", 0))
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            return

        await update.message.reply_text("⚠️ Web App ma'lumoti tan olinmadi.")
    except Exception as e:
        logging.error(f"WebApp data xatosi: {e}")
        await update.message.reply_text("❌ Web App dan ma'lumot xato keldi.")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = update.message.voice
    if not v:
        await update.message.reply_text("⚠️ Ovozli xabaringiz topilmadi. Iltimos qayta yuboring.")
        return
    await process_file(update, context, v.file_id, ".ogg", v.duration or 0)


async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    a = update.message.audio
    ext = os.path.splitext(a.file_name or "audio.mp3")[1] or ".mp3"
    await process_file(update, context, a.file_id, ext, a.duration or 0)


async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = update.message.video
    ext = os.path.splitext(v.file_name or "video.mp4")[1] or ".mp4"
    await process_file(update, context, v.file_id, ext, v.duration or 0)


async def handle_video_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = update.message.video_note
    await process_file(update, context, v.file_id, ".mp4", v.duration or 0)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    mime = doc.mime_type or ""
    name = doc.file_name or ""
    ext = os.path.splitext(name)[1].lower()
    audio_exts = [".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".wma", ".opus"]
    video_exts = [".mp4", ".avi", ".mov", ".mkv", ".webm", ".3gp"]
    if any(e in mime for e in ["audio", "video"]) or ext in audio_exts + video_exts:
        await process_file(update, context, doc.file_id, ext or ".mp3", 0)
    else:
        await update.message.reply_text("⚠️ Bu fayl turi qo'llab-quvvatlanmaydi.")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    url = extract_url(text)
    if url:
        await process_url(update, context, url)
    else:
        await update.message.reply_text(
            "📌 Iltimos quyidagilardan birini yuboring:\n\n"
            "• 🎤 Ovozli xabar\n"
            "• 🎵 Audio fayl\n"
            "• 🎬 Video fayl\n"
            "• 💬 Dumaloq video\n"
            "• 🔗 YouTube/TikTok/Instagram havolasi\n\n"
            "Yoki Web ilovani oching 👇",
            reply_markup=webapp_keyboard(chat_id=update.effective_user.id),
        )


# ── HTTP API (WebApp uchun) ─────────────────────────────────────────────────

def telegram_send_message(chat_id, text):
    """Telegram API ga to'g'ridan to'g'ri HTTP — alohida loop'dan xavfsiz."""
    if not text:
        return
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        for i in range(0, len(text), 4000):
            chunk = text[i:i+4000]
            requests.post(url, data={"chat_id": chat_id, "text": chunk}, timeout=60)
    except Exception as e:
        logging.error(f"Telegram send error: {e}")


def telegram_send_document(chat_id, file_path, filename=None, caption=None):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
        with open(file_path, 'rb') as f:
            files = {"document": (filename or os.path.basename(file_path), f, "application/pdf")}
            data = {"chat_id": chat_id}
            if caption:
                data["caption"] = caption
            requests.post(url, data=data, files=files, timeout=120)
    except Exception as e:
        logging.error(f"Telegram document send error: {e}")


def _send_text_and_pdf(user_id, text):
    """Matn + PDF yuborish (HTTP fallback yo'lida)."""
    telegram_send_message(user_id, f"📝 Matn:\n\n{text}")
    try:
        pdf_path = make_pdf(text)
        try:
            telegram_send_document(user_id, pdf_path, filename="seston-matn.pdf", caption="📎 Matn PDF formatda")
        finally:
            if os.path.exists(pdf_path):
                try: os.remove(pdf_path)
                except Exception: pass
    except Exception as e:
        logging.error(f"PDF (HTTP) xato: {e}")


def process_audio_for_user(user_id, file_path):
    try:
        telegram_send_message(user_id, "🎙 Web ilova yuborgan fayl tanilmoqda...")
        text = transcribe(file_path)
        if text and text.strip() != "Matn aniqlanmadi.":
            _send_text_and_pdf(user_id, text)
        else:
            telegram_send_message(user_id, "Matn aniqlanmadi.")
    except Exception as e:
        logging.error(f"process_audio_for_user xato: {e}")
        telegram_send_message(user_id, f"❌ Xato: {str(e)[:300]}")
    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass


def process_url_for_user(user_id, url):
    audio_path = None
    try:
        telegram_send_message(user_id, f"📥 Video yuklanmoqda...\n🔗 {url[:80]}")
        audio_path = download_audio_from_url(url)
        telegram_send_message(user_id, "✅ Yuklanidi! 🎙 Matn tanilmoqda...")
        text = transcribe(audio_path)
        if text and text.strip() != "Matn aniqlanmadi.":
            _send_text_and_pdf(user_id, text)
        else:
            telegram_send_message(user_id, "Matn aniqlanmadi.")
    except Exception as e:
        logging.error(f"process_url_for_user xato: {e}")
        telegram_send_message(user_id, f"❌ Xato: {str(e)[:300]}")
    finally:
        if audio_path:
            shutil.rmtree(os.path.dirname(audio_path), ignore_errors=True)


async def handle_webapp_audio(request):
    """WebApp mikrofon yozuvi (base64)."""
    try:
        data = await request.json()
        user_id = data.get("user_id")
        audio_data = data.get("audio", "")
        format_hint = data.get("format", "audio/webm")
        if not user_id or not audio_data:
            return web.json_response({"error": "user_id yoki audio yo'q"}, status=400, headers=cors_headers())
        ext = format_hint.split("/")[-1].split(";")[0] if "/" in format_hint else format_hint
        if not ext.startswith('.'):
            ext = '.' + ext
        tmp_path = save_base64_audio(audio_data, ext)
        threading.Thread(target=process_audio_for_user, args=(int(user_id), tmp_path), daemon=True).start()
        return web.json_response({"status": "ok"}, headers=cors_headers())
    except Exception as e:
        logging.error(f"HTTP audio xatosi: {e}")
        return web.json_response({"error": str(e)}, status=500, headers=cors_headers())


async def handle_webapp_upload(request):
    """WebApp dan fayl yuklash (multipart) — audio/video."""
    try:
        reader = await request.multipart()
        user_id = None
        file_data = None
        file_name = None
        while True:
            part = await reader.next()
            if part is None:
                break
            if part.name == "user_id":
                user_id = (await part.text()).strip()
            elif part.name == "file":
                file_name = part.filename or "upload.bin"
                file_data = await part.read()
        if not user_id or not file_data:
            return web.json_response({"error": "user_id yoki fayl yo'q"}, status=400, headers=cors_headers())
        ext = os.path.splitext(file_name)[1] or ".bin"
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(file_data)
            tmp_path = tmp.name
        threading.Thread(target=process_audio_for_user, args=(int(user_id), tmp_path), daemon=True).start()
        return web.json_response({"status": "ok"}, headers=cors_headers())
    except Exception as e:
        logging.error(f"HTTP upload xatosi: {e}")
        return web.json_response({"error": str(e)}, status=500, headers=cors_headers())


async def handle_webapp_url_post(request):
    """WebApp dan URL yuborish (YouTube/Instagram/TikTok)."""
    try:
        data = await request.json()
        user_id = data.get("user_id")
        url = (data.get("url") or "").strip()
        url = extract_url(url) or url
        if not user_id or not url:
            return web.json_response({"error": "user_id yoki url yo'q"}, status=400, headers=cors_headers())
        threading.Thread(target=process_url_for_user, args=(int(user_id), url), daemon=True).start()
        return web.json_response({"status": "ok"}, headers=cors_headers())
    except Exception as e:
        logging.error(f"HTTP URL xatosi: {e}")
        return web.json_response({"error": str(e)}, status=500, headers=cors_headers())


async def handle_options(request):
    return web.Response(status=204, headers=cors_headers())


async def serve_index(request):
    if not os.path.exists(INDEX_HTML):
        return web.Response(text="index.html topilmadi", status=404)
    return web.FileResponse(INDEX_HTML, headers={"Cache-Control": "no-store"})


async def run_http_server():
    web_app = web.Application(client_max_size=200 * 1024 * 1024)  # 200 MB
    web_app.router.add_get('/', serve_index)
    web_app.router.add_get('/index.html', serve_index)
    web_app.router.add_post('/audio', handle_webapp_audio)
    web_app.router.add_post('/upload', handle_webapp_upload)
    web_app.router.add_post('/url', handle_webapp_url_post)
    web_app.router.add_route('OPTIONS', '/{tail:.*}', handle_options)

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', HTTP_PORT)
    await site.start()
    print(f"HTTP server started on port {HTTP_PORT}")
    await asyncio.Event().wait()


def run_http_server_thread():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_http_server())


def main():
    global bot_app

    # Tashqi dasturlarni tekshirish
    missing = []
    if not have_cmd("ffmpeg"):
        missing.append("ffmpeg")
    if not have_cmd("yt-dlp"):
        missing.append("yt-dlp")
    if missing:
        print(f"⚠️  OGOHLANTIRISH: quyidagi dasturlar PATH'da topilmadi: {', '.join(missing)}")
        print("   ffmpeg: https://www.gyan.dev/ffmpeg/builds/ (winget: Gyan.FFmpeg)")
        print("   yt-dlp: pip install -U yt-dlp")

    app = Application.builder().token(BOT_TOKEN).build()
    bot_app = app
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_web_app_data))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.AUDIO, handle_audio))
    app.add_handler(MessageHandler(filters.VIDEO, handle_video))
    app.add_handler(MessageHandler(filters.VIDEO_NOTE, handle_video_note))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    http_thread = threading.Thread(target=run_http_server_thread, daemon=True)
    http_thread.start()

    print(f"✅ SesTon bot ishga tushdi... (HTTP: {HTTP_PORT}, WebApp: {WEBAPP_URL})")
    app.run_polling()


if __name__ == "__main__":
    main()
