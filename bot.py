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

# TTS voices (Edge TTS — Microsoft, BEPUL)
VOICES = {
    "uz": "uz-UZ-MadinaNeural",
    "ru": "ru-RU-SvetlanaNeural",
    "en": "en-US-JennyNeural",
    "ar": "ar-SA-ZariyahNeural",  # Arabcha (Saudi Arabia, ayollar ovozi)
}

# Tarjima yo'nalishi — manba til avto, hosil til foydalanuvchi tanlaydi
# 'auto' — tarjima qilmaslik (manba tilda qoldirish)
TRANSLATION_TARGETS = {
    "auto": "🌐 Manba tilida (tarjimasiz)",
    "uz": "🇺🇿 O'zbekcha",
    "ru": "🇷🇺 Rus tiliga",
    "en": "🇬🇧 Ingliz tiliga",
    "ar": "🇸🇦 Arab tiliga",
}
TRANSLATION_TARGET_NAMES = {"uz": "O'zbek", "ru": "rus", "en": "ingliz", "ar": "arab", "auto": "asl"}

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

# Tarjima narxi koeffitsienti — boshqa xizmatlar bilan teng (1 daq media = 1 daq tarif)
TRANSLATION_MULTIPLIER = 1

# Tarjima qilinadigan manba tillar (auto — Whisper o'zi aniqlaydi, har qanday til)
TRANSLATION_LANGS = {
    "auto": "🌐 Har qanday til (Avto)",
    "uz": "🇺🇿 O'zbek tilidan",
    "ru": "🇷🇺 Rus tilidan",
    "en": "🇬🇧 Ingliz tilidan",
    "ar": "🇸🇦 Arab tilidan",
}
TRANSLATION_LANG_NAMES = {"uz": "o'zbek", "ru": "rus", "en": "ingliz", "ar": "arab", "auto": "xorijiy"}
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
    "free":     {"name": "🌸 Bepul",    "minutes": 3,   "price": 0},
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
# === [USERS] Admin ko'rishi uchun user info: {user_id: {"username": "@x", "first_name": "Ali", "last_seen": 1234567890}} ===
user_info = {}
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
        # Format: {user_id: {"source": "ru", "target": "uz"}} yoki eski format: "ru"
        for k, v in (data.get("pending_translations") or {}).items():
            try:
                if isinstance(v, dict) and v.get("source") in TRANSLATION_LANGS:
                    pending_translations[int(k)] = v
                elif isinstance(v, str) and v in TRANSLATION_LANGS:
                    # Eski format — backward compat
                    pending_translations[int(k)] = {"source": v, "target": "uz"}
            except (ValueError, TypeError):
                pass
        # === [USERS] user info (username, first_name, last_seen) ===
        for k, v in (data.get("user_info") or {}).items():
            try:
                if isinstance(v, dict):
                    user_info[int(k)] = v
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
                # === [USERS] user_info ham saqlanadi (deploy'larda yo'qolmasligi uchun) ===
                "user_info": {str(k): v for k, v in user_info.items()},
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


def track_user(update):
    """=== [USERS] Foydalanuvchi ma'lumotlarini saqlash (admin keyinroq ko'rishi uchun) ===
    Har handler chaqirilganda chaqiriladi — username, first_name, last_seen yangilanadi."""
    if not update or not getattr(update, "effective_user", None):
        return
    u = update.effective_user
    user_id = u.id
    prev = user_info.get(user_id, {})
    new_info = {
        "username": u.username or "",
        "first_name": u.first_name or "",
        "last_name": u.last_name or "",
        "language_code": u.language_code or "",
        "last_seen": int(time.time()),
        "first_seen": prev.get("first_seen") or int(time.time()),
    }
    # Faqat o'zgargan bo'lsa saqlaymiz (har xabarda yozish optimal emas)
    if (prev.get("username") != new_info["username"] or
        prev.get("first_name") != new_info["first_name"] or
        prev.get("last_name") != new_info["last_name"] or
        not prev.get("first_seen")):
        user_info[user_id] = new_info
        _save_user_data()
    else:
        # last_seen yangilanadi, lekin har safar diskga yozmaymiz (har 10 daqiqada)
        if new_info["last_seen"] - prev.get("last_seen", 0) > 600:
            user_info[user_id] = new_info
            _save_user_data()


def is_admin(update):
    """Foydalanuvchi adminmi tekshiradi (username asosida)."""
    track_user(update)  # === [USERS] Har chaqiruvda user'ni saqlaymiz ===
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
    # Linux (Docker) — DejaVu Sans (o'/g' va kengaytirilgan Unicode'ni qo'llab-quvvatlaydi)
    r"/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    r"/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    # Linux — Noto Sans (Unicode standart)
    r"/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    # Windows fallback
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
    # macOS fallback
    r"/Library/Fonts/Arial.ttf",
]

# Arabcha matn uchun alohida font (DejaVu arabcha qo'llab-quvvatlamasa, Noto Naskh)
ARABIC_FONT_CANDIDATES = [
    r"/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf",
    r"/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
    r"/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # qisman arabcha bor
    r"C:\Windows\Fonts\arial.ttf",
]


def _find_font(candidates=None):
    cands = candidates if candidates is not None else FONT_CANDIDATES
    for p in cands:
        if os.path.exists(p):
            return p
    return None


def _normalize_uzbek_apostrophes(text):
    """O'zbek tilidagi noto'g'ri apostroflarni to'g'rilash:
    `o``, `o'` → `o'` (tipografik); `g`` → `g'`. Bu PDF/matn sifati uchun.
    """
    if not text:
        return text
    replacements = [
        ("o`", "o'"), ("O`", "O'"),
        ("g`", "g'"), ("G`", "G'"),
        ("o´", "o'"), ("O´", "O'"),
        ("g´", "g'"), ("G´", "G'"),
        # ' (asciidan keyin) → ' qoldiramiz, tipograf bo'lsa o'tib ketadi
    ]
    out = text
    for a, b in replacements:
        out = out.replace(a, b)
    return out


def make_pdf(text, title="Audio & Konspekt — Matn"):
    """Matnni PDF qiladi va vaqtinchalik fayl yo'lini qaytaradi.
    DejaVuSans yoki Noto Sans Unicode fontidan foydalanadi —
    o'zbek o'/g', arab yozuvi va boshqa Unicode belgilarini to'g'ri ko'rsatadi."""
    text = _normalize_uzbek_apostrophes(text)
    pdf = FPDF()
    pdf.add_page()
    pdf.set_title(title)

    body_font = _find_font()
    arabic_font = _find_font(ARABIC_FONT_CANDIDATES)

    if body_font:
        pdf.add_font("Body", "", body_font)
        # Agar arabcha font alohida bo'lsa, qo'shib qo'yamiz
        if arabic_font and arabic_font != body_font:
            try:
                pdf.add_font("Arabic", "", arabic_font)
            except Exception:
                pass
        pdf.set_font("Body", size=14)
        pdf.cell(0, 12, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
        pdf.ln(4)
        pdf.set_font("Body", size=11)
    else:
        # Hech qanday Unicode font topilmadi — Helvetica (faqat ASCII)
        # Bu holda o'/g' va arabcha buziladi, lekin hech qaytmaslikdan ko'ra yaxshi
        logging.warning("Unicode font topilmadi (DejaVu/Noto). PDF buzilishi mumkin.")
        pdf.set_font("Helvetica", size=14)
        pdf.cell(0, 12, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
        pdf.ln(4)
        pdf.set_font("Helvetica", size=11)

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


def make_tts_edge(text, lang=None):
    """Matnni Edge TTS (Microsoft, bepul) bilan MP3 ga aylantiradi.
    Uzun matn 3000 belgili bo'laklarga ajratiladi va PARALLEL ishlanadi
    (5-6x tezroq). Bo'laklar MP3 sifatida birlashtiriladi."""
    if not text or not text.strip():
        return None
    if lang is None:
        lang = detect_lang(text)
    voice = VOICES.get(lang, VOICES["uz"])
    snippet = text.strip()
    out_path = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False).name

    # 3000 belgili bo'laklarga ajratish (gap chegaralarida)
    CHUNK_SIZE = 3000
    chunks = []
    if len(snippet) <= CHUNK_SIZE:
        chunks = [snippet]
    else:
        cur = 0
        while cur < len(snippet):
            end = min(cur + CHUNK_SIZE, len(snippet))
            if end < len(snippet):
                for delim in [".", "!", "?", "\n", ","]:
                    idx = snippet.rfind(delim, cur, end)
                    if idx > cur + CHUNK_SIZE // 2:
                        end = idx + 1
                        break
            chunks.append(snippet[cur:end].strip())
            cur = end
        logging.info(f"🔊 Edge TTS: {len(snippet)} belgi → {len(chunks)} bo'lak (PARALLEL)")

    async def _tts_chunk(idx, ch, semaphore):
        """Bitta bo'lakni TTS qiladi va vaqtinchalik fayl yo'lini qaytaradi."""
        async with semaphore:
            chunk_path = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False).name
            try:
                comm = edge_tts.Communicate(ch, voice)
                await asyncio.wait_for(comm.save(chunk_path), timeout=90)
                if os.path.exists(chunk_path) and os.path.getsize(chunk_path) > 0:
                    logging.info(f"   ✅ bo'lak {idx+1}/{len(chunks)} tayyor")
                    return (idx, chunk_path)
            except asyncio.TimeoutError:
                logging.warning(f"   ⏱ bo'lak {idx+1} timeout (90s)")
            except Exception as e:
                logging.warning(f"   ❌ bo'lak {idx+1} xato: {e}")
            try: os.remove(chunk_path)
            except Exception: pass
            return (idx, None)

    async def _run():
        # 4 ta bo'lak parallel (Edge API rate limit hisobi bilan)
        semaphore = asyncio.Semaphore(4)
        tasks = [_tts_chunk(i, ch, semaphore) for i, ch in enumerate(chunks) if ch]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        # Tartibni saqlab birlashtiramiz
        results.sort(key=lambda x: x[0])
        with open(out_path, "wb") as out_f:
            for idx, chunk_path in results:
                if chunk_path and os.path.exists(chunk_path):
                    try:
                        with open(chunk_path, "rb") as in_f:
                            out_f.write(in_f.read())
                    except Exception as e:
                        logging.warning(f"chunk read xato: {e}")
                    try: os.remove(chunk_path)
                    except Exception: pass

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_run())
    finally:
        loop.close()
    if not os.path.exists(out_path) or os.path.getsize(out_path) < 100:
        try: os.remove(out_path)
        except Exception: pass
        return None
    final_size = os.path.getsize(out_path) / 1024
    logging.info(f"🔊 Edge TTS yakuni: {final_size:.0f} KB")
    return out_path


# OpenAI TTS uchun ovozlar (har til uchun mos)
OPENAI_TTS_VOICES = {
    "uz": "nova",      # o'zbek uchun yumshoq ayol ovoz (Edge ham xizmat qiladi)
    "ru": "onyx",      # rus uchun chuqur erkak ovoz
    "en": "alloy",     # ingliz neyutral
    "ar": "shimmer",   # arab uchun yumshoq
}


def _openai_tts_chunk(text_chunk, voice, model="tts-1-hd"):
    """OpenAI TTS bitta bo'lakka so'rov yuboradi (max 4096 belgi)."""
    url = "https://api.openai.com/v1/audio/speech"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "input": text_chunk,
        "voice": voice,
        "response_format": "mp3",
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=300)
    if resp.status_code != 200:
        raise Exception(f"OpenAI TTS xato: HTTP {resp.status_code} — {resp.text[:200]}")
    return resp.content  # MP3 bytes


