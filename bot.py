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
import shutil
import requests
import re
import asyncio
import threading
from telegram import (
    Update, KeyboardButton, ReplyKeyboardMarkup, WebAppInfo, BotCommand,
    MenuButtonWebApp, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice,
)
from fpdf import FPDF
from fpdf.enums import XPos, YPos
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    PreCheckoutQueryHandler, filters, ContextTypes,
)
from aiohttp import web
import edge_tts
import speech_recognition as sr
import pypdf

# TTS voices
VOICES = {
    "uz": "uz-UZ-MadinaNeural",
    "ru": "ru-RU-SvetlanaNeural",
    "en": "en-US-JennyNeural",
}

# STT lang codes (Google Speech uchun)
GOOGLE_LANG = {
    "ru": "ru-RU",
    "uz": "uz-UZ",
    "en": "en-US",
}

_sr_recognizer = sr.Recognizer()

BOT_TOKEN   = os.getenv("BOT_TOKEN", "8502384684:AAETKbx4YBtiQ9W7PRTWUeVumwwnG-lH9R8")
MUXLISA_KEY = os.getenv("MUXLISA_KEY", "UYaezERZPBO7pkJj4wzttq5eV90cGdFrI8XxGyCl")

# To'lov ma'lumotlari (Railway env variable orqali kiritiladi — kodga qo'yilmaydi!)
PAYMENT_CARD = os.getenv("PAYMENT_CARD", "")
PAYMENT_CARD_HOLDER = os.getenv("PAYMENT_CARD_HOLDER", "")
ADMIN_CONTACT = os.getenv("ADMIN_CONTACT", "@Nazokat_571")
# Markdown V1 uchun xavfsiz versiya (pastki chiziqni qochirish — italic talqin qilinmasligi uchun)
ADMIN_CONTACT_MD = ADMIN_CONTACT.replace("_", "\\_")

# Foydalanuvchilarga ko'rsatiladigan neutral nom (admin username yashiriladi)
SUPPORT_NAME = os.getenv("SUPPORT_NAME", "Audio Bot Yordam markazi")

# Admin Telegram user ID — agar sozlangan bo'lsa, bot startup'da ADMIN_CHAT_ID ga yoziladi.
# Bu admin /start yubormay turib ham chek xabarlarini olish imkonini beradi.
try:
    _admin_id_env = os.getenv("ADMIN_USER_ID", "").strip()
    ADMIN_USER_ID = int(_admin_id_env) if _admin_id_env else None
except ValueError:
    ADMIN_USER_ID = None

# Telegram Payments — BotFather'dan olingan provider token (Click/Stripe/etc.)
# BotFather → /mybots → bot tanlang → Payments → provayder ulang → token nusxalang
# Railway'da PAYMENT_PROVIDER_TOKEN env qo'shing
PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN", "")
# Telegram Payments valyutasi (UZS yoki test uchun USD)
PAYMENT_CURRENCY = os.getenv("PAYMENT_CURRENCY", "UZS")

# === [TARJIMA MODULI — YANGI] ====================================================
# Whisper (OpenAI) + GPT-4o (Anthropic) orqali xorijiy tildan tarjima
# Railway'da quyidagi env'larni qo'shing:
#   OPENAI_API_KEY=sk-...
#   ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Tarjima narxi koeffitsienti — sarflangan vaqt 2x sanaydi (STT + tarjima)
TRANSLATION_MULTIPLIER = 2

# Tarjima qilinadigan manba tillar
TRANSLATION_LANGS = {
    "ru": "🇷🇺 Rus tilidan",
    "en": "🇬🇧 Ingliz tilidan",
    "ar": "🇸🇦 Arab tilidan",
}
TRANSLATION_LANG_NAMES = {"ru": "rus", "en": "ingliz", "ar": "arab"}
# === [/TARJIMA MODULI] ==========================================================

# Web App URL — ngrok yoki o'z serveringiz URL'ini kiriting
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://botch-engaging-mustang.ngrok-free.dev")
# Railway/Heroku PORT env, lokal sinov uchun HTTP_PORT yoki default 8000
HTTP_PORT  = int(os.getenv("HTTP_PORT") or os.getenv("PORT") or 8000)

MUXLISA_URL   = "https://service.muxlisa.uz/api/v2/stt"
# Muxlisa cheklovi: 60 sek. CHUNK_SECONDS = 50 sek (xavfsizlik bufer).
# OVERLAP_SECONDS = 2 sek — bo'lak chegarasidagi so'zlar kesilmasligi uchun
# har bir bo'lak oldingisining oxirgi 2 sek bilan ustma-ust tushadi.
CHUNK_SECONDS = 50
OVERLAP_SECONDS = 2

HERE       = os.path.dirname(os.path.abspath(__file__))
INDEX_HTML = os.path.join(HERE, "index.html")

bot_app = None

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

# ── ADMIN & TARIFLAR KONFIGURATSIYASI ──────────────────────────────────────
# Admin Telegram username (kichik harf, @ siz)
ADMIN_USERNAMES = {"nazokat_571"}

# Tariflar (O'zbek STT uchun)
TARIFFS = {
    "free":     {"name": "🌸 Bepul",    "minutes": 5,   "price": 0},
    "standart": {"name": "🌿 Standart", "minutes": 180, "price": 170000},  # 3 soat
    "premium":  {"name": "🌺 Premium",  "minutes": 360, "price": 300000},  # 6 soat
    "pro":      {"name": "💎 Pro",      "minutes": 600, "price": 500000},  # 10 soat
}

# Foydalanuvchi xarajatlarini saqlash {user_id: jami_soniya}
user_uzbek_usage = {}
# Foydalanuvchi tarifi {user_id: tariff_kalit}, default = "free"
user_tariffs = {}
# "Men to'ladim" tugmasini bosgan foydalanuvchilar — keyingi rasmni chek deb qabul qilamiz
# {user_id: tariff_key}. Deploy'larda yo'qolmasligi uchun JSON'ga saqlanadi.
pending_payments = {}
# === [TARJIMA STATE] Foydalanuvchi tilini tanlagach audio kutamiz ===
# {user_id: source_lang} — JSON'ga saqlanadi (deploy'larda yo'qolmaydi)
pending_translations = {}
# Admin tomonidan /setcard va /setholder orqali sozlanadigan karta ma'lumotlari
# Env variable yo'q bo'lsa yoki adminb buyruq bilan yangilangan bo'lsa shu ishlatiladi.
runtime_settings = {"payment_card": "", "payment_card_holder": ""}
# Admin /test buyrug'i bilan yoqadigan rejim — Muxlisa chaqirilmaydi
TEST_MODE = {"on": False}
# Muxlisa tarifi (so'm/daqiqa) — statistika uchun
MUXLISA_PRICE_PER_MIN = 500
# Admin chat_id (avtomatik saqlanadi admin botga xabar yuborganda) — to'lov xabarnomasi uchun
ADMIN_CHAT_ID = {"id": None}

# ── PERSISTENCE: usage va tarif ma'lumotlarini JSON faylga saqlash ──────────
# Railway'da volume bo'lsa /data ga, aks holda working dir'ga yoziladi.
# Bot qayta yoqilganda limitlar yo'qolib ketmasligi uchun.
DATA_FILE = os.getenv("DATA_FILE", os.path.join(HERE, "user_data.json"))
_save_lock = threading.Lock()


def _load_user_data():
    """Bot ishga tushganda saqlangan usage, tariflar va admin_chat_id'ni yuklaydi."""
    if not os.path.exists(DATA_FILE):
        return
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        for k, v in (data.get("usage") or {}).items():
            try:
                user_uzbek_usage[int(k)] = int(v)
            except (ValueError, TypeError):
                pass
        for k, v in (data.get("tariffs") or {}).items():
            try:
                if v in TARIFFS:
                    user_tariffs[int(k)] = v
            except (ValueError, TypeError):
                pass
        # Admin chat_id — bir marta admin /start yuborgach saqlanib qoladi
        saved_admin = data.get("admin_chat_id")
        if saved_admin:
            try:
                ADMIN_CHAT_ID["id"] = int(saved_admin)
            except (ValueError, TypeError):
                pass
        # Pending payments — deploy'da yo'qolmasligi uchun
        for k, v in (data.get("pending_payments") or {}).items():
            try:
                if v in TARIFFS:
                    pending_payments[int(k)] = v
            except (ValueError, TypeError):
                pass
        # === [TARJIMA] pending translations — til tanlash holatini saqlash ===
        for k, v in (data.get("pending_translations") or {}).items():
            try:
                if v in TRANSLATION_LANGS:
                    pending_translations[int(k)] = v
            except (ValueError, TypeError):
                pass
        # Runtime settings (karta raqami va boshqalar) — admin /setcard orqali yangilaydi
        rs = data.get("runtime_settings") or {}
        if isinstance(rs, dict):
            for k in ("payment_card", "payment_card_holder"):
                if k in rs and isinstance(rs[k], str):
                    runtime_settings[k] = rs[k]
        logging.info(f"📂 user_data.json yuklandi: {len(user_uzbek_usage)} usage, {len(user_tariffs)} tarif, {len(pending_payments)} pending, admin_chat_id={ADMIN_CHAT_ID['id']}, card_set={bool(runtime_settings['payment_card'])}")
    except Exception as e:
        logging.warning(f"user_data.json o'qishda xato: {e}")


def _save_user_data():
    """user_uzbek_usage, user_tariffs va admin_chat_id ni faylga yozadi (atomik)."""
    with _save_lock:
        try:
            data = {
                "usage": {str(k): int(v) for k, v in user_uzbek_usage.items()},
                "tariffs": {str(k): v for k, v in user_tariffs.items()},
                "admin_chat_id": ADMIN_CHAT_ID["id"],
                "pending_payments": {str(k): v for k, v in pending_payments.items()},
                # === [TARJIMA] pending translations ham saqlanadi ===
                "pending_translations": {str(k): v for k, v in pending_translations.items()},
                "runtime_settings": dict(runtime_settings),
            }
            tmp_path = DATA_FILE + ".tmp"
            os.makedirs(os.path.dirname(DATA_FILE) or ".", exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp_path, DATA_FILE)
            logging.info(f"💾 user_data.json saqlandi: {len(user_uzbek_usage)} usage, {len(user_tariffs)} tarif → {DATA_FILE}")
        except Exception as e:
            logging.error(f"❌ user_data.json yozishda xato: {e} | DATA_FILE={DATA_FILE}")


def is_admin(update):
    """Foydalanuvchi adminmi tekshiradi (username asosida)."""
    if not update or not getattr(update, "effective_user", None):
        return False
    uname = (update.effective_user.username or "").lower()
    if uname in ADMIN_USERNAMES:
        # Admin chat_id'ini eslab qolamiz — to'lov xabarnomalari uchun
        new_id = update.effective_user.id
        if ADMIN_CHAT_ID["id"] != new_id:
            ADMIN_CHAT_ID["id"] = new_id
            _save_user_data()  # Doimiy saqlash — deploy'lardan o'tib ham qolsin
            logging.info(f"👑 ADMIN_CHAT_ID saqlandi: {new_id}")
        return True
    return False


def get_user_tariff(user_id):
    return user_tariffs.get(user_id, "free")


def get_user_limit_sec(user_id):
    tariff = get_user_tariff(user_id)
    return TARIFFS[tariff]["minutes"] * 60


def get_user_usage_sec(user_id):
    return user_uzbek_usage.get(user_id, 0)


def add_user_usage(user_id, seconds):
    logging.info(f"➕ add_user_usage(user_id={user_id}, seconds={seconds}, joriy={user_uzbek_usage.get(user_id, 0)})")
    if seconds and seconds > 0:
        user_uzbek_usage[user_id] = user_uzbek_usage.get(user_id, 0) + seconds
        logging.info(f"   ✅ Yangi total: {user_uzbek_usage[user_id]} sek")
        _save_user_data()
    else:
        logging.warning(f"   ⚠️ seconds={seconds} musbat emas, daqiqa qo'shilmadi")


def format_tariffs_text():
    lines = ["💎 *Tariflar*\n"]
    lines.append("Tarif daqiqalari barcha xizmatlarga sarflanadi:")
    lines.append("• 🎤 Audio/video → matn (har qanday tilda)")
    lines.append("• 📄 PDF → Audio (TTS)")
    lines.append("• 📝 Matn → Ovoz (TTS)")
    lines.append("")
    for _, t in TARIFFS.items():
        mins = t["minutes"]
        hrs_str = f" ({mins // 60} soat)" if mins >= 60 else ""
        if t["price"] == 0:
            lines.append(f"{t['name']} — *{mins} daqiqa/oy* — BEPUL")
        else:
            lines.append(f"{t['name']} — *{mins} daqiqa{hrs_str}* — *{t['price']:,} so'm*")
    lines.append("\n💎 Tarif sotib olish uchun pastdagi tugmani bosing 👇")
    return "\n".join(lines)


async def can_process_uzbek(update, duration_seconds=0):
    """O'zbek STT limitini tekshiradi. Adminda har doim True."""
    if is_admin(update):
        return True
    user_id = update.effective_user.id
    used = get_user_usage_sec(user_id)
    limit = get_user_limit_sec(user_id)
    tariff = TARIFFS[get_user_tariff(user_id)]
    if used >= limit:
        await update.message.reply_text(
            f"⚠️ *Limit tugadi!*\n\n"
            f"🌸 Tarifingiz: {tariff['name']}\n"
            f"📊 Ishlatilgan: {used/60:.1f} / {tariff['minutes']} daqiqa\n\n"
            f"💎 Tarif sotib olish: /tariflar",
            parse_mode="Markdown"
        )
        return False
    if duration_seconds > 0 and used + duration_seconds > limit:
        rem = max(0, limit - used) / 60
        await update.message.reply_text(
            f"⚠️ *Bu audio limitga sig'maydi!*\n\n"
            f"🌸 Tarifingiz: {tariff['name']}\n"
            f"📊 Ishlatilgan: {used/60:.1f} / {tariff['minutes']} daqiqa\n"
            f"⏳ Bu audio: {duration_seconds/60:.1f} daqiqa\n"
            f"📉 Qoldiq: {rem:.1f} daqiqa\n\n"
            f"💎 Yuqori tarif: /tariflar",
            parse_mode="Markdown"
        )
        return False
    return True

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


def _prepare_cookies_file():
    """YOUTUBE_COOKIES env'dan cookies.txt yaratadi (agar bo'lsa)."""
    cookies_text = os.getenv("YOUTUBE_COOKIES", "").strip()
    if not cookies_text:
        return None
    cookies_path = os.path.join(tempfile.gettempdir(), "yt_cookies.txt")
    try:
        with open(cookies_path, "w", encoding="utf-8") as f:
            f.write(cookies_text)
        return cookies_path
    except Exception as e:
        logging.warning(f"Cookies fayl yaratishda xato: {e}")
        return None


