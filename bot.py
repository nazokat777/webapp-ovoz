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
import html
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
    "free":     {"name": "🌸 Bepul",         "minutes": 5,    "price": 0},       # 5 daq (testlik)
    "basic":    {"name": "💎 Boshlang'ich", "minutes": 180,  "price": 60000},   # 3 soat — 60,000 so'm
    "standart": {"name": "⭐ Standart",     "minutes": 600,  "price": 150000},  # 10 soat — 150,000 so'm
    "premium":  {"name": "👑 Premium",      "minutes": 1500, "price": 300000},  # 25 soat — 300,000 so'm
    # Eski tariflar — backward compat (eski paid userlar uchun)
    "pro":      {"name": "💎 Pro",          "minutes": 600,  "price": 500000}, # eski, mavjud paid userlar uchun
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
# === [TXT export] Oxirgi transkripsiya matni — TXT yuklab olish uchun ===
# {user_id: {"text": "...", "ts": timestamp}} — RAM'da saqlanadi (qisqa muddatli)
last_transcripts = {}
# === [REFERRAL] Do'st taklif qilish tizimi ===
# Sozlash:
REFERRAL_BONUS_MIN = 5         # Har taklif uchun har ikkalasiga +5 daqiqa
MAX_REFERRALS_PER_USER = 3     # Bitta user max 3 ta odam taklif qila oladi (anti-abuse)
# Ma'lumotlar:
# {user_id: extra_min} — referral va boshqa bonus daqiqalar (tarif daqiqalariga qo'shiladi)
user_bonus_minutes = {}
# {invited_user_id: inviter_user_id} — kim kimni taklif qilgan (bir marta)
user_referrals = {}
# {invited_user_id: True} — taklif qilingan user bonus'ini olgan bo'lsa (real foydalanish tasdiq)
user_referral_claimed = {}
# === [/REFERRAL] ============================================

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
        # === [REFERRAL] bonus daqiqalar va taklif tizimi ===
        for k, v in (data.get("user_bonus_minutes") or {}).items():
            try:
                user_bonus_minutes[int(k)] = int(v)
            except (ValueError, TypeError):
                pass
        for k, v in (data.get("user_referrals") or {}).items():
            try:
                user_referrals[int(k)] = int(v)
            except (ValueError, TypeError):
                pass
        for k, v in (data.get("user_referral_claimed") or {}).items():
            try:
                if v:
                    user_referral_claimed[int(k)] = True
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
                # === [REFERRAL] bonus daqiqalar va taklif tizimi ===
                "user_bonus_minutes": {str(k): int(v) for k, v in user_bonus_minutes.items()},
                "user_referrals": {str(k): int(v) for k, v in user_referrals.items()},
                "user_referral_claimed": {str(k): True for k in user_referral_claimed},
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


def get_user_bonus_min(user_id):
    """Referral va boshqa bonus daqiqalar (tarif daqiqalariga qo'shimcha)."""
    return int(user_bonus_minutes.get(user_id, 0))


def get_user_limit_sec(user_id):
    tariff = get_user_tariff(user_id)
    base_min = TARIFFS[tariff]["minutes"]
    bonus_min = get_user_bonus_min(user_id)
    return (base_min + bonus_min) * 60


def get_user_usage_sec(user_id):
    return user_uzbek_usage.get(user_id, 0)


def add_user_usage(user_id, seconds):
    logging.info(f"➕ add_user_usage(user_id={user_id}, seconds={seconds}, joriy={user_uzbek_usage.get(user_id, 0)})")
    if seconds and seconds > 0:
        user_uzbek_usage[user_id] = user_uzbek_usage.get(user_id, 0) + seconds
        logging.info(f"   ✅ Yangi total: {user_uzbek_usage[user_id]} sek")
        # Referral bonus — birinchi real foydalanishdan keyin beriladi (anti-fake)
        _try_claim_referral_bonus(user_id)
        _save_user_data()
    else:
        logging.warning(f"   ⚠️ seconds={seconds} musbat emas, daqiqa qo'shilmadi")


def _try_claim_referral_bonus(user_id):
    """User real foydalanish qilgach, taklif bonusi'ni faollashtirish.
    Bonus shu yerda beriladi (har ikkalasiga +REFERRAL_BONUS_MIN daqiqa).

    Shartlar:
    - user_id taklif qilingan bo'lishi kerak (user_referrals'da bor)
    - Hali bonus berilmagan (user_referral_claimed'da yo'q)
    - Inviter max 5 ta talab limitiga yetmagan
    """
    if user_id in user_referral_claimed:
        return  # Allaqachon olingan
    inviter_id = user_referrals.get(user_id)
    if not inviter_id:
        return  # Taklif qilinmagan

    # Inviter referral sonini hisoblash
    inviter_count = sum(
        1 for invited, ref in user_referrals.items()
        if ref == inviter_id and invited in user_referral_claimed
    )
    if inviter_count >= MAX_REFERRALS_PER_USER:
        logging.info(f"🚫 Inviter {inviter_id} max referral limitiga yetdi ({MAX_REFERRALS_PER_USER})")
        user_referral_claimed[user_id] = True  # Belgilab qo'yamiz, qayta sinab ko'rmasin
        return

    # Bonus berish — har ikkalasi uchun
    user_bonus_minutes[user_id] = user_bonus_minutes.get(user_id, 0) + REFERRAL_BONUS_MIN
    user_bonus_minutes[inviter_id] = user_bonus_minutes.get(inviter_id, 0) + REFERRAL_BONUS_MIN
    user_referral_claimed[user_id] = True
    logging.info(f"🎁 Referral bonus: +{REFERRAL_BONUS_MIN} daqiqa user_id={user_id} va inviter={inviter_id}")
    # Userlarga xabar
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": user_id,
            "text": f"🎁 *Tabriklaymiz!* Do'stingiz tavsiyasi orqali keldingiz.\n\n"
                    f"Sizga *+{REFERRAL_BONUS_MIN} daqiqa* bonus berildi! "
                    f"Tarifingizdagi daqiqalar yana ko'paydi.",
            "parse_mode": "Markdown",
        }, timeout=15)
        requests.post(url, json={
            "chat_id": inviter_id,
            "text": f"🎁 *Bonus!* Sizning tavsiyangiz orqali yangi do'st keldi.\n\n"
                    f"Sizga *+{REFERRAL_BONUS_MIN} daqiqa* bonus berildi! Rahmat 💚",
            "parse_mode": "Markdown",
        }, timeout=15)
    except Exception as e:
        logging.warning(f"Referral bonus xabarini yuborish xato: {e}")


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
    # Timeout 10 daqiqa — uzun videolar uchun yetarli, lekin cheksiz osilib qolmasin
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        # Soxta result obyekt — keyingi urinish uchun
        class _T:
            returncode = -1
            stderr = "yt-dlp timeout (10 daq) — server javob bermadi"
            stdout = ""
        return _T()
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
            # Bot detection'ni chetlab o'tish uchun har xil strategiyalar.
            # YouTube datacenter IP'larni bloklaydi — turli player_client'lar
            # boshqacha API endpoint'larga so'rov yuboradi.
            attempts = [
                {"use_cookies": True,  "player_client": None},
                {"use_cookies": True,  "player_client": "android"},
                {"use_cookies": True,  "player_client": "mweb"},
                {"use_cookies": False, "player_client": "mweb"},
                {"use_cookies": False, "player_client": "tv_embedded"},
                {"use_cookies": False, "player_client": "tv"},
                {"use_cookies": False, "player_client": "android,web"},
                {"use_cookies": False, "player_client": "ios"},
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


def convert_latin_to_cyrillic(text):
    """O'zbek Lotin alifbosidagi matnni Kirill alifbosiga o'tkazish — GPT-4o orqali.
    Yuqori sifat, imloviy xatolarsiz. Uzun matn 3000 so'zlik bo'laklarda ishlanadi.
    """
    if not text or not text.strip():
        return text
    if not OPENAI_API_KEY:
        logging.warning("OPENAI_API_KEY yo'q, Kirill konversiya imkonsiz")
        return text

    text = _normalize_uzbek_apostrophes(text)
    words = text.split()

    def _convert_chunk(chunk_text):
        """Bitta bo'lakni GPT bilan kirillga o'tkazish."""
        url_api = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }
        system_prompt = (
            "You are a PRECISE Uzbek alphabet converter. Convert the given Uzbek "
            "LATIN text to Uzbek CYRILLIC alphabet (current official Uzbek Cyrillic).\n\n"
            "STRICT RULES:\n"
            "1) Keep meaning EXACTLY — do not translate, only transliterate.\n"
            "2) Use correct Uzbek Cyrillic letters: а, б, в, г, ғ, д, е, ё, ж, з, и, й, "
            "к, қ, л, м, н, нг, о, ў, п, р, с, т, у, ф, х, ҳ, ч, ш, ъ, э, ю, я.\n"
            "3) Common conversions: o' → ў, g' → ғ, ch → ч, sh → ш, h → ҳ, x → х, "
            "q → қ, ng → нг, yo → ё, yu → ю, ya → я, ts → ц.\n"
            "4) 'e' at word start = 'э' (echki → эчки), inside word = 'е' (men → мен).\n"
            "5) PRESERVE proper nouns (foreign names like London, Microsoft stay as-is).\n"
            "6) PRESERVE numbers, dates, English/Arabic words unchanged.\n"
            "7) PRESERVE punctuation and formatting.\n"
            "8) NO spelling errors — use literary Uzbek Cyrillic norms.\n\n"
            "Return ONLY the converted Cyrillic text, no explanations."
        )
        payload = {
            "model": "gpt-4o",
            "max_tokens": 16000,
            "temperature": 0.0,  # eng aniq, ijodga ehtiyoj yo'q
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Convert this Uzbek Latin text to Uzbek Cyrillic:\n\n{chunk_text}"},
            ],
        }
        resp = requests.post(url_api, headers=headers, json=payload, timeout=300)
        if resp.status_code != 200:
            raise Exception(f"Kirill konversiya xatosi: HTTP {resp.status_code}")
        data = resp.json()
        return data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

    # Kichik matn — bir martada
    CYR_CHUNK_WORDS = 3000
    if len(words) <= CYR_CHUNK_WORDS:
        try:
            return _convert_chunk(text)
        except Exception as e:
            logging.error(f"Kirill konversiya xato: {e}")
            return text  # asl matnni qaytarib, hech bo'lmaganda yetkazamiz

    # Uzun matn — bo'laklarga
    chunks = []
    for i in range(0, len(words), CYR_CHUNK_WORDS):
        chunks.append(" ".join(words[i:i + CYR_CHUNK_WORDS]))
    logging.info(f"🔤 Kirill konversiya: {len(words)} so'z → {len(chunks)} bo'lak")

    converted_parts = []
    for idx, chunk in enumerate(chunks, 1):
        try:
            converted_parts.append(_convert_chunk(chunk))
            logging.info(f"   ✅ bo'lak {idx}/{len(chunks)} kirillga o'tkazildi")
        except Exception as e:
            logging.warning(f"   ❌ bo'lak {idx} kirill konversiya xato: {e}")
            converted_parts.append(chunk)  # asl bo'lakni qaytaramiz

    return "\n\n".join(converted_parts)


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