def make_tts_openai(text, lang=None):
    """Matnni OpenAI TTS (premium tabiiy ovoz) bilan MP3 ga aylantiradi.
    Uzun matn 4000 belgili bo'laklarga bo'linadi va MP3'lar birlashtiriladi.
    Returns: MP3 fayl yo'li yoki None (agar API_KEY yo'q yoki xato)."""
    if not text or not text.strip():
        return None
    if not OPENAI_API_KEY:
        return None
    if lang is None:
        lang = detect_lang(text)
    voice = OPENAI_TTS_VOICES.get(lang, OPENAI_TTS_VOICES["en"])
    snippet = text.strip()

    # 4000 belgili bo'laklarga ajratish (gap chegaralarida)
    CHUNK_SIZE = 4000
    chunks = []
    if len(snippet) <= CHUNK_SIZE:
        chunks = [snippet]
    else:
        cur = 0
        while cur < len(snippet):
            end = min(cur + CHUNK_SIZE, len(snippet))
            # Yaqindagi gap oxirini izlash (. ! ? \n)
            if end < len(snippet):
                for delim in [".", "!", "?", "\n"]:
                    idx = snippet.rfind(delim, cur, end)
                    if idx > cur + CHUNK_SIZE // 2:
                        end = idx + 1
                        break
            chunks.append(snippet[cur:end].strip())
            cur = end

    out_path = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False).name
    try:
        # Har bir bo'lakni TTS qilib, MP3 bytes'larni ketma-ket yozamiz
        with open(out_path, "wb") as out_f:
            for i, ch in enumerate(chunks, 1):
                if not ch:
                    continue
                try:
                    mp3_bytes = _openai_tts_chunk(ch, voice)
                    out_f.write(mp3_bytes)
                except Exception as e:
                    logging.warning(f"OpenAI TTS bo'lak {i}/{len(chunks)} xato: {e}")
                    # Agar 1 ta bo'lak buzilsa, qolganlari hali yozilgan
                    if i == 1:
                        raise  # birinchi bo'lak ham yiqilsa, butun fayl yo'q
        # Tekshiramiz — fayl bo'sh emasmi
        if os.path.getsize(out_path) < 100:
            try: os.remove(out_path)
            except Exception: pass
            return None
        return out_path
    except Exception as e:
        logging.error(f"OpenAI TTS to'liq xato: {e}")
        try: os.remove(out_path)
        except Exception: pass
        return None


def make_tts(text, lang=None, force_engine=None):
    """Matnni ovozli MP3 ga aylantiradi.
    Strategiya (premium sifat):
      • O'zbek (uz) → Edge TTS (Microsoft) — bepul, sifati yaxshi
      • Boshqa tillar (ru/en/ar) → OpenAI TTS (premium, tabiiy ovoz)
      • OpenAI yiqilsa yoki API_KEY yo'q → Edge TTS fallback

    force_engine: 'edge' yoki 'openai' — ixtiyoriy, sinov uchun.
    """
    if not text or not text.strip():
        return None
    if lang is None:
        lang = detect_lang(text)

    # Force override
    if force_engine == "edge":
        return make_tts_edge(text, lang)
    if force_engine == "openai":
        return make_tts_openai(text, lang) or make_tts_edge(text, lang)

    # Default strategiya: chet tilda OpenAI, o'zbekda Edge
    if lang in ("ru", "en", "ar") and OPENAI_API_KEY:
        try:
            path = make_tts_openai(text, lang)
            if path:
                logging.info(f"✅ OpenAI TTS ({lang}) muvaffaqiyatli")
                return path
        except Exception as e:
            logging.warning(f"OpenAI TTS yiqildi ({lang}), Edge fallback: {e}")
    # O'zbek yoki OpenAI yiqilgan holatda — Edge TTS
    return make_tts_edge(text, lang)


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


# === [WHISPER UNIFIED STT] Barcha audio→matn endi Whisper orqali =================
# Muxlisa o'rniga ham, Google STT o'rniga ham Whisper ishlatiladi.
# Sabab: Whisper arzonroq ($0.006/daq), barcha tillarni qo'llab-quvvatlaydi,
# va sifati yuqori. Bitta model bilan ish soddaroq.

def _uzbek_transcription_quality(text):
    """O'zbek transkripsiyaning sifatini 0.0-1.0 oraliqda baholaydi.
    Past ball — sifat past, Muxlisa fallback'ga arziydi.

    Tekshiriladi:
      • Kirill harflari ulushi (uzbek lotin alifbosi — kirill bo'lmasligi kerak)
      • So'roq belgisi `?` ulushi (Whisper biror so'zni o'qiy olmasa shu chiqaradi)
      • Lotin harflari ulushi (juda kam bo'lsa, transkripsiya buzuq)
      • o'/g' apostroflarning normal nisbat
    """
    if not text or len(text) < 20:
        return 0.0  # juda qisqa — ishonchsiz
    total = len(text)
    cyrillic = sum(1 for ch in text if 'Ѐ' <= ch <= 'ӿ' or 'а' <= ch <= 'я' or 'А' <= ch <= 'Я')
    qmarks = text.count('?')
    latin = sum(1 for ch in text if ('a' <= ch <= 'z') or ('A' <= ch <= 'Z'))

    score = 1.0
    # Kirill harflari ko'p bo'lsa, lotin alifbo o'zbekcha buzuq deb hisoblanadi
    if cyrillic / total > 0.20:
        score -= 0.5
    # So'roq belgilari haddan tashqari ko'p bo'lsa
    if qmarks / total > 0.05:
        score -= 0.3
    # Lotin harflari juda kam (matn bo'sh yoki belgilar)
    if latin / total < 0.40:
        score -= 0.3
    return max(0.0, score)


def transcribe_unified(file_path, progress_cb=None, language="uz"):
    """Audio/video'ni matnga aylantirish — Whisper (OpenAI) orqali.

    Muxlisa AI FAQAT 2 ta holatda ishlatiladi (qo'shimcha xarajat oldini olish):
      1) OPENAI_API_KEY yo'q (Whisper umuman ishlamaydi)
      2) Whisper xato qaytaradi yoki BO'SH natija qaytaradi (faqat o'zbek)

    Whisper muvaffaqiyatli ishlasa, sifat past bo'lsa ham Muxlisa CHAQIRILMAYDI —
    chunki bu ikkala API uchun pul yechilishiga olib keladi.
    """
    if not OPENAI_API_KEY:
        logging.warning("OPENAI_API_KEY yo'q, Muxlisa/Google fallback ishlatiladi")
        return transcribe(file_path, progress_cb, language)

    # 1) Asosiy yo'l: Whisper STT
    try:
        whisper_text = transcribe_whisper(file_path, language, None)
    except Exception as e:
        logging.error(f"Whisper xato, Muxlisa fallback (faqat uz uchun): {e}")
        if language == "uz":
            try:
                return transcribe(file_path, progress_cb, language)
            except Exception as me:
                logging.error(f"Muxlisa fallback ham yiqildi: {me}")
                raise e
        else:
            # Boshqa tillar uchun Muxlisa ishlamaydi — Whisper xatosini qaytaramiz
            raise e

    # 2) Whisper bo'sh natija qaytardi va o'zbek bo'lsa — Muxlisa fallback
    if (not whisper_text or not whisper_text.strip()) and language == "uz":
        logging.warning("Whisper bo'sh, Muxlisa fallback (uz)...")
        try:
            muxlisa_text = transcribe(file_path, progress_cb, language)
            if muxlisa_text and muxlisa_text.strip():
                return muxlisa_text
        except Exception as me:
            logging.warning(f"Muxlisa fallback yiqildi: {me}")

    # Whisper natijasini qaytaramiz (sifat past bo'lsa ham — pul tejaymiz)
    return whisper_text or ""
# === [/WHISPER UNIFIED STT] =====================================================


# === [TARJIMA MODULI — API HELPERS] =============================================
# Whisper: max 25 MB per request. 4 soatlik audio uchun bo'laklash kerak.
# Claude: max 8192 output tokens. 30K+ so'zlar uchun bo'laklash kerak.

WHISPER_CHUNK_SECONDS = 600    # 10 daqiqa per chunk (xavfsiz, kichik fayllar)
WHISPER_MAX_FILE_MB = 22        # 22 MB dan oshganda bo'laklash (25 MB Whisper chegarasi - 3 MB margin)
WHISPER_CHUNK_BITRATE = "64k"   # 64 kbps mono — 10 daqiqa ≈ 4.8 MB
CLAUDE_CHUNK_WORDS = 2000       # Claude'ga max 2000 so'zlik bo'lak


def split_audio_for_whisper(file_path, chunk_seconds=WHISPER_CHUNK_SECONDS):
    """Whisper uchun audio'ni bo'laklarga ajratish — SODDA va ISHONCHLI strategiya.

    Qadamlar:
      1) Avval butun audioni 64kbps mono 16kHz MP3 ga qayta kodlash
         (har 1 daqiqa ≈ 0.48 MB)
      2) Yangi fayl <= 22 MB bo'lsa, 1 ta fayl qaytariladi
      3) Aks holda, vaqt bo'yicha 10 daqiqali bo'laklarga ajratamiz
    """
    if not have_cmd("ffmpeg"):
        logging.warning("ffmpeg topilmadi — bo'laklash imkonsiz")
        return [file_path]

    try:
        orig_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    except Exception:
        orig_size_mb = 0

    logging.info(f"🔪 split_audio: orig size={orig_size_mb:.1f}MB")

    # === Qadam 1: butun audioni past bitrate MP3 ga qayta kodlash ===
    tmp_dir = tempfile.mkdtemp(prefix="whisper_recode_")
    recoded_path = os.path.join(tmp_dir, "recoded.mp3")
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-i", file_path,
        "-vn", "-ac", "1", "-ar", "16000",
        "-acodec", "libmp3lame", "-b:a", WHISPER_CHUNK_BITRATE,
        recoded_path
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=900)
    except subprocess.TimeoutExpired:
        logging.error("ffmpeg qayta kodlash timeout (15 daq)")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return [file_path]
    except Exception as e:
        logging.error(f"ffmpeg qayta kodlash xato: {e}")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return [file_path]

    if not os.path.exists(recoded_path) or os.path.getsize(recoded_path) == 0:
        logging.error("Qayta kodlangan fayl bo'sh")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return [file_path]

    new_size_mb = os.path.getsize(recoded_path) / (1024 * 1024)
    logging.info(f"   ✅ qayta kodlangan: {new_size_mb:.1f}MB (orig {orig_size_mb:.1f}MB)")

    # === Qadam 2: yangi fayl Whisper limitidan kichik bo'lsa, bitta fayl ===
    if new_size_mb <= WHISPER_MAX_FILE_MB:
        logging.info("   → 1 ta fayl yetarli")
        return [recoded_path]

    # === Qadam 3: Hali ham katta — vaqt bo'yicha bo'laklash ===
    # Yangi faylning davomiyligi: 64kbps = 8 KB/sec
    duration_sec = int(new_size_mb * 1024 / 8)  # ≈ MB * 128 sec
    logging.info(f"   → katta fayl, vaqt bo'yicha bo'laklash (dur≈{duration_sec}s)")
    return _split_by_time(recoded_path, chunk_seconds, duration_sec)