def _run_yt_dlp(url, output_template, use_cookies=True, player_client=None):
    """yt-dlp ni har xil parametrlar bilan chaqiradi. Returnlar (returncode, stderr)."""
    cmd = [
        "yt-dlp", "-x",
        "--audio-format", "wav",
        "--no-playlist",
        "--no-warnings",
        "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    ]
    if use_cookies:
        cookies_path = _prepare_cookies_file()
        if cookies_path:
            cmd.extend(["--cookies", cookies_path])
    if player_client:
        cmd.extend(["--extractor-args", f"youtube:player_client={player_client}"])
    cmd.extend(["-o", output_template, url])
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result


def download_audio_from_url(url):
    if not have_cmd("yt-dlp"):
        raise Exception("yt-dlp o'rnatilmagan. Terminalda: pip install -U yt-dlp")
    if not have_cmd("ffmpeg"):
        raise Exception("ffmpeg topilmadi. yt-dlp ga audio konvertatsiya kerak.")

    tmp_dir = tempfile.mkdtemp()
    output_template = os.path.join(tmp_dir, "audio.%(ext)s")
    is_youtube = bool(re.search(r"(youtube\.com|youtu\.be)", url, re.I))
    try:
        # YouTube uchun bir nechta strategiya — birortasi ishlasa bas
        # 1) cookies bilan (eng ishonchli — agar YOUTUBE_COOKIES env bor bo'lsa)
        # 2) android player_client (ba'zan bot detection'ni chetlab o'tadi)
        # 3) web_safari player_client
        # 4) cookies'siz oddiy (default)
        attempts = []
        if is_youtube:
            attempts = [
                {"use_cookies": True,  "player_client": None},
                {"use_cookies": True,  "player_client": "android"},
                {"use_cookies": False, "player_client": "android,web"},
                {"use_cookies": False, "player_client": "web_safari"},
                {"use_cookies": False, "player_client": None},
            ]
        else:
            attempts = [
                {"use_cookies": True,  "player_client": None},
                {"use_cookies": False, "player_client": None},
            ]

        result = None
        last_stderr = ""
        for i, attempt in enumerate(attempts):
            logging.info(f"yt-dlp urinish #{i+1}: cookies={attempt['use_cookies']}, player={attempt['player_client']}")
            result = _run_yt_dlp(url, output_template, **attempt)
            if result.returncode == 0:
                logging.info(f"✅ yt-dlp urinish #{i+1} muvaffaqiyatli")
                break
            last_stderr = (result.stderr or "").strip()
            # Bo'sh bot detection xatosi bo'lsa keyingi urinish; boshqa xato bo'lsa to'xtatamiz
            low = last_stderr.lower()
            if not ("sign in" in low or "not a bot" in low or "confirm" in low or
                    "http error 403" in low or "forbidden" in low):
                break

        if result.returncode != 0:
            stderr = last_stderr
            low = stderr.lower()
            if "sign in" in low or "not a bot" in low or "confirm" in low:
                raise Exception(
                    "YouTube cloud serverni bot deb bloklayapti. "
                    "Iltimos boshqa havola yuborib ko'ring yoki keyinroq urining."
                )
            if "instagram" in url.lower():
                if "login" in low or "rate" in low or "cookies" in low or "private" in low:
                    raise Exception(
                        "Instagram bu havolaga login yoki cookies talab qilyapti. "
                        "Iltimos public post yuboring."
                    )
                if "unsupported url" in low:
                    raise Exception("Instagram havolasi tan olinmadi. Public post URL yuboring.")
            if "login" in low or "private" in low:
                raise Exception("Bu video private yoki login talab qiladi.")
            if "unsupported url" in low:
                raise Exception("Bu havola turi qo'llab-quvvatlanmaydi.")
            if "http error 403" in low or "forbidden" in low:
                raise Exception("Manba 403 qaytardi. yt-dlp ni yangilang yoki cookies sozlang.")
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
    """Audio/video davomiyligini soniyada qaytaradi. Uch xil strategiya:
    1) ffprobe format=duration (eng tezkor, metadata bo'lsa)
    2) ffprobe stream=duration (audio stream)
    3) ffmpeg -i decode + stderr parse (eng aniq, lekin sekin)
    Hech qaysisi ishlamasa 0 qaytaradi."""
    # 1) Format-level duration
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=15
        )
        out = (result.stdout or "").strip()
        if out and out.upper() != "N/A":
            try:
                d = float(out)
                if d > 0:
                    return d
            except ValueError:
                pass
    except Exception as e:
        logging.debug(f"get_duration strategy 1 xato: {e}")
    # 2) Stream-level duration
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=15
        )
        out = (result.stdout or "").strip()
        if out and out.upper() != "N/A":
            try:
                d = float(out)
                if d > 0:
                    return d
            except ValueError:
                pass
    except Exception as e:
        logging.debug(f"get_duration strategy 2 xato: {e}")
    # 3) ffmpeg decode — eng ishonchli, lekin sekin
    try:
        result = subprocess.run(
            ["ffmpeg", "-i", path, "-f", "null", "-"],
            capture_output=True, text=True, timeout=90
        )
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr or "")
        if m:
            h, mm, ss = int(m.group(1)), int(m.group(2)), float(m.group(3))
            d = h * 3600 + mm * 60 + ss
            if d > 0:
                return d
    except Exception as e:
        logging.warning(f"get_duration strategy 3 xato: {e}")
    logging.warning(f"⚠️ get_duration({path}) hech qaysi strategiya bilan davomiylik aniqlanmadi")
    return 0


def estimate_duration_from_size(path):
    """Davomiylik aniqlanmaganda fayl o'lchamidan taxminlaydi.
    16KB/sek (~128kbps MP3) bo'yicha taxmin. Foydalanuvchi cheklov bypass qilolmasin."""
    try:
        size = os.path.getsize(path)
        if size <= 0:
            return 60  # default 1 daqiqa
        est = max(int(size / 16000), 30)  # kamida 30 soniya
        return est
    except Exception:
        return 60


def get_duration_or_estimate(path):
    """get_duration ishlamasa fayl o'lchamidan taxminlaydi.
    Bu cheklov bypass'ini yopadi — duration aniqlanmasa ham daqiqa hisoblanadi."""
    d = get_duration(path)
    if d > 0:
        return d
    est = estimate_duration_from_size(path)
    logging.warning(f"⏱ Duration probe FAIL, fayl o'lchami taxmini = {est}s, path={path}")
    return est


def fmt_time(seconds):
    """Sekundlarni 'M:SS' yoki 'H:MM:SS' formatga aylantiradi."""
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def split_audio(wav_path):
    """Audio'ni overlap bilan bo'laklarga ajratadi.

    Returns list of (chunk_path, start_sec, end_sec).
    """
    duration = get_duration(wav_path)
    if duration <= CHUNK_SECONDS:
        return [(wav_path, 0.0, duration)]
    chunks = []
    step = CHUNK_SECONDS - OVERLAP_SECONDS  # masalan 50 - 2 = 48 sek
    i = 0
    while True:
        start = i * step
        if start >= duration:
            break
        end = min(start + CHUNK_SECONDS, duration)
        chunk_path = wav_path + f"_part{i}.wav"
        subprocess.run([
            "ffmpeg", "-y", "-i", wav_path,
            "-ss", str(start), "-t", str(CHUNK_SECONDS),
            "-ar", "16000", "-ac", "1",
            "-acodec", "pcm_s16le", chunk_path
        ], check=True, capture_output=True)
        chunks.append((chunk_path, float(start), float(end)))
        i += 1
        # juda qisqa qoldiq bo'lak bo'lsa to'xtaymiz (overlap'ning o'zi)
        if end >= duration:
            break
    return chunks


def _do_muxlisa_request(path, timeout, language="uz"):
    with open(path, "rb") as f:
        return requests.post(
            MUXLISA_URL,
            headers={"x-api-key": MUXLISA_KEY},
            files=[("audio", ("audio.wav", f, "audio/wav"))],
            data={"language": language} if language else {},
            timeout=timeout,
        )


def google_speech_chunk(path, lang_code="ru-RU"):
    """Google Speech API (bepul) orqali transcribe."""
    with sr.AudioFile(path) as source:
        audio = _sr_recognizer.record(source)
    try:
        return (_sr_recognizer.recognize_google(audio, language=lang_code) or "").strip()
    except sr.UnknownValueError:
        return ""  # bo'lakda nutq yo'q yoki tan olinmadi


def _transcribe_chunk_google(path, max_retries=3, lang_code="ru-RU"):
    last_error = None
    for attempt in range(max_retries):
        try:
            return google_speech_chunk(path, lang_code=lang_code)
        except sr.RequestError as e:
            last_error = Exception(f"Google Speech tarmoq xatosi: {e}")
        except Exception as e:
            last_error = e
        if attempt < max_retries - 1:
            time.sleep(1 + attempt)
    raise last_error or Exception("Google Speech noma'lum xato")


def transcribe_chunk(path, max_retries=3, language="uz"):
    """Bo'lakni transcribe qiladi. uz -> Muxlisa, ru/en -> Google Speech."""
    if language in ("ru", "en"):
        lang_code = GOOGLE_LANG.get(language, "ru-RU")
        return _transcribe_chunk_google(path, max_retries=max_retries, lang_code=lang_code)
    # default: uz -> Muxlisa
    last_error = None
    timeouts = [60, 90, 120]
    for attempt in range(max_retries):
        timeout = timeouts[min(attempt, len(timeouts) - 1)]
        try:
            response = _do_muxlisa_request(path, timeout, language=language)
            if response.status_code == 200:
                return response.json().get("text", "").strip()
            # Fatal xatolar (auth/balance) — retry yo'q
            err_text = response.text or ""
            err_lower = err_text.lower()
            if response.status_code in (401, 402, 403) or any(
                k in err_lower for k in ("balance", "insufficient", "credit", "quota", "unauthorized", "forbidden")
            ):
                raise Exception(f"AI xatosi: {response.status_code} - {err_text[:200]}")
            # Boshqa xato (4xx/5xx) — retry qilamiz
            last_error = Exception(f"AI xatosi: {response.status_code} - {err_text[:200]}")
        except requests.exceptions.Timeout:
            last_error = Exception(f"AI javob bermadi ({timeout} sek)")
        except requests.exceptions.ConnectionError as e:
            last_error = Exception(f"Tarmoq xatosi: {str(e)[:80]}")
        except Exception as e:
            # Fatal bo'lsa darhol — retry qilmasdan
            if _is_fatal_error(str(e)):
                raise
            last_error = e
        # Keyingi urinishgacha kutish (1, 2 sek)
        if attempt < max_retries - 1:
            time.sleep(1 + attempt)
            logging.info(f"Bo'lak retry #{attempt + 2} ({path})")
    raise last_error or Exception("AI noma'lum xato")


FATAL_KEYWORDS = ("balance", "insufficient", "credit", "payment", "quota",
                  "limit reach", "unauthorized", "forbidden", "401", "402", "403")


def _is_fatal_error(err_str):
    s = err_str.lower()
    return any(k in s for k in FATAL_KEYWORDS)


def transcribe(file_path, progress_cb=None, language="uz"):
    """progress_cb(stage, current, total) — sync callback. stage: 'convert','split','chunk'."""
    if progress_cb:
        try: progress_cb('convert', 0, 0)
        except Exception: pass
    wav_path = convert_to_wav(file_path)

    if progress_cb:
        try: progress_cb('split', 0, 0)
        except Exception: pass
    chunks = split_audio(wav_path)  # list of (chunk_path, start_sec, end_sec)
    total = len(chunks)
    results = []
    failed_segments = []   # (segment_no, start_sec, end_sec)
    consecutive_errors = 0
    fatal_msg = None
    last_processed = 0
    last_ok_end = 0.0
    try:
        for i, (chunk_path, start_sec, end_sec) in enumerate(chunks):
            last_processed = i
            if progress_cb:
                try: progress_cb('chunk', i + 1, total)
                except Exception: pass
            try:
                text = transcribe_chunk(chunk_path, language=language)
                if text:
                    results.append(text)
                last_ok_end = end_sec
                consecutive_errors = 0
            except Exception as e:
                logging.error(f"Bo'lak {i+1} ({fmt_time(start_sec)}-{fmt_time(end_sec)}) xatosi: {e}")
                failed_segments.append((i + 1, start_sec, end_sec))
                consecutive_errors += 1
                err_str = str(e)
                if _is_fatal_error(err_str):
                    fatal_msg = (
                        "AI servisidagi balans tugagan yoki API kalit muammoli. "
                        "Iltimos hisobingizni to'ldirib qayta urinib ko'ring."
                    )
                    break
                if consecutive_errors >= 3:
                    fatal_msg = "Ketma-ket 3 ta bo'lak xato qaytardi — to'xtatildi."
                    break
            finally:
                if chunk_path != wav_path and os.path.exists(chunk_path):
                    try: os.remove(chunk_path)
                    except Exception: pass
        # Erta to'xtagan bo'lsak — qolgan vaqtinchalik bo'laklarni tozalash
        if fatal_msg:
            for j in range(last_processed + 1, total):
                rest = chunks[j][0]
                if rest != wav_path and os.path.exists(rest):
                    try: os.remove(rest)
                    except Exception: pass
    finally:
        if wav_path != file_path and os.path.exists(wav_path):
            try: os.remove(wav_path)
            except Exception: pass

    text_part = " ".join(results).strip() if results else ""

    # Diagnostika tuzish — qaysi vaqt oraliqlari yo'qoldi
    diag_lines = []
    if failed_segments:
        diag_lines.append(f"\n\n⚠️ {len(failed_segments)} ta bo'lak qayta ishlanmadi:")
        for seg in failed_segments[:15]:
            s, e = seg[1], seg[2]
            diag_lines.append(f"• {fmt_time(s)} - {fmt_time(e)}")
        if len(failed_segments) > 15:
            diag_lines.append(f"...va yana {len(failed_segments) - 15} ta")
        diag_lines.append("Bu vaqtlarni audiodan qayta tinglab matnni qo'l bilan to'ldirishingiz mumkin.")

    if fatal_msg:
        diag_lines.append(f"\n⛔ {fatal_msg}")
        if results:
            diag_lines.append(f"📍 Matn 0:00 dan {fmt_time(last_ok_end)} gacha olindi.")

    diag = "\n".join(diag_lines)

    if not text_part and not diag:
        return "Matn aniqlanmadi."
    if not text_part:
        return diag.lstrip()
    return text_part + diag


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


def make_pdf(text, title="Audio & Konspekt — Matn"):
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


def user_lang(update):
    """Foydalanuvchi chat'i uchun tilni aniqlash:
    1) /lang buyruq orqali saqlangan tanlov (chat_data) — bu handlerdan tashqarida)
    2) Telegram language_code (ru-RU -> ru, en-US -> en, aks holda uz)
    """
    code = ""
    try:
        code = (update.effective_user.language_code or "").lower()
    except Exception:
        code = ""
    if code.startswith("ru") or code.startswith("be") or code.startswith("kk"):
        return "ru"
    if code.startswith("en"):
        return "en"
    return "uz"


def detect_lang(text):
    """Matn tilini aniqlash: kirill -> ru, lotin asosan ASCII English -> en, aks holda uz."""
    if not text:
        return "uz"
    cyr = sum(1 for ch in text if 'Ѐ' <= ch <= 'ӿ')
    if cyr / max(len(text), 1) > 0.35:
        return "ru"
    # Lotin matn — agar uzbek-specific belgilar bo'lmasa, ingliz deb hisoblaymiz
    uz_specific = ("o'", "g'", "o‘", "g‘", "sh", "ch", "ng")
    low = text.lower()
    if any(m in low for m in uz_specific):
        return "uz"
    # ko'p ASCII inglizcha so'zlar bormi
    return "en"


def extract_pdf_text(pdf_path):
    """PDF faylidan matn ajratib oladi (bot sarlavhalari, fayl nomi tozalanadi)."""
    try:
        reader = pypdf.PdfReader(pdf_path)
        parts = []
        for page in reader.pages:
            t = page.extract_text() or ""
            if t.strip():
                parts.append(t.strip())
        full = "\n\n".join(parts)
        return _clean_pdf_text(full)
    except Exception as e:
        raise Exception(f"PDF o'qib bo'lmadi: {e}")


def _clean_pdf_text(text):
    """Bot yaratgan PDF sarlavhalari va fayl metadata sini tozalash."""
    if not text:
        return text
    lines = text.split("\n")
    # Bot sarlavhalari ('MNSM — Matn', 'SesTon — Matn', va h.k.) olib tashlash
    cleaned = []
    skip_keywords = (
        "mnsm", "seston", "audio & konspekt", "konspekt",
        "— matn", "—matn", "matn:", "📝", "📎", "🔊", "🌸",
    )
    for ln in lines:
        s = ln.strip()
        if not cleaned and (not s or any(kw in s.lower() for kw in skip_keywords)):
            continue  # boshlanishidagi sarlavhalarni tashlab ketish
        cleaned.append(ln)
    return "\n".join(cleaned).strip()


def make_tts(text, lang=None):
    """Matnni ovozli MP3 ga aylantiradi (edge-tts) — vaqt cheklovsiz."""
    if not text or not text.strip():
        return None
    if lang is None:
        lang = detect_lang(text)
    voice = VOICES.get(lang, VOICES["uz"])
    snippet = text.strip()
    out_path = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False).name

    async def _run():
        comm = edge_tts.Communicate(snippet, voice)
        await comm.save(out_path)

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_run())
    finally:
        loop.close()
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


# === [TARJIMA MODULI — API HELPERS] =============================================
# Whisper: max 25 MB per request. 4 soatlik audio uchun bo'laklash kerak.
# Claude: max 8192 output tokens. 30K+ so'zlar uchun bo'laklash kerak.