def make_tts_muxlisa(text, lang="uz"):
    """Matnni Muxlisa AI TTS bilan MP3 ga aylantiradi (faqat O'zbek tili).
    User talabi: PDF→audio uchun OpenAI/Edge yiqilganda fallback sifatida ishlatiladi.
    Returns: MP3 fayl yo'li yoki None (xato bo'lsa)."""
    if not text or not text.strip():
        return None
    if lang != "uz":
        # Muxlisa faqat O'zbek tilini qo'llab-quvvatlaydi
        return None
    if not MUXLISA_KEY:
        logging.warning("MUXLISA_KEY yo'q — Muxlisa TTS ishlamaydi")
        return None

    # Muxlisa TTS endpoint (taxminiy — Muxlisa hujjatiga qarab to'g'irlanishi mumkin)
    url = "https://service.muxlisa.uz/api/v2/tts"
    out_path = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False).name
    try:
        resp = requests.post(
            url,
            headers={"x-api-key": MUXLISA_KEY},
            json={"text": text.strip()[:5000], "format": "mp3"},  # 5000 belgi limit (xavfsizlik)
            timeout=180,
        )
        if resp.status_code != 200:
            logging.warning(f"Muxlisa TTS xato: HTTP {resp.status_code} — {resp.text[:200]}")
            try: os.remove(out_path)
            except Exception: pass
            return None
        # Audio bytes saqlash
        with open(out_path, "wb") as f:
            f.write(resp.content)
        if os.path.getsize(out_path) < 100:
            try: os.remove(out_path)
            except Exception: pass
            return None
        logging.info("✅ Muxlisa TTS muvaffaqiyatli ishladi")
        return out_path
    except Exception as e:
        logging.warning(f"Muxlisa TTS so'rov xato: {e}")
        try: os.remove(out_path)
        except Exception: pass
        return None


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
    Strategiya:
      • O'zbek (uz): OpenAI TTS → Edge TTS fallback → Muxlisa fallback
      • Boshqa tillar (ru/en/ar): OpenAI TTS → Edge fallback
      • Muxlisa AI faqat oxirgi chora (User talabi: 'open ai ishlolmasaginadan keyin')

    force_engine: 'edge', 'openai', yoki 'muxlisa' — ixtiyoriy, sinov uchun.
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
    if force_engine == "muxlisa":
        return make_tts_muxlisa(text, lang) or make_tts_edge(text, lang)

    # === Boshqa tillar (ru/en/ar): OpenAI TTS premium → Edge fallback ===
    if lang in ("ru", "en", "ar") and OPENAI_API_KEY:
        try:
            path = make_tts_openai(text, lang)
            if path:
                logging.info(f"✅ OpenAI TTS ({lang}) muvaffaqiyatli")
                return path
        except Exception as e:
            logging.warning(f"OpenAI TTS yiqildi ({lang}), Edge fallback: {e}")
        return make_tts_edge(text, lang)

    # === O'zbek (uz): Edge TTS (bepul, sifatli) → Muxlisa fallback ===
    # Edge TTS Uzbek native voice bor, sifati yaxshi
    try:
        path = make_tts_edge(text, lang)
        if path:
            return path
        logging.warning("Edge TTS bo'sh natija qaytardi (uz)")
    except Exception as e:
        logging.warning(f"Edge TTS yiqildi (uz): {e}")

    # Edge yiqilgan — Muxlisa fallback (faqat O'zbek uchun)
    logging.info("Edge TTS yiqildi, Muxlisa TTS fallback (uz)...")
    return make_tts_muxlisa(text, lang)


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


def transcribe_unified(file_path, progress_cb=None, language="uz", failed_ranges_out=None):
    """Audio/video'ni matnga aylantirish — FAQAT Whisper/gpt-4o-transcribe (OpenAI) orqali.

    failed_ranges_out: list pass qilsangiz, yiqilgan bo'lak vaqt oraliqlari to'ldiriladi:
        [(start_sec, end_sec, error), ...]
    """
    if not OPENAI_API_KEY:
        logging.warning("OPENAI_API_KEY yo'q — Muxlisa fallback ishlatiladi")
        return transcribe(file_path, progress_cb, language)

    # 1) STT
    text = transcribe_whisper(file_path, language, None, failed_ranges_out) or ""

    # 2) O'zbek matn — HAR DOIM GPT-4o bilan tozalash (TAK! TEXT darajasidagi sifat)
    if language == "uz" and text:
        text = _cleanup_uzbek_transcript(text)

    # 3) YAKUNIY xavfsizlik: takrorlarni yana tozalash (lekin matnni saqlab)
    if text:
        text = _dedupe_repeated_words(text)
        # Hallucination bo'lsa log qoldiramiz, lekin matnni o'chirmaymiz
        if _is_chunk_hallucinated(text):
            logging.warning("⚠️ Yakuniy natija qisman hallucination — agressive dedupe qilindi")

    return text
# === [/WHISPER UNIFIED STT] =====================================================


# === [TARJIMA MODULI — API HELPERS] =============================================
# Whisper: max 25 MB per request. 4 soatlik audio uchun bo'laklash kerak.
# Claude: max 8192 output tokens. 30K+ so'zlar uchun bo'laklash kerak.

WHISPER_CHUNK_SECONDS = 300    # 5 daqiqa per chunk (kichikroq = hallucination kam, oxiri yo'qolmaydi)

# OpenAI Whisper API qo'llab-quvvatlovchi tillar (ISO 639-1).
# Uzbek (uz), Kyrgyz (ky), Tajik (tg), Mongolian (mn) — qo'llab-quvvatlanmaydi.
# Bu tillarda audio yuborilsa, language parametri o'tkazib yuboriladi va Whisper
# auto-detect orqali tilni aniqlaydi (90% holatda to'g'ri).
WHISPER_SUPPORTED_LANGS = {
    "af", "ar", "hy", "az", "be", "bs", "bg", "ca", "zh", "hr", "cs", "da",
    "nl", "en", "et", "fi", "fr", "gl", "de", "el", "he", "hi", "hu", "is",
    "id", "it", "ja", "kn", "kk", "ko", "lv", "lt", "mk", "ms", "mr", "mi",
    "ne", "no", "fa", "pl", "pt", "ro", "ru", "sr", "sk", "sl", "es", "sw",
    "sv", "tl", "ta", "th", "tr", "uk", "ur", "vi", "cy",
}
WHISPER_MAX_FILE_MB = 22        # 22 MB dan oshganda bo'laklash (25 MB Whisper chegarasi - 3 MB margin)
WHISPER_CHUNK_BITRATE = "64k"   # 64 kbps mono — 10 daqiqa ≈ 4.8 MB
CLAUDE_CHUNK_WORDS = 3000       # GPT-4o uchun 3000 so'z (16k token output limitida xavfsiz)


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

    # === Qadam 1: butun audioni qayta kodlash + normalizatsiya (silenceremove YO'Q!) ===
    # silenceremove olib tashlandi — u so'zlarni kesib, Whisper'ni chalkashtirardi.
    # Faqat normalizatsiya va highpass shovqin filtri qoldi.
    tmp_dir = tempfile.mkdtemp(prefix="whisper_recode_")
    recoded_path = os.path.join(tmp_dir, "recoded.mp3")
    audio_filter = (
        "loudnorm=I=-16:LRA=11:TP=-1.5,"
        "highpass=f=80"
    )
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-i", file_path,
        "-vn", "-ac", "1", "-ar", "16000",
        "-af", audio_filter,
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
    # ffprobe orqali aniq davomiylik (taxminiy hisoblash o'rniga — oxirgi bo'lak yo'qolmasligi uchun)
    duration_sec = 0
    try:
        p = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", recoded_path],
            capture_output=True, text=True, timeout=15
        )
        duration_sec = int(float(p.stdout.strip())) if p.stdout.strip() else 0
    except Exception as e:
        logging.warning(f"ffprobe davomiylik aniqlash xato: {e}")
    if duration_sec <= 0:
        # Fallback: taxminiy (64kbps = 8 KB/sec)
        duration_sec = int(new_size_mb * 1024 / 8)
    logging.info(f"   → katta fayl, vaqt bo'yicha bo'laklash (dur={duration_sec}s)")
    return _split_by_time(recoded_path, chunk_seconds, duration_sec)