def _split_by_time(file_path, chunk_seconds, total_dur):
    """Audio'ni vaqt bo'yicha bo'laklarga ajratish (past bitrate bilan).
    Eslatma: file_path AVVAL qayta kodlangan bo'lishi kerak (64kbps mono)."""
    n_chunks = int(total_dur // chunk_seconds) + (1 if total_dur % chunk_seconds > 0 else 0)
    n_chunks = max(1, min(n_chunks, 50))  # max 50 ta bo'lak (xavfsizlik)
    chunks = []
    tmp_dir = tempfile.mkdtemp(prefix="whisper_chunks_")
    logging.info(f"🔪 vaqt bo'yicha bo'laklash: {n_chunks} ta bo'lak")
    for i in range(n_chunks):
        start = i * chunk_seconds
        out_path = os.path.join(tmp_dir, f"chunk_{i:03d}.mp3")
        # Fayl allaqachon kodlangan — copy stream tezroq
        cmd = [
            "ffmpeg", "-y", "-v", "error",
            "-ss", str(start),
            "-i", file_path,
            "-t", str(chunk_seconds),
            "-c", "copy",
            out_path
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=120)
            if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                chunks.append(out_path)
        except Exception as e:
            logging.warning(f"Whisper chunk {i} yaratish xatosi: {e}")
            # Copy ishlamasa, qayta kodlash bilan urinish
            try:
                cmd2 = [
                    "ffmpeg", "-y", "-v", "error",
                    "-ss", str(start),
                    "-i", file_path,
                    "-t", str(chunk_seconds),
                    "-vn", "-ac", "1", "-ar", "16000",
                    "-acodec", "libmp3lame", "-b:a", WHISPER_CHUNK_BITRATE,
                    out_path
                ]
                subprocess.run(cmd2, check=True, capture_output=True, timeout=180)
                if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                    chunks.append(out_path)
            except Exception as e2:
                logging.warning(f"Whisper chunk {i} ikkinchi urinish ham xato: {e2}")
    if not chunks:
        logging.error("Hech qanday bo'lak yaratilmadi — original fayl qaytarildi")
        return [file_path]
    return chunks


def transcribe_whisper(file_path, source_lang, progress_cb=None):
    """OpenAI Whisper API orqali audio'ni matnga aylantirish.
    HAR DOIM avval optimallashtirish (64kbps mono MP3) qilinadi — bu Whisper
    25 MB limitiga moslashish va arzonroq tarmoq trafigi uchun.
    progress_cb(current_chunk, total_chunks) — sync progress callback."""
    if not OPENAI_API_KEY:
        raise Exception("OPENAI_API_KEY sozlanmagan. Railway env qo'shing.")

    try:
        orig_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    except Exception:
        orig_size_mb = 0

    logging.info(f"🎙 Whisper transkripsiya: {file_path} ({orig_size_mb:.1f}MB)")

    # Har doim split_audio_for_whisper chaqiramiz — u qayta kodlash va bo'laklashni hal qiladi
    chunks_to_process = split_audio_for_whisper(file_path, WHISPER_CHUNK_SECONDS)
    chunk_dir_to_cleanup = None
    if chunks_to_process and chunks_to_process[0] != file_path:
        chunk_dir_to_cleanup = os.path.dirname(chunks_to_process[0])
        logging.info(f"   → {len(chunks_to_process)} ta bo'lak tayyor")

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
                    "response_format": "verbose_json",
                }
                # === 'auto' bo'lsa language yuborilmaydi (Whisper o'zi aniqlaydi) ===
                if source_lang and source_lang != "auto":
                    data["language"] = source_lang
                resp = requests.post(url, headers=headers, files=files, data=data, timeout=600)
            if resp.status_code != 200:
                raise Exception(f"Transkripsiya xatosi (bo'lak {idx}/{total}): HTTP {resp.status_code}")
            result = resp.json()
            text = (result.get("text") or "").strip()
            if text:
                results.append(text)
    finally:
        if chunk_dir_to_cleanup:
            try: shutil.rmtree(chunk_dir_to_cleanup, ignore_errors=True)
            except Exception: pass

    return "\n\n".join(results)


def _gpt_translate_one(text, source_lang, target_lang="uz"):
    """Bir bo'lakni OpenAI GPT-4o bilan tarjima qilish — Claude darajasida sifat.
    Diniy darslar uchun maxsus mantiq: Qur'on oyatlari arab tilida qoldiriladi,
    diniy terminlar va shahar nomlari o'zbek ilmiy shaklida yoziladi.

    source_lang: manba til (yoki 'auto' — avto aniqlash)
    target_lang: hosil til ('uz', 'ru', 'en', 'ar')"""
    src_name = TRANSLATION_LANG_NAMES.get(source_lang, source_lang)
    tgt_name = TRANSLATION_TARGET_NAMES.get(target_lang, "O'zbek")
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    # Diniy darslar uchun maxsus yo'riqnoma (target=uz holatida kuchliroq)
    religious_rules_uz = (
        "\n\nMUHIM QOIDALAR (diniy va ilmiy matnlar uchun):\n"
        "1) Qur'on oyatlari (arab tilidagi original matn) — ASLO TARJIMA QILMA. "
        "Ularni asl arab tilida qoldir (يَا أَيُّهَا الَّذِينَ آمَنُوا kabi). "
        "Agar oyat keltirilgan bo'lsa va undan keyin tarjima/sharh kelsa, "
        "faqat sharh qismini tarjima qil.\n"
        "2) Hadis matnlari (arabcha) ham asl shaklida qoldir, faqat sharhlarni tarjima qil.\n"
        "3) Diniy atamalar — o'zbek ilmiy/rasmiy shaklida yoz:\n"
        "   • Allah / Olloh → Alloh\n"
        "   • Muhammed / Muhammad → Muhammad (s.a.v.)\n"
        "   • salavat → salovat / sallallohu alayhi va sallam (s.a.v.)\n"
        "   • Quran / Qur'on → Qur'on\n"
        "   • imom (Imam) → imom\n"
        "   • hadis → hadis\n"
        "   • salat → namoz (kontekstga qarab)\n"
        "   • du'a → duo\n"
        "   • sajda → sajda\n"
        "   • Ka'aba → Ka'ba\n"
        "   • Madina, Makka, Quds, Misr — o'zbekcha rasmiy nomlar bilan\n"
        "4) Sahobalar va olimlar ismlari — o'zbek ilmiy translit:\n"
        "   • Abu Bakr (r.a.), Umar (r.a.), Usmon (r.a.), Ali (r.a.)\n"
        "   • Imom Buxoriy, Imom Muslim, Imom Termiziy, Imom Abu Hanifa\n"
        "5) Arab shahar va joy nomlari — o'zbekcha rasmiy variant ishlatilsin:\n"
        "   • Mecca → Makka, Medina → Madina, Jerusalem → Quds, Cairo → Qohira\n"
        "6) Agar matnda arab harflari (Qur'on yoki hadis) bo'lsa, ularni o'rinda qoldir, "
        "transliteratsiya qilma.\n"
    )

    # Target tilni mukammal aniqlash uchun maxsus, ingliz tilida (GPT uchun aniq) qoidalar
    target_english_name = {
        "uz": "Uzbek (Latin alphabet)",
        "ru": "Russian (Cyrillic alphabet)",
        "en": "English",
        "ar": "Arabic (Arabic script العربية)",
    }
    target_strict_rules = {
        "uz": (
            "CRITICAL: Output MUST be in UZBEK LATIN alphabet (o', g', sh, ch, ng). "
            "NOT Turkish, NOT Uyghur, NOT Kazakh. Use: 'O'zbekiston', 'kishi', "
            "'g'oyat'. NEVER use Turkish characters (ı, ş, ğ, ç, ö, ü)."
        ),
        "ru": "CRITICAL: Output MUST be in Russian (Cyrillic script only).",
        "en": "CRITICAL: Output MUST be in English only.",
        "ar": (
            "CRITICAL: Output MUST be in ARABIC SCRIPT only (العربية). "
            "Do NOT output Latin or Cyrillic. Use proper Modern Standard Arabic. "
            "If input is in another language, you MUST translate ALL of it to Arabic."
        ),
    }
    target_rule = target_strict_rules.get(target_lang, "")
    target_eng = target_english_name.get(target_lang, tgt_name)

    base_system = (
        f"You are a professional translator specializing in religious and academic texts. "
        f"Translate the given text into {target_eng}. "
        f"Use literary, natural style while preserving exact meaning. "
        f"Replace idioms with equivalent expressions in the target language. "
        f"Do NOT translate word-by-word. "
        f"Return ONLY the translation — no explanations, no headers, no introductions.\n\n"
        f"{target_rule}"
    )

    # Diniy qoidalar faqat o'zbek tilga tarjima qilganda kuchli, boshqalarda yumshoq
    if target_lang == "uz":
        system_prompt = base_system + religious_rules_uz
    else:
        system_prompt = (
            base_system +
            "\n\nESLATMA: Agar matnda Qur'on oyatlari (arab tilidagi original) bo'lsa, "
            "ularni tarjima qilma — asl arab tilida qoldir."
        )

    # Ingliz tilida aniq instructions — GPT ularni yaxshiroq tushinadi
    source_english = {
        "auto": "the input language (auto-detect)",
        "uz": "Uzbek",
        "ru": "Russian",
        "en": "English",
        "ar": "Arabic",
    }
    src_eng = source_english.get(source_lang, source_lang)

    if source_lang == "auto":
        user_prompt = (
            f"Translate the following text into {target_eng}.\n"
            f"First detect the source language, then translate ALL of it into {target_eng}.\n"
            f"Preserve religious terms and Arabic Quranic verses in their original form.\n"
            f"Return ONLY the translation:\n\n{text}"
        )
    else:
        user_prompt = (
            f"Translate the following {src_eng} text into {target_eng}.\n"
            f"Translate EVERYTHING — do not leave any words in the source language.\n"
            f"Preserve religious terms and Arabic Quranic verses in their original form.\n"
            f"Return ONLY the translation:\n\n{text}"
        )
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
        raise Exception(f"Tarjima xatosi: HTTP {resp.status_code}")
    data = resp.json()
    choices = data.get("choices", [])
    if not choices:
        raise Exception("GPT bo'sh javob qaytardi.")
    return choices[0].get("message", {}).get("content", "").strip()


def translate_with_claude(text, source_lang, progress_cb=None, target_lang="uz"):
    """Tarjima — OpenAI GPT-4o orqali.
    source_lang: manba til (yoki 'auto')
    target_lang: hosil til ('uz', 'ru', 'en', 'ar')"""
    if not OPENAI_API_KEY:
        raise Exception("OPENAI_API_KEY sozlanmagan. Railway env qo'shing.")

    words = text.split()
    # Kichik matn — bir martada tarjima
    if len(words) <= CLAUDE_CHUNK_WORDS:
        if progress_cb:
            try: progress_cb(1, 1)
            except Exception: pass
        return _gpt_translate_one(text, source_lang, target_lang)

    # Uzun matn — bo'laklarga ajratamiz (so'zlar chegarasida)
    chunks = []
    for i in range(0, len(words), CLAUDE_CHUNK_WORDS):
        chunks.append(" ".join(words[i:i + CLAUDE_CHUNK_WORDS]))
    logging.info(f"🔪 GPT bo'laklash: {len(words)} so'z → {len(chunks)} bo'lak (target: {target_lang})")
    translations = []
    for idx, chunk in enumerate(chunks, 1):
        if progress_cb:
            try: progress_cb(idx, len(chunks))
            except Exception: pass
        try:
            translations.append(_gpt_translate_one(chunk, source_lang, target_lang))
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
        text = await asyncio.to_thread(transcribe_unified, file_path, cb, language)
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
        text = await asyncio.to_thread(transcribe_unified, tmp_path, cb, language)
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
        text = await asyncio.to_thread(transcribe_unified, audio_path, cb, language)
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
            [KeyboardButton(text="💳 Sotib olish"), KeyboardButton(text="❓ Yordam")],
            [KeyboardButton(text="💬 Murojaat"), KeyboardButton(text="🔄 /start")],
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
        "🌸 Assalomu alaykum, 👑*{}*👑!\n\n"
        "Men audio va videolarni matn hamda PDF formatiga aylantiruvchi va "
        "istalgan tildan istalgan tilga yoki o'zbek tiliga tarjima qilib PDF qilib "
        "bera oladigan aqlli botman. Men bilan darslaringizni yanada oson va "
        "tartibli qiling.\n\n"
        "🎧 Shuningdek, PDF hujjatlarni istalgan tilda ovozli audio formatga "
        "aylantirib, ularni istalgan joyda qulay tinglashingizga yordam beraman.\n\n"
        "📌 *Yuborishingiz mumkin:*\n"
        "🌐 Istalgan tildagi:\n"
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
    """=== [TARJIMA] Eski helper — source_lang ni qaytaradi va state'ni o'chiradi. ==="""
    state = _pop_translation_state(user_id)
    if state:
        return state.get("source")
    return None


def _pop_translation_state(user_id):
    """=== [TARJIMA] User tarjima rejimida bo'lsa {source, target} qaytaradi. ===
    Backward compat: agar eski format (string) bo'lsa, target='uz' deb qaytariladi.
    """
    if user_id and user_id in pending_translations:
        val = pending_translations.pop(user_id, None)
        _save_user_data()
        if isinstance(val, dict):
            return val
        if isinstance(val, str):
            return {"source": val, "target": "uz"}
    return None


def _peek_translation_state(user_id):
    """Holatni o'chirmasdan qaytaradi (faqat o'qish)."""
    val = pending_translations.get(user_id)
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        return {"source": val, "target": "uz"}
    return None


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = update.message.voice
    if not v:
        await update.message.reply_text("⚠️ Ovozli xabaringiz topilmadi. Iltimos qayta yuboring.")
        return
    # === [TARJIMA INTEGRATSIYASI] ===
    state = _pop_translation_state(update.effective_user.id)
    if state and state.get("source"):
        await process_translation_from_file_id(
            update, context, v.file_id, ".ogg", v.duration or 0,
            state["source"], state.get("target") or "uz"
        )
        return
    # === [/TARJIMA INTEGRATSIYASI] ===
    lang = _chat_lang(context, update)
    await process_file(update, context, v.file_id, ".ogg", v.duration or 0, language=lang)