WHISPER_CHUNK_SECONDS = 1200   # 20 daqiqa per chunk (~14 MB @ 96kbps MP3)
WHISPER_MAX_FILE_MB = 24        # 24 MB dan oshganda bo'laklash
CLAUDE_CHUNK_WORDS = 2000       # Claude'ga max 2000 so'zlik bo'lak


def split_audio_for_whisper(file_path, chunk_seconds=WHISPER_CHUNK_SECONDS):
    """Whisper uchun katta audio'ni bo'laklarga ajratish (ffmpeg orqali).
    20 daqiqalik MP3 @ 96kbps ≈ 14 MB. Whisper 25 MB chegarasi ichida.
    Returns: list of chunk file paths."""
    if not have_cmd("ffmpeg"):
        return [file_path]
    total_dur = 0
    try:
        total_dur = get_duration_or_estimate(file_path)
    except Exception:
        pass
    if total_dur <= 0 or total_dur <= chunk_seconds:
        return [file_path]
    n_chunks = int(total_dur // chunk_seconds) + (1 if total_dur % chunk_seconds > 0 else 0)
    chunks = []
    tmp_dir = tempfile.mkdtemp(prefix="whisper_chunks_")
    for i in range(n_chunks):
        start = i * chunk_seconds
        out_path = os.path.join(tmp_dir, f"chunk_{i:03d}.mp3")
        cmd = [
            "ffmpeg", "-y", "-v", "error",
            "-ss", str(start),
            "-i", file_path,
            "-t", str(chunk_seconds),
            "-vn", "-acodec", "libmp3lame", "-b:a", "96k",
            out_path
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=180)
            if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                chunks.append(out_path)
        except Exception as e:
            logging.warning(f"Whisper chunk {i} yaratish xatosi: {e}")
    return chunks if chunks else [file_path]


def transcribe_whisper(file_path, source_lang, progress_cb=None):
    """OpenAI Whisper API orqali audio'ni original tilida matnga aylantirish.
    Katta fayl avtomatik bo'laklanadi (24 MB / 25 daq chegara).
    progress_cb(current_chunk, total_chunks) — async progress callback."""
    if not OPENAI_API_KEY:
        raise Exception("OPENAI_API_KEY sozlanmagan. Railway env qo'shing.")

    # Fayl o'lchami va davomiyligi
    try:
        size_mb = os.path.getsize(file_path) / (1024 * 1024)
    except Exception:
        size_mb = 0
    duration = get_duration_or_estimate(file_path)

    # Bo'laklashga ehtiyoj bormi?
    chunks_to_process = [file_path]
    chunk_dir_to_cleanup = None
    if size_mb > WHISPER_MAX_FILE_MB or duration > (WHISPER_CHUNK_SECONDS + 60):
        logging.info(f"🔪 Whisper bo'laklash: size={size_mb:.1f}MB, dur={duration}s")
        chunks = split_audio_for_whisper(file_path, WHISPER_CHUNK_SECONDS)
        if chunks and chunks[0] != file_path:
            chunks_to_process = chunks
            chunk_dir_to_cleanup = os.path.dirname(chunks[0])
            logging.info(f"   → {len(chunks)} bo'lak yaratildi")

    # Har bir bo'lakni Whisper'ga yuborish
    url = "https://api.openai.com/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
    results = []
    total = len(chunks_to_process)
    try:
        for idx, chunk_path in enumerate(chunks_to_process, 1):
            if progress_cb:
                try: progress_cb(idx, total)
                except Exception: pass
            with open(chunk_path, "rb") as f:
                files = {"file": (os.path.basename(chunk_path), f, "application/octet-stream")}
                data = {
                    "model": "whisper-1",
                    "language": source_lang,
                    "response_format": "verbose_json",
                }
                resp = requests.post(url, headers=headers, files=files, data=data, timeout=600)
            if resp.status_code != 200:
                raise Exception(f"Whisper xato (bo'lak {idx}/{total}): HTTP {resp.status_code} — {resp.text[:200]}")
            result = resp.json()
            text = (result.get("text") or "").strip()
            if text:
                results.append(text)
    finally:
        if chunk_dir_to_cleanup:
            try: shutil.rmtree(chunk_dir_to_cleanup, ignore_errors=True)
            except Exception: pass

    return "\n\n".join(results)


def _gpt_translate_one(text, source_lang):
    """Bir bo'lakni OpenAI GPT-4o bilan tarjima qilish — Claude darajasida sifat.
    GPT-4o (mini emas) — eng yuqori tarjima sifati, ma'no buzilmaydi."""
    src_name = TRANSLATION_LANG_NAMES.get(source_lang, source_lang)
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    system_prompt = (
        "Sen O'zbek tilini mukammal biladigan professional tarjimon. "
        "Xorijiy tildagi matnni O'zbek tiliga adabiy, tabiiy va to'liq aniq "
        "ma'noni saqlagan holda tarjima qil. Iboralar va idiomalarni "
        "O'zbekcha ekvivalent bilan almashtir, so'zma-so'z tarjima qilma. "
        "Faqat tarjimani qaytar — boshqa hech qanday izoh, sarlavha yoki "
        "kirish so'zi yozma."
    )
    user_prompt = f"{src_name.capitalize()} tilidagi matnni O'zbekchaga tarjima qil:\n\n{text}"
    payload = {
        "model": "gpt-4o",
        "max_tokens": 16000,
        "temperature": 0.3,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=300)
    if resp.status_code != 200:
        raise Exception(f"GPT xato: HTTP {resp.status_code} — {resp.text[:200]}")
    data = resp.json()
    choices = data.get("choices", [])
    if not choices:
        raise Exception("GPT bo'sh javob qaytardi.")
    return choices[0].get("message", {}).get("content", "").strip()


def translate_with_claude(text, source_lang, progress_cb=None):
    """Tarjima — OpenAI GPT-4o orqali (avval Claude edi).
    Funksiya nomi mavjud chaqiruvchilarga mos qoldirildi.
    progress_cb(current_chunk, total_chunks) — async progress callback."""
    if not OPENAI_API_KEY:
        raise Exception("OPENAI_API_KEY sozlanmagan. Railway env qo'shing.")

    words = text.split()
    # Kichik matn — bir martada tarjima
    if len(words) <= CLAUDE_CHUNK_WORDS:
        if progress_cb:
            try: progress_cb(1, 1)
            except Exception: pass
        return _gpt_translate_one(text, source_lang)

    # Uzun matn — bo'laklarga ajratamiz (so'zlar chegarasida)
    chunks = []
    for i in range(0, len(words), CLAUDE_CHUNK_WORDS):
        chunks.append(" ".join(words[i:i + CLAUDE_CHUNK_WORDS]))
    logging.info(f"🔪 GPT bo'laklash: {len(words)} so'z → {len(chunks)} bo'lak")
    translations = []
    for idx, chunk in enumerate(chunks, 1):
        if progress_cb:
            try: progress_cb(idx, len(chunks))
            except Exception: pass
        try:
            translations.append(_gpt_translate_one(chunk, source_lang))
        except Exception as e:
            logging.warning(f"GPT bo'lak {idx}/{len(chunks)} xato: {e}")
            translations.append(f"[Bo'lak {idx} tarjima xatosi]")
    return "\n\n".join(translations)
# === [/TARJIMA MODULI — API HELPERS] ============================================


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
    # PDF qilib yuborish (audio kontekstida — TTS yo'q)
    pdf_path = None
    try:
        pdf_path = await asyncio.to_thread(make_pdf, text)
        with open(pdf_path, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename="mnsm-matn.pdf",
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


async def process_local_audio(update, context, file_path, duration=0, language="uz"):
    # Tarif limiti — barcha tillarda qo'llanadi
    if not await can_process_uzbek(update, duration):
        return

    est = f"{duration // 60} daqiqa {duration % 60} soniya" if duration else "noma'lum"

    # Admin test rejimi — Muxlisa chaqirilmaydi
    if language == "uz" and is_admin(update) and TEST_MODE["on"]:
        await update.message.reply_text(
            f"🧪 *TEST REJIMI* — Muxlisa chaqirilmadi (pul ketmadi)\n⏱ {est}",
            parse_mode="Markdown"
        )
        msg = await update.message.reply_text("Test natijasi tayyorlanyapti...")
        await send_result(update, msg, "[TEST REJIMI] Bu sahta natija. Muxlisa balansidan pul yechilmadi. /test buyrug'i bilan o'chirib qo'ying.")
        return

    msg = await update.message.reply_text(
        f"🎙 Tanilmoqda...\n⏱ Davomiyligi: {est}\n\nBiroz sabr qiling..."
    )
    try:
        # Davomiylik noma'lum bo'lsa (webapp duration=0 yuborgan bo'lsa) — ffprobe bilan aniqlaymiz
        actual_duration = duration
        if not is_admin(update) and (not duration or duration <= 0):
            try:
                actual_duration = int(await asyncio.to_thread(get_duration_or_estimate, file_path))
            except Exception:
                actual_duration = 0
            if actual_duration > 0:
                user_id = update.effective_user.id
                used = get_user_usage_sec(user_id)
                limit = get_user_limit_sec(user_id)
                tariff = TARIFFS[get_user_tariff(user_id)]
                if used + actual_duration > limit:
                    rem = max(0, limit - used) / 60
                    await msg.edit_text(
                        f"⚠️ *Bu audio limitga sig'maydi!*\n\n"
                        f"🌸 Tarif: {tariff['name']}\n"
                        f"📊 Ishlatilgan: {used/60:.1f} / {tariff['minutes']} daqiqa\n"
                        f"⏳ Bu audio: {actual_duration/60:.1f} daqiqa\n"
                        f"📉 Qoldiq: {rem:.1f} daqiqa\n\n"
                        f"💎 Yuqori tarif: /tariflar",
                        parse_mode="Markdown"
                    )
                    return

        loop = asyncio.get_running_loop()
        cb = make_progress_cb(loop, msg)
        text = await asyncio.to_thread(transcribe, file_path, cb, language)
        await send_result(update, msg, text)
        if not is_admin(update) and actual_duration > 0:
            add_user_usage(update.effective_user.id, actual_duration)
    except Exception as e:
        logging.error(f"Xato: {e}")
        await msg.edit_text(f"❌ Xato: {str(e)[:300]}")


async def process_file(update, context, file_id, suffix, duration=0, language="uz"):
    # Tarif limiti — barcha tillarda qo'llanadi
    uid = update.effective_user.id if update.effective_user else None
    uname = (update.effective_user.username if update.effective_user else None) or ""
    logging.info(f"📥 process_file: user_id={uid}, username='{uname}', is_admin={is_admin(update)}, duration={duration}, language={language}")
    if not await can_process_uzbek(update, duration):
        return

    est = f"{duration // 60} daqiqa {duration % 60} soniya" if duration else "noma'lum"

    # Admin test rejimi — Muxlisa chaqirilmaydi
    if language == "uz" and is_admin(update) and TEST_MODE["on"]:
        await update.message.reply_text(
            f"🧪 *TEST REJIMI* — Muxlisa chaqirilmadi (pul ketmadi)\n⏱ {est}",
            parse_mode="Markdown"
        )
        msg = await update.message.reply_text("Test natijasi tayyorlanyapti...")
        await send_result(update, msg, "[TEST REJIMI] Bu sahta natija. Muxlisa balansidan pul yechilmadi. /test buyrug'i bilan o'chirib qo'ying.")
        return

    msg = await update.message.reply_text(
        f"🎙 Tanilmoqda...\n⏱ Davomiyligi: {est}\n\nBiroz sabr qiling..."
    )
    tmp_path = None
    try:
        file = await context.bot.get_file(file_id)
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp_path = tmp.name
        await file.download_to_drive(tmp_path)

        # Agar Telegram metadata davomiylikni bermagan bo'lsa (masalan, document fayl)
        # ffprobe orqali aniqlaymiz va limitni qayta tekshiramiz — chetlab o'tilmasin.
        actual_duration = duration
        if not is_admin(update) and (not duration or duration <= 0):
            try:
                actual_duration = int(await asyncio.to_thread(get_duration_or_estimate, tmp_path))
            except Exception:
                actual_duration = 0
            if actual_duration > 0:
                user_id = update.effective_user.id
                used = get_user_usage_sec(user_id)
                limit = get_user_limit_sec(user_id)
                tariff = TARIFFS[get_user_tariff(user_id)]
                if used + actual_duration > limit:
                    rem = max(0, limit - used) / 60
                    await msg.edit_text(
                        f"⚠️ *Bu fayl limitga sig'maydi!*\n\n"
                        f"🌸 Tarif: {tariff['name']}\n"
                        f"📊 Ishlatilgan: {used/60:.1f} / {tariff['minutes']} daqiqa\n"
                        f"⏳ Bu fayl: {actual_duration/60:.1f} daqiqa\n"
                        f"📉 Qoldiq: {rem:.1f} daqiqa\n\n"
                        f"💎 Yuqori tarif: /tariflar",
                        parse_mode="Markdown"
                    )
                    return

        loop = asyncio.get_running_loop()
        cb = make_progress_cb(loop, msg)
        text = await asyncio.to_thread(transcribe, tmp_path, cb, language)
        await send_result(update, msg, text)
        if not is_admin(update) and actual_duration > 0:
            add_user_usage(update.effective_user.id, actual_duration)
    except Exception as e:
        logging.error(f"Xato: {e}")
        await msg.edit_text(f"❌ Xato: {str(e)[:300]}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try: os.remove(tmp_path)
            except Exception: pass


async def process_url(update, context, url, language="uz"):
    logging.info(f"🔗 process_url chaqirildi: lang={language}, url={url[:80]}")
    # Tarif limiti — barcha tillarda qo'llanadi (davomiylik yuklab olingach tekshiriladi)
    ok = await can_process_uzbek(update, 0)
    logging.info(f"🔐 can_process tarif natijasi: {ok}")
    if not ok:
        return

    # Admin test rejimi — yuklash ham, transcribe ham yo'q
    if language == "uz" and is_admin(update) and TEST_MODE["on"]:
        await update.message.reply_text(
            f"🧪 *TEST REJIMI* — Video yuklanmadi, Muxlisa chaqirilmadi (pul ketmadi)",
            parse_mode="Markdown"
        )
        msg = await update.message.reply_text("Test natijasi tayyorlanyapti...")
        await send_result(update, msg, "[TEST REJIMI] Bu sahta natija. URL yuklanmadi, Muxlisa chaqirilmadi.")
        return

    msg = await update.message.reply_text(
        f"📥 Video yuklanmoqda...\n🔗 {url[:50]}\n\nBiroz sabr qiling..."
    )
    audio_path = None
    actual_duration = 0
    try:
        audio_path = await asyncio.to_thread(download_audio_from_url, url)
        # Yuklangan audio davomiyligini aniqlash (event loop'ni bloklamaslik uchun thread'da)
        def _probe_duration(path):
            try:
                p = subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", path],
                    capture_output=True, text=True, timeout=10
                )
                return int(float(p.stdout.strip())) if p.stdout.strip() else 0
            except Exception:
                return 0
        try:
            actual_duration = await asyncio.to_thread(_probe_duration, audio_path)
        except Exception:
            actual_duration = 0

        # Limit qaytadan tekshirish (real davomiyligi bilan)
        if not is_admin(update) and actual_duration > 0:
            user_id = update.effective_user.id
            used = get_user_usage_sec(user_id)
            limit = get_user_limit_sec(user_id)
            tariff = TARIFFS[get_user_tariff(user_id)]
            if used + actual_duration > limit:
                rem = max(0, limit - used) / 60
                await msg.edit_text(
                    f"⚠️ *Bu video limitga sig'maydi!*\n\n"
                    f"🌸 Tarif: {tariff['name']}\n"
                    f"📊 Ishlatilgan: {used/60:.1f} / {tariff['minutes']} daqiqa\n"
                    f"⏳ Bu video: {actual_duration/60:.1f} daqiqa\n"
                    f"📉 Qoldiq: {rem:.1f} daqiqa\n\n"
                    f"💎 Yuqori tarif: /tariflar",
                    parse_mode="Markdown"
                )
                return

        await msg.edit_text("✅ Yuklanidi! 🎙 Matn tanilmoqda...")

        loop = asyncio.get_running_loop()
        cb = make_progress_cb(loop, msg)
        text = await asyncio.to_thread(transcribe, audio_path, cb, language)
        await send_result(update, msg, text)
        if not is_admin(update) and actual_duration > 0:
            add_user_usage(update.effective_user.id, actual_duration)
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
        [
            [KeyboardButton(text="🎙 Web ilovani ochish", web_app=WebAppInfo(url=url))],
            [KeyboardButton(text="📊 Balansim"), KeyboardButton(text="💎 Tariflar")],
            [KeyboardButton(text="💳 Sotib olish"), KeyboardButton(text="🌐 Tarjima")],
            [KeyboardButton(text="❓ Yordam"), KeyboardButton(text="💬 Murojaat")],
            [KeyboardButton(text="🔄 /start")],
        ],
        resize_keyboard=True,
    )


# ── BOT HANDLERS ────────────────────────────────────────────────────────────

def fresh_webapp_url(chat_id=None):
    sep = "&" if "?" in WEBAPP_URL else "?"
    parts = [f"v={int(time.time())}"]
    if chat_id is not None:
        parts.append(f"user={chat_id}")
    return f"{WEBAPP_URL}{sep}{'&'.join(parts)}"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_user.id
    # Admin /start yuborgan bo'lsa ADMIN_CHAT_ID ni darrov saqlash
    is_admin(update)
    # Menu button'ni har gal yangi URL bilan o'rnatish — eski cache buziladi
    try:
        await context.bot.set_chat_menu_button(
            chat_id=update.effective_chat.id,
            menu_button=MenuButtonWebApp(
                text="🎙 MNSM",
                web_app=WebAppInfo(url=fresh_webapp_url(chat_id)),
            ),
        )
    except Exception as e:
        logging.error(f"Menu button set xato: {e}")

    await update.message.reply_text(
        "🌸 Assalomu alaykum, *{}*!\n\n"
        "Men audio va videolarni matn hamda PDF formatiga aylantiruvchi aqlli botman. "
        "Darslaringizni yanada osonlashtirish uchun tartibli, chiroyli va tushunarli "
        "konspektlar tayyorlab beraman.\n\n"
        "🎧 Shuningdek, PDF hujjatlarni ovozli audio formatga aylantirib, "
        "ularni istalgan joyda qulay tinglashingizga yordam beraman.\n\n"
        "📌 *Yuborishingiz mumkin:*\n"
        "• 🎤 Ovozli xabar / audio fayl\n"
        "• 🎬 Video / dumaloq video\n"
        "• 🔗 YouTube / TikTok / Instagram havolasi\n"
        "• 📄 PDF fayl (matn ovozga aylanadi)\n\n"
        "Quyidagi tugma orqali *Web ilovani* oching 👇".format(
            update.effective_user.first_name
        ),
        parse_mode="Markdown",
        reply_markup=webapp_keyboard(chat_id=chat_id),
    )


async def handle_web_app_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Web App dan json ma'lumot kelganda ishlaydi (faqat KeyboardButton orqali)."""
    logging.info(f"📨 WebApp data keldi userdan: {update.effective_user.id}")
    try:
        raw = update.message.web_app_data.data if update.message.web_app_data else ""
        logging.info(f"📋 WebApp raw data (ilk 200): {raw[:200]}")
        data = json.loads(raw)
        file_type = data.get("type", "")
        url = data.get("url", "")
        logging.info(f"🎯 WebApp type={file_type}, url={url[:60] if url else ''}")

        if file_type == "url" and url:
            url = extract_url(url) or url
            url_lang = (data.get("language") or "").lower()
            if url_lang not in ("uz", "ru", "en"):
                url_lang = _chat_lang(context, update)
            await process_url(update, context, url, language=url_lang)
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
            wa_lang = (data.get("language") or "").lower()
            if wa_lang not in ("uz", "ru", "en"):
                wa_lang = _chat_lang(context, update)
            try:
                await process_local_audio(update, context, tmp_path, data.get("duration", 0), language=wa_lang)
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            return

        await update.message.reply_text("⚠️ Web App ma'lumoti tan olinmadi.")
    except Exception as e:
        logging.error(f"WebApp data xatosi: {e}")
        await update.message.reply_text("❌ Web App dan ma'lumot xato keldi.")


def _pop_translation_lang(user_id):
    """=== [TARJIMA] User tarjima rejimida bo'lsa source_lang qaytaradi va state'ni o'chiradi. ==="""
    if user_id and user_id in pending_translations:
        lang = pending_translations.pop(user_id, None)
        _save_user_data()
        return lang
    return None


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = update.message.voice
    if not v:
        await update.message.reply_text("⚠️ Ovozli xabaringiz topilmadi. Iltimos qayta yuboring.")
        return
    # === [TARJIMA INTEGRATSIYASI] ===
    src_lang = _pop_translation_lang(update.effective_user.id)
    if src_lang:
        await process_translation_from_file_id(update, context, v.file_id, ".ogg", v.duration or 0, src_lang)
        return
    # === [/TARJIMA INTEGRATSIYASI] ===
    lang = _chat_lang(context, update)
    await process_file(update, context, v.file_id, ".ogg", v.duration or 0, language=lang)


async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    a = update.message.audio
    ext = os.path.splitext(a.file_name or "audio.mp3")[1] or ".mp3"
    # === [TARJIMA INTEGRATSIYASI] ===
    src_lang = _pop_translation_lang(update.effective_user.id)
    if src_lang:
        await process_translation_from_file_id(update, context, a.file_id, ext, a.duration or 0, src_lang)
        return
    # === [/TARJIMA INTEGRATSIYASI] ===
    lang = _chat_lang(context, update)
    await process_file(update, context, a.file_id, ext, a.duration or 0, language=lang)


async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = update.message.video
    ext = os.path.splitext(v.file_name or "video.mp4")[1] or ".mp4"
    # === [TARJIMA INTEGRATSIYASI] ===
    src_lang = _pop_translation_lang(update.effective_user.id)
    if src_lang:
        await process_translation_from_file_id(update, context, v.file_id, ext, v.duration or 0, src_lang)
        return
    # === [/TARJIMA INTEGRATSIYASI] ===
    lang = _chat_lang(context, update)
    await process_file(update, context, v.file_id, ext, v.duration or 0, language=lang)


async def handle_video_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = update.message.video_note
    # === [TARJIMA INTEGRATSIYASI] ===
    src_lang = _pop_translation_lang(update.effective_user.id)
    if src_lang:
        await process_translation_from_file_id(update, context, v.file_id, ".mp4", v.duration or 0, src_lang)
        return
    # === [/TARJIMA INTEGRATSIYASI] ===
    lang = _chat_lang(context, update)
    await process_file(update, context, v.file_id, ".mp4", v.duration or 0, language=lang)


def _chat_lang(context, update):
    """Chat'da saqlangan til (/lang buyrug'i orqali) yoki Telegram language_code."""
    try:
        saved = context.chat_data.get("lang") if context and hasattr(context, "chat_data") else None
        if saved in ("uz", "ru", "en"):
            return saved
    except Exception:
        pass
    return user_lang(update)


async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User uchun: o'z balansi. Admin uchun: panel."""
    if is_admin(update):
        total_users = len(user_uzbek_usage)
        total_sec = sum(user_uzbek_usage.values())
        total_cost = int(total_sec / 60 * MUXLISA_PRICE_PER_MIN)
        test_status = "✅ YONIQ" if TEST_MODE["on"] else "❌ O'CHIQ"
        # Tariflar bo'yicha foydalanuvchilar soni
        tariff_counts = {}
        for t in user_tariffs.values():
            tariff_counts[t] = tariff_counts.get(t, 0) + 1
        tariff_lines = []
        for key, t in TARIFFS.items():
            cnt = tariff_counts.get(key, 0)
            if cnt > 0:
                tariff_lines.append(f"• {t['name']}: {cnt} ta")
        tariff_text = "\n".join(tariff_lines) if tariff_lines else "• 🌸 Bepul (default): hamma"
        admin_uname_md = (update.effective_user.username or "").replace("_", "\\_").replace("*", "\\*")
        await update.message.reply_text(
            f"👑 *ADMIN PANEL* — @{admin_uname_md}\n\n"
            f"🧪 Test rejimi: *{test_status}*\n"
            f"👥 Foydalanuvchilar: {total_users}\n"
            f"⏱ Jami O'zbek STT: {total_sec/60:.1f} daqiqa\n"
            f"💰 Jami xarajat: ~{total_cost:,} so'm\n\n"
            f"*Tariflar bo'yicha:*\n{tariff_text}\n\n"
            f"*Admin buyruqlari:*\n"
            f"• /test — test rejimi\n"
            f"• /stats — userlar statistikasi\n"
            f"• /grant `<user id>` `<tarif>` — tarif berish\n"
            f"• /setcard `<karta>` — karta raqamini sozlash\n"
            f"• /setholder `<ism>` — karta egasini sozlash\n"
            f"• /reply `<id>` `<xabar>` — javob berish\n"
            f"• /debug — persistence holatini ko'rish\n"
            f"• /reset — limitlarni tiklash",
            parse_mode="Markdown"
        )
        return

    user_id = update.effective_user.id
    used = get_user_usage_sec(user_id)
    limit = get_user_limit_sec(user_id)
    rem = max(0, limit - used) / 60
    tariff = TARIFFS[get_user_tariff(user_id)]
    await update.message.reply_text(
        f"📊 *Sizning hisobingiz*\n\n"
        f"🌸 Tarif: *{tariff['name']}* ({tariff['minutes']} daqiqa/oy)\n"
        f"⏱ Ishlatilgan: {used/60:.1f} daqiqa\n"
        f"📉 Qoldiq: {rem:.1f} daqiqa\n\n"
        f"💎 Tariflarni ko'rish: /tariflar\n"
        f"💳 Tarif sotib olish: /buy\n\n"
        f"🆔 Sizning ID'ingiz: `{user_id}`",
        parse_mode="Markdown"
    )


async def test_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: test rejimini yoqish/o'chirish."""
    if not is_admin(update):
        await update.message.reply_text("⛔ Bu buyruq faqat admin uchun.")
        return
    TEST_MODE["on"] = not TEST_MODE["on"]
    if TEST_MODE["on"]:
        await update.message.reply_text(
            "🧪 *Test rejimi YONIQ ✅*\n\n"
            "Endi O'zbek audiolar Muxlisa ga yuborilmaydi — pul ketmaydi.\n"
            "Bot sahta natija qaytaradi.\n\n"
            "O'chirish uchun: /test",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "🧪 *Test rejimi O'CHIQ ❌*\n\n"
            "Endi haqiqiy Muxlisa STT ishlaydi (balansdan pul yechiladi).",
            parse_mode="Markdown"
        )


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: barcha userlar statistikasi."""
    if not is_admin(update):
        await update.message.reply_text("⛔ Bu buyruq faqat admin uchun.")
        return
    if not user_uzbek_usage:
        await update.message.reply_text("📊 Hozircha foydalanuvchilar STT ishlatmagan.")
        return
    lines = ["📊 *Foydalanuvchi statistikasi:*\n"]
    sorted_users = sorted(user_uzbek_usage.items(), key=lambda x: x[1], reverse=True)
    for user_id, sec in sorted_users[:20]:
        cost = int(sec / 60 * MUXLISA_PRICE_PER_MIN)
        lines.append(f"• `{user_id}` — {sec/60:.1f} daq (~{cost:,} so'm)")
    total_sec = sum(user_uzbek_usage.values())
    total_cost = int(total_sec / 60 * MUXLISA_PRICE_PER_MIN)
    lines.append(f"\n*Jami:* {total_sec/60:.1f} daqiqa = ~{total_cost:,} so'm")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: barcha foydalanuvchi limitlarini tiklash."""
    if not is_admin(update):
        await update.message.reply_text("⛔ Bu buyruq faqat admin uchun.")
        return
    n = len(user_uzbek_usage)
    user_uzbek_usage.clear()
    _save_user_data()
    await update.message.reply_text(f"✅ {n} ta foydalanuvchining limiti tiklandi.")


async def tariflar_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Hammaga: tariflar ro'yxati + sotib olish tugmasi."""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💎 Tarifni sotib olish", callback_data="buy:menu")]
    ])
    await update.message.reply_text(
        format_tariffs_text(),
        parse_mode="Markdown",
        reply_markup=keyboard
    )