def _split_by_time(file_path, chunk_seconds, total_dur):
    """Audio'ni vaqt bo'yicha bo'laklarga ajratish (past bitrate bilan).
    Eslatma: file_path AVVAL qayta kodlangan bo'lishi kerak (64kbps mono)."""
    n_chunks = int(total_dur // chunk_seconds) + (1 if total_dur % chunk_seconds > 0 else 0)
    n_chunks = max(1, min(n_chunks, 100))  # max 100 ta bo'lak (~16 soat)
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


def _is_output_quality_acceptable(text, audio_duration_sec=0):
    """Yakuniy natija sifati tarif daqiqasini yechishga arziydimi tekshirish.

    AGAR:
      - Matn juda qisqa (5 daqiqali audio'dan 50 ta so'z kam) — yomon
      - Bitta so'z 25%+ takrorlanadi — hallucination
      - Unique so'zlar nisbati < 15% — hallucination
    → False (sifat past, pul yechilmasin)
    """
    if not text or len(text.strip()) < 30:
        return False

    words = text.split()
    if len(words) < 10:
        return False

    # Tekshiruv 1: davomiylik mos kelyaptimi?
    # O'rtacha tezlik 130-150 so'z/daq, minimum 50 so'z/daq
    if audio_duration_sec > 300:  # 5 daq+ audio
        expected_min_words = int(audio_duration_sec / 60 * 30)  # 30 so'z/daq xavfsiz minimum
        if len(words) < expected_min_words:
            logging.warning(
                f"⚠️ Sifat past: {audio_duration_sec/60:.1f} daq audio → {len(words)} so'z "
                f"(kutilgan: {expected_min_words}+)"
            )
            return False

    # Tekshiruv 2: unique so'z nisbati
    unique_words = set(w.lower().strip(".,!?\"'") for w in words)
    unique_ratio = len(unique_words) / len(words)
    if unique_ratio < 0.15 and len(words) > 100:
        logging.warning(f"⚠️ Sifat past: unique_ratio={unique_ratio:.2f}")
        return False

    # Tekshiruv 3: bitta so'z 25%+ ?
    word_freq = {}
    for w in words:
        wl = w.lower().strip(".,!?\"'")
        if len(wl) > 2:  # juda qisqa so'zlarni hisoblamaslik (va, bu, men)
            word_freq[wl] = word_freq.get(wl, 0) + 1
    if word_freq:
        max_freq = max(word_freq.values())
        if max_freq / len(words) > 0.25:
            most_common = max(word_freq, key=word_freq.get)
            logging.warning(
                f"⚠️ Sifat past: '{most_common}' {max_freq}/{len(words)} "
                f"({max_freq/len(words)*100:.0f}%)"
            )
            return False

    return True


def _is_chunk_hallucinated(text, chunk_duration_sec=600):
    """Bo'lak natijasi hallucination ekanini aniqlash.
    10 daqiqa audio uchun normal 800-1500 so'z bo'ladi.
    Agar:
      - Juda kam so'z (< 100 ta) va davomiyligi > 5 daq
      - Yoki bitta so'z/ibora >40% takrorlanadi
    → hallucination deb hisoblaymiz."""
    if not text or len(text) < 30:
        return False

    words = text.split()
    if len(words) < 5:
        return False

    # Tekshiruv 1: so'z xilma-xilligi (unique ratio)
    unique_words = set(w.lower().strip(".,!?") for w in words)
    unique_ratio = len(unique_words) / len(words)
    if unique_ratio < 0.10 and len(words) > 50:
        # Juda kam unique so'z = takrorlangan hallucination
        logging.warning(f"⚠️ Hallucination aniqlandi: unique_ratio={unique_ratio:.2f}")
        return True

    # Tekshiruv 2: bitta so'z butun matnning 30%+
    word_freq = {}
    for w in words:
        wl = w.lower().strip(".,!?")
        word_freq[wl] = word_freq.get(wl, 0) + 1
    max_freq = max(word_freq.values()) if word_freq else 0
    if max_freq / len(words) > 0.30:
        most_common = max(word_freq, key=word_freq.get)
        logging.warning(f"⚠️ Hallucination: '{most_common}' so'zi {max_freq}/{len(words)} marta ({max_freq/len(words)*100:.0f}%)")
        return True

    return False


def _clean_whisper_hallucination(text):
    """Whisper hallucinatsiyani aniqlash va tozalash.
    Whisper jim/shovqinli audio'da bir xil iborani 10-500 marta qaytaradi.

    Algoritm (2 darajada):
      1) Gap darajasida: agar bir gap ketma-ket 2 martadan ko'p takrorlansa
      2) So'z darajasida: agar bir so'z/ibora 5+ marta ketma-ket takrorlansa

    MUHIM: bo'lakni butunlay o'chirmaydi (BOSHI YO'Q bo'lib qoladi).
    Faqat takrorlarni olib tashlaydi.
    """
    if not text or len(text) < 100:
        return text

    # === 0-daraja: hallucination bormi log uchun (lekin o'chirmaydi) ===
    if _is_chunk_hallucinated(text):
        logging.warning("⚠️ Bo'lak hallucination borligi — agressive dedupe qilamiz")
        # Bo'sh qaytarmaymiz! Faqat takrorlarni tozalaymiz

    # === 1-daraja: so'z/ibora darajasida tozalash ===
    text = _dedupe_repeated_words(text)

    # === 2-daraja: gap darajasida tozalash ===
    sentences = re.split(r'(?<=[.!?])\s+', text)
    cleaned = []
    last_normalized = None
    repeat_count = 0
    skipped_total = 0

    for sent in sentences:
        s = sent.strip()
        if not s:
            continue
        normalized = re.sub(r'[^\w\s]', '', s.lower()).strip()
        if not normalized:
            cleaned.append(s)
            continue

        if normalized == last_normalized:
            repeat_count += 1
            if repeat_count >= 2:
                skipped_total += 1
                continue
        else:
            last_normalized = normalized
            repeat_count = 0

        cleaned.append(s)

    if skipped_total > 0:
        logging.info(f"🧹 Whisper gap takror: {skipped_total} ta o'chirildi")

    result = " ".join(cleaned)
    # 3-daraja: yana so'z darajasida (chunki gap birlashtirilgandan keyin yangi takrorlar paydo bo'lishi mumkin)
    result = _dedupe_repeated_words(result)
    return result


def _dedupe_by_frequency(words, is_timestamp_fn=None, max_repeats=5):
    """Agar bir ibora (1-3 so'z) butun matnda max_repeats martadan ko'p uchrasa,
    qolgan takrorlarni o'chiramiz. Vaqt belgilari saqlanadi.

    Misol: 'Malikul Mulk' butun matnda 20 marta uchrasa,
    faqat birinchi 5 tasi qoladi, qolgan 15 tasi o'chiriladi.
    """
    if not words or len(words) < 20:
        return words

    is_ts = is_timestamp_fn or (lambda w: False)

    # 1-3 so'zli ibora kombinatsiyalari uchun sanash
    for window in [3, 2, 1]:
        # Phrase frequency
        phrase_count = {}
        i = 0
        while i < len(words) - window + 1:
            phrase_parts = []
            j = i
            consumed = 0
            while j < len(words) and consumed < window:
                if not is_ts(words[j]):
                    phrase_parts.append(words[j].lower().strip(".,;:!?\"'"))
                    consumed += 1
                j += 1
            if consumed == window:
                phrase = " ".join(phrase_parts)
                if len(phrase) > 3:  # juda qisqa iboralarni o'tkazib yuborish
                    phrase_count[phrase] = phrase_count.get(phrase, 0) + 1
            i += 1

        # Takror iboralarni topish
        repeat_phrases = {p for p, c in phrase_count.items() if c > max_repeats}
        if not repeat_phrases:
            continue

        # Endi takror iboralarni o'chiramiz (birinchi 'max_repeats' martagacha qoldiramiz)
        seen_count = {p: 0 for p in repeat_phrases}
        result = []
        i = 0
        while i < len(words):
            # Vaqt belgisi — har doim qoldiramiz
            if is_ts(words[i]):
                result.append(words[i])
                i += 1
                continue
            # Kandidat ibora
            phrase_parts = []
            j = i
            consumed = 0
            while j < len(words) and consumed < window:
                if not is_ts(words[j]):
                    phrase_parts.append(words[j].lower().strip(".,;:!?\"'"))
                    consumed += 1
                j += 1
            if consumed == window:
                phrase = " ".join(phrase_parts)
                if phrase in repeat_phrases:
                    seen_count[phrase] += 1
                    if seen_count[phrase] > max_repeats:
                        # O'chir — bu iboraga tegishli so'zlarni o'tkazib yuboramiz
                        i = j
                        continue
            result.append(words[i])
            i += 1
        words = result

    return words


def _dedupe_repeated_words(text):
    """So'z/ibora takroridan tozalash.
    'yaqinlikka yaqinlikka yaqinlikka... yaqinlikka' → 'yaqinlikka'
    Bir xil so'z 3+ marta ketma-ket bo'lsa, 1 ta qoldiramiz.
    Ibora (2-5 so'z) takrori ham aniqlanadi.

    VAQT BELGILARI ([MM:SS]) tekshirishda e'tiborga olinmaydi — ular ajratuvchi
    bo'lib turishi mumkin, lekin asl matn takror bo'lishi mumkin."""
    if not text:
        return text

    # Vaqt belgilarini olib tashlab tekshirish uchun helper
    import re as _re
    def _is_timestamp(w):
        """[12:34] yoki [1:23:45] formatdagi vaqt belgisi"""
        return bool(_re.match(r'^\[\d{1,2}:\d{2}(:\d{2})?\]?$', w.strip(".,;:")))

    words = text.split()
    if len(words) < 10:
        return text

    # 1. Bir so'z 3+ marta ketma-ket (vaqt belgilarini hisoblamasdan)
    cleaned = []
    skipped = 0
    # Vaqt belgilarisiz oldingi so'zlarni izlash uchun
    def _last_non_ts(arr, n=2):
        result = []
        for x in reversed(arr):
            if not _is_timestamp(x):
                result.append(x)
                if len(result) >= n:
                    break
        return list(reversed(result))

    for i, w in enumerate(words):
        # Vaqt belgilari har doim saqlanadi (skip qilinmaydi)
        if _is_timestamp(w):
            cleaned.append(w)
            continue
        # Oldingi 2 ta non-timestamp so'z bilan solishtirish
        prev = _last_non_ts(cleaned, 2)
        if len(prev) >= 2 and prev[-1].lower() == w.lower() and prev[-2].lower() == w.lower():
            skipped += 1
            continue
        cleaned.append(w)

    # 2. Frequency-based filtering: agar bir ibora butun matnda 5+ marta takrorlansa,
    #    har bir ortiqcha takrorni o'chiramiz (timestamp'lar e'tiborga olinmaydi)
    cleaned = _dedupe_by_frequency(cleaned, _is_timestamp)

    # 3. Ibora (2-4 so'z) takrori — masalan "Yaxshi yaxshi yaxshi yaxshi yaxshi"
    # yoki "Va men va men va men va men"
    for window in [4, 3, 2]:
        result = []
        i = 0
        while i < len(cleaned):
            # Keyingi window ta so'z (kandidat ibora)
            if i + window <= len(cleaned):
                phrase = " ".join(cleaned[i:i+window]).lower()
                # Bu ibora keyin yana takrorlanadimi?
                repeat_count = 0
                j = i + window
                while j + window <= len(cleaned):
                    next_phrase = " ".join(cleaned[j:j+window]).lower()
                    if phrase == next_phrase:
                        repeat_count += 1
                        j += window
                    else:
                        break
                if repeat_count >= 2:  # 3+ marta takrorlangan (1 asl + 2 takror)
                    # Faqat birinchi 1 marta qoldiramiz
                    result.extend(cleaned[i:i+window])
                    i = j  # takrorlarni o'tkazib yuboramiz
                    skipped += repeat_count * window
                    continue
            result.append(cleaned[i])
            i += 1
        cleaned = result

    if skipped > 5:
        logging.info(f"🧹 So'z/ibora takrorlari tozalandi: {skipped} ta so'z o'chirildi")

    return " ".join(cleaned)


def _format_text_with_timestamps(segments, chunk_offset_sec=0, marker_interval=30):
    """Whisper segmentlarini har 30 sek belgi bilan formatlash.
    Misol: '[00:00] Salom... [00:30] Bugun... [01:00] Ko'rib chiqamiz...'

    segments: Whisper verbose_json'dan kelgan segmentlar ro'yxati
    chunk_offset_sec: bu bo'lakning butun audio'da boshlanish vaqti (sekundlar)
    marker_interval: belgi qo'yiladigan interval (default: har 30 sek)
    """
    if not segments:
        return ""

    parts = []
    next_marker_at = 0  # keyingi belgi qachon qo'yilishi
    last_marker_sec = -marker_interval

    for seg in segments:
        seg_start = chunk_offset_sec + (seg.get("start") or 0)
        seg_text = (seg.get("text") or "").strip()
        if not seg_text:
            continue

        # Belgi qo'yish kerakmi?
        if seg_start >= last_marker_sec + marker_interval:
            # MM:SS formatda
            mins = int(seg_start // 60)
            secs = int(seg_start % 60)
            timestamp = f"[{mins:02d}:{secs:02d}]"
            parts.append(timestamp)
            last_marker_sec = seg_start - (seg_start % marker_interval)

        parts.append(seg_text)

    return " ".join(parts)


def _cleanup_uzbek_transcript(text):
    """O'zbek transkripsiyani GPT-4o bilan tozalash — TAK! TEXT darajasidagi sifat.

    Bu funksiya HAR DOIM o'zbek STT natijasi uchun chaqiriladi:
    1) Arab alifbosini Uzbek lotin transliteratsiyasiga aylantirish
    2) Noto'g'ri so'zlarni to'g'rilash (Whisper xatolari)
    3) Apostroflar (o', g') to'g'ri yozish
    4) Buzilgan qismlarni kontekstdan tiklash
    5) Diniy atamalar va ismlarni rasmiy shaklda
    6) Tinish belgilarini qo'shish
    """
    if not text or not OPENAI_API_KEY:
        return text
    # Uzun matn — chunklash kerak
    if len(text) > 30000:
        # Juda uzun, chunklab tozalash
        words = text.split()
        chunks = []
        cur, count = [], 0
        for w in words:
            cur.append(w)
            count += len(w) + 1
            if count >= 8000:
                chunks.append(" ".join(cur))
                cur, count = [], 0
        if cur:
            chunks.append(" ".join(cur))
        cleaned_parts = []
        for ch in chunks:
            cleaned_parts.append(_cleanup_uzbek_transcript_chunk(ch))
        return "\n\n".join(cleaned_parts)
    return _cleanup_uzbek_transcript_chunk(text)


def _cleanup_uzbek_transcript_chunk(text):
    """Bitta chunk uchun cleanup."""
    if not text or not OPENAI_API_KEY:
        return text

    logging.info(f"🧹 Uzbek transkripsiyani GPT bilan tozalash ({len(text)} belgi)...")
    url_api = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    system_prompt = (
        "You are a professional Uzbek language editor. Your job is to clean up "
        "speech transcription output to produce PERFECT Uzbek Latin text.\n\n"
        "INPUT: Speech-to-text output that may have errors:\n"
        "- Mixed Latin and Arabic scripts\n"
        "- Misspelled or garbled words\n"
        "- Wrong apostrophe styles (o`, o', ó instead of o')\n"
        "- Missing or wrong punctuation\n"
        "- Phonetic errors from speech recognition\n"
        "- REPEATED phrases (hallucination): same phrase 10-500 times in a row\n\n"
        "RULES:\n"
        "1) OUTPUT MUST be 100% Uzbek Latin alphabet (no Arabic script).\n"
        "2) Transliterate Arabic religious phrases to Latin Uzbek:\n"
        "   - 'بسم الله' → 'Bismillahir Rohmanir Rohim'\n"
        "   - 'الله اكبر' → 'Allohu akbar'\n"
        "   - 'سبحان الله' → 'Subhanalloh'\n"
        "   - 'الحمد لله' → 'Alhamdulillah'\n"
        "3) Use proper Uzbek Latin: o', g', sh, ch, ng (not o`, ó, oʻ).\n"
        "4) Fix obvious phonetic transcription errors using context.\n"
        "5) Religious terms in standard Uzbek form:\n"
        "   - 'payg'ambar', 'sallallohu alayhi va sallam' (or 's.a.v.')\n"
        "   - 'Imom Buxoriy', 'Imom Muslim'\n"
        "   - 'sahobalar', 'ulamolar', 'shariat'\n"
        "6) Proper punctuation: capital letters, periods, commas.\n"
        "7) CRITICAL — REMOVE REPETITIVE HALLUCINATION:\n"
        "   - If a SAME phrase appears 3+ times in a row, keep ONLY ONE instance.\n"
        "   - Example INPUT: 'salom salom salom salom salom' → OUTPUT: 'salom'\n"
        "   - Example INPUT: 'va shu va shu va shu va shu' → OUTPUT: 'va shu'\n"
        "   - Be AGGRESSIVE about removing repetitions.\n"
        "8) DO NOT translate, DO NOT summarize, DO NOT add new content.\n"
        "9) Preserve ALL UNIQUE information from input — just clean and correct.\n\n"
        "Output ONLY the cleaned Uzbek text, no explanations."
    )
    payload = {
        "model": "gpt-4o",
        "max_tokens": 16000,
        "temperature": 0.0,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Clean up this Uzbek transcription:\n\n{text}"},
        ],
    }
    try:
        resp = requests.post(url_api, headers=headers, json=payload, timeout=300)
        if resp.status_code == 200:
            cleaned = resp.json()["choices"][0]["message"]["content"].strip()
            # Tekshiruv: tozalangan matn juda qisqarib ketmaganmi?
            if cleaned and len(cleaned) >= len(text) * 0.5:
                logging.info(f"✅ Uzbek matn tozalandi ({len(text)} → {len(cleaned)} belgi)")
                return cleaned
            else:
                logging.warning(f"Tozalangan matn juda qisqa, asl matnni qaytaramiz")
    except Exception as e:
        logging.warning(f"Uzbek cleanup xato: {e}")
    return text


# Eski nom uchun backward-compat (boshqa joylarda chaqiriladi)
def _cleanup_mixed_uzbek_arabic(text):
    return _cleanup_uzbek_transcript(text)


def _get_whisper_prompt(source_lang):
    """Whisper'ga kontekst beruvchi prompt qaytaradi.
    Bu so'zlar Whisper'ga 'shu mavzularda gap bo'ladi' deb signal beradi.
    Sifatni 30-40% oshiradi (ayniqsa o'zbek diniy/akademik matnlarda)."""

    # O'zbek tili uchun kontekst — oddiy va xilma-xil so'zlar (takror prompt'da bo'lmasin!)
    # MUHIM: prompt'da bir so'z takror yozilmaslik kerak, aks holda Whisper takror yozadi.
    # Arabcha translit so'zlar ham yo'q (output'ni arab alifbosida qaytarmasligi uchun).
    uz_prompt = (
        "Bu o'zbek tilidagi nutq. Salom, qanday yaxshi yashayapsiz. "
        "Bugun maktabda dars o'tdik. Talabalar ko'p kitob o'qiydi. "
        "Toshkent shahrida yangi bino qurildi. Samarqand chiroyli joy. "
        "Otam mehnat qilib pul topadi, onam ovqat pishiradi. "
        "Bola maktabga boradi va dars tayyorlaydi. "
        "Birinchidan, ikkinchidan, uchinchidan deb tushuntiraman. "
        "Ko'ngil quvonadi, fikr aniq bo'ladi, hayot davom etadi."
    )

    # Rus tili uchun
    ru_prompt = (
        "Здравствуйте. Сегодня поговорим о важной теме. "
        "Психология, образование, наука, технологии, искусство. "
        "Москва, Санкт-Петербург, Россия. Спасибо за внимание."
    )

    # Ingliz tili uchun
    en_prompt = (
        "Hello, welcome to this lesson. Today we will discuss "
        "education, science, technology, business, and culture. "
        "Thank you for listening. Please subscribe."
    )

    # Arab tili uchun (diniy kontekst kuchli)
    ar_prompt = (
        "بسم الله الرحمن الرحيم. السلام عليكم ورحمة الله وبركاته. "
        "اللهم صل على محمد وعلى آل محمد. القرآن الكريم، الحديث الشريف، "
        "الإسلام، الصلاة، الزكاة، الصيام، الحج، التوحيد، الفقه، التفسير."
    )

    prompts = {
        "uz": uz_prompt,
        "ru": ru_prompt,
        "en": en_prompt,
        "ar": ar_prompt,
    }

    # Auto bo'lsa, eng keng prompt (O'zbek, chunki userlar asosan O'zbek)
    if source_lang == "auto" or not source_lang:
        return uz_prompt

    return prompts.get(source_lang, uz_prompt)


def _try_transcribe(chunk_path, model, source_lang, url, headers, chunk_offset_sec=0):
    """Bitta bo'lakni belgilangan model bilan transkripsiya qilish.
    3 marta retry (HTTP 429/500/502/503). Bo'sh natija ham xato.
    whisper-1 uchun verbose_json + segments (timestamps) ishlatamiz.
    gpt-4o-transcribe uchun oddiy json (segments yo'q).
    Returnlar: (chunk_text yoki None, error_str yoki None)."""
    is_whisper1 = (model == "whisper-1")
    response_format = "verbose_json" if is_whisper1 else "json"
    last_error = None
    for attempt in range(3):
        try:
            with open(chunk_path, "rb") as f:
                files = {"file": (os.path.basename(chunk_path), f, "application/octet-stream")}
                data = {
                    "model": model,
                    "response_format": response_format,
                    "prompt": _get_whisper_prompt(source_lang),
                    "temperature": 0.0,
                }
                if is_whisper1:
                    data["timestamp_granularities[]"] = "segment"
                if source_lang and source_lang != "auto" and source_lang in WHISPER_SUPPORTED_LANGS:
                    data["language"] = source_lang
                resp = requests.post(url, headers=headers, files=files, data=data, timeout=600)

            if resp.status_code == 200:
                result = resp.json()
                if is_whisper1:
                    segments = result.get("segments") or []
                    if segments:
                        text = _format_text_with_timestamps(segments, chunk_offset_sec)
                    else:
                        text = (result.get("text") or "").strip()
                else:
                    text = (result.get("text") or "").strip()
                if text:
                    return _clean_whisper_hallucination(text), None
                # Bo'sh natija — qayta urinish foydasiz (audio jim)
                return None, "Bo'sh natija"
            elif resp.status_code == 400:
                err_text = resp.text[:200] if resp.text else "Unknown"
                return None, f"HTTP 400: {err_text}"
            elif resp.status_code in (429, 500, 502, 503):
                last_error = f"HTTP {resp.status_code}"
                time.sleep(2 ** attempt)
            else:
                return None, f"HTTP {resp.status_code}"
        except requests.exceptions.Timeout:
            last_error = "Timeout"
            if attempt < 2:
                time.sleep(2 ** attempt)
        except Exception as e:
            last_error = str(e)[:200]
            if attempt < 2:
                time.sleep(2 ** attempt)
    return None, last_error or "Noma'lum xato"


def _format_time_range(start_sec, end_sec):
    """Vaqt oraliqini chiroyli formatlash: 'MM:SS — MM:SS' yoki 'H:MM:SS' agar 1 soatdan ko'p."""
    def fmt(s):
        s = int(s)
        h, rem = divmod(s, 3600)
        m, ss = divmod(rem, 60)
        if h > 0:
            return f"{h}:{m:02d}:{ss:02d}"
        return f"{m:02d}:{ss:02d}"
    return f"{fmt(start_sec)} — {fmt(end_sec)}"


def _merge_failed_ranges(failed_ranges):
    """Ketma-ket yiqilgan bo'laklarni bitta oraliqqa birlashtirish.
    Input: [(start, end, err), ...]  sorted by start
    Output: [(start, end), ...]  merged
    """
    if not failed_ranges:
        return []
    sorted_ranges = sorted(failed_ranges, key=lambda r: r[0])
    merged = [(sorted_ranges[0][0], sorted_ranges[0][1])]
    for s, e, _ in sorted_ranges[1:]:
        last_s, last_e = merged[-1]
        if s <= last_e:
            merged[-1] = (last_s, max(last_e, e))
        else:
            merged.append((s, e))
    return merged


def _format_failed_ranges_text(failed_ranges):
    """Yiqilgan vaqt oraliqlarini user uchun chiroyli matn (HTML formatda) qiladi.
    Bo'sh ro'yxat bo'lsa "" qaytaradi.
    """
    if not failed_ranges:
        return ""
    merged = _merge_failed_ranges(failed_ranges)
    if not merged:
        return ""
    lines = ["⚠️ <b>Eslatma:</b> quyidagi vaqt oraliqlari transkripsiya qilinmadi (server xato):"]
    for s, e in merged:
        lines.append(f"• <code>{_format_time_range(s, e)}</code>")
    lines.append("\n💡 Bu qismlarni qayta olish uchun: audio'ni o'sha vaqtdan kesib qayta yuboring.")
    return "\n".join(lines)


def _send_failed_ranges_notice(user_id, failed_ranges):
    """Sync HTTP context — yiqilgan oraliqlar haqida userga xabar."""
    msg = _format_failed_ranges_text(failed_ranges)
    if not msg:
        return
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": user_id, "text": msg, "parse_mode": "HTML",
        }, timeout=30)
    except Exception as e:
        logging.warning(f"Failed ranges xabar yuborish xato: {e}")