async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    a = update.message.audio
    ext = os.path.splitext(a.file_name or "audio.mp3")[1] or ".mp3"
    # === [TARJIMA INTEGRATSIYASI] ===
    state = _pop_translation_state(update.effective_user.id)
    if state and state.get("source"):
        await process_translation_from_file_id(
            update, context, a.file_id, ext, a.duration or 0,
            state["source"], state.get("target") or "uz"
        )
        return
    # === [/TARJIMA INTEGRATSIYASI] ===
    lang = _chat_lang(context, update)
    await process_file(update, context, a.file_id, ext, a.duration or 0, language=lang)


async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = update.message.video
    ext = os.path.splitext(v.file_name or "video.mp4")[1] or ".mp4"
    # === [TARJIMA INTEGRATSIYASI] ===
    state = _pop_translation_state(update.effective_user.id)
    if state and state.get("source"):
        await process_translation_from_file_id(
            update, context, v.file_id, ext, v.duration or 0,
            state["source"], state.get("target") or "uz"
        )
        return
    # === [/TARJIMA INTEGRATSIYASI] ===
    lang = _chat_lang(context, update)
    await process_file(update, context, v.file_id, ext, v.duration or 0, language=lang)


async def handle_video_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = update.message.video_note
    # === [TARJIMA INTEGRATSIYASI] ===
    state = _pop_translation_state(update.effective_user.id)
    if state and state.get("source"):
        await process_translation_from_file_id(
            update, context, v.file_id, ".mp4", v.duration or 0,
            state["source"], state.get("target") or "uz"
        )
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
        # Tarifli userlar uchun "Bekor qilish" tugmalarini tayyorlash
        paid_users_list = [(uid, t) for uid, t in user_tariffs.items() if t != "free"]
        admin_buttons = []
        if paid_users_list:
            admin_buttons.append([InlineKeyboardButton(
                f"👥 Tarifli userlar: {len(paid_users_list)} ta — boshqarish",
                callback_data="adm:paid_users"
            )])
        admin_buttons.append([InlineKeyboardButton("📊 Statistika (top 30)", callback_data="adm:stats")])
        admin_buttons.append([InlineKeyboardButton("💳 Kutilayotgan to'lovlar", callback_data="adm:pending_payments")])
        admin_buttons.append([InlineKeyboardButton("ℹ️ Komandalar ro'yxati", callback_data="adm:help")])
        await update.message.reply_text(
            f"👑 *ADMIN PANEL* — @{admin_uname_md}\n\n"
            f"🧪 Test rejimi: *{test_status}*\n"
            f"👥 Foydalanuvchilar: {total_users}\n"
            f"⏱ Jami O'zbek STT: {total_sec/60:.1f} daqiqa\n"
            f"💰 Jami xarajat: ~{total_cost:,} so'm\n\n"
            f"*Tariflar bo'yicha:*\n{tariff_text}\n\n"
            f"💡 Quyidagi tugmalardan foydalaning:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(admin_buttons),
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


def _user_label(user_id):
    """=== [USERS] Foydalanuvchi nomini chiroyli ko'rsatish ===
    Format: '@username (Ism)' yoki agar username yo'q bo'lsa 'Ism' yoki shunchaki ID."""
    info = user_info.get(user_id) or {}
    uname = info.get("username") or ""
    fname = info.get("first_name") or ""
    lname = info.get("last_name") or ""
    full_name = (fname + " " + lname).strip()
    if uname and full_name:
        return f"@{uname} ({full_name})"
    if uname:
        return f"@{uname}"
    if full_name:
        return full_name
    return f"ID:{user_id}"


async def admin_panel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin uchun tugmali panel — userlarni boshqarish onsonroq.
    /admin yoki /panel komandasi."""
    if not is_admin(update):
        await update.message.reply_text("⛔ Bu buyruq faqat admin uchun.")
        return
    total_users = len(set(list(user_uzbek_usage.keys()) + list(user_info.keys())))
    total_min = sum(user_uzbek_usage.values()) / 60
    paid_users = sum(1 for uid in user_tariffs if user_tariffs.get(uid) != "free")
    buttons = [
        [InlineKeyboardButton("📊 Statistika (top 30)", callback_data="adm:stats")],
        [InlineKeyboardButton("👥 Tarifli userlar (manage)", callback_data="adm:paid_users")],
        [InlineKeyboardButton("💳 Kutilayotgan to'lovlar", callback_data="adm:pending_payments")],
        [InlineKeyboardButton("🔍 User qidirish (ID/username)", callback_data="adm:search_help")],
        [InlineKeyboardButton("ℹ️ Komandalar ro'yxati", callback_data="adm:help")],
    ]
    await update.message.reply_text(
        f"🔐 *Admin Panel*\n\n"
        f"👥 Jami userlar: *{total_users}*\n"
        f"💎 Tarif sotib olgan: *{paid_users}*\n"
        f"⏱ Ishlatilgan: *{total_min:.1f}* daqiqa\n\n"
        f"Quyidan tanlang:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin panel tugmalari uchun callback."""
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()
    if not is_admin(update):
        await query.edit_message_text("⛔ Bu buyruq faqat admin uchun.")
        return
    action = query.data.split(":", 1)[1] if ":" in query.data else ""

    if action == "stats":
        lines = ["📊 *Statistika (top 30 — ishlatish bo'yicha):*\n"]
        all_ids = set(list(user_uzbek_usage.keys()) + list(user_info.keys()))
        data_list = [(uid, user_uzbek_usage.get(uid, 0)) for uid in all_ids]
        data_list.sort(key=lambda x: x[1], reverse=True)
        for uid, sec in data_list[:30]:
            label = _user_label(uid).replace("_", "\\_").replace("*", "\\*").replace("`", "\\`")
            tariff_name = TARIFFS.get(get_user_tariff(uid), TARIFFS["free"])["name"]
            lines.append(f"• {label}\n  `{uid}` — {sec/60:.1f} daq — {tariff_name}")
        back = [[InlineKeyboardButton("⬅️ Orqaga", callback_data="adm:back")]]
        await query.edit_message_text(
            "\n".join(lines) if len(data_list) > 0 else "Hech qanday user yo'q.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(back),
        )
        return

    if action == "paid_users":
        # Tarifli userlar ro'yxati — har biriga "Bekor qilish" tugmasi
        paid_list = [(uid, t) for uid, t in user_tariffs.items() if t != "free"]
        if not paid_list:
            back = [[InlineKeyboardButton("⬅️ Orqaga", callback_data="adm:back")]]
            await query.edit_message_text(
                "💎 Hozircha tarifli user yo'q.",
                reply_markup=InlineKeyboardMarkup(back),
            )
            return
        text_lines = ["💎 *Tarifli userlar* (test uchun bergan bo'lsangiz — bekor qilish tugmasini bosing):\n"]
        buttons = []
        for uid, tkey in paid_list[:20]:
            tariff = TARIFFS.get(tkey, TARIFFS["free"])
            label = _user_label(uid).replace("_", "\\_").replace("*", "\\*").replace("`", "\\`")
            used = user_uzbek_usage.get(uid, 0) / 60
            text_lines.append(
                f"• {label}\n  `{uid}` — {tariff['name']} ({used:.1f}/{tariff['minutes']} daq)"
            )
            buttons.append([InlineKeyboardButton(
                f"❌ {label[:25]} ({tariff['name'][:10]}) bekor",
                callback_data=f"adm_revoke:{uid}"
            )])
        buttons.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="adm:back")])
        await query.edit_message_text(
            "\n".join(text_lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return

    if action == "pending_payments":
        if not pending_payments:
            back = [[InlineKeyboardButton("⬅️ Orqaga", callback_data="adm:back")]]
            await query.edit_message_text(
                "💳 Kutilayotgan to'lov yo'q.",
                reply_markup=InlineKeyboardMarkup(back),
            )
            return
        lines = ["💳 *Kutilayotgan to'lovlar:*\n"]
        for uid, tariff_key in list(pending_payments.items())[:20]:
            label = _user_label(uid).replace("_", "\\_").replace("*", "\\*")
            tname = TARIFFS.get(tariff_key, {}).get("name", tariff_key)
            lines.append(f"• {label} → `{uid}` → *{tname}*")
        back = [[InlineKeyboardButton("⬅️ Orqaga", callback_data="adm:back")]]
        await query.edit_message_text(
            "\n".join(lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(back),
        )
        return

    if action == "search_help":
        back = [[InlineKeyboardButton("⬅️ Orqaga", callback_data="adm:back")]]
        await query.edit_message_text(
            "🔍 *User qidirish*\n\n"
            "Quyidagi komandalardan biri:\n"
            "• `/user 629686772` — ID bo'yicha\n"
            "• `/user @username` — username bo'yicha\n"
            "• `/stats` — barcha userlar ro'yxati\n\n"
            "Manage:\n"
            "• `/grant 629686772 premium` — tarif berish\n"
            "• `/revoke 629686772` — tarif bekor qilish\n"
            "• `/reset 629686772` — daqiqalarni 0 ga tiklash",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(back),
        )
        return

    if action == "help":
        back = [[InlineKeyboardButton("⬅️ Orqaga", callback_data="adm:back")]]
        await query.edit_message_text(
            "📖 *Admin komandalar:*\n\n"
            "*User boshqaruvi:*\n"
            "• `/user <id>` — ma'lumot ko'rish\n"
            "• `/grant <id> <tariff>` — tarif berish\n"
            "• `/revoke <id>` — tarif bekor qilish\n"
            "• `/reset <id>` — daqiqalarni tiklash\n"
            "• `/stats` — top 30 user\n\n"
            "*To'lovlar:*\n"
            "• `/setcard <card>` — to'lov kartasi\n"
            "• `/setholder <name>` — karta egasi\n\n"
            "*Murojaat:*\n"
            "• `/reply <id> <matn>` — userga javob\n\n"
            "*Boshqa:*\n"
            "• `/debug` — debug ma'lumot\n"
            "• `/feedback` — fidbeklar\n"
            "• `/admin` — bu panel",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(back),
        )
        return

    if action == "back":
        # Asosiy panelga qaytish
        total_users = len(set(list(user_uzbek_usage.keys()) + list(user_info.keys())))
        total_min = sum(user_uzbek_usage.values()) / 60
        paid_users = sum(1 for uid in user_tariffs if user_tariffs.get(uid) != "free")
        buttons = [
            [InlineKeyboardButton("📊 Statistika (top 30)", callback_data="adm:stats")],
            [InlineKeyboardButton("👥 Tarifli userlar (manage)", callback_data="adm:paid_users")],
            [InlineKeyboardButton("💳 Kutilayotgan to'lovlar", callback_data="adm:pending_payments")],
            [InlineKeyboardButton("🔍 User qidirish (ID/username)", callback_data="adm:search_help")],
            [InlineKeyboardButton("ℹ️ Komandalar ro'yxati", callback_data="adm:help")],
        ]
        await query.edit_message_text(
            f"🔐 *Admin Panel*\n\n"
            f"👥 Jami userlar: *{total_users}*\n"
            f"💎 Tarif sotib olgan: *{paid_users}*\n"
            f"⏱ Ishlatilgan: *{total_min:.1f}* daqiqa\n\n"
            f"Quyidan tanlang:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return


async def admin_revoke_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin panel orqali user tarifini 1 bosishda bekor qilish."""
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()
    if not is_admin(update):
        await query.edit_message_text("⛔ Bu buyruq faqat admin uchun.")
        return
    try:
        target_id = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await query.edit_message_text("❌ Noto'g'ri user ID.")
        return
    old_tariff = TARIFFS.get(get_user_tariff(target_id), TARIFFS["free"])
    label = _user_label(target_id).replace("_", "\\_").replace("*", "\\*")
    user_tariffs[target_id] = "free"
    user_uzbek_usage[target_id] = 0
    _save_user_data()
    back = [[InlineKeyboardButton("⬅️ Panelga qaytish", callback_data="adm:back")]]
    await query.edit_message_text(
        f"✅ *Tarif bekor qilindi*\n\n"
        f"👤 {label}\n"
        f"🆔 `{target_id}`\n"
        f"❌ Eski: {old_tariff['name']}\n"
        f"🌸 Yangi: Bepul (3 daq)\n"
        f"⏱ Daqiqalar tiklandi: 0",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(back),
    )
    # Userga ham xabar (best-effort)
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=(
                "ℹ️ *Tarifingiz yangilandi*\n\n"
                "Hozir 🌸 Bepul tarifdasiz (3 daqiqa/oy).\n"
                "Yangi tarif olish: /tariflar"
            ),
            parse_mode="Markdown",
        )
    except Exception as e:
        logging.warning(f"User'ga ({target_id}) tarif bekor qilish xabari yetmadi: {e}")


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: barcha userlar statistikasi (username bilan)."""
    if not is_admin(update):
        await update.message.reply_text("⛔ Bu buyruq faqat admin uchun.")
        return
    if not user_uzbek_usage and not user_info:
        await update.message.reply_text("📊 Hozircha foydalanuvchilar bot'ni ishlatmagan.")
        return
    lines = ["📊 *Foydalanuvchi statistikasi:*\n"]
    # Userlarni tarif daqiqalari bo'yicha tartiblash
    all_user_ids = set(list(user_uzbek_usage.keys()) + list(user_info.keys()))
    user_data_list = [(uid, user_uzbek_usage.get(uid, 0)) for uid in all_user_ids]
    user_data_list.sort(key=lambda x: x[1], reverse=True)
    for user_id, sec in user_data_list[:30]:
        label = _user_label(user_id)
        # Markdown'da xavfsiz qilamiz (underscore, asterisk)
        safe_label = label.replace("_", "\\_").replace("*", "\\*").replace("`", "\\`")
        tariff_key = get_user_tariff(user_id)
        tariff_name = TARIFFS.get(tariff_key, TARIFFS["free"])["name"]
        lines.append(f"• {safe_label}\n  `{user_id}` — {sec/60:.1f} daq — {tariff_name}")
    total_sec = sum(user_uzbek_usage.values())
    lines.append(f"\n*Jami:* {len(all_user_ids)} ta user, {total_sec/60:.1f} daqiqa ishlatilgan")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def revoke_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: /revoke <user_id> — foydalanuvchining tarifini bekor qilish.
    Foydalanuvchi Bepul tarifga qaytariladi (3 daqiqa). Test uchun bergan tariflarni qaytarish uchun."""
    if not is_admin(update):
        await update.message.reply_text("⛔ Bu buyruq faqat admin uchun.")
        return
    args = (update.message.text or "").split()
    if len(args) < 2:
        await update.message.reply_text(
            "*Foydalanish:*\n"
            "`/revoke <user_id>`\n\n"
            "Misol: `/revoke 629686772`\n\n"
            "Foydalanuvchi 🌸 Bepul tarifga qaytariladi va daqiqalari 0 ga tiklanadi.",
            parse_mode="Markdown"
        )
        return
    try:
        target_id = int(args[1])
    except ValueError:
        await update.message.reply_text("❌ user_id raqam bo'lishi kerak.")
        return
    old_tariff = TARIFFS.get(get_user_tariff(target_id), TARIFFS["free"])
    label = _user_label(target_id)
    safe_label = label.replace("_", "\\_").replace("*", "\\*")
    # Bepul tarifga qaytarish + daqiqalarni tiklash
    user_tariffs[target_id] = "free"
    user_uzbek_usage[target_id] = 0
    _save_user_data()
    await update.message.reply_text(
        f"✅ *Tarif bekor qilindi*\n\n"
        f"👤 Foydalanuvchi: {safe_label}\n"
        f"🆔 ID: `{target_id}`\n"
        f"❌ Eski tarif: {old_tariff['name']} ({old_tariff['minutes']} daq)\n"
        f"🌸 Yangi tarif: 🌸 Bepul (3 daq)\n"
        f"⏱ Ishlatilgan: 0 daqiqa (tiklandi)",
        parse_mode="Markdown"
    )
    # Foydalanuvchiga ham xabar (ixtiyoriy — yumshoqroq)
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=(
                "ℹ️ *Tarifingiz yangilandi*\n\n"
                "Hozir 🌸 Bepul tarifdasiz (3 daqiqa/oy).\n"
                "Yangi tarif olish uchun: /tariflar"
            ),
            parse_mode="Markdown"
        )
    except Exception as e:
        logging.warning(f"User'ga ({target_id}) tarif bekor qilish xabari yetmadi: {e}")


async def user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: /user <user_id> — foydalanuvchining batafsil ma'lumotini ko'rish."""
    if not is_admin(update):
        await update.message.reply_text("⛔ Bu buyruq faqat admin uchun.")
        return
    args = (update.message.text or "").split()
    if len(args) < 2:
        await update.message.reply_text(
            "*Foydalanish:*\n"
            "`/user <user_id>`\n\n"
            "*Misol:*\n"
            "`/user 629686772`\n\n"
            "Yoki `/stats` orqali barcha foydalanuvchilar ro'yxatini ko'ring.",
            parse_mode="Markdown"
        )
        return
    try:
        target_id = int(args[1])
    except ValueError:
        await update.message.reply_text("❌ user_id raqam bo'lishi kerak.")
        return
    info = user_info.get(target_id) or {}
    if not info and target_id not in user_uzbek_usage:
        await update.message.reply_text(f"❌ `{target_id}` user topilmadi.", parse_mode="Markdown")
        return
    # Ma'lumotlarni yig'ish
    uname = info.get("username") or "(yo'q)"
    fname = info.get("first_name") or "(yo'q)"
    lname = info.get("last_name") or ""
    lang_code = info.get("language_code") or "(yo'q)"
    first_seen = info.get("first_seen", 0)
    last_seen = info.get("last_seen", 0)
    used_sec = user_uzbek_usage.get(target_id, 0)
    tariff_key = get_user_tariff(target_id)
    tariff = TARIFFS.get(tariff_key, TARIFFS["free"])
    full_name = (fname + " " + lname).strip() if lname else fname
    # Vaqtni formatga aylantirish
    import datetime
    fs = datetime.datetime.fromtimestamp(first_seen).strftime("%Y-%m-%d %H:%M") if first_seen else "noma'lum"
    ls = datetime.datetime.fromtimestamp(last_seen).strftime("%Y-%m-%d %H:%M") if last_seen else "noma'lum"
    # Markdown escape
    uname_safe = uname.replace("_", "\\_") if uname != "(yo'q)" else uname
    fname_safe = full_name.replace("_", "\\_").replace("*", "\\*") if full_name else "(yo'q)"
    # Telegram URL (agar username bor bo'lsa)
    profile_url = f"https://t.me/{uname}" if uname not in ("(yo'q)", "") else None
    text = (
        f"👤 *Foydalanuvchi ma'lumoti*\n\n"
        f"🆔 ID: `{target_id}`\n"
        f"👤 Ism: *{fname_safe}*\n"
        f"📛 Username: @{uname_safe}\n"
        f"🌐 Til kodi: {lang_code}\n\n"
        f"🌸 Tarif: *{tariff['name']}* ({tariff['minutes']} daqiqa/oy)\n"
        f"⏱ Ishlatilgan: *{used_sec/60:.1f} daqiqa*\n"
        f"📉 Qoldiq: *{max(0, tariff['minutes']*60 - used_sec)/60:.1f} daqiqa*\n\n"
        f"📅 Birinchi marta: {fs}\n"
        f"🕐 Oxirgi marta: {ls}\n\n"
        f"💡 Tarif berish: `/grant {target_id} <tarif>`\n"
        f"💬 Xabar yuborish: `/reply {target_id} <xabar>`"
    )
    keyboard = None
    if profile_url:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"💬 @{uname} bilan yozish", url=profile_url)]
        ])
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)


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
        state = _pop_translation_state(update.effective_user.id)
        if state and state.get("source"):
            await process_translation_from_file_id(
                update, context, doc.file_id, ext or ".mp3", 0,
                state["source"], state.get("target") or "uz"
            )
            return
        # === [/TARJIMA INTEGRATSIYASI] ===
        lang = _chat_lang(context, update)
        await process_file(update, context, doc.file_id, ext or ".mp3", 0, language=lang)
        return
    if ext == ".pdf" or "pdf" in mime:
        # === [TARJIMA INTEGRATSIYASI] PDF + tarjima rejimi → tarjima qilingan PDF + audio ===
        state = _pop_translation_state(update.effective_user.id)
        if state and state.get("source"):
            await process_pdf_via_translation(
                update, context, doc.file_id,
                state["source"], state.get("target") or "uz"
            )
            return
        # === [/TARJIMA INTEGRATSIYASI] ===
        await process_pdf_to_voice(update, context, doc.file_id)
        return
    await update.message.reply_text("⚠️ Bu fayl turi qo'llab-quvvatlanmaydi.\n\nQo'llab-quvvatlanadi: audio, video, PDF.")