async def buy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tarif sotib olish menyusi."""
    await _show_buy_menu(update.message)


async def _show_buy_menu(message_obj):
    """Tarif tugmalari ko'rsatadi (chat message yoki callback edit uchun)."""
    paid = [(k, t) for k, t in TARIFFS.items() if t["price"] > 0]
    buttons = []
    for key, t in paid:
        hrs = t["minutes"] // 60
        label = f"{t['name']} • {hrs} soat • {t['price']:,} so'm"
        buttons.append([InlineKeyboardButton(label, callback_data=f"buy:{key}")])
    text = (
        "💎 *Tarifni tanlang*\n\n"
        "Tanlagan tarifingiz uchun to'lov ma'lumotlari ko'rinadi.\n"
        "💳 Click / Payme / Paynet / Uzcard / Humo orqali to'lashingiz mumkin.\n\n"
        "📸 To'lov chekini botga yuborgach tarifingiz tasdiqlanadi va faollashadi."
    )
    if hasattr(message_obj, "edit_message_text"):
        await message_obj.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))
    else:
        await message_obj.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))


async def buy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User tarif tugmasini bosganida — Telegram Payments invoice yuboriladi."""
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()

    if query.data == "buy:menu":
        await _show_buy_menu(query)
        return

    if not query.data.startswith("buy:"):
        return
    tariff_key = query.data.split(":", 1)[1]
    if tariff_key not in TARIFFS or TARIFFS[tariff_key]["price"] == 0:
        await query.edit_message_text("❌ Bu tarif sotuvga qo'yilmagan.")
        return

    t = TARIFFS[tariff_key]
    user = query.from_user

    # PROVIDER_TOKEN sozlanmagan bo'lsa — manual to'lov rejimi
    # (karta raqami ko'rsatiladi, foydalanuvchi to'laydi va chek yuboradi)
    if not PAYMENT_PROVIDER_TOKEN:
        # Karta ma'lumotlarini olish — runtime_settings (admin /setcard orqali) ustivor,
        # bo'lmasa env variable, oxirgi chora — placeholder
        card = runtime_settings.get("payment_card") or PAYMENT_CARD or "(karta raqami sozlanmagan)"
        holder = runtime_settings.get("payment_card_holder") or PAYMENT_CARD_HOLDER
        holder_line = f"👤 Karta egasi: *{holder}*\n" if holder else ""
        text = (
            f"💳 *To'lov*\n\n"
            f"🌸 Tarif: *{t['name']}*\n"
            f"⏱ Limit: *{t['minutes']} daqiqa/oy* ({t['minutes']//60} soat)\n"
            f"💰 To'lov miqdori: *{t['price']:,} so'm*\n\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"📋 *Karta raqami:*\n`{card}`\n"
            f"{holder_line}"
            f"━━━━━━━━━━━━━━━━━\n\n"
            f"💸 To'lov usullari:\n"
            f"✅ Click / Payme / Paynet (kartaga o'tkazma)\n"
            f"✅ Humo / Uzcard P2P\n"
            f"✅ Boshqa bank ilovalari\n\n"
            f"📸 *To'lovdan keyin pastdagi tugmani bosing va chekni shu chatga yuboring* 👇"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Men to'ladim — chek yuboraman", callback_data=f"paid:{tariff_key}")],
            [InlineKeyboardButton("⬅️ Boshqa tarif", callback_data="buy:menu")],
        ])
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)
        return

    payload = f"tariff:{tariff_key}:{user.id}"
    title = f"{t['name']} tarif"
    description = (
        f"{t['minutes']} daqiqa/oy ({t['minutes']//60} soat) "
        f"O'zbek tilida ovoz/videoni matnga aylantirish."
    )
    # Telegram Payments narxni eng kichik valyuta birligida kutadi.
    # UZS uchun rasmiy birlik — tiyin yo'q, lekin Telegram amount * 100 talab qiladi.
    amount_minor = t["price"] * 100
    prices = [LabeledPrice(label=t["name"], amount=amount_minor)]

    try:
        await context.bot.send_invoice(
            chat_id=query.message.chat_id,
            title=title,
            description=description,
            payload=payload,
            provider_token=PAYMENT_PROVIDER_TOKEN,
            currency=PAYMENT_CURRENCY,
            prices=prices,
            start_parameter=f"buy_{tariff_key}",
            need_name=False,
            need_phone_number=False,
            need_email=False,
            is_flexible=False,
        )
        # Tugma menyusini "tarif tanlandi" ko'rinishiga o'zgartiramiz
        try:
            await query.edit_message_text(
                f"💳 *{t['name']}* uchun to'lov oynasi yuborildi 👇\n\n"
                f"Telegramning ichki to'lov oynasidan to'lovni amalga oshiring.\n"
                f"To'lov muvaffaqiyatli o'tgach tarif avtomat faollashadi.",
                parse_mode="Markdown"
            )
        except Exception:
            pass
    except Exception as e:
        logging.error(f"send_invoice xatosi: {e}")
        await query.edit_message_text(
            f"❌ To'lov oynasini ochishda xato: {str(e)[:200]}\n\n"
            f"Iltimos keyinroq urinib ko'ring."
        )


async def precheckout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Telegram to'lovni tasdiqlash so'rovi — 10 sek ichida javob berish shart."""
    q = update.pre_checkout_query
    if not q:
        return
    payload = q.invoice_payload or ""
    parts = payload.split(":")
    if len(parts) >= 3 and parts[0] == "tariff" and parts[1] in TARIFFS:
        await q.answer(ok=True)
    else:
        await q.answer(ok=False, error_message="Noma'lum tarif. Iltimos qayta urining.")