def transcribe_whisper(file_path, source_lang, progress_cb=None, failed_ranges_out=None):
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
    failed_chunks = []
    # === [PARALLEL] 4 ta bo'lak bir vaqtda Whisper'ga yuboriladi (tezlik 4x) ===
    from concurrent.futures import ThreadPoolExecutor, as_completed
    chunk_results = {}   # {idx: chunk_text}
    completed = {"count": 0}
    completed_lock = threading.Lock()

    def _process_one_chunk(idx_and_path):
        idx, chunk_path = idx_and_path
        try:
            chunk_size_kb = os.path.getsize(chunk_path) / 1024
        except Exception:
            chunk_size_kb = 0
        if chunk_size_kb < 5:
            logging.warning(f"Bo'lak {idx} juda kichik ({chunk_size_kb:.1f}KB), o'tkazib yuborildi")
            return idx, None, None

        chunk_offset_sec = (idx - 1) * WHISPER_CHUNK_SECONDS
        # whisper-1 primary
        chunk_text, err1 = _try_transcribe(
            chunk_path, "whisper-1", source_lang, url, headers, chunk_offset_sec=chunk_offset_sec
        )
        if not chunk_text:
            logging.warning(f"Bo'lak {idx}/{total} whisper-1 yiqildi: {err1}. gpt-4o-transcribe fallback...")
            chunk_text, err2 = _try_transcribe(
                chunk_path, "gpt-4o-transcribe", source_lang, url, headers
            )
            if not chunk_text:
                logging.error(f"Bo'lak {idx}/{total} IKKALA model yiqildi: {err1} | {err2}")
                return idx, None, f"whisper-1: {err1} | gpt-4o: {err2}"
        return idx, chunk_text, None

    try:
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(_process_one_chunk, (idx, chunk_path)): idx
                       for idx, chunk_path in enumerate(chunks_to_process, 1)}
            for future in as_completed(futures):
                try:
                    idx, chunk_text, err = future.result()
                except Exception as e:
                    idx = futures[future]
                    chunk_text, err = None, str(e)[:200]

                with completed_lock:
                    completed["count"] += 1
                    cur = completed["count"]
                if progress_cb:
                    try: progress_cb(cur, total)
                    except Exception: pass

                if chunk_text:
                    chunk_results[idx] = chunk_text
                elif err:
                    failed_chunks.append((idx, err))
                    if failed_ranges_out is not None:
                        start_sec = (idx - 1) * WHISPER_CHUNK_SECONDS
                        end_sec = idx * WHISPER_CHUNK_SECONDS
                        failed_ranges_out.append((start_sec, end_sec, err))
    finally:
        if chunk_dir_to_cleanup:
            try: shutil.rmtree(chunk_dir_to_cleanup, ignore_errors=True)
            except Exception: pass

    # Natijalarni TARTIBDA yig'amiz (idx bo'yicha)
    results = [chunk_results[k] for k in sorted(chunk_results.keys())]

    # Agar BARCHA bo'laklar yiqilgan bo'lsa — xato qaytaramiz
    if not results and failed_chunks:
        first_err = failed_chunks[0][1] if failed_chunks else "Noma'lum"
        raise Exception(f"Whisper barcha bo'laklarda yiqildi. Sabab: {first_err}")

    # Qisman muvaffaqiyat — log qoldiramiz lekin natijani qaytaramiz
    if failed_chunks:
        logging.warning(f"⚠️ {len(failed_chunks)}/{total} bo'lak yo'qoldi, lekin {len(results)} bo'lak yetkazildi")

    final_text = "\n\n".join(results)
    return _clean_whisper_hallucination(final_text)


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
        f"You are a HIGHLY PRECISE professional translator specializing in religious, "
        f"academic, and technical texts. Your job is ACCURATE translation into {target_eng}.\n\n"
        f"STRICT RULES:\n"
        f"1) PRESERVE EXACT MEANING — every fact, name, number, date must be accurate.\n"
        f"2) TRANSLATE COMPLETELY — do not skip, summarize, or omit any sentence.\n"
        f"3) NATURAL FLOW — use literary style of target language, not word-by-word.\n"
        f"4) IDIOMS — use equivalent expressions in target language.\n"
        f"5) PROPER NOUNS — keep names as is (e.g., Muhammad, London, Tashkent).\n"
        f"6) NUMBERS — preserve exactly (numbers, dates, statistics).\n"
        f"7) RELIGIOUS TERMS — keep Quranic verses in original Arabic.\n"
        f"8) OUTPUT FORMAT — ONLY the translation, no preamble, no notes, no apologies.\n\n"
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
        "temperature": 0.1,  # past temperatura = aniqroq, kam ijodiy
        "top_p": 0.9,
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