async def process_pdf_via_translation(update, context, file_id, source_lang, target_lang="uz"):
    """Chat'dan kelgan PDF + tarjima rejimi: PDF yuklab olinadi va
    process_pdf_translation_for_user (HTTP yo'l bilan ishlaydigan) chaqiriladi.
    Natija: matn + tarjima PDF + audio (target tilda)."""
    user_id = update.effective_user.id
    if not is_admin(update):
        if not await can_process_uzbek(update, 0):
            return
    await update.message.reply_text(
        f"📄 PDF tarjima rejimida qabul qilindi.\n"
        f"📥 Manba: {TRANSLATION_LANGS.get(source_lang, source_lang)}\n"
        f"🎯 Natija: {TRANSLATION_TARGETS.get(target_lang, target_lang)}\n\n"
        f"⏳ Biroz kuting..."
    )
    tmp_path = None
    try:
        file = await context.bot.get_file(file_id)
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name
        await file.download_to_drive(tmp_path)
        # process_pdf_translation_for_user — sinxron, threadda ishlatamiz
        threading.Thread(
            target=process_pdf_translation_for_user,
            args=(int(user_id), tmp_path, source_lang, target_lang),
            daemon=True,
        ).start()
    except Exception as e:
        logging.error(f"PDF tarjima yuklash xato: {e}")
        await update.message.reply_text(
            f"❌ PDF tayyorlashda xato: {str(e)[:200]}\n\n💚 Daqiqa hisobingizdan yechilmadi."
        )
        if tmp_path and os.path.exists(tmp_path):
            try: os.remove(tmp_path)
            except Exception: pass


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
async def process_translation(update, context, file_path, duration_sec, source_lang, target_lang="uz"):
    """Audio'ni xorijiy tildan tanlangan tilga tarjima qilish.
    Workflow: Whisper STT → GPT-4o tarjima → matn + PDF + audio (TTS) target tilda.
    Tarif: duration * 1x — boshqa xizmatlar bilan teng."""
    if not is_admin(update):
        cost_seconds = (duration_sec or 60) * TRANSLATION_MULTIPLIER
        if not await can_process_uzbek(update, cost_seconds):
            return

    msg = await update.message.reply_text("⏳ Biroz kuting, tarjima qilinmoqda...")
    try:
        # 1) Davomiylikni aniqlash
        actual_duration = duration_sec
        if not actual_duration or actual_duration <= 0:
            try:
                actual_duration = int(await asyncio.to_thread(get_duration_or_estimate, file_path))
            except Exception:
                actual_duration = 60

        # 2) Whisper STT
        original_text = await asyncio.to_thread(transcribe_whisper, file_path, source_lang, None)
        if not original_text or not original_text.strip():
            await msg.edit_text("❌ Audiodan matn topilmadi.")
            return

        # 3) GPT tarjima (target_lang ga) — Avto bo'lsa tarjima qilmaymiz
        if target_lang == "auto":
            translated = original_text  # asl matnda qoldiramiz
            audio_lang = "uz"  # default TTS uchun (manba tilini bilmasak)
        else:
            translated = await asyncio.to_thread(translate_with_claude, original_text, source_lang, None, target_lang)
            audio_lang = target_lang
        if not translated or not translated.strip():
            await msg.edit_text("❌ Tarjima bo'sh qaytdi.")
            return

        # 4) Natija — matn + PDF + audio
        await msg.delete()
        tgt_label = TRANSLATION_TARGETS.get(target_lang, "🇺🇿 O'zbekcha")
        src_label = TRANSLATION_LANGS.get(source_lang, source_lang) if source_lang else "🌐 Avto"
        await update.message.reply_text(
            f"🌐 *Tarjima ({src_label} → {tgt_label}):*",
            parse_mode="Markdown"
        )
        for i in range(0, len(translated), 4000):
            await update.message.reply_text(translated[i:i+4000])
        # PDF
        try:
            pdf_path = await asyncio.to_thread(make_pdf, translated, f"Tarjima — {tgt_label}")
            with open(pdf_path, "rb") as f:
                await update.message.reply_document(
                    document=f, filename=f"tarjima_{target_lang}.pdf",
                    caption=f"📎 Tarjima PDF ({tgt_label})"
                )
            try: os.remove(pdf_path)
            except Exception: pass
        except Exception as e:
            logging.warning(f"Tarjima PDF xato: {e}")

        # 5) Tarif daqiqalari
        if not is_admin(update) and actual_duration > 0:
            add_user_usage(update.effective_user.id, actual_duration * TRANSLATION_MULTIPLIER)
    except Exception as e:
        logging.error(f"Tarjima xato: {e}")
        await msg.edit_text(f"❌ Tarjima xato: {str(e)[:300]}")