async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """To'lov muvaffaqiyatli o'tgach — tarifni avtomat faollashtirish."""
    sp = update.message.successful_payment
    if not sp:
        return
    payload = sp.invoice_payload or ""
    parts = payload.split(":")
    if len(parts) < 3 or parts[0] != "tariff":
        logging.warning(f"Notanish payment payload: {payload}")
        return
    tariff_key = parts[1]
    try:
        target_id = int(parts[2])
    except ValueError:
        target_id = update.effective_user.id
    if tariff_key not in TARIFFS:
        logging.warning(f"Notanish tariff_key: {tariff_key}")
        return

    user_tariffs[target_id] = tariff_key
    user_uzbek_usage[target_id] = 0
    _save_user_data()

    t = TARIFFS[tariff_key]
    await update.message.reply_text(
        f"✅ *To'lov muvaffaqiyatli!*\n\n"
        f"🌸 Tarif: *{t['name']}*\n"
        f"⏱ Limit: *{t['minutes']} daqiqa/oy* ({t['minutes']//60} soat)\n"
        f"💰 To'langan: {sp.total_amount//100:,} {sp.currency}\n\n"
        f"Tarifingiz faollashdi. Endi audio yuborishingiz mumkin 🎙",
        parse_mode="Markdown"
    )
    # Adminga xabar
    if ADMIN_CHAT_ID["id"]:
        u = update.effective_user
        username = f"@{u.username}" if u.username else (u.first_name or "noma'lum")
        try:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID["id"],
                text=(
                    f"💸 *Yangi to'lov keldi!*\n\n"
                    f"👤 Foydalanuvchi: {username}\n"
                    f"🆔 ID: `{target_id}`\n"
                    f"🌸 Tarif: *{t['name']}*\n"
                    f"💰 Miqdor: {sp.total_amount//100:,} {sp.currency}\n"
                    f"🧾 Provider id: `{sp.provider_payment_charge_id}`\n\n"
                    f"Tarif avtomat faollashtirildi."
                ),
                parse_mode="Markdown"
            )
        except Exception as e:
            logging.warning(f"Admin xabari yuborilmadi: {e}")


# ── MANUAL TO'LOV REJIMI: chek + admin tasdiqlash ──────────────────────────

async def paid_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User 'Men to'ladim' tugmasini bossa — botga chek (rasm) yuborishini kutamiz."""
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()
    if not query.data.startswith("paid:"):
        return
    tariff_key = query.data.split(":", 1)[1]
    if tariff_key not in TARIFFS:
        return
    # User holatini saqlaymiz — keyingi photo shu tarif uchun chek deb qabul qilinadi
    # Ikkala joyga ham saqlaymiz: context.user_data (tezkor) va pending_payments (deploy'lardan o'tib qoladi)
    context.user_data["awaiting_payment_for"] = tariff_key
    pending_payments[query.from_user.id] = tariff_key
    _save_user_data()
    t = TARIFFS[tariff_key]
    await query.edit_message_text(
        f"📸 *{t['name']}* uchun chekni shu chatga yuboring (rasm/screenshot).\n\n"
        f"💰 Miqdor: *{t['price']:,} so'm*\n\n"
        f"Chek tasdiqlanganidan keyin tarifingiz avtomat faollashadi.\n"
        f"Odatda 5-30 daqiqa ichida.",
        parse_mode="Markdown"
    )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User chek (rasm) yuborganda — agar to'lov kutilayotgan bo'lsa adminga uzatamiz."""
    user_id = update.effective_user.id if update.effective_user else None
    # Atomik pop — bir vaqtning o'zida ikkita rasm yuborilsa, faqat bittasi qabul qilinadi
    tariff_key = None
    with _save_lock:
        if context.user_data:
            tariff_key = context.user_data.pop("awaiting_payment_for", None)
        if not tariff_key and user_id in pending_payments:
            tariff_key = pending_payments.pop(user_id, None)
    if not tariff_key or tariff_key not in TARIFFS:
        # Boshqa rasm yuborilgan — javob bermaymiz (o'tkazib yuboramiz)
        logging.info(f"📸 Photo (chek emas) user_id={user_id} — pending_payments'da yo'q")
        return
    # State allaqachon olib tashlandi — faylga yozish (deploy'da yo'qolmasligi uchun)
    _save_user_data()
    logging.info(f"📸 Chek qabul qilindi: user_id={user_id}, tariff_key={tariff_key}")

    if not ADMIN_CHAT_ID["id"]:
        await update.message.reply_text(
            "⚠️ Admin tizimi hali sozlanmagan. Iltimos keyinroq urinib ko'ring."
        )
        return

    t = TARIFFS[tariff_key]
    user = update.effective_user
    photo = update.message.photo[-1]  # eng katta o'lchamdagi rasm
    username_raw = f"@{user.username}" if user.username else (user.first_name or "noma'lum")
    # Markdown'da pastki chiziq italic boshlovchi bo'lib qolmasin
    username_safe = username_raw.replace("_", "\\_").replace("*", "\\*")
    tariff_name_safe = t['name'].replace("_", "\\_").replace("*", "\\*")

    caption = (
        f"💸 *Yangi to'lov cheki*\n\n"
        f"👤 Foydalanuvchi: {username_safe}\n"
        f"🆔 ID: `{user.id}`\n"
        f"🌸 Tarif: *{tariff_name_safe}*\n"
        f"⏱ Limit: {t['minutes']} daqiqa/oy\n"
        f"💰 Miqdor: *{t['price']:,} so'm*"
    )
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"approve:{user.id}:{tariff_key}"),
            InlineKeyboardButton("❌ Rad etish",  callback_data=f"reject:{user.id}:{tariff_key}"),
        ]
    ])
    try:
        await context.bot.send_photo(
            chat_id=ADMIN_CHAT_ID["id"],
            photo=photo.file_id,
            caption=caption,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
    except Exception as e:
        logging.error(f"Chekni adminga (Markdown) yuborishda xato: {e}")
        # Fallback: Markdown'siz qayta urinish — har qanday matn xavfsiz
        try:
            plain_caption = (
                f"💸 Yangi to'lov cheki\n\n"
                f"👤 Foydalanuvchi: {username_raw}\n"
                f"🆔 ID: {user.id}\n"
                f"🌸 Tarif: {t['name']}\n"
                f"⏱ Limit: {t['minutes']} daqiqa/oy\n"
                f"💰 Miqdor: {t['price']:,} so'm"
            )
            await context.bot.send_photo(
                chat_id=ADMIN_CHAT_ID["id"],
                photo=photo.file_id,
                caption=plain_caption,
                reply_markup=keyboard,
            )
        except Exception as e2:
            logging.error(f"Chekni adminga (plain) yuborishda xato: {e2}, ADMIN_CHAT_ID={ADMIN_CHAT_ID['id']}")
            # Xato bo'ldi — state'ni qaytaramiz, user qayta urinib ko'rsin
            with _save_lock:
                pending_payments[user_id] = tariff_key
            _save_user_data()
            await update.message.reply_text(
                f"❌ Chekni yuborishda xato. Iltimos keyinroq urinib ko'ring.\n\n"
                f"Texnik ma'lumot: {str(e2)[:100]}"
            )
            return

    await update.message.reply_text(
        "✅ Chek qabul qilindi.\n\n"
        "To'lov tekshirilmoqda. Tasdiqlanganidan keyin tarif avtomat faollashadi.\n"
        "Odatda 5-30 daqiqa ichida xabar olasiz."
    )
    # State allaqachon yuqorida (atomik pop bloki ichida) tozalangan, qayta tozalash shart emas


def _is_admin_callback(query):
    """Callback adminmi tekshirish."""
    user = query.from_user
    if user.username and user.username.lower() in ADMIN_USERNAMES:
        return True
    if ADMIN_CHAT_ID["id"] and user.id == ADMIN_CHAT_ID["id"]:
        return True
    return False


async def approve_reject_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin chek ostidagi 'Tasdiqlash' yoki 'Rad etish' tugmasi."""
    query = update.callback_query
    if not query or not query.data:
        return
    if not _is_admin_callback(query):
        await query.answer("⛔ Faqat admin uchun.", show_alert=True)
        return
    await query.answer()

    parts = query.data.split(":")
    if len(parts) < 3:
        return
    action = parts[0]
    try:
        target_id = int(parts[1])
    except ValueError:
        return
    tariff_key = parts[2]
    if tariff_key not in TARIFFS:
        return
    t = TARIFFS[tariff_key]

    if action == "approve":
        user_tariffs[target_id] = tariff_key
        user_uzbek_usage[target_id] = 0
        _save_user_data()
        # Admin xabar caption'ini yangilash
        try:
            await query.edit_message_caption(
                caption=(query.message.caption or "") + f"\n\n✅ *TASDIQLANDI* — tarif berildi.",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        # Foydalanuvchiga xabar
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=(
                    f"✅ *To'lovingiz tasdiqlandi!*\n\n"
                    f"🌸 Tarif: *{t['name']}*\n"
                    f"⏱ Limit: *{t['minutes']} daqiqa/oy* ({t['minutes']//60} soat)\n\n"
                    f"Tarifingiz faollashdi. Endi audio yuborishingiz mumkin 🎙"
                ),
                parse_mode="Markdown"
            )
        except Exception as e:
            logging.warning(f"Userga ({target_id}) tasdiq xabari yuborilmadi: {e}")
    elif action == "reject":
        try:
            await query.edit_message_caption(
                caption=(query.message.caption or "") + "\n\n❌ *RAD ETILDI*",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=(
                    f"❌ *To'lovingiz tasdiqlanmadi*\n\n"
                    f"Iltimos chekni qayta tekshirib /buy orqali qaytadan urining."
                ),
                parse_mode="Markdown"
            )
        except Exception as e:
            logging.warning(f"Userga ({target_id}) rad xabari yuborilmadi: {e}")


async def grant_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: foydalanuvchiga tarif berish.
    Foydalanish: /grant <user_id> <free|standart|premium|pro>"""
    if not is_admin(update):
        await update.message.reply_text("⛔ Bu buyruq faqat admin uchun.")
        return
    args = (update.message.text or "").split()
    if len(args) < 3:
        await update.message.reply_text(
            "*Foydalanish:*\n"
            "`/grant <user_id> <tarif>`\n\n"
            "*Tariflar:* `free`, `standart`, `premium`, `pro`\n\n"
            "*Misol:*\n"
            "`/grant 123456789 standart`",
            parse_mode="Markdown"
        )
        return
    try:
        target_id = int(args[1])
    except ValueError:
        await update.message.reply_text("❌ user_id raqam bo'lishi kerak.")
        return
    tariff_key = args[2].lower()
    if tariff_key not in TARIFFS:
        await update.message.reply_text(
            f"❌ Tarif `{tariff_key}` mavjud emas.\n\n"
            f"Mavjud: `free`, `standart`, `premium`, `pro`",
            parse_mode="Markdown"
        )
        return
    user_tariffs[target_id] = tariff_key
    # Yangi tarif berilganda ishlatilganlar tiklanadi
    user_uzbek_usage[target_id] = 0
    _save_user_data()
    t = TARIFFS[tariff_key]
    await update.message.reply_text(
        f"✅ *Tarif berildi!*\n\n"
        f"👤 User ID: `{target_id}`\n"
        f"🌸 Tarif: {t['name']}\n"
        f"⏱ Limit: {t['minutes']} daqiqa/oy\n"
        f"💰 Narx: {t['price']:,} so'm\n\n"
        f"Limitlar tiklandi (0 dan boshlanadi).",
        parse_mode="Markdown"
    )
    # Foydalanuvchiga ham xabar yuborish
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=f"🎉 *Tabriklaymiz!*\n\n"
                 f"Sizga yangi tarif berildi: {t['name']}\n"
                 f"⏱ Limit: {t['minutes']} daqiqa/oy\n\n"
                 f"Hisobingizni ko'rish: /balance",
            parse_mode="Markdown"
        )
    except Exception as e:
        logging.warning(f"Userga ({target_id}) tarif xabari yuborilmadi: {e}")


async def debug_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: persistence va saqlash holatini tekshirish."""
    if not is_admin(update):
        await update.message.reply_text("⛔ Bu buyruq faqat admin uchun.")
        return
    # Fayl mavjudligi va o'lchami
    file_exists = os.path.exists(DATA_FILE)
    file_size = os.path.getsize(DATA_FILE) if file_exists else 0
    # Xotirada saqlangan ma'lumotlar
    lines = [
        f"🔧 *Debug — persistence holati*\n",
        f"📁 DATA\\_FILE: `{DATA_FILE}`",
        f"📂 Fayl mavjud: {'✅' if file_exists else '❌'}",
        f"📏 Fayl o'lchami: {file_size} bayt",
        f"",
        f"💾 *Xotirada:*",
        f"• user\\_uzbek\\_usage: {len(user_uzbek_usage)} ta user",
        f"• user\\_tariffs: {len(user_tariffs)} ta user",
        f"• pending\\_payments: {len(pending_payments)} ta user",
        f"• admin\\_chat\\_id: `{ADMIN_CHAT_ID['id']}`",
        f"• runtime\\_settings.payment\\_card: {'sozlangan' if runtime_settings.get('payment_card') else 'yo`q'}",
        f"",
    ]
    # Eng ko'p ishlatgan 5 ta user
    if user_uzbek_usage:
        top = sorted(user_uzbek_usage.items(), key=lambda x: x[1], reverse=True)[:5]
        lines.append("*Eng ko'p ishlatganlar:*")
        for uid, sec in top:
            tariff = TARIFFS.get(user_tariffs.get(uid, "free"), TARIFFS["free"])
            lines.append(f"• `{uid}` — {sec/60:.1f} / {tariff['minutes']} daq ({tariff['name']})")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def setcard_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: /setcard <karta raqami> — karta raqamini sozlash (faylga saqlanadi)."""
    if not is_admin(update):
        await update.message.reply_text("⛔ Bu buyruq faqat admin uchun.")
        return
    args = (update.message.text or "").split(None, 1)
    if len(args) < 2 or not args[1].strip():
        cur = runtime_settings.get("payment_card") or "(sozlanmagan)"
        await update.message.reply_text(
            f"*Foydalanish:*\n"
            f"`/setcard 8600 1234 5678 9012`\n\n"
            f"*Joriy karta:* `{cur}`",
            parse_mode="Markdown"
        )
        return
    card = args[1].strip()
    runtime_settings["payment_card"] = card
    _save_user_data()
    await update.message.reply_text(
        f"✅ Karta raqami saqlandi:\n`{card}`\n\n"
        f"Endi /buy menyusida foydalanuvchilarga shu karta ko'rsatiladi.",
        parse_mode="Markdown"
    )


async def setholder_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: /setholder <ism> — karta egasini sozlash (faylga saqlanadi)."""
    if not is_admin(update):
        await update.message.reply_text("⛔ Bu buyruq faqat admin uchun.")
        return
    args = (update.message.text or "").split(None, 1)
    if len(args) < 2 or not args[1].strip():
        cur = runtime_settings.get("payment_card_holder") or "(sozlanmagan)"
        await update.message.reply_text(
            f"*Foydalanish:*\n"
            f"`/setholder NAZOKAT ARABOVA`\n\n"
            f"*Joriy egasi:* `{cur}`",
            parse_mode="Markdown"
        )
        return
    holder = args[1].strip()
    runtime_settings["payment_card_holder"] = holder
    _save_user_data()
    await update.message.reply_text(
        f"✅ Karta egasi saqlandi: *{holder}*",
        parse_mode="Markdown"
    )