def _gpt_translate_with_retry(chunk, source_lang, target_lang, max_retries=3):
    """Bitta bo'lakni GPT bilan tarjima qilish — 3 marta urinish (retry).
    Birinchi urinish 1 sek pauza, keyingilari 2, 4 sek (exponential backoff)."""
    last_err = None
    for attempt in range(max_retries):
        try:
            result = _gpt_translate_one(chunk, source_lang, target_lang)
            if result and result.strip():
                return result
            # Bo'sh natija — qayta urinish
            last_err = Exception("GPT bo'sh natija qaytardi")
        except Exception as e:
            last_err = e
            logging.warning(f"   GPT urinish #{attempt+1} xato: {e}")
        # Pauza (exponential backoff: 1, 2, 4 sek)
        if attempt < max_retries - 1:
            time.sleep(1 << attempt)  # 1, 2, 4
    # 3 marta ham yiqilsa — exception
    raise last_err or Exception("GPT 3 marta yiqildi")


def translate_with_claude(text, source_lang, progress_cb=None, target_lang="uz"):
    """Tarjima — OpenAI GPT-4o orqali.
    Uzun matn 3000 so'zlik bo'laklarga ajratiladi va har biri 3 marta urinish bilan
    tarjima qilinadi. Agar bir bo'lak 3 marta ham yiqilsa — butun tarjima xato qaytaradi
    (qisman natija bilan emas, to'liq xato bilan).

    source_lang: manba til (yoki 'auto')
    target_lang: hosil til ('uz', 'ru', 'en', 'ar')"""
    if not OPENAI_API_KEY:
        raise Exception("OPENAI_API_KEY sozlanmagan. Railway env qo'shing.")

    words = text.split()
    # Kichik matn — bir martada tarjima (retry bilan)
    if len(words) <= CLAUDE_CHUNK_WORDS:
        if progress_cb:
            try: progress_cb(1, 1)
            except Exception: pass
        return _gpt_translate_with_retry(text, source_lang, target_lang)

    # Uzun matn — bo'laklarga ajratamiz (so'zlar chegarasida)
    chunks = []
    for i in range(0, len(words), CLAUDE_CHUNK_WORDS):
        chunks.append(" ".join(words[i:i + CLAUDE_CHUNK_WORDS]))
    logging.info(f"🔪 GPT bo'laklash: {len(words)} so'z → {len(chunks)} bo'lak (target: {target_lang})")

    translations = []
    failed_chunks = []
    for idx, chunk in enumerate(chunks, 1):
        if progress_cb:
            try: progress_cb(idx, len(chunks))
            except Exception: pass
        try:
            result = _gpt_translate_with_retry(chunk, source_lang, target_lang)
            translations.append(result)
            logging.info(f"   ✅ bo'lak {idx}/{len(chunks)} tarjima qilindi ({len(result)} belgi)")
        except Exception as e:
            logging.error(f"GPT bo'lak {idx}/{len(chunks)} 3 marta ham yiqildi: {e}")
            failed_chunks.append((idx, str(e)[:100]))
            # Bo'lakni saqlab qolamiz, lekin xato deb belgilaymiz
            translations.append("")  # bo'sh joy

    # Agar 30% dan ko'p bo'lak yiqilgan bo'lsa — butun tarjima xato
    if len(failed_chunks) > len(chunks) * 0.3:
        err_msg = ", ".join([f"#{idx}: {err}" for idx, err in failed_chunks[:3]])
        raise Exception(
            f"Tarjima yiqildi: {len(failed_chunks)}/{len(chunks)} bo'lak xato. "
            f"Misol: {err_msg}"
        )

    # Bo'sh bo'laklarni o'chiramiz va birlashtiramiz
    result = "\n\n".join([t for t in translations if t])
    if failed_chunks:
        logging.warning(f"⚠️ {len(failed_chunks)} bo'lak yo'qoldi, lekin asosiy tarjima yetkazildi")
    return result