async def process_translation_from_file_id(update, context, file_id, suffix, duration_sec, source_lang, target_lang="uz"):
    """File_id orqali kelgan audio/video uchun wrapper."""
    tmp_path = None
    try:
        file = await context.bot.get_file(file_id)
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp_path = tmp.name
        await file.download_to_drive(tmp_path)
        await process_translation(update, context, tmp_path, duration_sec, source_lang, target_lang)
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
    if not OPENAI_API_KEY:
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
        "Audio yoki videoni xorijiy tildan O'zbek tiliga tarjima qilamiz.\n\n"
        f"💡 *Tarif daqiqalari:* tarjima ham boshqa xizmatlar bilan birga umumiy "
        f"daqiqa hisobidan sanaydi (1 daqiqa audio = 1 daqiqa tarifdan).\n\n"
        "Qaysi tildan tarjima qilamiz?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def translation_lang_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """1-bosqich: Manba til tanlangach — 2-bosqich (natija til) menyusi ko'rsatiladi."""
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

    # 1-bosqich tamomlandi — manba til vaqtinchalik saqlanadi, target hali yo'q
    pending_translations[user_id] = {"source": choice, "target": None}
    _save_user_data()
    src_label = TRANSLATION_LANGS[choice]

    # 2-bosqich: Natija tilini tanlash
    target_buttons = [
        [InlineKeyboardButton("🇺🇿 O'zbek tiliga", callback_data="transltgt:uz")],
        [InlineKeyboardButton("🇷🇺 Rus tiliga",    callback_data="transltgt:ru")],
        [InlineKeyboardButton("🇬🇧 Ingliz tiliga", callback_data="transltgt:en")],
        [InlineKeyboardButton("🇸🇦 Arab tiliga",   callback_data="transltgt:ar")],
        [InlineKeyboardButton("❌ Bekor qilish",    callback_data="transltgt:cancel")],
    ]
    await query.edit_message_text(
        f"✅ Manba til: *{src_label}*\n\n"
        f"🎯 *Natija tilini tanlang*\n\n"
        f"Audio/video matni va PDF qaysi tilda chiqsin?\n"
        f"📄 PDF va matn ham shu tilda tayyorlanadi.\n\n"
        f"💡 1 daqiqa audio = 1 daqiqa tarifdan ayriladi.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(target_buttons),
    )


async def translation_target_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """2-bosqich: Natija til tanlangach, user audio/video/PDF yuborishi mumkin."""
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()
    if not query.data.startswith("transltgt:"):
        return
    target = query.data.split(":", 1)[1]
    user_id = query.from_user.id
    if target == "cancel":
        pending_translations.pop(user_id, None)
        _save_user_data()
        await query.edit_message_text("❌ Tarjima rejimi bekor qilindi.")
        return
    if target not in TRANSLATION_TARGETS:
        return

    # 1-bosqichdagi manba tilni o'qiymiz
    state = pending_translations.get(user_id)
    source = None
    if isinstance(state, dict):
        source = state.get("source")
    elif isinstance(state, str):
        source = state
    if not source or source not in TRANSLATION_LANGS:
        await query.edit_message_text(
            "⚠️ Manba til topilmadi. Iltimos /tarjima orqali qaytadan boshlang."
        )
        pending_translations.pop(user_id, None)
        _save_user_data()
        return

    # To'liq state saqlanadi
    pending_translations[user_id] = {"source": source, "target": target}
    _save_user_data()

    src_label = TRANSLATION_LANGS.get(source, source)
    tgt_label = TRANSLATION_TARGETS.get(target, target)
    await query.edit_message_text(
        f"✅ *Tarjima sozlandi*\n\n"
        f"📥 Manba: {src_label}\n"
        f"🎯 Natija: {tgt_label}\n\n"
        f"📤 Endi quyidagilardan birini yuboring:\n"
        f"• 🎤 Ovozli xabar / audio fayl\n"
        f"• 🎬 Video / dumaloq video\n"
        f"• 📄 PDF fayl\n\n"
        f"💡 1 daqiqa = 1 daqiqa tarifdan ayriladi.\n"
        f"Bekor qilish: /cancel",
        parse_mode="Markdown",
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


def telegram_send_chat_action(chat_id, action="typing"):
    """Telegram'da 'bot yozmoqda...' / 'bot audio yubormoqda...' indikatori.
    Mavjud action turlari:
      - typing (xabar yozyapti)
      - upload_voice (audio yubormoqda)
      - record_voice (audio yozmoqda)
      - upload_document (PDF yubormoqda)
    Indikator 5 sek davom etadi, har 4 sek qaytarish kerak."""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendChatAction"
        requests.post(url, data={"chat_id": chat_id, "action": action}, timeout=10)
    except Exception as e:
        logging.debug(f"Telegram chat action xato: {e}")


class ProgressIndicator:
    """Uzoq jarayonlarda Telegram'da indikator ko'rsatadigan context manager.

    Misol:
        with ProgressIndicator(user_id, action="upload_voice"):
            # uzoq audio yaratish
            tts_path = make_tts(text, lang)

    User chat'da "bot audio yubormoqda..." ko'radi va jarayon ishlayotganini biladi.
    """
    def __init__(self, chat_id, action="typing", interval=4):
        self.chat_id = chat_id
        self.action = action
        self.interval = interval
        self._stop = threading.Event()
        self._thread = None

    def _loop(self):
        # Darhol bir marta yuboramiz
        telegram_send_chat_action(self.chat_id, self.action)
        while not self._stop.is_set():
            self._stop.wait(self.interval)
            if self._stop.is_set():
                break
            telegram_send_chat_action(self.chat_id, self.action)

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)

    def set_action(self, new_action):
        """Indikator turini o'zgartirish (jarayon davomida)."""
        self.action = new_action
        telegram_send_chat_action(self.chat_id, self.action)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()


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
    """Voice/audio yuboradi. Katta fayl (> 1 MB) bo'lsa sendAudio orqali yuboriladi
    (sendVoice 1 MB lik chegaraga ega, uzun audio uchun mos emas)."""
    try:
        size_mb = 0
        try:
            size_mb = os.path.getsize(file_path) / (1024 * 1024)
        except Exception:
            pass

        # Katta fayl uchun sendAudio (1 MB dan oshsa)
        if size_mb > 1.0:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendAudio"
            with open(file_path, 'rb') as f:
                files = {"audio": ("audio.mp3", f, "audio/mpeg")}
                data = {"chat_id": chat_id, "title": "Audio"}
                if caption:
                    data["caption"] = caption
                resp = requests.post(url, data=data, files=files, timeout=300)
                if resp.status_code != 200:
                    logging.error(f"Telegram sendAudio xato: {resp.status_code} — {resp.text[:200]}")
                    return False
                return True
        # Kichik fayl uchun sendVoice
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendVoice"
        with open(file_path, 'rb') as f:
            files = {"voice": ("voice.mp3", f, "audio/mpeg")}
            data = {"chat_id": chat_id}
            if caption:
                data["caption"] = caption
            resp = requests.post(url, data=data, files=files, timeout=300)
            if resp.status_code != 200:
                logging.error(f"Telegram sendVoice xato: {resp.status_code} — {resp.text[:200]}")
                return False
        return True
    except Exception as e:
        logging.error(f"Telegram voice/audio send error: {e}")
        return False


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
    """PDF dan matn ajratib, audio sifatida qaytaradi.
    XAVFSIZ TO'LOV: daqiqa faqat audio yuborilgandan keyin yechiladi."""
    tts_path = None
    success = False
    actual_duration = 0
    try:
        # Limit dastlabki tekshiruvi — qoldiq daqiqalari bormi
        if not check_limit_by_user_id(user_id, 0):
            return

        telegram_send_message(user_id, "📄 PDF qabul qilindi. Ovozga aylantirilmoqda...")
        try:
            text = extract_pdf_text(pdf_path)
        except Exception as e:
            logging.error(f"PDF o'qish xato: {e}")
            telegram_send_message(
                user_id,
                f"❌ PDF o'qib bo'lmadi: {str(e)[:200]}\n\n💚 Daqiqa hisobingizdan yechilmadi."
            )
            return
        if not text or not text.strip():
            telegram_send_message(
                user_id,
                "❌ PDF dan matn topilmadi (skanlangan rasm bo'lishi mumkin).\n\n💚 Daqiqa hisobingizdan yechilmadi."
            )
            return

        try:
            tts_path = make_tts(text)
        except Exception as e:
            logging.error(f"PDF TTS xato: {e}")
            telegram_send_message(
                user_id,
                f"❌ Ovoz yaratilmadi: {str(e)[:200]}\n\n💚 Daqiqa hisobingizdan yechilmadi."
            )
            return
        if not tts_path:
            telegram_send_message(
                user_id,
                "❌ Ovoz yaratilmadi.\n\n💚 Daqiqa hisobingizdan yechilmadi."
            )
            return

        # Audio davomiyligini aniqlash va limitni qayta tekshirish
        if not _is_admin_id(user_id):
            try:
                actual_duration = int(get_duration_or_estimate(tts_path))
            except Exception:
                actual_duration = 0
            if not check_limit_by_user_id(user_id, actual_duration):
                return

        telegram_send_voice(user_id, tts_path, caption="🔊 PDF ovoz shaklida")
        success = True

        if success and not _is_admin_id(user_id) and actual_duration > 0:
            add_user_usage(user_id, actual_duration)
    except Exception as e:
        logging.error(f"process_pdf_for_user xato: {e}")
        telegram_send_message(
            user_id,
            f"❌ Xato: {str(e)[:200]}\n\n💚 Daqiqa hisobingizdan yechilmadi."
        )
    finally:
        if tts_path and os.path.exists(tts_path):
            try: os.remove(tts_path)
            except Exception: pass
        if pdf_path and os.path.exists(pdf_path):
            try: os.remove(pdf_path)
            except Exception: pass


def process_audio_for_user(user_id, file_path, language="uz"):
    """WebApp orqali yuborilgan audio'ni matnga aylantirish — tarif limiti qo'llanadi.
    XAVFSIZ TO'LOV: daqiqa faqat muvaffaqiyatli natija yuborilgandan keyin yechiladi."""
    success = False  # natija userga yetkazilganmi
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
        text = transcribe_unified(file_path, language=language)
        if text and text.strip() and text.strip() != "Matn aniqlanmadi.":
            _send_text_and_pdf(user_id, text)
            success = True
        else:
            telegram_send_message(
                user_id,
                "❌ Matn aniqlanmadi. Daqiqa hisobingizdan yechilmadi."
            )

        # Faqat success bo'lsa balansdan yechamiz
        if success and not _is_admin_id(user_id) and actual_duration > 0:
            add_user_usage(user_id, actual_duration)
    except Exception as e:
        logging.error(f"process_audio_for_user xato: {e}")
        telegram_send_message(
            user_id,
            f"❌ Xato yuz berdi: {str(e)[:200]}\n\n"
            f"💚 Daqiqa hisobingizdan yechilmadi."
        )
    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass


# === [TARJIMA — WEBAPP THREAD MODE] ============================================
def process_translation_for_user(user_id, file_path, source_lang, target_lang="uz"):
    """WebApp orqali yuborilgan audio'ni xorijiy tildan tanlangan tilga tarjima.
    Hosil: matn + PDF (audio yo'q).
    XAVFSIZ TO'LOV: daqiqa faqat tarjima muvaffaqiyatli yetkazilgandan keyin yechiladi.
    PROGRESS: Telegram'da 'bot yozmoqda...' indikatori ishlaydi."""
    success = False
    actual_duration = 0
    progress = ProgressIndicator(user_id, action="typing")
    progress.start()
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
        telegram_send_message(user_id, "⏳ Biroz kuting, tarjima qilinmoqda...")
        # 1) Whisper STT
        try:
            original_text = transcribe_whisper(file_path, source_lang, None)
        except Exception as e:
            logging.error(f"Whisper STT xato: {e}")
            telegram_send_message(
                user_id,
                f"❌ Audio matnga aylanmadi: {str(e)[:200]}\n\n"
                f"💚 Daqiqa hisobingizdan yechilmadi."
            )
            return
        if not original_text or not original_text.strip():
            telegram_send_message(
                user_id,
                "❌ Audiodan matn topilmadi.\n\n💚 Daqiqa hisobingizdan yechilmadi."
            )
            return
        # 2) GPT tarjima (target_lang ga) — Avto bo'lsa tarjima qilmaymiz
        if target_lang == "auto":
            translated = original_text
        else:
            try:
                translated = translate_with_claude(original_text, source_lang, None, target_lang)
            except Exception as e:
                logging.error(f"GPT tarjima xato: {e}")
                telegram_send_message(
                    user_id,
                    f"❌ Tarjima xato: {str(e)[:200]}\n\n"
                    f"💚 Daqiqa hisobingizdan yechilmadi."
                )
                return
        if not translated or not translated.strip():
            telegram_send_message(
                user_id,
                "❌ Tarjima bo'sh qaytdi.\n\n💚 Daqiqa hisobingizdan yechilmadi."
            )
            return
        # 3) Natija — matn + PDF
        src_label = TRANSLATION_LANGS.get(source_lang, source_lang)
        tgt_label = TRANSLATION_TARGETS.get(target_lang, "🇺🇿 O'zbekcha")
        telegram_send_message(user_id, f"🌐 Tarjima ({src_label} → {tgt_label}):")
        for i in range(0, len(translated), 4000):
            telegram_send_message(user_id, translated[i:i+4000])
        # PDF (best-effort — agar PDF buzilsa ham matn yetkazilgan, hisoblanadi)
        try:
            pdf_path = make_pdf(translated, f"Tarjima — {tgt_label}")
            telegram_send_document(user_id, pdf_path, filename=f"tarjima_{target_lang}.pdf", caption=f"📎 Tarjima PDF ({tgt_label})")
            try: os.remove(pdf_path)
            except Exception: pass
        except Exception as e:
            logging.warning(f"Tarjima PDF xato (HTTP): {e}")
        success = True  # matn yuborildi — to'lov haqli
        # 4) Tarif daqiqalari — faqat success'da
        if success and not _is_admin_id(user_id) and actual_duration > 0:
            add_user_usage(user_id, actual_duration * TRANSLATION_MULTIPLIER)
    except Exception as e:
        logging.error(f"process_translation_for_user xato: {e}")
        telegram_send_message(
            user_id,
            f"❌ Tarjima xato: {str(e)[:200]}\n\n"
            f"💚 Daqiqa hisobingizdan yechilmadi."
        )
    finally:
        progress.stop()
        if file_path and os.path.exists(file_path):
            try: os.remove(file_path)
            except Exception: pass
# === [/TARJIMA — WEBAPP THREAD MODE] ===========================================


def process_pdf_audio_only(user_id, pdf_path, target_lang="uz"):
    """PDF → AUDIO (faqat audio, matn/PDF tarjimasi yo'q).
    WebApp PDF kartasidan kelganda — user faqat audio xohlaydi.

    Agar manba va target tillari farq qilsa, ichida tarjima qilinadi,
    lekin natija sifatida FAQAT audio MP3 yuboriladi (matn ko'rsatilmaydi).
    XAVFSIZ TO'LOV: audio yetkazilgach yechiladi.
    PROGRESS: Telegram'da 'bot yozmoqda...' indikatori ishlaydi."""
    success = False
    estimated_audio_sec = 0
    progress = ProgressIndicator(user_id, action="typing")
    progress.start()
    try:
        # 1) PDF dan matn ajratish
        try:
            original_text = extract_pdf_text(pdf_path)
        except Exception as e:
            telegram_send_message(
                user_id,
                f"❌ PDF o'qib bo'lmadi: {str(e)[:200]}\n\n💚 Daqiqa hisobingizdan yechilmadi."
            )
            return
        if not original_text or not original_text.strip():
            telegram_send_message(
                user_id,
                "❌ PDF dan matn topilmadi (skanlangan rasm bo'lishi mumkin).\n\n💚 Daqiqa hisobingizdan yechilmadi."
            )
            return

        word_count = len(original_text.split())
        estimated_audio_sec = max(60, int(word_count * 0.4))
        if not _is_admin_id(user_id):
            if not check_limit_by_user_id(user_id, estimated_audio_sec):
                return

        tgt_label = TRANSLATION_TARGETS.get(target_lang, "🇺🇿 O'zbekcha")
        word_count_msg = f"📊 PDF: {word_count} so'z"
        telegram_send_message(user_id, f"⏳ Biroz kuting...\n{word_count_msg}\n🎯 Audio til: {tgt_label}")

        # 2) Matn tilini aniqlash — agar manba va target bir xil bo'lsa, tarjima yo'q
        detected = detect_lang(original_text)
        logging.info(f"📄 PDF audio_only: word_count={word_count}, detected={detected}, target={target_lang}")

        if detected == target_lang or target_lang == "auto":
            # Tarjimaga ehtiyoj yo'q — to'g'ridan-to'g'ri TTS
            tts_text = original_text
            tts_lang = detected if target_lang == "auto" else target_lang
            logging.info("   → tarjimasiz, direct TTS")
        else:
            # Tarjima kerak (ichida bo'ladi, lekin user matn ko'rmaydi)
            telegram_send_message(user_id, f"🔄 Matn {tgt_label} tiliga tarjima qilinmoqda...")
            try:
                logging.info(f"   → GPT tarjima: {detected} → {target_lang}")
                translated = translate_with_claude(original_text, detected, None, target_lang)
                logging.info(f"   ✅ Tarjima tayyor: {len(translated)} belgi")
            except Exception as e:
                logging.error(f"PDF audio uchun tarjima xato: {e}")
                telegram_send_message(
                    user_id,
                    f"❌ Tarjima xato: {str(e)[:200]}\n\n💚 Daqiqa hisobingizdan yechilmadi."
                )
                return
            if not translated or not translated.strip():
                telegram_send_message(
                    user_id,
                    "❌ Tarjima bo'sh qaytdi.\n\n💚 Daqiqa hisobingizdan yechilmadi."
                )
                return
            tts_text = translated
            tts_lang = target_lang

        # 3) Audio yaratish (TTS — target tilda)
        telegram_send_message(user_id, f"🎙 Audio yaratilmoqda ({len(tts_text)} belgi)... bu biroz vaqt olishi mumkin.")
        try:
            logging.info(f"   → TTS boshlandi: {len(tts_text)} belgi, lang={tts_lang}")
            tts_path = make_tts(tts_text, tts_lang)
            logging.info(f"   ✅ TTS tayyor: {tts_path}")
        except Exception as e:
            logging.error(f"PDF audio_only TTS xato: {e}", exc_info=True)
            telegram_send_message(
                user_id,
                f"❌ Audio yaratilmadi: {str(e)[:200]}\n\n💚 Daqiqa hisobingizdan yechilmadi."
            )
            return
        if not tts_path:
            telegram_send_message(
                user_id,
                "❌ Audio yaratilmadi (bo'sh natija).\n\n💚 Daqiqa hisobingizdan yechilmadi."
            )
            return

        # 4) FAQAT audio yuborish (matn yo'q, PDF yo'q)
        logging.info(f"   → Telegram'ga yuborilmoqda...")
        sent = telegram_send_voice(user_id, tts_path, caption=f"🔊 PDF audio ({tgt_label})")
        try: os.remove(tts_path)
        except Exception: pass
        if not sent:
            telegram_send_message(
                user_id,
                "❌ Audio Telegram'ga yuborilmadi.\n\n💚 Daqiqa hisobingizdan yechilmadi."
            )
            return
        success = True
        logging.info("✅ PDF audio_only muvaffaqiyatli yakunlandi")

        # 5) Tarif daqiqalari — faqat success'da
        if success and not _is_admin_id(user_id) and estimated_audio_sec > 0:
            add_user_usage(user_id, estimated_audio_sec)
    except Exception as e:
        logging.error(f"process_pdf_audio_only xato: {e}")
        telegram_send_message(
            user_id,
            f"❌ Xato: {str(e)[:200]}\n\n💚 Daqiqa hisobingizdan yechilmadi."
        )
    finally:
        progress.stop()  # Indikatorni o'chirish
        if pdf_path and os.path.exists(pdf_path):
            try: os.remove(pdf_path)
            except Exception: pass


def process_pdf_translation_for_user(user_id, pdf_path, source_lang="auto", target_lang="uz"):
    """PDF'ni xorijiy tildan tanlangan tilga tarjima qilib audio + PDF chiqarish.
    XAVFSIZ TO'LOV: faqat audio MUVAFFAQIYATLI yuborilgandan keyin daqiqa yechiladi.
    PROGRESS: Telegram'da 'bot yozmoqda...' indikatori ishlaydi."""
    success = False
    estimated_audio_sec = 0
    progress = ProgressIndicator(user_id, action="typing")
    progress.start()
    try:
        # 1) PDF dan matn ajratish
        try:
            original_text = extract_pdf_text(pdf_path)
        except Exception as e:
            telegram_send_message(
                user_id,
                f"❌ PDF o'qib bo'lmadi: {str(e)[:200]}\n\n💚 Daqiqa hisobingizdan yechilmadi."
            )
            return
        if not original_text or not original_text.strip():
            telegram_send_message(
                user_id,
                "❌ PDF dan matn topilmadi (skanlangan rasm bo'lishi mumkin).\n\n💚 Daqiqa hisobingizdan yechilmadi."
            )
            return
        # 2) PDF uzunligi (so'z) tarif uchun — taxminiy 1 so'z = 0.4 sek audio
        word_count = len(original_text.split())
        estimated_audio_sec = max(60, int(word_count * 0.4))  # kamida 1 daqiqa
        if not _is_admin_id(user_id):
            if not check_limit_by_user_id(user_id, estimated_audio_sec):
                return
        telegram_send_message(user_id, "⏳ Biroz kuting, PDF tarjima qilinmoqda...")
        # 3) GPT tarjima (agar source != target bo'lsa)
        try:
            if source_lang and source_lang != target_lang and source_lang != "":
                translated = translate_with_claude(original_text, source_lang, None, target_lang)
            else:
                translated = translate_with_claude(original_text, "auto", None, target_lang)
        except Exception as e:
            logging.error(f"PDF GPT tarjima xato: {e}")
            telegram_send_message(
                user_id,
                f"❌ Tarjima xato: {str(e)[:200]}\n\n💚 Daqiqa hisobingizdan yechilmadi."
            )
            return
        if not translated or not translated.strip():
            telegram_send_message(
                user_id,
                "❌ Tarjima bo'sh qaytdi.\n\n💚 Daqiqa hisobingizdan yechilmadi."
            )
            return
        # 4) Natija — matn + PDF + audio (target tilda)
        tgt_label = TRANSLATION_TARGETS.get(target_lang, "🇺🇿 O'zbekcha")
        telegram_send_message(user_id, f"🌐 PDF tarjima ({tgt_label}):")
        for i in range(0, len(translated), 4000):
            telegram_send_message(user_id, translated[i:i+4000])
        # PDF (best-effort)
        try:
            pdf_out = make_pdf(translated, f"Tarjima — {tgt_label}")
            telegram_send_document(user_id, pdf_out, filename=f"tarjima_pdf_{target_lang}.pdf", caption=f"📎 Tarjima PDF ({tgt_label})")
            try: os.remove(pdf_out)
            except Exception: pass
        except Exception as e:
            logging.warning(f"PDF tarjima PDF yaratishda xato: {e}")
        # 5) Audio (TTS target tilda) — bu asosiy natija, success bunga bog'liq
        try:
            tts_path = make_tts(translated, target_lang)
            if tts_path:
                telegram_send_voice(user_id, tts_path, caption=f"🔊 Audio versiya ({tgt_label})")
                try: os.remove(tts_path)
                except Exception: pass
                success = True
            else:
                telegram_send_message(
                    user_id,
                    "⚠️ Audio yaratilmadi, lekin matn va PDF yetkazildi.\n💚 Daqiqa hisobingizdan yechilmadi."
                )
        except Exception as e:
            logging.warning(f"PDF tarjima TTS xato: {e}")
            telegram_send_message(
                user_id,
                f"⚠️ Audio yaratilmadi: {str(e)[:150]}\n💚 Daqiqa hisobingizdan yechilmadi."
            )
        # 6) Tarif daqiqalari — faqat audio yetkazilgan bo'lsa
        if success and not _is_admin_id(user_id) and estimated_audio_sec > 0:
            add_user_usage(user_id, estimated_audio_sec)
    except Exception as e:
        logging.error(f"process_pdf_translation_for_user xato: {e}")
        telegram_send_message(
            user_id,
            f"❌ PDF tarjima xato: {str(e)[:200]}\n\n💚 Daqiqa hisobingizdan yechilmadi."
        )
    finally:
        progress.stop()
        if pdf_path and os.path.exists(pdf_path):
            try: os.remove(pdf_path)
            except Exception: pass