async def lang_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/lang uz | /lang ru | /lang en — chat tilini saqlash."""
    text = (update.message.text or "").strip().split(None, 1)
    code = (text[1].strip().lower() if len(text) > 1 else "")[:2]
    if code not in ("uz", "ru", "en"):
        cur = _chat_lang(context, update)
        await update.message.reply_text(
            f"🌐 Joriy til: *{cur.upper()}*\n\n"
            "Boshqa tilni tanlash uchun:\n"
            "• `/lang uz` — O'zbekcha\n"
            "• `/lang ru` — Русский\n"
            "• `/lang en` — English",
            parse_mode="Markdown",
        )
        return
    try:
        context.chat_data["lang"] = code
    except Exception:
        pass
    names = {"uz": "O'zbekcha 🇺🇿", "ru": "Русский 🇷🇺", "en": "English 🇬🇧"}
    await update.message.reply_text(f"✅ Til o'zgartirildi: *{names[code]}*", parse_mode="Markdown")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    mime = doc.mime_type or ""
    name = doc.file_name or ""
    ext = os.path.splitext(name)[1].lower()
    audio_exts = [".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".wma", ".opus"]
    video_exts = [".mp4", ".avi", ".mov", ".mkv", ".webm", ".3gp"]
    if any(e in mime for e in ["audio", "video"]) or ext in audio_exts + video_exts:
        # === [TARJIMA INTEGRATSIYASI] document audio/video ham tarjima qilinishi mumkin ===
        src_lang = _pop_translation_lang(update.effective_user.id)
        if src_lang:
            await process_translation_from_file_id(update, context, doc.file_id, ext or ".mp3", 0, src_lang)
            return
        # === [/TARJIMA INTEGRATSIYASI] ===
        lang = _chat_lang(context, update)
        await process_file(update, context, doc.file_id, ext or ".mp3", 0, language=lang)
        return
    if ext == ".pdf" or "pdf" in mime:
        await process_pdf_to_voice(update, context, doc.file_id)
        return
    await update.message.reply_text("⚠️ Bu fayl turi qo'llab-quvvatlanmaydi.\n\nQo'llab-quvvatlanadi: audio, video, PDF.")


async def process_pdf_to_voice(update, context, file_id):
    """PDF dan matn ajratib, faqat ovozga aylantirib yuboradi (matn ko'rsatilmaydi).
    Tarif limiti qo'llanadi — natija audio davomiyligi ishlatilgan daqiqaga qo'shiladi."""
    # Adminda har doim True (limit yo'q)
    if not is_admin(update):
        # Foydalanuvchining qoldiq daqiqalari bormi tekshirish
        if not await can_process_uzbek(update, 0):
            return

    msg = await update.message.reply_text("📄 PDF qabul qilindi. Ovozga aylantirilmoqda...")
    tmp_path = None
    tts_path = None
    try:
        file = await context.bot.get_file(file_id)
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name
        await file.download_to_drive(tmp_path)

        text = await asyncio.to_thread(extract_pdf_text, tmp_path)
        if not text or not text.strip():
            await msg.edit_text("❌ PDF dan matn topilmadi (skanlangan rasm bo'lishi mumkin).")
            return

        tts_path = await asyncio.to_thread(make_tts, text)
        if not tts_path:
            await msg.edit_text("❌ Ovoz yaratib bo'lmadi.")
            return

        # Audio davomiyligini aniqlash va limit qayta tekshirish
        actual_duration = 0
        if not is_admin(update):
            try:
                actual_duration = int(await asyncio.to_thread(get_duration_or_estimate, tts_path))
            except Exception:
                actual_duration = 0
            if actual_duration > 0:
                user_id = update.effective_user.id
                used = get_user_usage_sec(user_id)
                limit = get_user_limit_sec(user_id)
                tariff = TARIFFS[get_user_tariff(user_id)]
                if used + actual_duration > limit:
                    rem = max(0, limit - used) / 60
                    await msg.edit_text(
                        f"⚠️ *Bu PDF limitga sig'maydi!*\n\n"
                        f"🌸 Tarif: {tariff['name']}\n"
                        f"📊 Ishlatilgan: {used/60:.1f} / {tariff['minutes']} daqiqa\n"
                        f"⏳ Bu PDF audiosi: {actual_duration/60:.1f} daqiqa\n"
                        f"📉 Qoldiq: {rem:.1f} daqiqa\n\n"
                        f"💎 Yuqori tarif: /tariflar",
                        parse_mode="Markdown"
                    )
                    return

        with open(tts_path, "rb") as f:
            await update.message.reply_voice(voice=f, caption="🔊 PDF ovoz shaklida")
        await msg.edit_text("✅ Tayyor!")

        if not is_admin(update) and actual_duration > 0:
            add_user_usage(update.effective_user.id, actual_duration)
    except Exception as e:
        logging.error(f"PDF -> voice xato: {e}")
        await msg.edit_text(f"❌ Xato: {str(e)[:300]}")
    finally:
        if tts_path and os.path.exists(tts_path):
            try: os.remove(tts_path)
            except Exception: pass
        if tmp_path and os.path.exists(tmp_path):
            try: os.remove(tmp_path)
            except Exception: pass


# === [TARJIMA MODULI — ASOSIY WORKFLOW] =========================================
async def process_translation(update, context, file_path, duration_sec, source_lang):
    """Audio'ni xorijiy tildan O'zbekchaga tarjima qilish.
    Workflow: Whisper STT (verbose_json) → GPT-4o (translation) → matn + PDF.
    Tarif: duration * TRANSLATION_MULTIPLIER (2x) ga sanaydi.
    Original transkripsiya user'ga ko'rsatilmaydi — faqat tarjima."""
    if not is_admin(update):
        cost_seconds = (duration_sec or 60) * TRANSLATION_MULTIPLIER
        if not await can_process_uzbek(update, cost_seconds):
            return

    src_label = TRANSLATION_LANGS.get(source_lang, source_lang)
    msg = await update.message.reply_text(
        f"🌐 *Tarjima jarayoni*\n\n"
        f"📡 Manba til: {src_label}\n"
        f"📝 1/2 — Audio matnga aylantirilmoqda (Whisper)...",
        parse_mode="Markdown"
    )
    try:
        # 1) Davomiylikni aniqlash (limit nazorat va billing uchun)
        actual_duration = duration_sec
        if not actual_duration or actual_duration <= 0:
            try:
                actual_duration = int(await asyncio.to_thread(get_duration_or_estimate, file_path))
            except Exception:
                actual_duration = 60

        # 2) Whisper STT — katta fayl avtomatik bo'laklanadi
        loop = asyncio.get_running_loop()
        last_progress = {"text": "", "ts": 0}
        def whisper_cb(cur, total):
            if total > 1:
                txt = (f"🌐 *Tarjima jarayoni*\n\n"
                       f"📡 Manba til: {src_label}\n"
                       f"⏱ Davomiylik: ~{actual_duration//60} daqiqa\n"
                       f"📝 1/2 — Whisper transkripsiya ({cur}/{total} bo'lak)...")
                now = time.time()
                if txt != last_progress["text"] and now - last_progress["ts"] > 1.5:
                    last_progress["text"] = txt
                    last_progress["ts"] = now
                    asyncio.run_coroutine_threadsafe(msg.edit_text(txt, parse_mode="Markdown"), loop)
        original_text = await asyncio.to_thread(transcribe_whisper, file_path, source_lang, whisper_cb)
        if not original_text or not original_text.strip():
            await msg.edit_text("❌ Audiodan matn topilmadi yoki tan olinmadi.")
            return

        # 3) Claude tarjima — uzun matn avtomatik bo'laklanadi
        word_count = len(original_text.split())
        await msg.edit_text(
            f"🌐 *Tarjima jarayoni*\n\n"
            f"📡 Manba til: {src_label}\n"
            f"📊 Matn: ~{word_count} so'z\n"
            f"✨ 2/2 — GPT tarjima qilmoqda...",
            parse_mode="Markdown"
        )
        last_claude = {"text": "", "ts": 0}
        def claude_cb(cur, total):
            if total > 1:
                txt = (f"🌐 *Tarjima jarayoni*\n\n"
                       f"📡 Manba til: {src_label}\n"
                       f"📊 Matn: ~{word_count} so'z\n"
                       f"✨ 2/2 — GPT tarjima ({cur}/{total} bo'lak)...")
                now = time.time()
                if txt != last_claude["text"] and now - last_claude["ts"] > 1.5:
                    last_claude["text"] = txt
                    last_claude["ts"] = now
                    asyncio.run_coroutine_threadsafe(msg.edit_text(txt, parse_mode="Markdown"), loop)
        translated = await asyncio.to_thread(translate_with_claude, original_text, source_lang, claude_cb)
        if not translated or not translated.strip():
            await msg.edit_text("❌ Tarjima bo'sh qaytdi.")
            return

        # 4) Natija — matn va PDF
        await msg.edit_text("✅ Tarjima tayyor!")
        # Matn (4000 belgidan uzunni bo'lib yuboramiz)
        await update.message.reply_text(
            f"🌐 *Tarjima ({src_label} → 🇺🇿 O'zbek):*",
            parse_mode="Markdown"
        )
        for i in range(0, len(translated), 4000):
            await update.message.reply_text(translated[i:i+4000])
        # PDF — mavjud make_pdf funksiyasidan foydalanamiz
        try:
            pdf_path = await asyncio.to_thread(make_pdf, translated, "Tarjima — O'zbek")
            with open(pdf_path, "rb") as f:
                await update.message.reply_document(
                    document=f, filename="tarjima.pdf",
                    caption="📎 Tarjima PDF formatda"
                )
            try: os.remove(pdf_path)
            except Exception: pass
        except Exception as e:
            logging.warning(f"Tarjima PDF xato: {e}")

        # 5) Tarif daqiqalarini ayrish — 2x koeffitsient bilan
        if not is_admin(update) and actual_duration > 0:
            add_user_usage(update.effective_user.id, actual_duration * TRANSLATION_MULTIPLIER)
    except Exception as e:
        logging.error(f"Tarjima xato: {e}")
        await msg.edit_text(f"❌ Tarjima xato: {str(e)[:300]}")


async def process_translation_from_file_id(update, context, file_id, suffix, duration_sec, source_lang):
    """File_id orqali kelgan audio/video uchun wrapper — yuklab olib process_translation chaqiradi."""
    tmp_path = None
    try:
        file = await context.bot.get_file(file_id)
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp_path = tmp.name
        await file.download_to_drive(tmp_path)
        await process_translation(update, context, tmp_path, duration_sec, source_lang)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try: os.remove(tmp_path)
            except Exception: pass
# === [/TARJIMA MODULI — ASOSIY WORKFLOW] =======================================


async def text_to_voice(update, context, text):
    """Berilgan matnni ovozli MP3 ga aylantirib yuboradi.
    Tarif limiti qo'llanadi — natija audio davomiyligi ishlatilgan daqiqaga qo'shiladi."""
    # Adminda limit yo'q
    if not is_admin(update):
        if not await can_process_uzbek(update, 0):
            return

    msg = await update.message.reply_text("🔊 Matn ovozga aylantirilmoqda...")
    tts_path = None
    try:
        tts_path = await asyncio.to_thread(make_tts, text)
        if not tts_path:
            await msg.edit_text("❌ Matn bo'sh ekan.")
            return

        # Audio davomiyligini aniqlash va limit qayta tekshirish
        actual_duration = 0
        if not is_admin(update):
            try:
                actual_duration = int(await asyncio.to_thread(get_duration_or_estimate, tts_path))
            except Exception:
                actual_duration = 0
            if actual_duration > 0:
                user_id = update.effective_user.id
                used = get_user_usage_sec(user_id)
                limit = get_user_limit_sec(user_id)
                tariff = TARIFFS[get_user_tariff(user_id)]
                if used + actual_duration > limit:
                    rem = max(0, limit - used) / 60
                    await msg.edit_text(
                        f"⚠️ *Bu matn limitga sig'maydi!*\n\n"
                        f"🌸 Tarif: {tariff['name']}\n"
                        f"📊 Ishlatilgan: {used/60:.1f} / {tariff['minutes']} daqiqa\n"
                        f"⏳ Bu ovoz: {actual_duration/60:.1f} daqiqa\n"
                        f"📉 Qoldiq: {rem:.1f} daqiqa\n\n"
                        f"💎 Yuqori tarif: /tariflar",
                        parse_mode="Markdown"
                    )
                    return

        await msg.edit_text("✅ Tayyor!")
        with open(tts_path, "rb") as f:
            await update.message.reply_voice(voice=f, caption="🔊 Matn ovoz shaklida")

        if not is_admin(update) and actual_duration > 0:
            add_user_usage(update.effective_user.id, actual_duration)
    except Exception as e:
        logging.error(f"TTS xato: {e}")
        await msg.edit_text(f"❌ Xato: {str(e)[:300]}")
    finally:
        if tts_path and os.path.exists(tts_path):
            try: os.remove(tts_path)
            except Exception: pass


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    # Admin "Javob yozish" tugmasini bosgan va keyingi matnni yozyapti
    if (context.user_data and context.user_data.get("awaiting_reply_for")
            and is_admin(update)):
        target_id = context.user_data.pop("awaiting_reply_for", None)
        if text == "/cancel":
            await update.message.reply_text("✅ Javob bekor qilindi.")
            return
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=f"💬 *Xizmatdan javob:*\n\n{text}",
                parse_mode="Markdown"
            )
            await update.message.reply_text(
                f"✅ Javob foydalanuvchiga (`{target_id}`) yuborildi.",
                parse_mode="Markdown"
            )
        except Exception as e:
            logging.error(f"reply tugma orqali yuborishda xato: {e}")
            await update.message.reply_text(f"❌ Yuborishda xato: {str(e)[:200]}")
        return
    # Admin oddiy reply (xabarga Reply UI bilan) qilgan bo'lsa — user'ga uzatamiz
    if await handle_admin_reply(update, context):
        return
    # Murojaat rejimi yoqilgan — keyingi text murojaat sifatida ketadi
    if context.user_data and context.user_data.get("awaiting_feedback"):
        # Tugma matnlari yoki /komandalar bekor qilmaydi murojaatni emas
        if text in ("/cancel", "Bekor qilish"):
            context.user_data.pop("awaiting_feedback", None)
            await update.message.reply_text("✅ Murojaat bekor qilindi.")
            return
        # Tugmalarni bosgan bo'lsa ham — murojaat rejimini bekor qilamiz
        if text in ("📊 Balansim", "💎 Tariflar", "💳 Sotib olish", "❓ Yordam",
                    "💬 Murojaat", "🔄 /start", "/start"):
            context.user_data.pop("awaiting_feedback", None)
            # Pastdagi tugma handler'lari ishlasin
        else:
            context.user_data.pop("awaiting_feedback", None)
            await _send_feedback_to_admin(update, context, text)
            return
    # Klaviatura tugmalari uchun yorliqlar
    if text == "📊 Balansim":
        await balance_cmd(update, context)
        return
    if text == "💎 Tariflar":
        await tariflar_cmd(update, context)
        return
    if text == "💳 Sotib olish":
        await buy_cmd(update, context)
        return
    # === [TARJIMA] keyboard tugmasi ===
    if text == "🌐 Tarjima":
        await translate_cmd(update, context)
        return
    if text == "❓ Yordam":
        await help_cmd(update, context)
        return
    if text == "💬 Murojaat":
        # Tugma bosilgan — to'g'ridan-to'g'ri rejimga o'tamiz (komanda parsing'ga kirmasin)
        context.user_data["awaiting_feedback"] = True
        await update.message.reply_text(
            "💬 *Murojaat yozish*\n\n"
            "Endi xabaringizni shu chatga oddiy yozib yuboring.\n"
            "Xizmatga avtomat uzatiladi va javob shu yerga keladi.\n\n"
            "Bekor qilish: /cancel",
            parse_mode="Markdown"
        )
        return
    if text == "🔄 /start" or text == "/start":
        await start(update, context)
        return
    url = extract_url(text)
    if url:
        await process_url(update, context, url, language=_chat_lang(context, update))
        return
    # Uzunroq matn bo'lsa — TTS audioga aylantiriladi
    if len(text) >= 30:
        await text_to_voice(update, context, text)
        return
    await update.message.reply_text(
        "📌 Iltimos quyidagilardan birini yuboring:\n\n"
        "• 🎤 Ovozli xabar / audio / video\n"
        "• 🔗 YouTube / TikTok / Instagram havolasi\n"
        "• 📄 PDF fayl (matn ovozga aylanadi)\n"
        "• 📝 Matn (30+ belgi — ovozga aylanadi)\n\n"
        "Yoki pastdagi tugmalardan birini bosing 👇",
        reply_markup=webapp_keyboard(chat_id=update.effective_user.id),
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchilar uchun yordam — admin'ga to'g'ridan-to'g'ri chiqmaydi."""
    text = (
        "❓ *Yordam*\n\n"
        "🌸 *Bot imkoniyatlari:*\n"
        "• 🎤 Audio / video → matn\n"
        "• 📄 PDF → ovoz (TTS)\n"
        "• 📝 Matn → ovoz (TTS)\n"
        "• 🔗 YouTube / TikTok / Instagram havolasi → matn\n\n"
        "📌 *Buyruqlar:*\n"
        "• 📊 Balansim — qoldiq daqiqalarim\n"
        "• 💎 Tariflar — narxlar ro'yxati\n"
        "• 💳 Sotib olish — tarif olish\n"
        "• 💬 Murojaat — savol/taklif yuborish\n"
        "• /lang uz/ru/en — bot tilini tanlash\n\n"
        "💡 *Murojaat yuborish:*\n"
        "Pastdagi 💬 *Murojaat* tugmasini bosing va xabar yozing — javob shu chatga keladi."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin chatda /feedback xabariga reply qilsa — bot foydalanuvchiga uzatadi.
    Bu yo'l bilan admin user'ga javob yozadi, lekin user adminning username'ini ko'rmaydi."""
    if not is_admin(update):
        return False  # boshqa handler ishlasin
    msg = update.message
    if not msg or not msg.reply_to_message:
        return False
    original = msg.reply_to_message
    original_text = original.text or original.caption or ""
    if "Foydalanuvchi murojaati" not in original_text:
        return False
    # User ID ni asl xabardan ajratib olamiz
    m = re.search(r"ID:\s*`?(\d+)`?", original_text)
    if not m:
        return False
    try:
        target_id = int(m.group(1))
    except ValueError:
        return False
    reply_text = (msg.text or msg.caption or "").strip()
    if not reply_text:
        return False
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=f"💬 *Xizmatdan javob:*\n\n{reply_text}",
            parse_mode="Markdown"
        )
        await msg.reply_text("✅ Javob foydalanuvchiga yuborildi.")
        return True
    except Exception as e:
        logging.error(f"Admin reply forward xato: {e}")
        await msg.reply_text(f"❌ Yuborishda xato: {str(e)[:100]}")
        return True


async def _send_feedback_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, msg_text: str):
    """Foydalanuvchi xabarini adminga avtomat yuboradi. User admin username'ini ko'rmaydi."""
    user = update.effective_user
    user_id = user.id
    username = f"@{user.username}" if user.username else (user.first_name or "noma'lum")
    if not ADMIN_CHAT_ID["id"]:
        await update.message.reply_text("⚠️ Xizmat hozir vaqtinchalik mavjud emas. Iltimos keyinroq urinib ko'ring.")
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Javob yozish", callback_data=f"reply:{user_id}")]
    ])
    try:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID["id"],
            text=(
                f"📩 *Foydalanuvchi murojaati*\n\n"
                f"👤 Kim: {username.replace('_', chr(92)+'_')}\n"
                f"🆔 ID: `{user_id}`\n\n"
                f"💬 Xabar:\n{msg_text}\n\n"
                f"━━━━━━━━━━━━━━\n"
                f"💡 Javob berish uchun pastdagi tugmani bosing 👇"
            ),
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
        await update.message.reply_text(
            "✅ Xabaringiz yuborildi.\nJavob shu chatga keladi (5-30 daqiqada)."
        )
    except Exception as e:
        logging.error(f"feedback yuborishda xato: {e}")
        await update.message.reply_text("❌ Xabar yuborishda xato. Iltimos keyinroq urinib ko'ring.")


async def reply_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin 'Javob yozish' tugmasini bosgan — rejimga o'tib keyingi matnni user'ga uzatamiz."""
    query = update.callback_query
    if not query or not query.data:
        return
    if not _is_admin_callback(query):
        await query.answer("⛔ Faqat admin uchun.", show_alert=True)
        return
    await query.answer()
    if not query.data.startswith("reply:"):
        return
    try:
        target_id = int(query.data.split(":", 1)[1])
    except ValueError:
        return
    context.user_data["awaiting_reply_for"] = target_id
    await context.bot.send_message(
        chat_id=query.from_user.id,
        text=(
            f"💬 *Javob yozing*\n\n"
            f"Foydalanuvchiga (ID: `{target_id}`) javobingizni shu chatga oddiy yozib yuboring.\n"
            f"Bot uni avtomat uzatadi.\n\n"
            f"Bekor qilish: /cancel"
        ),
        parse_mode="Markdown"
    )


async def reply_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: /reply <user_id> <xabar> — foydalanuvchiga javob yuborish.
    User admin'ning username'ini ko'rmaydi, faqat 'Xizmatdan javob' deb keladi."""
    if not is_admin(update):
        await update.message.reply_text("⛔ Bu buyruq faqat admin uchun.")
        return
    args = (update.message.text or "").split(None, 2)
    if len(args) < 3:
        await update.message.reply_text(
            "*Foydalanish:*\n"
            "`/reply <user_id> <xabar matni>`\n\n"
            "*Misol:*\n"
            "`/reply 629686772 Salom! Tarif faollashtirildi.`\n\n"
            "User ID'ni foydalanuvchi murojaatidan oling.",
            parse_mode="Markdown"
        )
        return
    try:
        target_id = int(args[1])
    except ValueError:
        await update.message.reply_text("❌ user_id raqam bo'lishi kerak.")
        return
    msg_text = args[2].strip()
    if not msg_text:
        await update.message.reply_text("❌ Xabar bo'sh bo'lmasligi kerak.")
        return
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=f"💬 *Xizmatdan javob:*\n\n{msg_text}",
            parse_mode="Markdown"
        )
        await update.message.reply_text(f"✅ Javob foydalanuvchiga (`{target_id}`) yuborildi.", parse_mode="Markdown")
    except Exception as e:
        logging.error(f"/reply xato: {e}")
        await update.message.reply_text(f"❌ Yuborishda xato: {str(e)[:200]}")


async def feedback_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User /feedback bossa — keyingi xabarini admin'ga uzatadi (oddiy oqim)."""
    args = (update.message.text or "").split(None, 1)
    if len(args) >= 2 and args[1].strip():
        # Agar /feedback xabar yozilgan bo'lsa, darrov yuboramiz
        await _send_feedback_to_admin(update, context, args[1].strip())
        return
    # Aks holda — "rejimga kiramiz", keyingi text shu user'dan murojaat bo'ladi
    context.user_data["awaiting_feedback"] = True
    await update.message.reply_text(
        "💬 *Murojaat yozish*\n\n"
        "Endi xabaringizni shu chatga oddiy yozib yuboring.\n"
        "Xizmatga avtomat uzatiladi va javob shu yerga keladi.\n\n"
        "Bekor qilish: /cancel",
        parse_mode="Markdown"
    )


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Joriy rejimni bekor qilish (masalan, murojaat yozish)."""
    user_id = update.effective_user.id if update.effective_user else None
    was_translation = False
    # === [TARJIMA] /cancel tarjima rejimini ham bekor qiladi ===
    if user_id and user_id in pending_translations:
        pending_translations.pop(user_id, None)
        _save_user_data()
        was_translation = True
    if context.user_data:
        was_fb = context.user_data.pop("awaiting_feedback", None)
        was_pay = context.user_data.pop("awaiting_payment_for", None)
        if was_fb or was_pay or was_translation:
            await update.message.reply_text("✅ Bekor qilindi.")
            return
    if was_translation:
        await update.message.reply_text("✅ Tarjima rejimi bekor qilindi.")
        return
    await update.message.reply_text("Hech qanday faol rejim yo'q.")


# === [TARJIMA MODULI — KOMANDA HANDLERS] ========================================
async def translate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/tarjima yoki '🌐 Tarjima' tugmasi — manba tilini tanlash menyusini ko'rsatadi."""
    if not OPENAI_API_KEY or not ANTHROPIC_API_KEY:
        await update.message.reply_text(
            "⚙️ Tarjima xizmati hozirda sozlanmoqda. Iltimos keyinroq urinib ko'ring.",
            parse_mode="Markdown"
        )
        return
    buttons = [
        [InlineKeyboardButton(label, callback_data=f"transl:{code}")]
        for code, label in TRANSLATION_LANGS.items()
    ]
    buttons.append([InlineKeyboardButton("❌ Bekor qilish", callback_data="transl:cancel")])
    await update.message.reply_text(
        "🌐 *Xorijiy tildan tarjima*\n\n"
        "Audio yoki videoni xorijiy tildan O'zbek tiliga tarjima qilamiz.\n"
        "Whisper (transkripsiya) + GPT-4o (tarjima).\n\n"
        f"⚠️ *Diqqat:* tarjima xizmati uchun daqiqalar *{TRANSLATION_MULTIPLIER}x* sanaydi "
        f"(masalan 1 daqiqalik audio = {TRANSLATION_MULTIPLIER} daqiqa tarifdan ayriladi).\n\n"
        "Qaysi tildan tarjima qilamiz?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def translation_lang_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manba til tanlangach — keyingi audio/video shu til bilan tarjima qilinadi."""
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()
    if not query.data.startswith("transl:"):
        return
    choice = query.data.split(":", 1)[1]
    user_id = query.from_user.id
    if choice == "cancel":
        pending_translations.pop(user_id, None)
        _save_user_data()
        await query.edit_message_text("❌ Tarjima rejimi bekor qilindi.")
        return
    if choice not in TRANSLATION_LANGS:
        return
    # User holatini saqlaymiz (deploy'larda yo'qolmaydi)
    pending_translations[user_id] = choice
    _save_user_data()
    label = TRANSLATION_LANGS[choice]
    await query.edit_message_text(
        f"✅ {label} tanlandi.\n\n"
        f"📥 Endi audio yoki video yuboring (voice xabar, audio fayl, video).\n"
        f"⚠️ Tarif daqiqalari *{TRANSLATION_MULTIPLIER}x* sanaydi.\n\n"
        f"Bekor qilish uchun: /cancel",
        parse_mode="Markdown"
    )
# === [/TARJIMA MODULI — KOMANDA HANDLERS] =======================================


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


def telegram_send_voice(chat_id, file_path, caption=None):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendVoice"
        with open(file_path, 'rb') as f:
            files = {"voice": ("voice.mp3", f, "audio/mpeg")}
            data = {"chat_id": chat_id}
            if caption:
                data["caption"] = caption
            requests.post(url, data=data, files=files, timeout=120)
    except Exception as e:
        logging.error(f"Telegram voice send error: {e}")


def _send_text_and_pdf(user_id, text):
    """Matn + PDF yuborish (HTTP fallback yo'lida) — audio kontekstida TTS yo'q."""
    telegram_send_message(user_id, f"📝 Matn:\n\n{text}")
    try:
        pdf_path = make_pdf(text)
        try:
            telegram_send_document(user_id, pdf_path, filename="mnsm-matn.pdf", caption="📎 Matn PDF formatda")
        finally:
            if os.path.exists(pdf_path):
                try: os.remove(pdf_path)
                except Exception: pass
    except Exception as e:
        logging.error(f"PDF (HTTP) xato: {e}")


# ── HTTP/THREAD CONTEXT UCHUN LIMIT TEKSHIRUVI ─────────────────────────────
# WebApp orqali yuborilgan fayllar Update obyektisiz thread'da ishlanadi.
# Shu sababli user_id asosida ishlaydigan alohida limit funksiyasi kerak.

def _is_admin_id(user_id):
    """user_id admin chat ID ga teng bo'lsa admin."""
    return ADMIN_CHAT_ID["id"] is not None and user_id == ADMIN_CHAT_ID["id"]


def check_limit_by_user_id(user_id, duration_seconds=0):
    """user_id uchun tarif limitini tekshiradi.
    Returns: (ok: bool) — agar limit oshib ketgan bo'lsa Telegram'ga xabar yuborib False qaytaradi."""
    if _is_admin_id(user_id):
        return True
    used = get_user_usage_sec(user_id)
    limit = get_user_limit_sec(user_id)
    tariff = TARIFFS[get_user_tariff(user_id)]
    if used >= limit:
        telegram_send_message(
            user_id,
            f"⚠️ Limit tugadi!\n\n"
            f"🌸 Tarifingiz: {tariff['name']}\n"
            f"📊 Ishlatilgan: {used/60:.1f} / {tariff['minutes']} daqiqa\n\n"
            f"💎 Tarif sotib olish: /tariflar"
        )
        return False
    if duration_seconds > 0 and used + duration_seconds > limit:
        rem = max(0, limit - used) / 60
        telegram_send_message(
            user_id,
            f"⚠️ Bu fayl limitga sig'maydi!\n\n"
            f"🌸 Tarifingiz: {tariff['name']}\n"
            f"📊 Ishlatilgan: {used/60:.1f} / {tariff['minutes']} daqiqa\n"
            f"⏳ Bu fayl: {duration_seconds/60:.1f} daqiqa\n"
            f"📉 Qoldiq: {rem:.1f} daqiqa\n\n"
            f"💎 Yuqori tarif: /tariflar"
        )
        return False
    return True


def process_pdf_for_user(user_id, pdf_path):
    """PDF dan matn ajratib, faqat audio sifatida qaytaradi (matn ko'rsatilmaydi).
    Tarif limiti qo'llanadi — TTS audio davomiyligi ishlatilgan daqiqaga qo'shiladi."""
    tts_path = None
    try:
        # Limit dastlabki tekshiruvi — qoldiq daqiqalari bormi
        if not check_limit_by_user_id(user_id, 0):
            return

        telegram_send_message(user_id, "📄 PDF qabul qilindi. Ovozga aylantirilmoqda...")
        text = extract_pdf_text(pdf_path)
        if not text or not text.strip():
            telegram_send_message(user_id, "❌ PDF dan matn topilmadi (skanlangan rasm bo'lishi mumkin).")
            return

        tts_path = make_tts(text)
        if not tts_path:
            telegram_send_message(user_id, "❌ Ovoz yaratib bo'lmadi.")
            return

        # Audio davomiyligini aniqlash va limitni qayta tekshirish
        actual_duration = 0
        if not _is_admin_id(user_id):
            try:
                actual_duration = int(get_duration_or_estimate(tts_path))
            except Exception:
                actual_duration = 0
            if not check_limit_by_user_id(user_id, actual_duration):
                return

        telegram_send_voice(user_id, tts_path, caption="🔊 PDF ovoz shaklida")

        if not _is_admin_id(user_id) and actual_duration > 0:
            add_user_usage(user_id, actual_duration)
    except Exception as e:
        logging.error(f"process_pdf_for_user xato: {e}")
        telegram_send_message(user_id, f"❌ Xato: {str(e)[:300]}")
    finally:
        if tts_path and os.path.exists(tts_path):
            try: os.remove(tts_path)
            except Exception: pass
        if pdf_path and os.path.exists(pdf_path):
            try: os.remove(pdf_path)
            except Exception: pass


def process_audio_for_user(user_id, file_path, language="uz"):
    """WebApp orqali yuborilgan audio'ni matnga aylantirish — tarif limiti qo'llanadi."""
    try:
        # Audio davomiyligini avval aniqlaymiz va limitni tekshiramiz
        actual_duration = 0
        if not _is_admin_id(user_id):
            try:
                actual_duration = int(get_duration_or_estimate(file_path))
            except Exception:
                actual_duration = 0
            # Limit (davomiylik bilan)
            if not check_limit_by_user_id(user_id, actual_duration):
                return

        telegram_send_message(user_id, "🎙 Web ilova yuborgan fayl tanilmoqda...")
        text = transcribe(file_path, language=language)
        if text and text.strip() != "Matn aniqlanmadi.":
            _send_text_and_pdf(user_id, text)
        else:
            telegram_send_message(user_id, "Matn aniqlanmadi.")

        if not _is_admin_id(user_id) and actual_duration > 0:
            add_user_usage(user_id, actual_duration)
    except Exception as e:
        logging.error(f"process_audio_for_user xato: {e}")
        telegram_send_message(user_id, f"❌ Xato: {str(e)[:300]}")
    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass


# === [TARJIMA — WEBAPP THREAD MODE] ============================================
def process_translation_for_user(user_id, file_path, source_lang):
    """WebApp orqali yuborilgan audio'ni xorijiy tildan O'zbekchaga tarjima.
    Update obyektisiz, thread-mode. Tarif 2x koeffitsient bilan."""
    try:
        if source_lang not in TRANSLATION_LANGS:
            telegram_send_message(user_id, "❌ Noma'lum manba til.")
            return
        # Davomiylik aniqlash
        try:
            actual_duration = int(get_duration_or_estimate(file_path))
        except Exception:
            actual_duration = 60
        cost = actual_duration * TRANSLATION_MULTIPLIER
        if not _is_admin_id(user_id):
            if not check_limit_by_user_id(user_id, cost):
                return
        src_label = TRANSLATION_LANGS[source_lang]
        telegram_send_message(user_id, f"🌐 Tarjima boshlandi ({src_label})\n⏱ Davomiylik: ~{actual_duration//60} daqiqa\n📝 1/2 — Whisper transkripsiya...")
        # 1) Whisper STT — katta fayl bo'laklanadi
        last_w = {"sent": 0}
        def whisper_progress(cur, total):
            if total > 1 and cur != last_w["sent"]:
                last_w["sent"] = cur
                telegram_send_message(user_id, f"📝 Whisper: {cur}/{total} bo'lak transkripsiya qilindi...")
        original_text = transcribe_whisper(file_path, source_lang, whisper_progress)
        if not original_text or not original_text.strip():
            telegram_send_message(user_id, "❌ Audiodan matn topilmadi.")
            return
        # 2) Claude tarjima — uzun matn bo'laklanadi
        word_count = len(original_text.split())
        telegram_send_message(user_id, f"✨ 2/2 — GPT tarjima qilmoqda... (~{word_count} so'z)")
        last_c = {"sent": 0}
        def claude_progress(cur, total):
            if total > 1 and cur != last_c["sent"]:
                last_c["sent"] = cur
                telegram_send_message(user_id, f"✨ Claude tarjima: {cur}/{total} bo'lak...")
        translated = translate_with_claude(original_text, source_lang, claude_progress)
        if not translated or not translated.strip():
            telegram_send_message(user_id, "❌ Tarjima bo'sh qaytdi.")
            return
        # 3) Natija — matn + PDF
        telegram_send_message(user_id, f"🌐 Tarjima ({src_label} → 🇺🇿 O'zbek):")
        for i in range(0, len(translated), 4000):
            telegram_send_message(user_id, translated[i:i+4000])
        try:
            pdf_path = make_pdf(translated, "Tarjima — O'zbek")
            telegram_send_document(user_id, pdf_path, filename="tarjima.pdf", caption="📎 Tarjima PDF")
            try: os.remove(pdf_path)
            except Exception: pass
        except Exception as e:
            logging.warning(f"Tarjima PDF xato (HTTP): {e}")
        # 4) Tarif daqiqalari (2x)
        if not _is_admin_id(user_id) and actual_duration > 0:
            add_user_usage(user_id, actual_duration * TRANSLATION_MULTIPLIER)
    except Exception as e:
        logging.error(f"process_translation_for_user xato: {e}")
        telegram_send_message(user_id, f"❌ Tarjima xato: {str(e)[:300]}")
    finally:
        if file_path and os.path.exists(file_path):
            try: os.remove(file_path)
            except Exception: pass
# === [/TARJIMA — WEBAPP THREAD MODE] ===========================================


def process_url_for_user(user_id, url, language="uz"):
    """WebApp URL'idan video yuklab matnga aylantirish — tarif limiti qo'llanadi."""
    audio_path = None
    try:
        # Limit dastlabki tekshiruvi (davomiylik hali noma'lum)
        if not check_limit_by_user_id(user_id, 0):
            return

        telegram_send_message(user_id, f"📥 Video yuklanmoqda...\n🔗 {url[:80]}")
        audio_path = download_audio_from_url(url)

        # Yuklab olingach real davomiylikni aniqlaymiz
        actual_duration = 0
        if not _is_admin_id(user_id):
            try:
                actual_duration = int(get_duration_or_estimate(audio_path))
            except Exception:
                actual_duration = 0
            if not check_limit_by_user_id(user_id, actual_duration):
                return

        telegram_send_message(user_id, "✅ Yuklanidi! 🎙 Matn tanilmoqda...")
        text = transcribe(audio_path, language=language)
        if text and text.strip() != "Matn aniqlanmadi.":
            _send_text_and_pdf(user_id, text)
        else:
            telegram_send_message(user_id, "Matn aniqlanmadi.")

        if not _is_admin_id(user_id) and actual_duration > 0:
            add_user_usage(user_id, actual_duration)
    except Exception as e:
        logging.error(f"process_url_for_user xato: {e}")
        telegram_send_message(user_id, f"❌ Xato: {str(e)[:300]}")
    finally:
        if audio_path:
            shutil.rmtree(os.path.dirname(audio_path), ignore_errors=True)


async def handle_webapp_audio(request):
    """WebApp mikrofon yozuvi (base64). === [TARJIMA] translation_lang qo'llab-quvvatlanadi ==="""
    try:
        data = await request.json()
        user_id = data.get("user_id")
        audio_data = data.get("audio", "")
        format_hint = data.get("format", "audio/webm")
        language = (data.get("language") or "uz").lower()
        if language not in ("uz", "ru", "en"):
            language = "uz"
        # === [TARJIMA] manba til (RU/EN/AR) ===
        translation_lang = (data.get("translation_lang") or "").lower()
        if translation_lang and translation_lang not in TRANSLATION_LANGS:
            translation_lang = ""
        if not user_id or not audio_data:
            return web.json_response({"error": "user_id yoki audio yo'q"}, status=400, headers=cors_headers())
        ext = format_hint.split("/")[-1].split(";")[0] if "/" in format_hint else format_hint
        if not ext.startswith('.'):
            ext = '.' + ext
        tmp_path = save_base64_audio(audio_data, ext)
        # === [TARJIMA] Agar translation_lang berilgan bo'lsa, tarjima thread'iga uzatamiz ===
        if translation_lang:
            threading.Thread(target=process_translation_for_user, args=(int(user_id), tmp_path, translation_lang), daemon=True).start()
        else:
            threading.Thread(target=process_audio_for_user, args=(int(user_id), tmp_path, language), daemon=True).start()
        return web.json_response({"status": "ok"}, headers=cors_headers())
    except Exception as e:
        logging.error(f"HTTP audio xatosi: {e}")
        return web.json_response({"error": str(e)}, status=500, headers=cors_headers())


async def handle_webapp_upload(request):
    """WebApp dan fayl yuklash (multipart) — audio/video. === [TARJIMA] translation_lang ==="""
    try:
        reader = await request.multipart()
        user_id = None
        file_data = None
        file_name = None
        language = "uz"
        translation_lang = ""  # === [TARJIMA] ===
        while True:
            part = await reader.next()
            if part is None:
                break
            if part.name == "user_id":
                user_id = (await part.text()).strip()
            elif part.name == "language":
                lang_val = (await part.text()).strip().lower()
                if lang_val in ("uz", "ru", "en"):
                    language = lang_val
            elif part.name == "translation_lang":
                tl = (await part.text()).strip().lower()
                if tl in TRANSLATION_LANGS:
                    translation_lang = tl
            elif part.name == "file":
                file_name = part.filename or "upload.bin"
                file_data = await part.read()
        if not user_id or not file_data:
            return web.json_response({"error": "user_id yoki fayl yo'q"}, status=400, headers=cors_headers())
        ext = os.path.splitext(file_name)[1].lower() or ".bin"
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(file_data)
            tmp_path = tmp.name
        # === [TARJIMA] Agar translation_lang bo'lsa - tarjima rejimi ===
        if translation_lang and ext != ".pdf":
            threading.Thread(target=process_translation_for_user, args=(int(user_id), tmp_path, translation_lang), daemon=True).start()
        elif ext == ".pdf":
            threading.Thread(target=process_pdf_for_user, args=(int(user_id), tmp_path), daemon=True).start()
        else:
            threading.Thread(target=process_audio_for_user, args=(int(user_id), tmp_path, language), daemon=True).start()
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
        language = (data.get("language") or "uz").lower()
        if language not in ("uz", "ru", "en"):
            language = "uz"
        if not user_id or not url:
            return web.json_response({"error": "user_id yoki url yo'q"}, status=400, headers=cors_headers())
        threading.Thread(target=process_url_for_user, args=(int(user_id), url, language), daemon=True).start()
        return web.json_response({"status": "ok"}, headers=cors_headers())
    except Exception as e:
        logging.error(f"HTTP URL xatosi: {e}")
        return web.json_response({"error": str(e)}, status=500, headers=cors_headers())


async def handle_options(request):
    return web.Response(status=204, headers=cors_headers())


async def serve_index(request):
    if not os.path.exists(INDEX_HTML):
        return web.Response(text="index.html topilmadi", status=404)
    return web.FileResponse(INDEX_HTML, headers={
        "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    })


async def serve_static(request):
    """Loyiha katalogidagi xavfsiz statik fayllarni xizmat qilish (logo va h.k.)."""
    name = request.match_info.get('name', '')
    # Faqat oddiy fayl nomi (slash, .., ~ taqiqlangan)
    if not name or '/' in name or '\\' in name or '..' in name or name.startswith('.'):
        return web.Response(status=403)
    allowed_ext = {'.png', '.jpg', '.jpeg', '.webp', '.svg', '.ico', '.gif'}
    if os.path.splitext(name)[1].lower() not in allowed_ext:
        return web.Response(status=403)
    full = os.path.join(HERE, name)
    if not os.path.exists(full) or not os.path.isfile(full):
        return web.Response(status=404)
    return web.FileResponse(full, headers={"Cache-Control": "public, max-age=3600"})


async def run_http_server():
    web_app = web.Application(client_max_size=200 * 1024 * 1024)  # 200 MB
    web_app.router.add_get('/', serve_index)
    web_app.router.add_get('/index.html', serve_index)
    web_app.router.add_get('/static/{name}', serve_static)
    web_app.router.add_get('/{name:[^/]+\\.(png|jpg|jpeg|webp|svg|ico|gif)}', serve_static)
    web_app.router.add_post('/audio', handle_webapp_audio)
    web_app.router.add_post('/upload', handle_webapp_upload)
    web_app.router.add_post('/url', handle_webapp_url_post)
    web_app.router.add_route('OPTIONS', '/{tail:.*}', handle_options)

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', HTTP_PORT)
    await site.start()
    print(f"✅ HTTP server started on port {HTTP_PORT} (0.0.0.0)", flush=True)
    await asyncio.Event().wait()


def run_http_server_thread():
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        print(f"[HTTP] Starting server thread, binding 0.0.0.0:{HTTP_PORT}", flush=True)
        loop.run_until_complete(run_http_server())
    except Exception as e:
        import traceback
        print(f"[HTTP] FATAL: {e}", flush=True)
        traceback.print_exc()


def main():
    global bot_app

    # Saqlangan usage va tariflarni yuklash
    _load_user_data()

    # Admin user ID env'dan o'qib ADMIN_CHAT_ID ga yozamiz (admin /start kutmasdan ishlasin)
    if ADMIN_USER_ID:
        ADMIN_CHAT_ID["id"] = ADMIN_USER_ID
        logging.info(f"👑 Admin chat ID env'dan o'rnatildi: {ADMIN_USER_ID}")

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

    async def _setup_commands(application):
        try:
            await application.bot.set_my_commands([
                BotCommand("start",    "Botni ishga tushirish"),
                BotCommand("balance",  "Mening balansim"),
                BotCommand("tariflar", "Tariflar ro'yxati"),
                BotCommand("buy",      "Tarif sotib olish"),
                BotCommand("tarjima",  "🌐 Xorijiy tildan tarjima"),
                BotCommand("lang",     "Til tanlash: uz / ru / en"),
                BotCommand("feedback", "Murojaat / shikoyat"),
                BotCommand("help",     "Yordam"),
            ])
            await application.bot.set_chat_menu_button()
            try:
                await application.bot.set_my_name("Audio & Konspekt bot")
            except Exception as e:
                logging.warning(f"set_my_name xato (rate-limit bo'lishi mumkin): {e}")
            try:
                await application.bot.set_my_short_description(
                    "🌸 Audio/video → matn va PDF konspekt. PDF → ovozli audio."
                )
            except Exception as e:
                logging.warning(f"set_my_short_description xato: {e}")
            try:
                await application.bot.set_my_description(
                    "🌸 Assalomu alaykum!\n"
                    "Men audio va videolarni matn hamda PDF formatiga aylantiruvchi aqlli botman. "
                    "Darslaringizni yanada osonlashtirish uchun tartibli, chiroyli va tushunarli "
                    "konspektlar tayyorlab beraman.\n\n"
                    "🎧 Shuningdek, PDF hujjatlarni ovozli audio formatga aylantirib, "
                    "ularni istalgan joyda qulay tinglashingizga yordam beraman."
                )
            except Exception as e:
                logging.warning(f"set_my_description xato: {e}")
        except Exception as e:
            logging.error(f"setMyCommands xato: {e}")
    app.post_init = _setup_commands

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("lang", lang_command))
    app.add_handler(CommandHandler("balance", balance_cmd))
    app.add_handler(CommandHandler("tariflar", tariflar_cmd))
    app.add_handler(CommandHandler("buy", buy_cmd))
    app.add_handler(CommandHandler("test", test_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("reset", reset_cmd))
    app.add_handler(CommandHandler("grant", grant_cmd))
    app.add_handler(CommandHandler("setcard", setcard_cmd))
    app.add_handler(CommandHandler("setholder", setholder_cmd))
    app.add_handler(CommandHandler("feedback", feedback_cmd))
    # === [TARJIMA] yangi /tarjima komandasi ===
    app.add_handler(CommandHandler("tarjima", translate_cmd))
    app.add_handler(CommandHandler("translate", translate_cmd))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(CommandHandler("reply", reply_cmd))
    app.add_handler(CommandHandler("debug", debug_cmd))
    app.add_handler(CallbackQueryHandler(buy_callback, pattern=r"^buy:"))

    # Manual to'lov rejimi handlerlari (chek + admin tasdiqlash)
    app.add_handler(CallbackQueryHandler(paid_callback, pattern=r"^paid:"))
    app.add_handler(CallbackQueryHandler(approve_reject_callback, pattern=r"^(approve|reject):"))
    app.add_handler(CallbackQueryHandler(reply_button_callback, pattern=r"^reply:"))
    # === [TARJIMA] callback handler (manba til tanlash) ===
    app.add_handler(CallbackQueryHandler(translation_lang_callback, pattern=r"^transl:"))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    # Telegram Payments handlerlari (kelajakda PROVIDER_TOKEN qo'shilsa avtomat ishlaydi)
    app.add_handler(PreCheckoutQueryHandler(precheckout_handler))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler))

    # Global error handler — barcha qaydqilinmagan xatolarni log + userga xabar
    async def _error_handler(update, context):
        err = context.error
        logging.error(f"Handler xatosi: {err}", exc_info=err)
        try:
            if update and getattr(update, "effective_message", None):
                await update.effective_message.reply_text(
                    f"❌ Xato yuz berdi: {str(err)[:300]}\n\nQayta urinib ko'ring."
                )
        except Exception:
            pass
    app.add_error_handler(_error_handler)
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_web_app_data))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.AUDIO, handle_audio))
    app.add_handler(MessageHandler(filters.VIDEO, handle_video))
    app.add_handler(MessageHandler(filters.VIDEO_NOTE, handle_video_note))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    http_thread = threading.Thread(target=run_http_server_thread, daemon=True)
    http_thread.start()

    print(f"✅ MNSM bot ishga tushdi... (HTTP: {HTTP_PORT}, WebApp: {WEBAPP_URL})")
    app.run_polling()


if __name__ == "__main__":
    main()