# === [/TARJIMA MODULI — API HELPERS] ============================================


# ── BOT HELPERS ─────────────────────────────────────────────────────────────

async def send_result(update, msg, text):
    if not text:
        await msg.edit_text("Matn aniqlanmadi.")
        return

    user_id = update.effective_user.id
    # Matnni keyingi yuklab olishlar uchun saqlaymiz (PDF/TXT tugma)
    try:
        last_transcripts[int(user_id)] = {"text": text, "ts": time.time()}
    except Exception:
        pass

    # Inline tugmalar — PDF, TXT, Yopish
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📥 PDF yuklab olish", callback_data="dl:pdf"),
            InlineKeyboardButton("📥 TXT yuklab olish", callback_data="dl:txt"),
        ],
        [InlineKeyboardButton("✕ Yopish", callback_data="dl:close")],
    ])

    # <pre> bloki — Telegram'da copy tugmasi bilan keladi
    CHUNK = 3900  # <pre> tag + header bilan 4096 char limit'ga sig'ishi uchun
    if len(text) <= CHUNK:
        escaped = html.escape(text)
        await msg.edit_text(
            f"📝 <b>Matn:</b>\n<pre>{escaped}</pre>",
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    else:
        await msg.edit_text("✅ Tayyor! Qismlarga bo'lib yuborilmoqda...")
        parts = [text[i:i+CHUNK] for i in range(0, len(text), CHUNK)]
        for i, part in enumerate(parts):
            escaped = html.escape(part)
            is_last = (i == len(parts) - 1)
            await update.message.reply_text(
                f"📄 <b>Qism {i+1}/{len(parts)}:</b>\n<pre>{escaped}</pre>",
                parse_mode="HTML",
                reply_markup=(keyboard if is_last else None),
            )


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
        failed_ranges = []
        text = await asyncio.to_thread(transcribe_unified, file_path, cb, language, failed_ranges)
        if failed_ranges:
            await update.message.reply_text(_format_failed_ranges_text(failed_ranges), parse_mode="HTML")
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
        failed_ranges = []
        text = await asyncio.to_thread(transcribe_unified, tmp_path, cb, language, failed_ranges)
        if failed_ranges:
            await update.message.reply_text(_format_failed_ranges_text(failed_ranges), parse_mode="HTML")
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

    # Doimiy xabar — URL chatda turaveradi, edit bo'lmaydi
    await update.message.reply_text(
        f"📌 Qabul qilindi:\n🔗 {url}",
        disable_web_page_preview=False,
    )
    # Progress xabari — yuklanish/transkripsiya jarayoni shu yerda edit bo'ladi
    msg = await update.message.reply_text("📥 Yuklanmoqda...\n\nBiroz sabr qiling...")
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
        failed_ranges = []
        text = await asyncio.to_thread(transcribe_unified, audio_path, cb, language, failed_ranges)
        if failed_ranges:
            await update.message.reply_text(_format_failed_ranges_text(failed_ranges), parse_mode="HTML")
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
    # === [REFERRAL] /start ref_<inviter_id> bo'lsa, taklif yozib qo'yamiz ===
    # Bonus FAQAT shu user 1-marta real audio yuborganda beriladi (anti-fake)
    try:
        args = context.args or []
        if args and args[0].startswith("ref_"):
            try:
                inviter_id = int(args[0][4:])
            except ValueError:
                inviter_id = 0
            if inviter_id and inviter_id != chat_id and chat_id not in user_referrals:
                # Sanab bo'lmaganda taklif qabul qilamiz, lekin bonus keyinroq
                user_referrals[chat_id] = inviter_id
                _save_user_data()
                logging.info(f"📨 Yangi referral: {chat_id} ← {inviter_id}")
    except Exception as e:
        logging.warning(f"Referral parse xato: {e}")
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
        "Men audio va videolardan *matn va PDF*, PDFdan esa *audio* yasaydigan botman.\n\n"
        "🎯 *Imkoniyatlarim:*\n"
        "• 🎤 Audio/video (har tilda) → 🇺🇿 O'zbek matn + PDF\n"
        "• 📄 O'zbek PDF → 🇺🇿 O'zbek audio MP3\n\n"
        "📥 *Yuborishingiz mumkin:*\n"
        "• Ovozli xabar, audio fayl\n"
        "• Video, dumaloq video\n"
        "• YouTube / TikTok / Instagram havolasi\n"
        "• PDF fayl\n\n"
        "💡 *Tavsiyalar:*\n"
        "• Istalgan uzunlikdagi audio/video qabul qilinadi (hatto bir necha soatli)\n"
        "• Aniqlik uchun uzun videolarni *10-20 daqiqali* bo'laklarga ajrating "
        "(YouTube/Instagram havolasini bo'lish shart emas)\n"
        "• *Aniq, tiniq ovoz* yuboring (shovqin kam bo'lsin)\n"
        "• Bir vaqtda bitta odam gapirsa, sifat yaxshi chiqadi\n\n"
        "🎁 *Bonus daqiqalar:* Do'st taklif qilsangiz ikkalangizgayam +5 daqiqa bepul!\n"
        "Tavsiya havolangizni olish: /tavsiya\n\n"
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
    bonus_min = get_user_bonus_min(user_id)
    bonus_line = f"🎁 Bonus: +{bonus_min} daqiqa (do'st taklif)\n" if bonus_min > 0 else ""
    await update.message.reply_text(
        f"📊 *Sizning hisobingiz*\n\n"
        f"🌸 Tarif: *{tariff['name']}* ({tariff['minutes']} daqiqa/oy)\n"
        f"{bonus_line}"
        f"⏱ Ishlatilgan: {used/60:.1f} daqiqa\n"
        f"📉 Qoldiq: {rem:.1f} daqiqa\n\n"
        f"💎 Tariflarni ko'rish: /tariflar\n"
        f"💳 Tarif sotib olish: /buy\n"
        f"🎁 Do'st taklif qilish: /tavsiya\n\n"
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


async def tavsiya_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/tavsiya — do'st taklif qilish havolasi va statistika."""
    user_id = update.effective_user.id
    try:
        me = await context.bot.get_me()
        bot_username = me.username
    except Exception:
        bot_username = "your_bot"
    ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"

    # Statistika
    total_invited = sum(1 for ref in user_referrals.values() if ref == user_id)
    claimed_count = sum(
        1 for invited, ref in user_referrals.items()
        if ref == user_id and invited in user_referral_claimed
    )
    bonus_earned = claimed_count * REFERRAL_BONUS_MIN
    bonus_current = get_user_bonus_min(user_id)
    remaining_slots = max(0, MAX_REFERRALS_PER_USER - claimed_count)

    text = (
        "🎁 *Do'st taklif qilish — bonus daqiqalar!*\n\n"
        f"Quyidagi havolani do'stlaringizga yuboring. "
        f"Ular ro'yxatdan o'tib audio yuborganda — *ikkalangizgayam +{REFERRAL_BONUS_MIN} daqiqa* bonus!\n\n"
        f"🔗 *Sizning havolangiz:*\n"
        f"`{ref_link}`\n\n"
        f"📊 *Statistika:*\n"
        f"• Taklif qilingan do'stlar: {total_invited}\n"
        f"• Bonus olganlar: {claimed_count}/{MAX_REFERRALS_PER_USER}\n"
        f"• Siz olgan bonus: +{bonus_earned} daqiqa\n"
        f"• Joriy bonus balansingiz: +{bonus_current} daqiqa\n"
        f"• Qolgan o'rin: {remaining_slots} ta\n\n"
        f"💡 *Eslatma:* Bonus do'st haqiqiy audio yuborgandan keyin beriladi (soxta hisoblardan himoya)."
    )
    await update.message.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True)


async def buy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tarif sotib olish menyusi."""
    await _show_buy_menu(update.message)


async def _show_buy_menu(message_obj):
    """Tarif tugmalari ko'rsatadi (chat message yoki callback edit uchun).
    'pro' eski legacy tarif — buy menyusida ko'rsatilmaydi, faqat 3 ta yangi tarif."""
    # Buy menyusida ko'rsatiladigan tariflar (legacy 'pro' yashirin)
    visible_keys = ["basic", "standart", "premium"]
    paid = [(k, TARIFFS[k]) for k in visible_keys if k in TARIFFS and TARIFFS[k].get("price", 0) > 0]
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

    async def _update_admin_message(suffix):
        """Admin xabarini yangilash — caption yoki text, qaysi mavjud bo'lsa."""
        try:
            # Caption (rasm/document'da) — birinchi navbatda
            if query.message.caption is not None:
                await query.edit_message_caption(
                    caption=(query.message.caption or "") + suffix,
                    parse_mode="Markdown",
                )
                return True
        except Exception as e:
            logging.debug(f"edit_message_caption xato: {e}")
        try:
            # Text — agar caption yo'q bo'lsa
            if query.message.text is not None:
                await query.edit_message_text(
                    text=(query.message.text or "") + suffix,
                    parse_mode="Markdown",
                )
                return True
        except Exception as e:
            logging.debug(f"edit_message_text xato: {e}")
        try:
            # Tugmalarni olib tashlash (eng kam mumkin)
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        return False

    if action == "approve":
        user_tariffs[target_id] = tariff_key
        user_uzbek_usage[target_id] = 0
        _save_user_data()
        # Admin uchun aniq alert
        await query.answer(
            f"✅ Tarif berildi: {t['name']} ({t['minutes']} daq)",
            show_alert=True,
        )
        # Xabarni yangilash (caption yoki text)
        await _update_admin_message(
            f"\n\n✅ *TASDIQLANDI* — {t['name']} tarif berildi ({t['minutes']} daq)"
        )
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
        await query.answer("❌ Rad etildi", show_alert=True)
        await _update_admin_message("\n\n❌ *RAD ETILDI*")
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
        failed_ranges = []
        original_text = await asyncio.to_thread(transcribe_whisper, file_path, source_lang, None, failed_ranges)
        if failed_ranges:
            await update.message.reply_text(_format_failed_ranges_text(failed_ranges), parse_mode="HTML")
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

        # 4) Natija — matn (PDF tugma orqali) + audio
        await msg.delete()
        tgt_label = TRANSLATION_TARGETS.get(target_lang, "🇺🇿 O'zbekcha")
        src_label = TRANSLATION_LANGS.get(source_lang, source_lang) if source_lang else "🌐 Avto"
        header = f"🌐 <b>Tarjima ({html.escape(src_label)} → {html.escape(tgt_label)}):</b>"
        await asyncio.to_thread(_send_text_card, update.effective_user.id, translated, header)

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


# === [DOWNLOAD TUGMALAR — PDF/TXT/Yopish] ================================
async def ai_tools_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Matn ostidagi tugmalar:
      dl:pdf   — matnni PDF qilib yuborish
      dl:txt   — matnni TXT fayl qilib yuborish
      dl:close — matn xabarini o'chirish
    """
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()
    if not (query.data.startswith("dl:") or query.data.startswith("ai:")):
        return
    action = query.data.split(":", 1)[1]
    user_id = query.from_user.id

    # Yopish — xabarni o'chirish
    if action == "close":
        try:
            await query.message.delete()
        except Exception as e:
            logging.debug(f"Yopish xato: {e}")
        return

    # PDF/TXT — matn kerak
    record = last_transcripts.get(user_id)
    if not record or not record.get("text"):
        await context.bot.send_message(
            chat_id=user_id,
            text="⚠️ Saqlangan matn yo'q. Avval audio/video yuboring.",
        )
        return
    text = record["text"]

    if action == "pdf":
        await context.bot.send_message(chat_id=user_id, text="📎 PDF tayyorlanmoqda...")
        try:
            pdf_path = await asyncio.to_thread(make_pdf, text)
        except Exception as e:
            await context.bot.send_message(chat_id=user_id, text=f"❌ PDF yaratilmadi: {str(e)[:200]}")
            return
        try:
            with open(pdf_path, "rb") as f:
                await context.bot.send_document(
                    chat_id=user_id, document=f,
                    filename="mnsm-matn.pdf",
                    caption="📎 Matn PDF formatda",
                )
        finally:
            try: os.remove(pdf_path)
            except Exception: pass
        return

    if action == "txt":
        await asyncio.to_thread(_send_txt_file, user_id, text, "matn.txt")
        return
# === [/DOWNLOAD TUGMALAR] =================================================


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


def _send_txt_file(user_id, text, filename="matn.txt"):
    """Matnni TXT fayl sifatida yuborish."""
    try:
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w", encoding="utf-8") as tmp:
            tmp.write(text)
            tmp_path = tmp.name
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
        with open(tmp_path, 'rb') as f:
            files = {"document": (filename, f, "text/plain")}
            data = {"chat_id": user_id, "caption": "📄 Matn TXT formatda"}
            requests.post(url, data=data, files=files, timeout=60)
        try: os.remove(tmp_path)
        except Exception: pass
        return True
    except Exception as e:
        logging.error(f"TXT yuborish xato: {e}")
        return False


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


def telegram_send_message_returning_id(chat_id, text):
    """Xabar yuboradi va message_id qaytaradi (keyin edit qilish uchun)."""
    if not text:
        return None
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        resp = requests.post(url, data={"chat_id": chat_id, "text": text}, timeout=30)
        if resp.status_code == 200:
            return resp.json().get("result", {}).get("message_id")
    except Exception as e:
        logging.debug(f"send_message_returning_id xato: {e}")
    return None


def telegram_edit_message(chat_id, message_id, text):
    """Mavjud xabarni tahrirlash (animatsiya uchun)."""
    if not message_id or not text:
        return
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
        requests.post(
            url,
            data={"chat_id": chat_id, "message_id": message_id, "text": text},
            timeout=10,
        )
    except Exception as e:
        logging.debug(f"edit_message xato: {e}")


def telegram_delete_message(chat_id, message_id):
    """Xabarni o'chirish."""
    if not message_id:
        return
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteMessage"
        requests.post(
            url, data={"chat_id": chat_id, "message_id": message_id}, timeout=10
        )
    except Exception as e:
        logging.debug(f"delete_message xato: {e}")


class ProgressIndicator:
    """Uzoq jarayonlarda Telegram'da indikator ko'rsatadigan context manager.

    Ikkita ish qiladi parallel:
      1) Chat action ("bot yozmoqda...") har 4 sek yuboriladi
      2) "⏳ Biroz kuting..." xabari aylanuvchi qum soat bilan har 2 sek yangilanadi
         (⏳ → ⌛ → ⏳ → ⌛ ...)

    Misol:
        progress = ProgressIndicator(user_id, "⏳ Biroz kuting, tarjima...")
        progress.start()
        # ... uzun ish
        progress.set_text("🎙 Audio yaratilmoqda...")  # matnni yangilash mumkin
        # ... yana ish
        progress.stop()  # qum soat xabari o'chiriladi
    """
    HOURGLASS = ["⏳", "⌛"]

    def __init__(self, chat_id, base_text="Biroz kuting...", action="typing", interval=4):
        self.chat_id = chat_id
        self.base_text = base_text
        self.action = action
        self.interval = interval
        self._stop = threading.Event()
        self._thread = None
        self._message_id = None
        self._text_lock = threading.Lock()

    def _current_message_text(self, frame_idx):
        emoji = self.HOURGLASS[frame_idx % len(self.HOURGLASS)]
        with self._text_lock:
            return f"{emoji} {self.base_text}"

    def _loop(self):
        # 1) Animatsiyali xabar yuborish
        self._message_id = telegram_send_message_returning_id(
            self.chat_id, self._current_message_text(0)
        )
        # 2) Chat action darhol yuborish
        telegram_send_chat_action(self.chat_id, self.action)

        frame = 0
        chat_action_counter = 0
        # Animatsiya har 2 sek, chat action har 4 sek (2 ta animatsiya = 1 ta chat action)
        while not self._stop.is_set():
            self._stop.wait(2)
            if self._stop.is_set():
                break
            frame += 1
            # Xabarni yangilash (qum soat aylantirish)
            if self._message_id:
                telegram_edit_message(
                    self.chat_id, self._message_id, self._current_message_text(frame)
                )
            chat_action_counter += 1
            # Chat action har 2 ta animatsiyada (≈4 sek)
            if chat_action_counter >= 2:
                telegram_send_chat_action(self.chat_id, self.action)
                chat_action_counter = 0

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self, delete_message=True):
        """Indikatorni to'xtatadi va animatsion xabarni o'chiradi (default)."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        if delete_message and self._message_id:
            telegram_delete_message(self.chat_id, self._message_id)
            self._message_id = None

    def set_text(self, new_text):
        """Animatsion xabar matnini yangilash (qum soat aylanishi davom etadi)."""
        with self._text_lock:
            self.base_text = new_text
        # Darhol xabarni yangilab qo'yamiz
        if self._message_id:
            telegram_edit_message(
                self.chat_id, self._message_id, f"⏳ {new_text}"
            )

    def set_action(self, new_action):
        """Chat action turini o'zgartirish."""
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