def process_url_translation_for_user(user_id, url, source_lang, target_lang="uz"):
    """URL'dan video yuklab xorijiy tildan tanlangan tilga tarjima — matn + PDF.
    XAVFSIZ TO'LOV: faqat matn yetkazilgandan keyin daqiqa yechiladi.
    PROGRESS: Telegram'da 'bot yozmoqda...' indikatori ishlaydi."""
    audio_path = None
    success = False
    actual_duration = 0
    progress = ProgressIndicator(user_id, action="typing")
    progress.start()
    try:
        if source_lang not in TRANSLATION_LANGS:
            telegram_send_message(user_id, "❌ Noma'lum manba til.")
            return
        # Limit dastlabki tekshiruvi
        if not check_limit_by_user_id(user_id, 0):
            return
        telegram_send_message(user_id, "⏳ Biroz kuting, tarjima qilinmoqda...")
        # 1) Video yuklab olish
        try:
            audio_path = download_audio_from_url(url)
        except Exception as e:
            logging.error(f"URL yuklab olish xato: {e}")
            telegram_send_message(
                user_id,
                f"❌ Video yuklanmadi: {str(e)[:200]}\n\n💚 Daqiqa hisobingizdan yechilmadi."
            )
            return
        # 2) Davomiylik va limit tekshiruvi
        try:
            actual_duration = int(get_duration_or_estimate(audio_path))
        except Exception:
            actual_duration = 60
        cost = actual_duration * TRANSLATION_MULTIPLIER
        if not _is_admin_id(user_id):
            if not check_limit_by_user_id(user_id, cost):
                return
        # 3) Whisper STT
        try:
            original_text = transcribe_whisper(audio_path, source_lang, None)
        except Exception as e:
            logging.error(f"URL Whisper STT xato: {e}")
            telegram_send_message(
                user_id,
                f"❌ Audio matnga aylanmadi: {str(e)[:200]}\n\n💚 Daqiqa hisobingizdan yechilmadi."
            )
            return
        if not original_text or not original_text.strip():
            telegram_send_message(
                user_id,
                "❌ Audiodan matn topilmadi.\n\n💚 Daqiqa hisobingizdan yechilmadi."
            )
            return
        # 4) GPT tarjima (target_lang ga) — Avto bo'lsa tarjima qilmaymiz
        if target_lang == "auto":
            translated = original_text
        else:
            try:
                translated = translate_with_claude(original_text, source_lang, None, target_lang)
            except Exception as e:
                logging.error(f"URL GPT tarjima xato: {e}")
                telegram_send_message(
                    user_id,
                    f"❌ Tarjima xato: {str(e)[:200]}\n\n💚 Daqiqa hisobingizdan yechilmadi."
                )
                return
        if not translated or not translated.strip():
            telegram_send_message(
                user_id,
                "❌ Tarjima bo'sh qaytdi.\n\n💚 Daqiqa hisobingizdan yechilmadi."
            )
            return
        # 5) Natija — matn + PDF
        src_label = TRANSLATION_LANGS[source_lang]
        tgt_label = TRANSLATION_TARGETS.get(target_lang, "🇺🇿 O'zbekcha")
        telegram_send_message(user_id, f"🌐 Tarjima ({src_label} → {tgt_label}):")
        for i in range(0, len(translated), 4000):
            telegram_send_message(user_id, translated[i:i+4000])
        # PDF (best-effort)
        try:
            pdf_path = make_pdf(translated, f"Tarjima — {tgt_label}")
            telegram_send_document(user_id, pdf_path, filename=f"tarjima_{target_lang}.pdf", caption=f"📎 Tarjima PDF ({tgt_label})")
            try: os.remove(pdf_path)
            except Exception: pass
        except Exception as e:
            logging.warning(f"URL tarjima PDF xato: {e}")
        success = True
        # 6) Tarif daqiqalari — faqat success'da
        if success and not _is_admin_id(user_id) and actual_duration > 0:
            add_user_usage(user_id, actual_duration * TRANSLATION_MULTIPLIER)
    except Exception as e:
        logging.error(f"process_url_translation_for_user xato: {e}")
        telegram_send_message(
            user_id,
            f"❌ URL tarjima xato: {str(e)[:200]}\n\n💚 Daqiqa hisobingizdan yechilmadi."
        )
    finally:
        progress.stop()
        if audio_path:
            try: shutil.rmtree(os.path.dirname(audio_path), ignore_errors=True)
            except Exception: pass


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
        text = transcribe_unified(audio_path, language=language)
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
        # === [TARJIMA] manba til (source) ===
        translation_lang = (data.get("translation_lang") or "").lower()
        if translation_lang and translation_lang not in TRANSLATION_LANGS:
            translation_lang = ""
        # === [TARJIMA] hosil til (target) — default 'uz' ===
        target_lang = (data.get("target_lang") or "uz").lower()
        if target_lang not in TRANSLATION_TARGETS:
            target_lang = "uz"
        if not user_id or not audio_data:
            return web.json_response({"error": "user_id yoki audio yo'q"}, status=400, headers=cors_headers())
        ext = format_hint.split("/")[-1].split(";")[0] if "/" in format_hint else format_hint
        if not ext.startswith('.'):
            ext = '.' + ext
        tmp_path = save_base64_audio(audio_data, ext)
        # === [TARJIMA] Tarjima rejimi yoqilgan bo'lsa, thread'iga target_lang bilan uzatamiz ===
        if translation_lang:
            threading.Thread(target=process_translation_for_user, args=(int(user_id), tmp_path, translation_lang, target_lang), daemon=True).start()
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
        translation_lang = ""  # === [TARJIMA] source ===
        target_lang = "uz"      # === [TARJIMA] target — default uzbek ===
        pdf_audio_lang = ""     # === [PDF→MP3] alohida audio rejimi (faqat audio chiqsin) ===
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
            elif part.name == "target_lang":
                tg = (await part.text()).strip().lower()
                if tg in TRANSLATION_TARGETS:
                    target_lang = tg
            elif part.name == "pdf_audio_lang":
                pal = (await part.text()).strip().lower()
                if pal in TRANSLATION_TARGETS:
                    pdf_audio_lang = pal
            elif part.name == "file":
                file_name = part.filename or "upload.bin"
                file_data = await part.read()
        if not user_id or not file_data:
            return web.json_response({"error": "user_id yoki fayl yo'q"}, status=400, headers=cors_headers())
        ext = os.path.splitext(file_name)[1].lower() or ".bin"
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(file_data)
            tmp_path = tmp.name
        # === [PDF → MP3] WebApp PDF flow — faqat audio chiqsin (matn yo'q) ===
        if ext == ".pdf" and pdf_audio_lang:
            threading.Thread(
                target=process_pdf_audio_only,
                args=(int(user_id), tmp_path, pdf_audio_lang),
                daemon=True,
            ).start()
        # === [TARJIMA] PDF + translation_lang/target -> PDF tarjima (matn+PDF+audio target tilda) ===
        elif ext == ".pdf" and translation_lang:
            threading.Thread(target=process_pdf_translation_for_user, args=(int(user_id), tmp_path, translation_lang, target_lang), daemon=True).start()
        # PDF tarjimasiz — oddiy PDF -> ovoz (default O'zbekcha)
        elif ext == ".pdf":
            threading.Thread(target=process_pdf_for_user, args=(int(user_id), tmp_path), daemon=True).start()
        # Audio/video + translation_lang -> tarjima
        elif translation_lang:
            threading.Thread(target=process_translation_for_user, args=(int(user_id), tmp_path, translation_lang, target_lang), daemon=True).start()
        # Oddiy audio/video -> oddiy STT
        else:
            threading.Thread(target=process_audio_for_user, args=(int(user_id), tmp_path, language), daemon=True).start()
        return web.json_response({"status": "ok"}, headers=cors_headers())
    except Exception as e:
        logging.error(f"HTTP upload xatosi: {e}")
        return web.json_response({"error": str(e)}, status=500, headers=cors_headers())


async def handle_webapp_url_post(request):
    """WebApp dan URL yuborish (YouTube/Instagram/TikTok). === [TARJIMA] translation_lang ==="""
    try:
        data = await request.json()
        user_id = data.get("user_id")
        url = (data.get("url") or "").strip()
        url = extract_url(url) or url
        language = (data.get("language") or "uz").lower()
        if language not in ("uz", "ru", "en"):
            language = "uz"
        # === [TARJIMA] manba til (source) ===
        translation_lang = (data.get("translation_lang") or "").lower()
        if translation_lang and translation_lang not in TRANSLATION_LANGS:
            translation_lang = ""
        # === [TARJIMA] hosil til (target) — default 'uz' ===
        target_lang = (data.get("target_lang") or "uz").lower()
        if target_lang not in TRANSLATION_TARGETS:
            target_lang = "uz"
        if not user_id or not url:
            return web.json_response({"error": "user_id yoki url yo'q"}, status=400, headers=cors_headers())
        # === [TARJIMA] Tarjima rejimi (source + target) ===
        if translation_lang:
            threading.Thread(target=process_url_translation_for_user, args=(int(user_id), url, translation_lang, target_lang), daemon=True).start()
        else:
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
                    "Men audio va videolarni matn hamda PDF formatiga aylantiruvchi va "
                    "istalgan tildan istalgan tilga tarjima qilib PDF qilib bera oladigan aqlli botman. "
                    "Men bilan darslaringizni yanada oson va tartibli qiling.\n\n"
                    "🎧 Shuningdek, PDF hujjatlarni istalgan tilda ovozli audio formatga "
                    "aylantirib, ularni istalgan joyda qulay tinglashingizga yordam beraman."
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
    app.add_handler(CommandHandler("user", user_cmd))
    app.add_handler(CommandHandler("revoke", revoke_cmd))
    # === Admin panel — onsonroq boshqaruv ===
    app.add_handler(CommandHandler("admin", admin_panel_cmd))
    app.add_handler(CommandHandler("panel", admin_panel_cmd))
    app.add_handler(CallbackQueryHandler(admin_panel_callback, pattern=r"^adm:"))
    app.add_handler(CallbackQueryHandler(admin_revoke_callback, pattern=r"^adm_revoke:"))
    app.add_handler(CallbackQueryHandler(buy_callback, pattern=r"^buy:"))

    # Manual to'lov rejimi handlerlari (chek + admin tasdiqlash)
    app.add_handler(CallbackQueryHandler(paid_callback, pattern=r"^paid:"))
    app.add_handler(CallbackQueryHandler(approve_reject_callback, pattern=r"^(approve|reject):"))
    app.add_handler(CallbackQueryHandler(reply_button_callback, pattern=r"^reply:"))
    # === [TARJIMA] callback handler (manba til tanlash) ===
    app.add_handler(CallbackQueryHandler(translation_lang_callback, pattern=r"^transl:"))
    app.add_handler(CallbackQueryHandler(translation_target_callback, pattern=r"^transltgt:"))
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