def _send_text_card(user_id, text, header="📝 <b>Matn:</b>"):
    """Matnni <pre> blokida + PDF/TXT/Yopish tugmalar bilan yuborish.
    Telegram'ning copy tugmasi <pre> blokida avtomatik chiqadi.
    Sync — async kontekstda ham xavfsiz ishlaydi (requests orqali).
    """
    try:
        last_transcripts[int(user_id)] = {"text": text, "ts": time.time()}
    except Exception:
        pass

    keyboard = {
        "inline_keyboard": [
            [
                {"text": "📥 PDF yuklab olish", "callback_data": "dl:pdf"},
                {"text": "📥 TXT yuklab olish", "callback_data": "dl:txt"},
            ],
            [{"text": "✕ Yopish", "callback_data": "dl:close"}],
        ]
    }

    CHUNK = 3900
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    if len(text) <= CHUNK:
        escaped = html.escape(text)
        try:
            requests.post(url, json={
                "chat_id": user_id,
                "text": f"{header}\n<pre>{escaped}</pre>",
                "parse_mode": "HTML",
                "reply_markup": keyboard,
            }, timeout=30)
        except Exception as e:
            logging.error(f"Matn card yuborish xato: {e}")
        return

    # Uzun matn — qismlarga bo'linadi, oxirgi qismda tugmalar
    parts = [text[i:i+CHUNK] for i in range(0, len(text), CHUNK)]
    for i, part in enumerate(parts):
        escaped = html.escape(part)
        is_last = (i == len(parts) - 1)
        body = {
            "chat_id": user_id,
            "text": f"{header} <i>Qism {i+1}/{len(parts)}</i>\n<pre>{escaped}</pre>",
            "parse_mode": "HTML",
        }
        if is_last:
            body["reply_markup"] = keyboard
        try:
            requests.post(url, json=body, timeout=30)
        except Exception as e:
            logging.error(f"Matn qism yuborish xato: {e}")


def _send_text_and_pdf(user_id, text):
    """Backwards-compatible wrapper — endi PDF avtomatik yuborilmaydi,
    foydalanuvchi tugma bosishi orqali yuklaydi."""
    _send_text_card(user_id, text, header="📝 <b>Matn:</b>")


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


def process_audio_for_user(user_id, file_path, language="uz", output_alphabet="latin"):
    """WebApp orqali yuborilgan audio'ni matnga aylantirish — tarif limiti qo'llanadi.
    XAVFSIZ TO'LOV: daqiqa faqat muvaffaqiyatli natija yuborilgandan keyin yechiladi.
    output_alphabet: 'latin' yoki 'cyrillic' — O'zbek matni alifbosi."""
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
        failed_ranges = []
        text = transcribe_unified(file_path, language=language, failed_ranges_out=failed_ranges)
        if failed_ranges:
            _send_failed_ranges_notice(user_id, failed_ranges)
        if text and text.strip() and text.strip() != "Matn aniqlanmadi.":
            # === SIFAT TEKSHIRUVI — YUBORISHDAN OLDIN ===
            if not _is_output_quality_acceptable(text, actual_duration):
                # Yomon natija — UMUMAN YUBORILMAYDI
                telegram_send_message(
                    user_id,
                    "⚠️ *Audio sifat past — to'liq matnga aylantirib bo'lmadi*\n\n"
                    "Bot bu audioda hallucination (xato takrorlar) aniqladi va "
                    "buzilgan natijani sizga yubormadi.\n\n"
                    "💚 Daqiqa hisobingizdan yechilmadi.\n\n"
                    "💡 *Yaxshi natija uchun:*\n"
                    "• Audio aniq, tiniq bo'lsin (shovqin kam)\n"
                    "• Jim joylar (sukunat) ko'p bo'lmasin\n"
                    "• Bir vaqtda bitta odam gapirsin\n"
                    "• Mikrofon yaqinroq bo'lsin"
                )
            else:
                # === [ALIFBO] Kirill so'ralsa matnni o'tkazamiz ===
                if output_alphabet == "cyrillic":
                    telegram_send_message(user_id, "🔤 Matn Kirill alifbosiga o'tkazilmoqda...")
                    text = convert_latin_to_cyrillic(text)
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
def process_translation_for_user(user_id, file_path, source_lang, target_lang="uz", output_alphabet="latin"):
    """WebApp orqali yuborilgan audio'ni xorijiy tildan tanlangan tilga tarjima.
    Hosil: matn + PDF (audio yo'q).
    XAVFSIZ TO'LOV: daqiqa faqat tarjima muvaffaqiyatli yetkazilgandan keyin yechiladi.
    PROGRESS: aylanuvchi qum soat ⏳↔⌛ bilan animatsion xabar.
    output_alphabet: 'latin' yoki 'cyrillic' (faqat target=uz uchun ahamiyatli)."""
    success = False
    actual_duration = 0
    progress = ProgressIndicator(user_id, base_text="Biroz kuting, tarjima qilinmoqda...", action="typing")
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
        progress.set_text("Audio matnga aylanmoqda...")
        # 1) Whisper STT
        failed_ranges = []
        try:
            original_text = transcribe_whisper(file_path, source_lang, None, failed_ranges)
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
        # Failed ranges xabari (agar bor bo'lsa)
        if failed_ranges:
            _send_failed_ranges_notice(user_id, failed_ranges)
        # 2) GPT tarjima (target_lang ga) — Avto bo'lsa tarjima qilmaymiz
        if target_lang == "auto":
            translated = original_text
        else:
            progress.set_text("Matn tarjima qilinmoqda...")
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
        # === SIFAT TEKSHIRUVI: YUBORISHDAN OLDIN ===
        if not _is_output_quality_acceptable(translated, actual_duration):
            telegram_send_message(
                user_id,
                "⚠️ *Audio sifat past — tarjima qila olmadim*\n\n"
                "Bot bu audioda hallucination (xato takrorlar) aniqladi va "
                "buzilgan natijani sizga yubormadi.\n\n"
                "💚 Daqiqa hisobingizdan yechilmadi.\n\n"
                "💡 *Yaxshi natija uchun:*\n"
                "• Audio aniq, tiniq bo'lsin (shovqin kam)\n"
                "• Jim joylar (sukunat) ko'p bo'lmasin\n"
                "• Bir vaqtda bitta odam gapirsin\n"
                "• Mikrofon yaqinroq bo'lsin"
            )
            success = False
        else:
            # 3) Natija — matn + PDF
            src_label = TRANSLATION_LANGS.get(source_lang, source_lang)
            tgt_label = TRANSLATION_TARGETS.get(target_lang, "🇺🇿 O'zbekcha")
            # === [ALIFBO] target=uz va Kirill so'ralsa, kirill alifbosiga o'tkazamiz ===
            if output_alphabet == "cyrillic" and target_lang == "uz":
                progress.set_text("Matn Kirill alifbosiga o'tkazilmoqda...")
                translated = convert_latin_to_cyrillic(translated)
                tgt_label = "🇺🇿 Ўзбекча (Кирилл)"
            header = f"🌐 <b>Tarjima ({html.escape(src_label)} → {html.escape(tgt_label)}):</b>"
            _send_text_card(user_id, translated, header=header)
            success = True

        # 4) Tarif daqiqalari — faqat success va sifat OK bo'lsa
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


def process_pdf_translation_for_user(user_id, pdf_path, source_lang="auto", target_lang="uz", output_alphabet="latin"):
    """PDF'ni xorijiy tildan tanlangan tilga tarjima qilib audio + PDF chiqarish.
    XAVFSIZ TO'LOV: faqat audio MUVAFFAQIYATLI yuborilgandan keyin daqiqa yechiladi.
    PROGRESS: Telegram'da 'bot yozmoqda...' indikatori ishlaydi.
    output_alphabet: 'latin' yoki 'cyrillic' — O'zbek matn alifbosi (target=uz uchun)."""
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
        # === [ALIFBO] Kirill so'ralsa O'zbek matni kirillga o'tkazamiz ===
        if output_alphabet == "cyrillic" and target_lang == "uz":
            progress.set_text("Matn Kirill alifbosiga o'tkazilmoqda...")
            translated = convert_latin_to_cyrillic(translated)
            tgt_label = "🇺🇿 Ўзбекча (Кирилл)"
        header = f"🌐 <b>PDF tarjima ({html.escape(tgt_label)}):</b>"
        _send_text_card(user_id, translated, header=header)
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


def process_url_translation_for_user(user_id, url, source_lang, target_lang="uz", output_alphabet="latin"):
    """URL'dan video yuklab xorijiy tildan tanlangan tilga tarjima — matn + PDF.
    XAVFSIZ TO'LOV: faqat matn yetkazilgandan keyin daqiqa yechiladi.
    PROGRESS: Telegram'da 'bot yozmoqda...' indikatori ishlaydi."""
    audio_path = None
    success = False
    actual_duration = 0
    progress = ProgressIndicator(
        user_id,
        base_text="Biroz kuting, tarjima qilinmoqda...",
        action="typing",
    )
    progress.start()
    try:
        if source_lang not in TRANSLATION_LANGS:
            telegram_send_message(user_id, "❌ Noma'lum manba til.")
            return
        # Limit dastlabki tekshiruvi
        if not check_limit_by_user_id(user_id, 0):
            return
        telegram_send_message(user_id, f"📌 Qabul qilindi:\n🔗 {url}")
        progress.set_text("Video yuklab olinmoqda... (uzun video 3-5 daqiqa olishi mumkin)")
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
        failed_ranges = []
        try:
            original_text = transcribe_whisper(audio_path, source_lang, None, failed_ranges)
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
        # Failed ranges xabari (agar bor bo'lsa)
        if failed_ranges:
            _send_failed_ranges_notice(user_id, failed_ranges)
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
        # === [ALIFBO] Kirill so'ralsa O'zbek matni kirillga o'tkazamiz ===
        if output_alphabet == "cyrillic" and target_lang == "uz":
            progress.set_text("Matn Kirill alifbosiga o'tkazilmoqda...")
            translated = convert_latin_to_cyrillic(translated)
            tgt_label = "🇺🇿 Ўзбекча (Кирилл)"
        header = f"🌐 <b>Tarjima ({html.escape(src_label)} → {html.escape(tgt_label)}):</b>"
        _send_text_card(user_id, translated, header=header)
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


def process_url_for_user(user_id, url, language="uz", output_alphabet="latin"):
    """WebApp URL'idan video yuklab matnga aylantirish — tarif limiti qo'llanadi.
    output_alphabet: 'latin' yoki 'cyrillic'."""
    audio_path = None
    try:
        # Limit dastlabki tekshiruvi (davomiylik hali noma'lum)
        if not check_limit_by_user_id(user_id, 0):
            return

        telegram_send_message(user_id, f"📌 Qabul qilindi:\n🔗 {url}")
        telegram_send_message(user_id, "📥 Yuklanmoqda...")
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
        failed_ranges = []
        text = transcribe_unified(audio_path, language=language, failed_ranges_out=failed_ranges)
        if failed_ranges:
            _send_failed_ranges_notice(user_id, failed_ranges)
        if text and text.strip() != "Matn aniqlanmadi.":
            # === [ALIFBO] Kirill so'ralsa o'tkazamiz ===
            if output_alphabet == "cyrillic":
                telegram_send_message(user_id, "🔤 Matn Kirill alifbosiga o'tkazilmoqda...")
                text = convert_latin_to_cyrillic(text)
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
        output_alphabet = "latin"  # === [ALIFBO] O'zbek matni Lotin yoki Kirill ===
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
            elif part.name == "output_alphabet":
                oa = (await part.text()).strip().lower()
                if oa in ("latin", "cyrillic"):
                    output_alphabet = oa
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
            threading.Thread(target=process_pdf_translation_for_user, args=(int(user_id), tmp_path, translation_lang, target_lang, output_alphabet), daemon=True).start()
        # PDF tarjimasiz — oddiy PDF -> ovoz (default O'zbekcha)
        elif ext == ".pdf":
            threading.Thread(target=process_pdf_for_user, args=(int(user_id), tmp_path), daemon=True).start()
        # Audio/video + translation_lang -> tarjima (faqat source != target bo'lsa)
        elif translation_lang and translation_lang != target_lang:
            threading.Thread(target=process_translation_for_user, args=(int(user_id), tmp_path, translation_lang, target_lang, output_alphabet), daemon=True).start()
        # Oddiy audio/video -> oddiy STT (source==target yoki til tanlanmagan)
        else:
            stt_lang = translation_lang if translation_lang else language
            threading.Thread(target=process_audio_for_user, args=(int(user_id), tmp_path, stt_lang, output_alphabet), daemon=True).start()
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
        # === [ALIFBO] O'zbek alifbosi ===
        output_alphabet = (data.get("output_alphabet") or "latin").lower()
        if output_alphabet not in ("latin", "cyrillic"):
            output_alphabet = "latin"
        if not user_id or not url:
            return web.json_response({"error": "user_id yoki url yo'q"}, status=400, headers=cors_headers())
        # === [TARJIMA] Tarjima rejimi (source + target) ===
        # MUHIM: agar source == target (masalan, Uz->Uz) tarjimasiz oddiy STT
        if translation_lang and translation_lang != target_lang:
            threading.Thread(target=process_url_translation_for_user, args=(int(user_id), url, translation_lang, target_lang, output_alphabet), daemon=True).start()
        else:
            # Oddiy transkripsiya — manba til tanlangan bo'lsa shuni ishlatamiz
            stt_lang = translation_lang if translation_lang else language
            threading.Thread(target=process_url_for_user, args=(int(user_id), url, stt_lang, output_alphabet), daemon=True).start()
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
                BotCommand("tavsiya",  "🎁 Do'st taklif — bonus daqiqalar"),
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
    app.add_handler(CommandHandler("tavsiya", tavsiya_cmd))
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
    # === [DOWNLOAD] Matn ostidagi PDF/TXT/Yopish tugmalari ===
    app.add_handler(CallbackQueryHandler(ai_tools_callback, pattern=r"^(dl|ai):"))
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
