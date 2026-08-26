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
import hmac
import hashlib
import urllib.parse
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
from telegram.error import BadRequest
from aiohttp import web
import edge_tts
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

# ── .env fayl yuklovchi (ixtiyoriy, LOKAL ishlash uchun) ──────────────────
# NEGA: .env.example bor edi, lekin uni HECH KIM O'QIMASDI — foydalanuvchi
# faylni to'ldirsa ham hech narsa o'zgarmasdi. Tashqi kutubxona (python-dotenv)
# qo'shmasdan, kichik parser bilan hal qilamiz.
#
# QOIDA: haqiqiy env HAR DOIM ustun. .env faqat MAVJUD BO'LMAGAN qiymatlarni
# to'ldiradi — shuning uchun Railway/Fly'dagi sozlamalar hech qachon
# repodagi fayl bilan almashib ketmaydi.
def _load_dotenv(path=None):
    """.env dan faqat YETISHMAYOTGAN o'zgaruvchilarni yuklaydi. Returns: soni."""
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(path):
        return 0
    loaded = 0
    try:
        # utf-8-sig: Windows Notepad UTF-8 ni BOM bilan saqlashi mumkin.
        # Oddiy "utf-8" bilan birinchi kalit "﻿BOT_TOKEN" bo'lib qolar,
        # ya'ni BOT_TOKEN JIMGINA topilmas va bot DEGRADED rejimga tushardi —
        # foydalanuvchi esa .env to'g'ri to'ldirilganini ko'rib turardi.
        # BOM bo'lmasa utf-8-sig oddiy utf-8 kabi ishlaydi.
        with open(path, "r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                if key.startswith("export "):
                    key = key[7:].strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
                    loaded += 1
    except Exception as e:
        print(f"⚠️ .env o'qishda xato: {e}", file=sys.stderr)
    return loaded


_dotenv_count = _load_dotenv()
if _dotenv_count:
    print(f"📄 .env dan {_dotenv_count} ta sozlama yuklandi "
          f"(mavjud env qiymatlari ustun turadi)")


# MUHIM: token HECH QACHON kodga yozilmaydi — faqat env orqali.
# Railway/Fly/Docker: BOT_TOKEN=... env qo'shing. Lokal sinov: .env yoki eksport.
BOT_TOKEN   = os.getenv("BOT_TOKEN", "").strip()

# DEGRADED REJIM: token yo'q bo'lsa jarayon O'LMAYDI, balki HTTP serverni
# ko'tarib, har so'rovga 503 va SABABNI qaytaradi.
#
# NEGA: ilgari bu yerda sys.exit(1) turardi. Natijada Railway'da deployment
# umuman yaratilmasdi va domen "Application not found" degan SIRLI javob
# berardi — sabab faqat deploy logida qolib, egasi uzoq vaqt izlab yurardi.
# Endi domen tirik qoladi va muammoni O'ZI aytadi. Bu "xatoni yashirish"
# emas: bot ishlamaydi, HAMMA endpoint 503 qaytaradi va log har daqiqada
# ogohlantiradi — shunchaki nosozlik KO'RINADIGAN bo'ladi.
DEGRADED_REASON = ""
if not BOT_TOKEN:
    # Yechim MUHITGA bog'liq: bulutda env o'zgaruvchisi, lokalda .env fayli.
    # Noto'g'ri joyni ko'rsatish foydalanuvchini behuda sarson qiladi.
    _on_cloud = bool(os.getenv("RAILWAY_PUBLIC_DOMAIN") or os.getenv("RAILWAY_PROJECT_ID")
                     or os.getenv("FLY_APP_NAME") or os.getenv("DYNO"))
    if _on_cloud:
        _fix = "Railway -> Variables -> BOT_TOKEN qo'shing va Redeploy qiling."
    else:
        _fix = (".env fayliga BOT_TOKEN=... yozing (.env.example dan nusxa oling), "
                "so'ng ishga_tushirish.bat ni qayta bosing.")
    DEGRADED_REASON = "BOT_TOKEN o'rnatilmagan. " + _fix
    print(
        "❌ BOT_TOKEN o'rnatilmagan — DEGRADED rejim.\n"
        "   Bot ishlamaydi; HTTP server faqat tashxis uchun ko'tariladi.\n"
        "   " + _fix,
        file=sys.stderr,
    )
# Muhlisa AI — Pro Uzbek tarifi uchun (premium sifat, Uzbek native STT)
# Bu kalitni Railway env vars'ga MUXLISA_KEY nomi bilan qo'shish kerak.
MUXLISA_KEY = os.getenv("MUXLISA_KEY", "")

# To'lov ma'lumotlari (Railway env variable orqali kiritiladi — kodga qo'yilmaydi!)
PAYMENT_CARD = os.getenv("PAYMENT_CARD", "")
PAYMENT_CARD_HOLDER = os.getenv("PAYMENT_CARD_HOLDER", "")
ADMIN_CONTACT = os.getenv("ADMIN_CONTACT", "@Nazokat_571")


def md_escape(text):
    """Telegram Markdown (V1) uchun maxsus belgilarni qochirish.

    NEGA KERAK: foydalanuvchi ismi yoki matni escape'siz `parse_mode="Markdown"`
    xabarga qo'yilsa, Telegram butun xabarni RAD ETADI ("Can't parse entities").
    Ya'ni ismida `_` bo'lgan odam /start ololmasdi, `*` yuborgan odamning
    murojaati adminga umuman yetmasdi — jimgina yo'qolardi.
    """
    if not text:
        return ""
    out = str(text)
    for ch in ("_", "*", "`", "["):
        out = out.replace(ch, "\\" + ch)
    return out


# Markdown V1 uchun xavfsiz versiya (barcha maxsus belgilar qochiriladi)
ADMIN_CONTACT_MD = md_escape(ADMIN_CONTACT)

# WebApp initData imzosi uchun kalit — BOT_TOKEN startupdan keyin o'zgarmaydi,
# shuning uchun har so'rovda qayta hisoblash shart emas.
_WEBAPP_SECRET = (
    hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    if BOT_TOKEN else None   # tokensiz imzo tekshirib bo'lmaydi -> hamma so'rov rad
)

# Foydalanuvchilarga ko'rsatiladigan neutral nom (admin username yashiriladi)
SUPPORT_NAME = os.getenv("SUPPORT_NAME", "Audio Bot Yordam markazi")

# Admin Telegram user ID(lar). ASOSIY autentifikatsiya manbai — username emas!
# Username Telegram'da bo'shatilishi va boshqa odam tomonidan egallanishi mumkin,
# user ID esa hech qachon o'zgarmaydi.
# Bir nechta admin uchun vergul bilan: ADMIN_USER_ID=123,456
ADMIN_USER_IDS = set()
for _piece in os.getenv("ADMIN_USER_ID", "").replace(";", ",").split(","):
    _piece = _piece.strip()
    if not _piece:
        continue
    try:
        ADMIN_USER_IDS.add(int(_piece))
    except ValueError:
        logging.warning(f"ADMIN_USER_ID noto'g'ri qiymat, o'tkazib yuborildi: {_piece!r}")
# Backward-compat: eski kod bitta ADMIN_USER_ID kutadi
ADMIN_USER_ID = next(iter(sorted(ADMIN_USER_IDS)), None)

# Telegram Payments — BotFather'dan olingan provider token (Click/Stripe/etc.)
# BotFather → /mybots → bot tanlang → Payments → provayder ulang → token nusxalang
# Railway'da PAYMENT_PROVIDER_TOKEN env qo'shing
PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN", "")
# Telegram Payments valyutasi (UZS yoki test uchun USD)
PAYMENT_CURRENCY = os.getenv("PAYMENT_CURRENCY", "UZS")

# === [TARJIMA MODULI] ===========================================================
# STT (Whisper/gpt-audio), matn tozalash va tarjima — hammasi OpenAI orqali.
# Railway env: OPENAI_API_KEY=sk-...
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")


def _ensure_openai_key():
    """Env runtime'da qayta o'qish — Railway redeploy chog'ida cached qiymat o'tib ketmasligi uchun.
    Agar env'da yangi qiymat bo'lsa, global OPENAI_API_KEY yangilanadi."""
    global OPENAI_API_KEY
    runtime_key = os.getenv("OPENAI_API_KEY", "").strip()
    if runtime_key and runtime_key != OPENAI_API_KEY:
        OPENAI_API_KEY = runtime_key
        logging.info("🔑 OPENAI_API_KEY runtime'da yangilandi")
    return OPENAI_API_KEY

# ── AI PROVAYDERLARI ────────────────────────────────────────────────────────
# TARTIB SIFAT BO'YICHA, NARX BO'YICHA EMAS.
#
# Uchala provayder ham OpenAI API shaklini gapiradi (/chat/completions va
# /audio/transcriptions), shuning uchun mavjud quvur o'zgarishsiz ishlaydi —
# faqat manzil, sarlavha va model nomi almashadi.
#
# Kalit yo'q provayder ro'yxatga UMUMAN qo'shilmaydi, ya'ni bitta kalit bilan
# ham bot to'liq ishlaydi. Zanjir yuqoridan pastga sinaladi: sifatlisi
# yiqilsa yoki limitga urilsa (429), keyingisiga o'tadi.
GROQ_API_KEY   = os.getenv("GROQ_API_KEY", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_STT_URL  = "https://api.openai.com/v1/audio/transcriptions"
GROQ_CHAT_URL   = "https://api.groq.com/openai/v1/chat/completions"
GROQ_STT_URL    = "https://api.groq.com/openai/v1/audio/transcriptions"
GEMINI_CHAT_URL = ("https://generativelanguage.googleapis.com"
                   "/v1beta/openai/chat/completions")


def _ensure_key(name, current):
    """Env'ni runtime'da qayta o'qish (deploy chog'ida eski qiymat qolmasin)."""
    runtime = os.getenv(name, "").strip()
    if runtime and runtime != current:
        logging.info("🔑 %s runtime'da yangilandi", name)
        return runtime
    return current


def _ensure_groq_key():
    global GROQ_API_KEY
    GROQ_API_KEY = _ensure_key("GROQ_API_KEY", GROQ_API_KEY)
    return GROQ_API_KEY


def _ensure_gemini_key():
    global GEMINI_API_KEY
    GEMINI_API_KEY = _ensure_key("GEMINI_API_KEY", GEMINI_API_KEY)
    return GEMINI_API_KEY


def _bearer(key):
    return {"Authorization": "Bearer " + key}


def _stt_attempts():
    """Bo'lakni transkripsiya qilish urinishlari — SIFAT tartibida.

    Har element: (nom, kind, model, url, headers, timestamps, langs)
      kind="chat_audio" — audio base64 bilan /chat/completions (faqat OpenAI)
      kind="form"       — multipart /audio/transcriptions (OpenAI va Groq)
      timestamps        — verbose_json + segment vaqt belgilari so'ralsinmi

    Tartib nega shunday:
      1) gpt-audio       — kodda o'lchangan: o'zbek uchun eng aniq
      2) groq large-v3   — Whisper'ning eng yangi versiyasi (whisper-1 = v2)
      3) whisper-1       — vaqt belgilari beradi
      4) gpt-4o-transcribe
      5) groq turbo      — eng tez, sifati bir oz pastroq (oxirgi chora)
    """
    oa = _ensure_openai_key()
    gq = _ensure_groq_key()
    out = []
    if oa:
        out.append(("gpt-audio", "chat_audio", "gpt-audio",
                    OPENAI_CHAT_URL, _bearer(oa), False, WHISPER_SUPPORTED_LANGS))
    if gq:
        out.append(("groq/whisper-large-v3", "form", "whisper-large-v3",
                    GROQ_STT_URL, _bearer(gq), True, GROQ_STT_LANGS))
    if oa:
        out.append(("whisper-1", "form", "whisper-1",
                    OPENAI_STT_URL, _bearer(oa), True, WHISPER_SUPPORTED_LANGS))
        out.append(("gpt-4o-transcribe", "form", "gpt-4o-transcribe",
                    OPENAI_STT_URL, _bearer(oa), False, WHISPER_SUPPORTED_LANGS))
    if gq:
        out.append(("groq/whisper-large-v3-turbo", "form", "whisper-large-v3-turbo",
                    GROQ_STT_URL, _bearer(gq), False, GROQ_STT_LANGS))
    return out


def _chat_attempts():
    """Matn modeli urinishlari — SIFAT tartibida.

    Har element: (nom, model, url, headers, max_out)

    max_out — o'sha provayderning max_tokens CHEGARASI. Bu qattiq chegara:
    Groq 8192 dan oshsa HTTP 400 ("must be less than or equal to 8192")
    yoki 413 qaytaradi va tozalash BUTUNLAY yiqiladi (amalda shunday
    bo'ldi — matn tozalanmay o'tib ketdi).

    Gemini 2.5 Pro birinchi: o'zbek kabi kam resursli tillarda kuchli.
    Bepul tarifda kuniga atigi ~50 so'rov, shuning uchun limitga urilganda
    (429) Flash'ga tushadi — u ham kuchli, lekin kuniga ~1500 so'rov.
    """
    oa = _ensure_openai_key()
    gm = _ensure_gemini_key()
    gq = _ensure_groq_key()
    out = []
    if gm:
        out.append(("gemini-2.5-pro", "gemini-2.5-pro", GEMINI_CHAT_URL,
                    _bearer(gm), 8192))
    if oa:
        out.append(("gpt-4o", "gpt-4o", OPENAI_CHAT_URL, _bearer(oa), 16000))
    if gm:
        out.append(("gemini-2.5-flash", "gemini-2.5-flash", GEMINI_CHAT_URL,
                    _bearer(gm), 8192))
    if gq:
        # Modellar HAQIQIY Groq ro'yxatidan olingan va o'zbek matnida
        # o'lchangan (llama-3.3 endi mavjud emas — qattiq yozilgani 404
        # berardi). Tanlov mezoni: o'zbek lotinidagi APOSTROF to'g'riligi,
        # chunki u ma'noni o'zgartiradi ("ma'ruza" != "maruza"):
        #   qwen3.8-27b   — apostrof to'g'ri, eng tez (1.1s)
        #   groq/compound — apostrof to'g'ri
        #   gpt-oss-120b  — apostrofni TUSHIRIB QOLDIRDI, shuning uchun oxirida
        # qwen3.6-27b ATAYLAB yo'q: u <think> fikrlashini matnga qo'shib yubordi.
        out.append(("groq/qwen3.8-27b", "qwen/qwen3.8-27b",
                    GROQ_CHAT_URL, _bearer(gq), 8192))
        out.append(("groq/compound", "groq/compound",
                    GROQ_CHAT_URL, _bearer(gq), 8192))
        out.append(("groq/gpt-oss-120b", "openai/gpt-oss-120b",
                    GROQ_CHAT_URL, _bearer(gq), 8192))
    return out


_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.S | re.I)


def _strip_think(text):
    """Ba'zi ochiq modellar ichki fikrlashini <think>...</think> ichida
    JAVOBGA qo'shib yuboradi (Groq'ning qwen3.6 modelida shunday bo'ldi —
    289 belgilik matn o'rniga 1450 belgi fikrlash chiqdi). Bunday matn
    to'g'ridan-to'g'ri foydalanuvchiga ketsa konspekt buziladi.
    Yopilmagan <think> ham kesiladi."""
    if not text or "<think>" not in text.lower():
        return text
    out = _THINK_RE.sub("", text)
    low = out.lower()
    if "<think>" in low:          # yopilmagan teg — qolganini tashlaymiz
        out = out[:low.index("<think>")]
    return out.strip()


def _chat_request(payload, timeout=300, label=""):
    """Matn modelini SIFAT tartibida sinaydi. Returns (text, error).

    Har provayderda 3 marta urinish (vaqtinchalik 5xx uchun), lekin 429
    (limit tugadi) da DARHOL keyingi provayderga o'tadi — kutish befoyda,
    kunlik kvota qayta tiklanmaydi. Aynan shu Gemini Pro (bepul tarifda
    kuniga ~50 so'rov) dan Flash (~1500) ga silliq o'tishni ta'minlaydi.
    """
    attempts = _chat_attempts()
    if not attempts:
        return None, ("matn modeli kaliti yo'q — GEMINI_API_KEY, "
                      "OPENAI_API_KEY yoki GROQ_API_KEY sozlang")
    errors = []
    backoffs = [2, 5, 12]
    for nom, model, url, headers, max_out in attempts:
        body = dict(payload)
        body["model"] = model
        # max_tokens ni provayder chegarasiga bo'ysundiramiz — oshsa
        # so'rov BUTUNLAY rad etiladi (400/413) va tozalash yiqiladi.
        if body.get("max_tokens"):
            body["max_tokens"] = min(int(body["max_tokens"]), max_out)
        h = dict(headers)
        h["Content-Type"] = "application/json"
        for attempt in range(3):
            try:
                resp = requests.post(url, headers=h, json=body, timeout=timeout)
                if resp.status_code == 200:
                    try:
                        txt = (resp.json()["choices"][0]["message"].get("content")
                               or "").strip()
                    except Exception as e:
                        errors.append(nom + ": javob shakli buzuq (" + str(e)[:60] + ")")
                        break
                    txt = _strip_think(txt)
                    if txt:
                        if errors:
                            logging.info("%s: %s bilan bajarildi (%d urinishdan keyin)",
                                         label, nom, len(errors))
                        return txt, None
                    errors.append(nom + ": bo'sh javob")
                    break
                if resp.status_code == 429:
                    errors.append(nom + ": limit (429)")
                    logging.warning("%s: %s limitga urildi — keyingi provayder",
                                    label, nom)
                    break
                if resp.status_code in (500, 502, 503, 504, 520) and attempt < 2:
                    time.sleep(backoffs[attempt])
                    continue
                errors.append(nom + ": HTTP " + str(resp.status_code) + " "
                              + (resp.text or "")[:100])
                break
            except Exception as e:
                if attempt < 2:
                    time.sleep(backoffs[attempt])
                    continue
                errors.append(nom + ": " + str(e)[:100])
    return None, " | ".join(errors)


def _has_any_ai_key():
    """Biror matn modeli mavjudmi — cleanup/tarjima shunga bog'liq."""
    return bool(_chat_attempts())


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
# WEBAPP_URL avtomatik aniqlash:
# 1) RAILWAY_PUBLIC_DOMAIN env (Railway avtomatik beradi — eng ishonchli)
# 2) WEBAPP_URL env (manual sozlangan bo'lsa)
# 3) Hardcoded Railway URL (oxirgi chora)
def _resolve_webapp_url():
    # ANIQ sozlangan qiymat HAR DOIM ustun turadi.
    #
    # Ilgari bu yerda `manual and "ngrok" not in manual` sharti bor edi:
    # .env'da ngrok manzili turgan bo'lsa u JIMGINA tashlab yuborilardi va
    # kod qattiq yozilgan Railway manziliga qaytardi. Natijada foydalanuvchi
    # sozlagan manzil ishlamas, "Web ilovani ochish" esa MUTLAQO BOSHQA
    # saytga olib borardi. Yuqoridagi izoh ngrok'ni tavsiya qilgani holda
    # kod uni rad etishi — hujjat bilan xatti-harakat orasidagi ziddiyat edi.
    manual = os.getenv("WEBAPP_URL", "").strip()
    if manual:
        return manual.rstrip("/")
    rw_domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip()
    if rw_domain:
        return f"https://{rw_domain}"
    # Sozlanmagan. Ilgari bu yerda qattiq yozilgan Railway manzili qaytarilardi —
    # u ALLAQACHON O'LIK bo'lsa ham tugma ko'rinaverardi va foydalanuvchi
    # "ilova ochilmayapti" degan xatoga duch kelardi (aynan shu sodir bo'ldi).
    # Endi bo'sh qaytadi: tugma KO'RSATILMAYDI. Yo'q tugma — o'lik tugmadan
    # yaxshi, chunki bot buzuq degan taassurot tug'dirmaydi.
    return ""


WEBAPP_URL = _resolve_webapp_url()
print("🔗 WEBAPP_URL = " + (WEBAPP_URL or
      "(sozlanmagan — Web ilova tugmasi berkitiladi)"))  # Deploy logda ko'rinadi
# Railway/Heroku PORT env, lokal sinov uchun HTTP_PORT yoki default 8000
HTTP_PORT  = int(os.getenv("HTTP_PORT") or os.getenv("PORT") or 8000)

# WebApp yuklama chegarasi. Server 512 MB RAM bilan ishlaydi, shuning uchun
# fayl RAM'ga emas, bo'lak-bo'lak diskka yoziladi va hajmi cheklanadi.
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "300"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

# Bir vaqtda nechta og'ir ish (STT/tarjima/TTS) bajarilishi mumkin.
# Har ish ichida yana 4 ta parallel Whisper so'rovi va ffmpeg jarayoni bo'ladi,
# shuning uchun bu son kichik bo'lishi kerak. Ilgari cheklov umuman yo'q edi:
# 10 ta bir vaqtdagi foydalanuvchi 50+ thread va 10 ta ffmpeg ochib,
# 512 MB / 1 vCPU mashinani OOM qilardi.
MAX_CONCURRENT_JOBS = int(os.getenv("MAX_CONCURRENT_JOBS", "3"))
# Navbatda kutayotganlar chegarasi — undan oshsa foydalanuvchiga darrov
# "hozir band" deb aytamiz (soatlab kutib o'tirmasin).
MAX_QUEUED_JOBS = int(os.getenv("MAX_QUEUED_JOBS", "12"))

# Muhlisa AI STT endpoint — Pro Uzbek tarifi uchun
MUXLISA_URL = "https://service.muxlisa.uz/api/v2/stt"
# Muhlisa cheklovi: 60 sek/request → 50 sek bo'laklar (xavfsizlik buferi)
CHUNK_SECONDS = 50
OVERLAP_SECONDS = 2

HERE       = os.path.dirname(os.path.abspath(__file__))
INDEX_HTML = os.path.join(HERE, "index.html")

bot_app = None

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

# Shovqinli kutubxona loglarini bo'g'amiz. fpdf2 har PDF yasashda
# fontTools'ning ~40 qator INFO logini to'kadi ('maxp pruned', 'glyf
# subsetted' ...) — bu haqiqiy xatolarni deploy logida ko'rinmas qiladi.
for _noisy in ('fontTools', 'fontTools.subset', 'fontTools.ttLib',
               'PIL', 'httpx', 'httpcore', 'urllib3'):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

# ── ADMIN & TARIFLAR KONFIGURATSIYASI ──────────────────────────────────────
# Admin Telegram username (kichik harf, @ siz)
ADMIN_USERNAMES = {"nazokat_571"}

# Tariflar (O'zbek STT uchun)
TARIFFS = {
    "free":           {"name": "🌸 Bepul",                "minutes": 5,    "price": 0},
    # === STANDART tarif (arzon, har qanday uzunlikda) ===
    "basic":          {"name": "💚 Standart Boshlang'ich", "minutes": 180,  "price": 60000},   # 3 soat
    "standart":       {"name": "💙 Standart O'rta",        "minutes": 600,  "price": 150000},  # 10 soat
    "premium":        {"name": "💜 Standart Maxsimum",     "minutes": 1500, "price": 300000},  # 25 soat
    # === PREMIUM tarif (eng yuqori sifat, har qanday uzunlikda) ===
    "pro_standart":   {"name": "⭐ Premium Boshlang'ich",  "minutes": 180,  "price": 170000},  # 3 soat
    "pro_premium":    {"name": "👑 Premium O'rta",         "minutes": 360,  "price": 300000},  # 6 soat
    "pro_max":        {"name": "💎 Premium Maxsimum",      "minutes": 600,  "price": 500000},  # 10 soat
}

# Foydalanuvchi xarajatlarini saqlash {user_id: jami_soniya} — TARIF LIMITI uchun (grant'da 0'ga tushadi)
user_uzbek_usage = {}
# Lifetime ishlatilgan daqiqalar {user_id: jami_soniya} — HECH QACHON 0'ga tushmaydi (statistika uchun)
user_total_usage = {}
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
# === [TXT export] Oxirgi transkripsiya matni — TXT/PDF tugmasi uchun ===
# {user_id: {"text": "...", "ts": timestamp}}
#
# FAQAT RAM. Ilgari bu user_data.json'ga ham yozilardi va natijada har
# transkripsiyada butun JSON (barcha foydalanuvchilarning to'liq matnlari bilan)
# qayta yozilardi — bir necha yuz foydalanuvchida fayl o'nlab MB bo'lib,
# har saqlash sekinlashardi. Matnlar baribir 24 soatlik vaqtinchalik kesh,
# tarif/usage kabi qimmatli ma'lumot emas.
last_transcripts = {}
LAST_TRANSCRIPTS_MAX = 200      # RAM'da ko'pi bilan shuncha yozuv
LAST_TRANSCRIPTS_TTL = 24 * 3600
_transcripts_lock = threading.Lock()


def remember_transcript(user_id, text):
    """Oxirgi matnni RAM'da eslab qolish + eskilarini tozalash."""
    if not text:
        return
    now = time.time()
    with _transcripts_lock:
        last_transcripts[int(user_id)] = {"text": text, "ts": now}
        # Eskirganlarni olib tashlash
        for uid in [u for u, v in last_transcripts.items()
                    if now - v.get("ts", 0) > LAST_TRANSCRIPTS_TTL]:
            last_transcripts.pop(uid, None)
        # Hajm chegarasi — eng eskilaridan boshlab qisqartiramiz
        if len(last_transcripts) > LAST_TRANSCRIPTS_MAX:
            for uid, _ in sorted(last_transcripts.items(), key=lambda kv: kv[1].get("ts", 0))[
                    :len(last_transcripts) - LAST_TRANSCRIPTS_MAX]:
                last_transcripts.pop(uid, None)

# === [PROCESSING TRACKER] User aynan hozir audio yuborganmi (duplicate click oldini olish) ===
# {user_id: (timestamp, token)} — token EGALIK belgisi: faqat belgini qo'ygan
# oqim uni olib tashlay oladi. Busiz uzun ish stale bo'lib, yangi ish belgi
# qo'ygach, ESKI ishning finally'si YANGI ishning belgisini o'chirib yuborardi
# (bitta user ikki parallel ish + ikki marta billing).
processing_users = {}
processing_lock = threading.Lock()
# Stale chegara: 3 soatlik audio STT ~1 soat olishi mumkin. 2 soat — uzun ish
# hali tugamagan bo'lsa belgi ushlab turadi; jarayon o'lsa xotira baribir
# tozalanadi (restart), shuning uchun "abadiy qulf" xavfi yo'q.
PROCESSING_STALE_SEC = int(os.getenv("PROCESSING_STALE_SEC", str(2 * 3600)))
_processing_seq = {"n": 0}


def _is_user_processing(user_id):
    """User aynan hozir audio/url ishlanmoqdami? Duplicate click oldini olish."""
    with processing_lock:
        entry = processing_users.get(user_id)
        if entry is not None:
            if time.time() - entry[0] < PROCESSING_STALE_SEC:
                return True
            # Stale — eski entry, o'chiramiz
            del processing_users[user_id]
        return False


def _try_mark_processing(user_id):
    """ATOMIK check-and-mark. Returns: token (truthy) — belgi qo'yildi,
    None — user band (ish boshlash MUMKIN EMAS).

    NEGA ATOMIK: alohida check + mark ikki thread (PTB loop va aiohttp loop)
    orasida race ochardi — user bir vaqtda Telegram'dan voice va WebApp'dan
    fayl yuborsa, ikkalasi ham o'tib, bitta audio ikki marta hisoblanardi."""
    now = time.time()
    with processing_lock:
        prev = processing_users.get(user_id)
        if prev is not None and now - prev[0] < PROCESSING_STALE_SEC:
            return None
        _processing_seq["n"] += 1
        token = _processing_seq["n"]
        processing_users[user_id] = (now, token)
        return token


def _unmark_processing(user_id, token=None):
    """Belgini olib tashlash. token berilsa — faqat EGASI o'chira oladi
    (stale-takeover'dan keyin eski ish yangi ishning belgisiga tegmaydi)."""
    with processing_lock:
        entry = processing_users.get(user_id)
        if entry is None:
            return
        if token is not None and entry[1] != token:
            return  # belgi endi boshqa ishniki
        processing_users.pop(user_id, None)
# === [JOB QUEUE] Og'ir ishlar uchun YAGONA umumiy pool ==========================
# BITTA ThreadPoolExecutor(MAX_CONCURRENT_JOBS) — WebApp ham, Telegram ham
# og'ir ishni (STT/tarjima/TTS/ffmpeg) faqat shu pool'da bajaradi.
#
# NEGA BITTA: ilgari ikkita mustaqil semafor bor edi (threading — WebApp,
# asyncio — Telegram), ya'ni real cap 2×MAX_CONCURRENT_JOBS bo'lib qolgan edi
# va /debug faqat WebApp tomonini sanardi. Endi cap haqiqiy va yagona.
from concurrent.futures import ThreadPoolExecutor as _TPE
import contextvars

_job_executor = _TPE(max_workers=MAX_CONCURRENT_JOBS, thread_name_prefix="job")
_job_counter_lock = threading.Lock()
_job_stats = {"running": 0, "queued": 0}

BUSY_MESSAGE = (
    "⏳ Sizning oldingi faylingiz hali tayyorlanmoqda.\n"
    "Iltimos tugashini kuting — daqiqalar ortiqcha yechilmasligi uchun."
)
QUEUE_FULL_MESSAGE = (
    "🚦 Hozir server juda band.\n\n"
    "Iltimos 5-10 daqiqadan keyin qayta yuboring.\n"
    "💚 Daqiqa hisobingizdan yechilmadi."
)


def _job_slots_info():
    with _job_counter_lock:
        return _job_stats["running"], _job_stats["queued"]


def _notify_async(user_id, text):
    """Xabarni event loop'ni bloklamasdan yuborish (rad etish holatlari uchun)."""
    threading.Thread(
        target=telegram_send_message, args=(user_id, text), daemon=True
    ).start()


class JobQueueFullError(BaseException):
    """Umumiy og'ir-ish navbati to'la — foydalanuvchiga ochiq rad javobi.

    ATAYLAB BaseException (Exception EMAS): oqimlarning ichki
    `except Exception` bloklari (masalan, process_local_audio'dagi umumiy
    "❌ Xato" handleri) bu signalni yutmasin — u busy_guard'gacha ko'tarilib,
    foydalanuvchi aniq QUEUE_FULL_MESSAGE javobini olishi kerak. Kelajakda
    yoziladigan oqimlar ham maxsus re-raise qo'shishni unutolmaydi."""


async def _run_heavy(fn, *args):
    """Telegram (asyncio) yo'lidagi og'ir sync ishni umumiy pool'da bajarish.

    asyncio.to_thread EMAS: u default executor'ni ishlatadi (cheklovsiz va
    5 ta thread'lik — pool'dan tashqari yuk + delivery starvation bo'lardi);
    bu yerda aynan _job_executor — WebApp ishlari bilan bitta budjet.

    MAX_QUEUED_JOBS: Telegram yo'li ham WebApp bilan bir xil navbat capiga
    bo'ysunadi — aks holda 15 ta Telegram-kutuvchi umumiy hisoblagichni
    to'ldirib, barcha WebApp yuklamalarini 429 bilan qaytarardi, o'zi esa
    cheksiz kutib concurrent_updates slotlarini band qilardi.
    Navbat to'la bo'lsa JobQueueFullError ko'tariladi — busy_guard uni
    QUEUE_FULL_MESSAGE javobiga aylantiradi.
    """
    loop = asyncio.get_running_loop()
    with _job_counter_lock:
        # Cap faqat hali "qabul qilinmagan" oqim uchun (yuqoridagi izohga qarang)
        if not _queue_admitted.get() and _job_stats["queued"] >= MAX_QUEUED_JOBS:
            raise JobQueueFullError()
        _job_stats["queued"] += 1
    _queue_admitted.set(True)

    def _tracked():
        with _job_counter_lock:
            _job_stats["queued"] -= 1
            _job_stats["running"] += 1
        try:
            return fn(*args)
        finally:
            with _job_counter_lock:
                _job_stats["running"] -= 1

    try:
        cfut = _job_executor.submit(_tracked)
    except BaseException:
        # submit'ning o'zi yiqilsa (masalan, shutdown) increment qaytariladi
        with _job_counter_lock:
            _job_stats["queued"] -= 1
        raise
    try:
        return await asyncio.wrap_future(cfut, loop=loop)
    except BaseException:
        # Kutish bekor qilinsa (CancelledError ham) va ish HALI BOSHLANMAGAN
        # bo'lsa, _tracked hech qachon ishlamaydi — queued hisobini shu yerda
        # to'g'rilaymiz, aks holda +1 abadiy qolib, oxir-oqibat hamma
        # so'rovlar "navbat to'la" bilan rad etilardi.
        if cfut.cancel() or cfut.cancelled():
            with _job_counter_lock:
                _job_stats["queued"] -= 1
        raise


# Bitta task ichida busy_guard qayta kirsa (masalan, process_translation
# process_translation_from_file_id orqali chaqirilsa) o'zini bloklamasin.
_busy_owner = contextvars.ContextVar("busy_owner", default=None)

# Navbat capi faqat oqimning BIRINCHI og'ir bosqichida tekshiriladi.
# Ko'p bosqichli oqim (STT -> tarjima -> TTS) birinchi bosqichdan o'tgach,
# keyingi bosqichlari rad etilmaydi — aks holda 60 daqiqalik STT'ga pul
# to'langach, tarjima bosqichi tasodifiy navbat-spike tufayli yiqilib,
# butun natija (va xarajat) bekor ketardi. Har update = yangi task = yangi
# kontekst, shuning uchun qiymat oqimlar orasida sizib o'tmaydi.
_queue_admitted = contextvars.ContextVar("queue_admitted", default=False)


def busy_guard(func):
    """Async flow'ni "bitta user — bitta og'ir ish" qoidasi bilan o'raydi.

    Handler KIRISHIDA (fayl yuklab olishdan OLDIN) atomik belgi qo'yiladi.
    CancelledError'da ham belgi kafolatli olib tashlanadi (finally).
    _run_heavy JobQueueFullError ko'tarsa — foydalanuvchiga navbat-to'la javobi.

    MUHIM: bu yerda is_admin() EMAS, _is_admin_user() — is_admin track_user
    orqali _save_user_data'ni (to'liq JSON + .bak nusxa, lock ostida)
    to'g'ridan-to'g'ri event loop'da chaqirardi."""
    import functools

    async def _call_with_queue_reply(update, *args, **kwargs):
        """Passthrough yo'llari uchun ham JobQueueFullError himoyasi.
        Busiz admin (yoki nested bo'lmagan chetlab o'tish) to'la navbatda
        BaseException'ni PTB'gacha ko'tarib, update jimgina yo'qolardi."""
        try:
            return await func(update, *args, **kwargs)
        except JobQueueFullError:
            try:
                if getattr(update, "message", None):
                    await update.message.reply_text(QUEUE_FULL_MESSAGE)
            except Exception:
                pass
            return None

    @functools.wraps(func)
    async def wrapper(update, *args, **kwargs):
        user = getattr(update, "effective_user", None)
        uid = user.id if user else None
        if uid is None:
            return await _call_with_queue_reply(update, *args, **kwargs)
        if _busy_owner.get() == uid:
            # Nested chaqiruv — tashqi wrapper baribir ushlaydi, o'rab o'tirmaymiz
            return await func(update, *args, **kwargs)
        if _is_admin_user(user):
            # Admin uchun busy-guard yo'q, lekin navbat signali himoyasi BOR
            return await _call_with_queue_reply(update, *args, **kwargs)
        mark_token = _try_mark_processing(uid)
        if not mark_token:
            try:
                if getattr(update, "message", None):
                    await update.message.reply_text(BUSY_MESSAGE)
            except Exception:
                pass
            return None
        ctx_token = _busy_owner.set(uid)
        try:
            return await func(update, *args, **kwargs)
        except JobQueueFullError:
            try:
                if getattr(update, "message", None):
                    await update.message.reply_text(QUEUE_FULL_MESSAGE)
            except Exception:
                pass
            return None
        finally:
            _busy_owner.reset(ctx_token)
            _unmark_processing(uid, mark_token)

    return wrapper


def submit_job(user_id, target, args=(), label="ish", cleanup_path=None):
    """WebApp yo'lidagi og'ir ishni umumiy pool'ga qo'yadi. Returns True — qabul.

    False — duplicate click yoki navbat to'la; foydalanuvchiga xabar chat'ga
    yuboriladi va HTTP handler ham xato status qaytarishi kerak (WebApp toast).

    cleanup_path — rad etilganda o'chiriladigan vaqtinchalik fayl."""

    def _reject(msg):
        if cleanup_path:
            try: os.remove(cleanup_path)
            except Exception: pass
        _notify_async(user_id, msg)
        return False

    # ATOMIK duplicate himoyasi — Telegram yo'lidagi busy_guard bilan bitta
    # processing_users store, shuning uchun user ikki kanaldan bir vaqtda
    # ikkita ish ochib yubora olmaydi.
    mark_token = _try_mark_processing(user_id)
    if not mark_token:
        return _reject(BUSY_MESSAGE)

    with _job_counter_lock:
        if _job_stats["queued"] >= MAX_QUEUED_JOBS:
            _unmark_processing(user_id, mark_token)
            logging.warning(f"🚦 Navbat to'la, rad etildi: user={user_id}, {label}")
            return _reject(QUEUE_FULL_MESSAGE)
        _job_stats["queued"] += 1
        waiting = _job_stats["running"] >= MAX_CONCURRENT_JOBS

    if waiting:
        _notify_async(
            user_id,
            "⏳ Navbatdasiz — server hozir boshqa fayllarni qayta ishlamoqda.\n"
            "Sizniki avtomat boshlanadi, kutib turing."
        )

    def _runner():
        with _job_counter_lock:
            _job_stats["queued"] -= 1
            _job_stats["running"] += 1
        try:
            target(*args)
        except Exception as e:
            logging.error(f"Job xatosi ({label}, user={user_id}): {e}", exc_info=True)
            telegram_send_message(
                user_id,
                f"❌ Kutilmagan xato: {str(e)[:200]}\n\n💚 Daqiqa hisobingizdan yechilmadi."
            )
        finally:
            with _job_counter_lock:
                _job_stats["running"] -= 1
            # MUHIM: belgini (faqat O'ZIMIZNIKINI) olib tashlash
            _unmark_processing(user_id, mark_token)

    try:
        _job_executor.submit(_runner)
    except BaseException:
        with _job_counter_lock:
            _job_stats["queued"] -= 1
        _unmark_processing(user_id, mark_token)
        raise
    return True
# === [/JOB QUEUE] ==============================================================


# === [REFERRAL] Do'st taklif qilish tizimi ===
# Sozlash:
REFERRAL_BONUS_MIN = 5         # Har taklif uchun har ikkalasiga +5 daqiqa
MAX_REFERRALS_PER_USER = 3     # Bitta user max 3 ta odam taklif qila oladi (anti-abuse)
# Ma'lumotlar:
# {user_id: extra_min} — KO'CHIRILGAN qoldiq (carryover) daqiqalar (tarif almashganda)
user_bonus_minutes = {}
# {user_id: extra_min} — faqat DO'ST TAKLIF (referral) bonus daqiqalari (alohida hisob)
user_referral_minutes = {}
# {invited_user_id: inviter_user_id} — kim kimni taklif qilgan (bir marta)
user_referrals = {}
# {invited_user_id: True} — taklif qilingan user bonus'ini olgan bo'lsa (real foydalanish tasdiq)
user_referral_claimed = {}
# === [/REFERRAL] ============================================

# Admin tomonidan /setcard va /setholder orqali sozlanadigan karta ma'lumotlari
# Env variable yo'q bo'lsa yoki adminb buyruq bilan yangilangan bo'lsa shu ishlatiladi.
runtime_settings = {"payment_card": "", "payment_card_holder": ""}
# Admin /test buyrug'i bilan yoqadigan rejim — Whisper API chaqirilmaydi
TEST_MODE = {"on": False}
# Admin chat_id (avtomatik saqlanadi admin botga xabar yuborganda) — to'lov xabarnomasi uchun
ADMIN_CHAT_ID = {"id": None}

# ── PERSISTENCE: usage va tarif ma'lumotlarini JSON faylga saqlash ──────────
# Railway'da volume bo'lsa /data ga, aks holda working dir'ga yoziladi.
# Bot qayta yoqilganda limitlar yo'qolib ketmasligi uchun.
def _resolve_data_file():
    """DATA_FILE yo'lini aniqlash — Railway'da MAJBURIY /data ishlatamiz.
    Railway env'ni o'qimasligini ham hisobga olamiz."""
    # 1) Agar env aniq /data bilan boshlansa — to'g'ri sozlangan
    env_path = os.getenv("DATA_FILE", "").strip()
    if env_path and env_path.startswith("/data"):
        return env_path
    # 2) Railway aniqlangan bo'lsa — /data majburiy (volume mount)
    if os.getenv("RAILWAY_PUBLIC_DOMAIN") or os.getenv("RAILWAY_PROJECT_ID"):
        return "/data/user_data.json"
    # 3) Lokal dev — script directory
    if env_path:
        return env_path
    return os.path.join(HERE, "user_data.json")


DATA_FILE = _resolve_data_file()
print(f"💾 DATA_FILE = {DATA_FILE}")  # Deploy logda ko'rinadi
_save_lock = threading.Lock()

# Oxirgi muvaffaqiyatli yozilgan yozuvlar soni. _save_user_data har chaqiruvda
# butun JSON'ni qayta parse qilmasligi uchun (bu jarayon faylning yagona
# yozuvchisi). "ready" False bo'lsa — hali diskdan o'qib tekshiramiz.
_last_written_counts = {"tariffs": 0, "usage": 0, "info": 0, "ready": False}


def _load_user_data():
    """Bot ishga tushganda saqlangan usage, tariflar va admin_chat_id'ni yuklaydi.
    Agar asosiy fayl buzilgan/yo'q bo'lsa, .bak fayldan tiklab olishga urinadi.
    """
    # 1) Avval asosiy faylni urinish
    data = None
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Validatsiya: minimal struktura tekshiruvi
            if not isinstance(data, dict):
                data = None
                logging.warning(f"⚠️ {DATA_FILE} noto'g'ri formatda")
        except Exception as e:
            logging.warning(f"⚠️ {DATA_FILE} o'qishda xato: {e}")
            data = None

    # 2) Agar asosiy yiqilsa, .bak fayldan urinish
    if data is None:
        bak_path = DATA_FILE + ".bak"
        if os.path.exists(bak_path):
            try:
                with open(bak_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    logging.warning(f"🔁 Asosiy fayl buzilgan — .bak'dan tiklandi: {bak_path}")
                    # .bak'ni asosiy faylga tiklash
                    try:
                        shutil.copy2(bak_path, DATA_FILE)
                    except Exception as e:
                        logging.warning(f"Bak → asosiy copy xato: {e}")
            except Exception as e:
                logging.error(f"❌ .bak fayl ham buzilgan: {e}")
                data = None

    if data is None:
        logging.warning("⚠️ Hech qaysi fayldan yukla bo'lmadi (yangi boshlash)")
        return

    # Buzuq yozuvlar JIMGINA tashlanmasin. Bu bot ma'lumot yo'qotishdan
    # ko'p azob chekkan (shuncha tiklash mexanizmi borligi shundan); fayl
    # qisman buzilsa, foydalanuvchilar yo'qolib, hech kim sezmasdi.
    _skipped = {"n": 0}

    def _skip(kind, key, err):
        _skipped["n"] += 1
        if _skipped["n"] <= 5:
            logging.warning("⚠️ Buzuq yozuv tashlandi [%s] key=%r: %s", kind, key, err)

    try:
        for k, v in (data.get("usage") or {}).items():
            try:
                user_uzbek_usage[int(k)] = int(v)
            except (ValueError, TypeError) as _e:
                _skip("usage", k, _e)
        # Lifetime usage — agar fayl'da yo'q bo'lsa, joriy usage'ni boshlanish nuqtasi qilamiz
        loaded_lifetime = data.get("total_usage") or {}
        if loaded_lifetime:
            for k, v in loaded_lifetime.items():
                try:
                    user_total_usage[int(k)] = int(v)
                except (ValueError, TypeError) as _e:
                    _skip("yozuv", k, _e)
        else:
            # Migration: birinchi marta — joriy usage'ni lifetime'ga ko'chiramiz
            for uid, sec in user_uzbek_usage.items():
                user_total_usage[uid] = sec
            logging.info(f"📊 Lifetime usage migration: {len(user_total_usage)} user")
        for k, v in (data.get("tariffs") or {}).items():
            try:
                if v in TARIFFS:
                    user_tariffs[int(k)] = v
            except (ValueError, TypeError) as _e:
                _skip("yozuv", k, _e)
        # Admin chat_id — bir marta admin /start yuborgach saqlanib qoladi
        saved_admin = data.get("admin_chat_id")
        if saved_admin:
            try:
                ADMIN_CHAT_ID["id"] = int(saved_admin)
            except (ValueError, TypeError) as _e:
                _skip("yozuv", k, _e)
        # Pending payments — deploy'da yo'qolmasligi uchun
        for k, v in (data.get("pending_payments") or {}).items():
            try:
                if v in TARIFFS:
                    pending_payments[int(k)] = v
            except (ValueError, TypeError) as _e:
                _skip("yozuv", k, _e)
        # === [TARJIMA] pending translations — til tanlash holatini saqlash ===
        # Format: {user_id: {"source": "ru", "target": "uz"}} yoki eski format: "ru"
        for k, v in (data.get("pending_translations") or {}).items():
            try:
                if isinstance(v, dict) and v.get("source") in TRANSLATION_LANGS:
                    pending_translations[int(k)] = v
                elif isinstance(v, str) and v in TRANSLATION_LANGS:
                    # Eski format — backward compat
                    pending_translations[int(k)] = {"source": v, "target": "uz"}
            except (ValueError, TypeError) as _e:
                _skip("yozuv", k, _e)
        # === [USERS] user info (username, first_name, last_seen) ===
        for k, v in (data.get("user_info") or {}).items():
            try:
                if isinstance(v, dict):
                    user_info[int(k)] = v
            except (ValueError, TypeError) as _e:
                _skip("yozuv", k, _e)
        # last_transcripts endi diskda SAQLANMAYDI (faqat RAM) — pastdagi
        # remember_transcript izohiga qarang. Eski fayllarda bu maydon bo'lishi
        # mumkin, ataylab e'tiborsiz qoldiramiz.
        # === [REFERRAL] bonus daqiqalar va taklif tizimi ===
        for k, v in (data.get("user_bonus_minutes") or {}).items():
            try:
                user_bonus_minutes[int(k)] = int(v)
            except (ValueError, TypeError) as _e:
                _skip("yozuv", k, _e)
        for k, v in (data.get("user_referral_minutes") or {}).items():
            try:
                user_referral_minutes[int(k)] = int(v)
            except (ValueError, TypeError) as _e:
                _skip("yozuv", k, _e)
        for k, v in (data.get("user_referrals") or {}).items():
            try:
                user_referrals[int(k)] = int(v)
            except (ValueError, TypeError) as _e:
                _skip("yozuv", k, _e)
        for k, v in (data.get("user_referral_claimed") or {}).items():
            try:
                if v:
                    user_referral_claimed[int(k)] = True
            except (ValueError, TypeError) as _e:
                _skip("yozuv", k, _e)
        # Runtime settings (karta raqami va boshqalar) — admin /setcard orqali yangilaydi
        rs = data.get("runtime_settings") or {}
        if isinstance(rs, dict):
            for k in ("payment_card", "payment_card_holder"):
                if k in rs and isinstance(rs[k], str):
                    runtime_settings[k] = rs[k]
        if _skipped["n"]:
            logging.error(
                "⛔ user_data.json'dan %d ta BUZUQ yozuv tashlandi — "
                "ma'lumot qisman yo'qolgan bo'lishi mumkin. Zaxiradan tiklash: /restore",
                _skipped["n"])
            STARTUP_WARNINGS.append((
                "critical",
                f"user_data.json'dan {_skipped['n']} ta buzuq yozuv tashlandi — "
                f"tariflar/hisob qisman yo'qolgan bo'lishi mumkin. /backup faylidan /restore qiling."))
        logging.info(f"📂 user_data.json yuklandi: {len(user_uzbek_usage)} usage, {len(user_tariffs)} tarif, {len(pending_payments)} pending, admin_chat_id={ADMIN_CHAT_ID['id']}, card_set={bool(runtime_settings['payment_card'])}")
    except Exception as e:
        logging.warning(f"user_data.json o'qishda xato: {e}")


def _save_user_data():
    """user_uzbek_usage, user_tariffs va admin_chat_id ni faylga yozadi (atomik).
    XAVFSIZLIK: bo'sh in-memory data eski to'la faylni overwrite qila olmaydi.
    Backup .bak fayl ham saqlanadi."""
    with _save_lock:
        try:
            data = {
                "usage": {str(k): int(v) for k, v in user_uzbek_usage.items()},
                "total_usage": {str(k): int(v) for k, v in user_total_usage.items()},
                "tariffs": {str(k): v for k, v in user_tariffs.items()},
                "admin_chat_id": ADMIN_CHAT_ID["id"],
                "pending_payments": {str(k): v for k, v in pending_payments.items()},
                "pending_translations": {str(k): v for k, v in pending_translations.items()},
                "user_info": {str(k): v for k, v in user_info.items()},
                # last_transcripts ATAYLAB yo'q — u faqat RAM'da (fayl shishmasin)
                "user_bonus_minutes": {str(k): int(v) for k, v in user_bonus_minutes.items()},
                "user_referral_minutes": {str(k): int(v) for k, v in user_referral_minutes.items()},
                "user_referrals": {str(k): int(v) for k, v in user_referrals.items()},
                "user_referral_claimed": {str(k): True for k in user_referral_claimed},
                "runtime_settings": dict(runtime_settings),
            }

            # XAVFSIZLIK 1: ENG QATTIQ himoya — memory diskdan KAMROQ bo'lsa darrov abort.
            # Bu kategoriyalar (tariffs, usage, info) faqat o'sadi, hech qachon kamaymaydi.
            # Shuning uchun memory < disk = ma'lumot yo'qolish belgisi.
            # TEZLIK: bu jarayon faylning YAGONA yozuvchisi — oxirgi yozilgan
            # sonlar keshda; kesh "kamayish" ko'rsatsagina haqiqiy fayl qayta
            # o'qib TASDIQLANADI (kesh eskirgan bo'lishi mumkin), so'ng abort.
            def _dcounts(d):
                return (len(d.get("tariffs") or {}),
                        len(d.get("usage") or {}),
                        len(d.get("user_info") or {}))

            mem_counts = (len(user_tariffs), len(user_uzbek_usage), len(user_info))
            existing = None
            if os.path.exists(DATA_FILE):
                try:
                    if _last_written_counts["ready"]:
                        disk_counts = (_last_written_counts["tariffs"],
                                       _last_written_counts["usage"],
                                       _last_written_counts["info"])
                    else:
                        with open(DATA_FILE, "r", encoding="utf-8") as fexist:
                            existing = json.load(fexist)
                        disk_counts = _dcounts(existing)
                    if any(m < d for m, d in zip(mem_counts, disk_counts)):
                        if existing is None:
                            with open(DATA_FILE, "r", encoding="utf-8") as fexist:
                                existing = json.load(fexist)
                            disk_counts = _dcounts(existing)
                    existing_tariffs, existing_usage, existing_info = disk_counts
                    if any(m < d for m, d in zip(mem_counts, disk_counts)):
                        logging.error(
                            f"🛑 SAVE ABORTED — memory diskdan kam! "
                            f"DISK: tariffs={existing_tariffs}, usage={existing_usage}, info={existing_info} | "
                            f"MEMORY: tariffs={len(user_tariffs)}, usage={len(user_uzbek_usage)}, info={len(user_info)}"
                        )
                        # Memory'ni diskdan to'ldirish — yo'qolgan entries qaytariladi
                        try:
                            # Diskdagilar memory'ga qo'shiladi (memory'dagilar ustivor — yangi o'zgarishlar)
                            for k, v in (existing.get("tariffs") or {}).items():
                                try:
                                    uid = int(k)
                                    if uid not in user_tariffs and v in TARIFFS:
                                        user_tariffs[uid] = v
                                except Exception:
                                    pass
                            for k, v in (existing.get("usage") or {}).items():
                                try:
                                    uid = int(k)
                                    if uid not in user_uzbek_usage:
                                        user_uzbek_usage[uid] = int(v)
                                except Exception:
                                    pass
                            for k, v in (existing.get("user_info") or {}).items():
                                try:
                                    uid = int(k)
                                    if uid not in user_info and isinstance(v, dict):
                                        user_info[uid] = v
                                except Exception:
                                    pass
                            logging.info(f"✅ Memory diskdan to'ldirildi: tariffs={len(user_tariffs)}, usage={len(user_uzbek_usage)}, info={len(user_info)}")
                        except Exception as e2:
                            logging.error(f"Memory to'ldirishda xato: {e2}")
                        return
                except Exception as e_check:
                    logging.debug(f"Save check xato (davom): {e_check}")

            os.makedirs(os.path.dirname(DATA_FILE) or ".", exist_ok=True)

            # XAVFSIZLIK 2: backup .bak fayl (eski versiya saqlanadi)
            if os.path.exists(DATA_FILE):
                try:
                    bak_path = DATA_FILE + ".bak"
                    shutil.copy2(DATA_FILE, bak_path)
                except Exception as e:
                    logging.debug(f"Backup .bak xato: {e}")

            tmp_path = DATA_FILE + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp_path, DATA_FILE)
            # Keshni yangilaymiz — keyingi saqlashda fayl qayta o'qilmaydi
            _last_written_counts.update({
                "tariffs": len(user_tariffs),
                "usage": len(user_uzbek_usage),
                "info": len(user_info),
                "ready": True,
            })
            logging.debug(f"💾 user_data.json saqlandi: {len(user_uzbek_usage)} usage, {len(user_tariffs)} tarif")
        except Exception as e:
            logging.error(f"❌ user_data.json yozishda xato: {e} | DATA_FILE={DATA_FILE}")


# === [TARIFF LOG] Append-only jurnal — har grant darrov yoziladi, hech qachon yo'qolmaydi ===
TARIFF_LOG_FILE = os.path.join(os.path.dirname(DATA_FILE) or ".", "tariff_log.jsonl")

# Startup replay chog'ida jurnal PULLIK tarifni o'zgartirgan holatlar —
# post_init'da adminga xabar qilinadi (jimgina pasayish bo'lmasin).
_replay_downgrades = []


async def _send_backup_snapshot_to_admin(bot, source="grant"):
    """Har grant/approve'dan keyin admin chat'iga TO'LIQ backup yuborish.
    Bu Telegram'da abadiy saqlanadi — Railway disk wipe bo'lsa /restore bilan tiklanadi."""
    if not ADMIN_CHAT_ID["id"]:
        return
    try:
        # 1) Matn snapshot
        paid_users = [(uid, t) for uid, t in user_tariffs.items() if t != "free"]
        lines = [f"🔐 BACKUP (source: {source})"]
        from datetime import datetime
        lines.append(f"Vaqt: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"Paid userlar: {len(paid_users)}\n")
        for uid, tariff in paid_users:
            used = int(user_uzbek_usage.get(uid, 0) / 60)
            lines.append(f"{uid} → {tariff} (used: {used} daq)")
        lines.append("\n💾 Pastdagi faylga REPLY qilib /restore yozing → tiklanadi")
        await bot.send_message(chat_id=ADMIN_CHAT_ID["id"], text="\n".join(lines))

        # 2) TO'LIQ JSON fayl — wipe bo'lsa /restore uchun
        if os.path.exists(DATA_FILE):
            try:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"backup_{ts}.json"
                with open(DATA_FILE, "rb") as f:
                    await bot.send_document(
                        chat_id=ADMIN_CHAT_ID["id"],
                        document=f,
                        filename=filename,
                        caption=f"💾 To'liq backup ({source})",
                    )
            except Exception as e:
                logging.warning(f"Backup file yuborilmadi: {e}")
    except Exception as e:
        logging.warning(f"Backup snapshot yuborilmadi: {e}")


def _append_tariff_log(user_id, tariff_key, source="approve"):
    """Tariff o'zgarishini append-only jurnal'ga yozish — Railway deploy chog'ida ham yo'qolmaydi.
    Har qator: {"uid": 123, "tariff": "pro_max", "ts": 1234567890, "src": "approve"}"""
    try:
        os.makedirs(os.path.dirname(TARIFF_LOG_FILE) or ".", exist_ok=True)
        entry = {"uid": int(user_id), "tariff": tariff_key, "ts": int(time.time()), "src": source}
        with open(TARIFF_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())  # diskka kafolatli yozish
        # Keshni joyida yangilaymiz — bu jarayon faylning yagona yozuvchisi,
        # shuning uchun keyingi get_user_tariff butun faylni qayta o'qimasin
        try:
            st = os.stat(TARIFF_LOG_FILE)
            with _tariff_log_lock:
                if tariff_key in TARIFFS:
                    _tariff_log_cache["map"][int(user_id)] = tariff_key
                _tariff_log_cache["mtime"] = st.st_mtime_ns
                _tariff_log_cache["size"] = st.st_size
        except Exception:
            pass
        logging.info(f"📝 Tariff log: {entry}")
    except Exception as e:
        logging.error(f"❌ Tariff log yozishda xato: {e}")


def _replay_tariff_log():
    """Bot ishga tushganda jurnal'dan eng so'nggi tarif'ni har user uchun tiklash.
    Bu user_data.json'dagi tarif'ni o'rnini bosadi (jurnal ustivor — chunki append-only)."""
    if not os.path.exists(TARIFF_LOG_FILE):
        return 0
    try:
        latest = _get_tariff_log_map()  # {user_id: tariff_key} — eng so'nggi
        # Faqat JSON'dagi tarif farq qilsa, jurnal'dan tiklash
        recovered = 0
        for uid, tariff in latest.items():
            if user_tariffs.get(uid) != tariff:
                json_val = user_tariffs.get(uid, "NONE")
                logging.warning(f"⚠️ Tariff mismatch: user_id={uid}, JSON={json_val}, LOG={tariff} - LOG'dan tiklandi")
                # PULLIK tarif jurnal tomonidan PASAYTIRILSA — bu kutilmagan
                # bo'lishi mumkin (masalan, eski qo'lda-berilgan tarif jurnalda
                # aks etmagan). Adminga startup'da ro'yxat yuboriladi.
                if json_val not in ("NONE", "free") and tariff != json_val:
                    _replay_downgrades.append((uid, json_val, tariff))
                user_tariffs[uid] = tariff
                recovered += 1
        if recovered > 0:
            _save_user_data()
            logging.info(f"✅ Tariff log replay: {recovered} ta user tarifi tiklandi")
        else:
            logging.info(f"✓ Tariff log replay: {len(latest)} entry, hech qaysi tariflanmagan")
        return recovered
    except Exception as e:
        logging.error(f"❌ Tariff log replay xato: {e}")
        return 0


def _append_tariff_log_many(entries, source):
    """Bir nechta jurnal yozuvini BITTA ochish/yozish/fsync bilan qo'shish.
    (Har yozuvga alohida fsync — restore paytida event loop'ni soniyalab
    muzlatardi.)"""
    if not entries:
        return 0
    try:
        os.makedirs(os.path.dirname(TARIFF_LOG_FILE) or ".", exist_ok=True)
        lines = []
        ts = int(time.time())
        for uid, tariff in entries:
            lines.append(json.dumps(
                {"uid": int(uid), "tariff": tariff, "ts": ts, "src": source},
                ensure_ascii=False))
        with open(TARIFF_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(chr(10).join(lines) + chr(10))
            f.flush()
            os.fsync(f.fileno())
        # Keshni ham yangilab qo'yamiz (to'liq qayta o'qish shart bo'lmasin)
        try:
            st = os.stat(TARIFF_LOG_FILE)
            with _tariff_log_lock:
                for uid, tariff in entries:
                    _tariff_log_cache["map"][int(uid)] = tariff
                _tariff_log_cache["mtime"] = st.st_mtime_ns
                _tariff_log_cache["size"] = st.st_size
        except Exception:
            pass
        return len(entries)
    except Exception as e:
        logging.error(f"Tariff log batch yozishda xato: {e}")
        return 0


def _reconcile_tariff_log_with_memory(source="restore"):
    """Xotiradagi tariflarni jurnalga YAKUNIY holat sifatida yozadi.

    Returns: (yozilgan_soni, backup'da_yo'q_paid_userlar_ro'yxati).

    XAVFSIZLIK: backup faylda YO'Q, lekin jurnalda PULLIK bo'lgan userlar
    HECH QACHON avtomatik 'free' qilinmaydi. Eski (stale) backup tiklansa,
    undan keyin to'lov qilgan mijozlar jurnal himoyasida qoladi — admin
    ularni ko'rib, kerak bo'lsa alohida /revoke qiladi. (Ilgari bu funksiya
    ularga avtomat 'free' yozib, jurnal himoyasini zaharlashi mumkin edi.)"""
    log_map = _get_tariff_log_map()
    to_write = []
    # Xotirada bor, jurnalda boshqacha -> jurnalga backup holati yoziladi
    for uid, tariff in list(user_tariffs.items()):
        if log_map.get(uid) != tariff:
            to_write.append((uid, tariff))
    written = _append_tariff_log_many(to_write, source=source)
    # Jurnalda pullik, backup'da yo'q -> TEGMAYMIZ, faqat ro'yxatini qaytaramiz
    absent_paid = sorted(
        uid for uid, tariff in log_map.items()
        if tariff != "free" and uid not in user_tariffs
    )
    if written:
        logging.info(f"🗂 Tariff jurnali moslashtirildi ({source}): {written} yozuv")
    if absent_paid:
        logging.warning(
            f"⚠️ Backup'da yo'q, jurnalda PULLIK userlar (tegilmadi): {absent_paid}"
        )
    return written, absent_paid


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


def _is_admin_user(user):
    """Telegram User obyekti adminmi. YAGONA manba — is_admin va
    _is_admin_callback ikkalasi ham shu funksiyaga tayanadi.

    Tartib:
      1) ADMIN_USER_IDS env sozlangan bo'lsa — FAQAT user.id bo'yicha.
      2) Sozlanmagan bo'lsa — eski username xatti-harakati (backward compat),
         lekin log'da ogohlantirish chiqadi.
    """
    if not user:
        return False
    if ADMIN_USER_IDS:
        return user.id in ADMIN_USER_IDS
    # Fallback — xavfsiz emas: username bo'shatilsa boshqa odam egallashi mumkin
    uname = (user.username or "").lower().lstrip("@")
    if uname in ADMIN_USERNAMES:
        logging.warning(
            "⚠️ Admin username orqali tasdiqlandi. ADMIN_USER_ID env'ni "
            f"sozlang (bu foydalanuvchining ID'si: {user.id})"
        )
        return True
    return False


def is_admin(update):
    """Foydalanuvchi adminmi tekshiradi (user.id — birlamchi, username — zaxira)."""
    track_user(update)  # === [USERS] Har chaqiruvda user'ni saqlaymiz ===
    if not update or not getattr(update, "effective_user", None):
        return False
    if not _is_admin_user(update.effective_user):
        return False
    # Admin chat_id'ini eslab qolamiz — to'lov xabarnomalari uchun
    new_id = update.effective_user.id
    if ADMIN_CHAT_ID["id"] != new_id:
        ADMIN_CHAT_ID["id"] = new_id
        _save_user_data()  # Doimiy saqlash — deploy'lardan o'tib ham qolsin
        logging.info(f"👑 ADMIN_CHAT_ID saqlandi: {new_id}")
    return True


# === [TARIFF LOG KESH] =========================================================
# Ilgari get_user_tariff HAR chaqiruvda butun tariff_log.jsonl faylini o'qirdi.
# Bu funksiya get_user_limit_sec, check_limit_by_user_id, _transcribe_for_user
# ichida, /stats va /openai esa uni HAR user uchun tsiklda chaqiradi —
# ya'ni O(userlar × log qatorlari). Log append-only bo'lgani uchun vaqt o'tgani
# sari sekinlashib borardi.
#
# Endi log bir marta xotiraga o'qiladi va faqat fayl o'zgarganda (mtime/size)
# qayta o'qiladi.
_tariff_log_cache = {"mtime": None, "size": None, "map": {}}
_tariff_log_lock = threading.Lock()


def _get_tariff_log_map_refresh():
    """Kesh eskirgan bo'lsa fayldan qayta o'qiydi (nusxa qaytarmaydi)."""
    try:
        st = os.stat(TARIFF_LOG_FILE)
    except OSError:
        with _tariff_log_lock:
            _tariff_log_cache["map"] = {}
            _tariff_log_cache["mtime"] = None
            _tariff_log_cache["size"] = None
        return
    with _tariff_log_lock:
        if (_tariff_log_cache["mtime"] == st.st_mtime_ns
                and _tariff_log_cache["size"] == st.st_size):
            return
    _get_tariff_log_map()  # to'liq o'qish yo'li keshni yangilaydi


def _get_tariff_log_map():
    """{user_id: oxirgi_tarif} — log fayldan, keshlab. Fayl o'zgarsa yangilanadi.
    NUSXA qaytaradi (iteratsiya xavfsizligi); issiq yakka-kalit yo'l uchun
    _get_tariff_log_entry'ni ishlating."""
    try:
        st = os.stat(TARIFF_LOG_FILE)
    except OSError:
        return {}
    with _tariff_log_lock:
        if (_tariff_log_cache["mtime"] == st.st_mtime_ns
                and _tariff_log_cache["size"] == st.st_size):
            return dict(_tariff_log_cache["map"])
        latest = {}
        _bad_lines = 0
        try:
            with open(TARIFF_LOG_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if entry["tariff"] in TARIFFS:
                            latest[int(entry["uid"])] = entry["tariff"]
                    except Exception:
                        # Buzuq qator = YO'QOLGAN PULLIK TARIF bo'lishi mumkin.
                        # Bu jurnal aynan shu himoya uchun bor, shuning uchun
                        # jimgina o'tib ketmaymiz.
                        _bad_lines += 1
                        continue
        except Exception as e:
            logging.error(f"Tariff log o'qishda xato: {e}")
            return dict(_tariff_log_cache["map"])
        _tariff_log_cache["mtime"] = st.st_mtime_ns
        _tariff_log_cache["size"] = st.st_size
        _tariff_log_cache["map"] = latest
        if _bad_lines:
            logging.error(
                "⛔ tariff_log.jsonl'da %d ta BUZUQ qator — pullik tarif "
                "yo'qolgan bo'lishi mumkin. /stats bilan tekshiring.", _bad_lines)
        logging.info(f"🗂 Tariff log keshi yangilandi: {len(latest)} user")
        # NUSXA qaytaramiz: _append_tariff_log keshni joyida yangilaydi,
        # chaqiruvchi (masalan, reconcile) iteratsiya qilayotgan dict o'rtada
        # o'zgarib ketmasin
        return dict(latest)


def _get_tariff_log_entry(uid):
    """Bitta user uchun jurnal qiymati — NUSXASIZ issiq yo'l.
    get_user_tariff har free-user tekshiruvida chaqiriladi; butun xaritani
    har safar nusxalash (_get_tariff_log_map) u yerda isrof edi."""
    _get_tariff_log_map_refresh()
    with _tariff_log_lock:
        return _tariff_log_cache["map"].get(int(uid))


def get_user_tariff(user_id):
    """Tariff o'qish — memory'dan, agar 'free' yoki yo'q bo'lsa log'dan tekshirish.
    Bu Railway deploy/restart chog'ida tarif yo'qolishini OLDINI OLADI.
    MUHIM: memory'da 'free' bo'lsa ham log'dan paid bo'lsa, log ustivor (wipe'dan keyin)."""
    uid = int(user_id)
    mem_tariff = user_tariffs.get(uid, "free")
    # Agar memory'da paid tariff bo'lsa, darrov qaytaramiz
    if mem_tariff != "free":
        return mem_tariff
    # Memory'da 'free' yoki yo'q — log'dan (keshdan, nusxasiz) tekshirish
    latest_tariff = _get_tariff_log_entry(uid)
    if latest_tariff and latest_tariff != "free":
        logging.warning(
            f"🔁 Tariff log'dan tiklandi: user_id={uid} → {latest_tariff} "
            f"(memory'da {mem_tariff} edi)"
        )
        user_tariffs[uid] = latest_tariff
        return latest_tariff
    return "free"


def _is_user_pro_tariff(user_id):
    """User Premium (pro_*) tarifdami? Muxlisa marshruti va statistika uchun
    YAGONA predikat — test ham aynan shu funksiyani tekshiradi."""
    tariff = get_user_tariff(user_id)
    return tariff.startswith("pro_") or tariff == "pro"


def get_user_bonus_min(user_id):
    """Jami qo'shimcha daqiqalar = ko'chirilgan qoldiq (carryover) + do'st taklif (referral)."""
    return int(user_bonus_minutes.get(user_id, 0)) + int(user_referral_minutes.get(user_id, 0))


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
        user_total_usage[user_id] = user_total_usage.get(user_id, 0) + seconds
        logging.info(f"   ✅ Yangi total: {user_uzbek_usage[user_id]} sek (lifetime: {user_total_usage[user_id]} sek)")
        # Referral bonus — birinchi real foydalanishdan keyin beriladi (anti-fake)
        _try_claim_referral_bonus(user_id)
        _save_user_data()
    else:
        logging.warning(f"   ⚠️ seconds={seconds} musbat emas, daqiqa qo'shilmadi")


# Bir xil grant ikki marta qo'llanmasligi uchun deduplikatsiya oynasi.
# Admin "Tasdiqlash" tugmasini ikki marta bosса (yoki tarmoq qayta yuborsa),
# _activate_tariff_with_carryover ikkinchi marta ishlab, joriy tarifning TO'LIQ
# qoldig'ini carryover sifatida qo'shardi — ya'ni foydalanuvchi ikki barobar
# daqiqa olardi. Endi shu oyna ichidagi takroriy grant e'tiborsiz qoldiriladi.
GRANT_DEDUPE_WINDOW_SEC = 300  # 5 daqiqa
_recent_grants = {}            # {(uid, tariff_key): timestamp}
_grant_lock = threading.Lock()


def _is_duplicate_grant(user_id, tariff_key):
    """Shu user'ga shu tarif yaqinda berilganmi? Berilgan bo'lsa True."""
    key = (int(user_id), tariff_key)
    now = time.time()
    with _grant_lock:
        # Eskirgan yozuvlarni tozalash (dict cheksiz o'smasin)
        for k in [k for k, ts in _recent_grants.items() if now - ts > GRANT_DEDUPE_WINDOW_SEC]:
            _recent_grants.pop(k, None)
        prev = _recent_grants.get(key)
        # Sof vaqt-oynali dedupe. Holatga qarash YO'Q: "joriy tarif boshqa
        # bo'lsa dup emas" sharti eskirgan approve tugmasi (5 daq ichida)
        # boshqa grant ustidan QAYTA ishlashiga yo'l ochardi. /revoke'dan
        # keyin qonuniy qayta berish esa revoke'ning o'zi kalitlarni
        # tozalashi bilan hal qilingan.
        if prev is not None and now - prev <= GRANT_DEDUPE_WINDOW_SEC:
            return True
        _recent_grants[key] = now
        return False


def _activate_tariff_with_carryover(user_id, tariff_key, source, force=False):
    """Yangi tarifni faollashtiradi va joriy tarifning ISHLATILMAGAN daqiqalarini
    yangi tarifga qo'shadi (yo'qolib ketmaydi).

    Hisob: qoldiq = (joriy_tarif_daqiqa + bonus) − ishlatilgan. Bu qoldiq yangi
    bonus bo'lib o'rnatiladi (eski bonus allaqachon qoldiqqa kirgani uchun
    OVERWRITE — qo'shish emas, aks holda ikki marta hisoblanadi).
    'free' tarifdan o'tishda carryover yo'q (bepul daqiqa ko'chirilmaydi).

    Returns: carry_min (int) yoki None — takroriy grant deb rad etilgan bo'lsa.
    force=True — deduplikatsiyani chetlab o'tish (admin ataylab qayta bersa)."""
    uid = int(user_id)
    if not force and _is_duplicate_grant(uid, tariff_key):
        logging.warning(
            f"🛑 Takroriy grant e'tiborsiz qoldirildi: user={uid}, tarif={tariff_key}, "
            f"manba={source} (oxirgi {GRANT_DEDUPE_WINDOW_SEC}s ichida allaqachon berilgan)"
        )
        return None
    carry_min = 0
    try:
        if get_user_tariff(uid) != "free":
            remaining_sec = get_user_limit_sec(uid) - get_user_usage_sec(uid)
            remaining_min = int(max(0, remaining_sec) // 60)
            # Referral bonusi alohida saqlanadi va o'z bucket'ida qoladi —
            # carryover'dan ayiramiz, aks holda ikki marta hisoblanadi.
            ref_min = int(user_referral_minutes.get(uid, 0))
            carry_min = max(0, remaining_min - ref_min)
    except Exception as e:
        logging.warning(f"Carryover hisoblash xato (user {uid}): {e}")
        carry_min = 0

    user_tariffs[uid] = tariff_key
    user_uzbek_usage[uid] = 0
    user_bonus_minutes[uid] = carry_min
    _append_tariff_log(uid, tariff_key, source=source)
    if carry_min > 0:
        logging.info(f"🎁 Carryover: user {uid} → yangi tarif '{tariff_key}' ga +{carry_min} daqiqa ko'chirildi ({source})")
    return carry_min


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

    # Bonus berish — har ikkalasi uchun (referral bucket'ga, carryover'dan alohida)
    user_referral_minutes[user_id] = user_referral_minutes.get(user_id, 0) + REFERRAL_BONUS_MIN
    user_referral_minutes[inviter_id] = user_referral_minutes.get(inviter_id, 0) + REFERRAL_BONUS_MIN
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
    lines.append("• 📄 Lotin va Kirill alifbosida PDF")
    lines.append("• 🔊 PDF → Audio")
    lines.append("")

    def _fmt(key):
        if key not in TARIFFS:
            return None
        t = TARIFFS[key]
        mins = t["minutes"]
        hrs_str = f" ({mins // 60} soat)" if mins >= 60 else ""
        if t["price"] == 0:
            return f"{t['name']} — *{mins} daqiqa* — BEPUL"
        return f"{t['name']} — *{mins} daqiqa{hrs_str}* — *{t['price']:,} so'm*"

    # Bepul
    free_line = _fmt("free")
    if free_line:
        lines.append(free_line)

    # Standart tariflar (arzon)
    lines.append("\n💚 *Standart* (arzon):")
    for k in ("basic", "standart", "premium"):
        line = _fmt(k)
        if line:
            lines.append(line)

    # Premium tariflar (eng yuqori sifat)
    lines.append("\n👑 *Premium* (eng yuqori sifat):")
    for k in ("pro_standart", "pro_premium", "pro_max"):
        line = _fmt(k)
        if line:
            lines.append(line)

    lines.append(
        "\nℹ️ Daqiqalar bir marta beriladi va tugaguncha amal qiladi "
        "(oylik yangilanish yo'q). Yangi tarif olsangiz, eski tarifdagi "
        "ishlatilmagan daqiqalar yangisiga qo'shiladi."
    )
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
    """YOUTUBE_COOKIES env'dan yoki /root/youtube_cookies.txt fayldan cookies oladi."""
    # 1) Env'dan tekshirish
    cookies_text = os.getenv("YOUTUBE_COOKIES", "").strip()
    if cookies_text:
        cookies_path = os.path.join(tempfile.gettempdir(), "yt_cookies.txt")
        try:
            with open(cookies_path, "w", encoding="utf-8") as f:
                f.write(cookies_text)
            return cookies_path
        except Exception as e:
            logging.warning(f"Cookies fayl yaratishda xato: {e}")
    # 2) Tashqi fayl yo'lidan tekshirish
    file_path = os.getenv("YOUTUBE_COOKIES_FILE", "").strip()
    if file_path and os.path.exists(file_path):
        return file_path
    # 3) Standart joydan
    default_path = "/root/youtube_cookies.txt"
    if os.path.exists(default_path):
        return default_path
    return None


def _run_yt_dlp(url, output_template, use_cookies=True, player_client=None):
    """yt-dlp ni har xil parametrlar bilan chaqiradi. Returnlar (returncode, stderr)."""
    cmd = [
        "yt-dlp", "-x",
        "-f", "bestaudio/best",
        "--audio-format", "wav",
        "--no-playlist",
        "--no-warnings",
        "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    ]
    # YouTube imzolarini yechish uchun JS runtime. Docker image'da nodejs bor
    # (Dockerfile'ga qo'shildi); lokal mashinada node bo'lmasa flag'ni
    # bermaymiz — yt-dlp o'zi topganini ishlatadi yoki runtime'siz urinadi.
    if have_cmd("node"):
        cmd.extend(["--js-runtimes", "node"])
    if use_cookies:
        cookies_path = _prepare_cookies_file()
        if cookies_path:
            cmd.extend(["--cookies", cookies_path])
    if player_client:
        cmd.extend(["--extractor-args", f"youtube:player_client={player_client}"])
    # `--` — undan keyingi hamma narsa argument emas, URL deb qabul qilinadi.
    # Busiz "--config-location=..." kabi qiymat yt-dlp parametri bo'lib ketardi.
    cmd.extend(["-o", output_template, "--", url])
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


# yt-dlp o'z-o'zini yangilash — YouTube tez-tez himoyasini o'zgartiradi va
# eski yt-dlp "Sign in to confirm you're not a bot" / extraction xatolari bera
# boshlaydi. Yangi versiya odatda 1-2 kun ichida tuzatadi. Har 6 soatda ko'pi
# bilan bir marta urinamiz (spam bo'lmasin).
_yt_dlp_last_update = {"ts": 0.0}
_YT_DLP_UPDATE_INTERVAL = 6 * 3600


def _try_self_update_yt_dlp():
    """pip orqali yt-dlp'ni yangilashga urinadi. Returns True — yangilandi."""
    now = time.time()
    if now - _yt_dlp_last_update["ts"] < _YT_DLP_UPDATE_INTERVAL:
        return False
    _yt_dlp_last_update["ts"] = now
    try:
        logging.warning("🔄 yt-dlp yangilanmoqda (YouTube himoyasi o'zgargan bo'lishi mumkin)...")
        r = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--no-cache-dir", "-U", "yt-dlp"],
            capture_output=True, text=True, timeout=180,
        )
        if r.returncode == 0:
            logging.info("✅ yt-dlp yangilandi")
            return True
        logging.warning(f"yt-dlp yangilash xato: {(r.stderr or '')[:200]}")
    except Exception as e:
        logging.warning(f"yt-dlp yangilash istisno: {e}")
    return False


def download_audio_from_url(url):
    # Xavfsizlik: faqat http/https. Boshqa sxema (file://, - bilan boshlanuvchi
    # argument va h.k.) yt-dlp'ga umuman yetib bormasin.
    if not isinstance(url, str) or not re.match(r"^https?://", url.strip(), re.I):
        raise Exception("Faqat http:// yoki https:// havolalar qabul qilinadi.")
    url = url.strip()
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

        def _run_attempts():
            res, last_err = None, ""
            for i, attempt in enumerate(attempts):
                logging.info(f"yt-dlp urinish #{i+1}: cookies={attempt['use_cookies']}, player={attempt['player_client']}")
                res = _run_yt_dlp(url, output_template, **attempt)
                if res.returncode == 0:
                    logging.info(f"✅ yt-dlp urinish #{i+1} muvaffaqiyatli")
                    return res, last_err
                last_err = (res.stderr or "").strip()
                # Bot-detection xatosi bo'lsa keyingi strategiya; boshqa xato bo'lsa to'xtaymiz
                low_e = last_err.lower()
                if not ("sign in" in low_e or "not a bot" in low_e or "confirm" in low_e or
                        "http error 403" in low_e or "forbidden" in low_e):
                    return res, last_err
            return res, last_err

        result, last_stderr = _run_attempts()

        # Hamma strategiya yiqildi + xato "YouTube himoyasi" turida bo'lsa —
        # yt-dlp'ni yangilab, BIR marta qayta urinamiz. YouTube himoya
        # o'zgarishlarini yt-dlp yangi versiyalari tezda tuzatadi.
        if result.returncode != 0:
            low_r = last_stderr.lower()
            if ("sign in" in low_r or "not a bot" in low_r or "confirm" in low_r
                    or "unable to extract" in low_r or "signature" in low_r
                    or "http error 403" in low_r):
                if _try_self_update_yt_dlp():
                    result, last_stderr = _run_attempts()

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


# === [PRO UZBEK STT] — Muhlisa AI orqali Uzbek native STT ===
# Faqat "pro_uz" tarifidagi userlar uchun ishlatiladi (user-facing nom: "Pro Uzbek").
# 60 sek/request limit — 50 sek chunklarga ajratamiz.
def _do_muxlisa_request(path, timeout=120):
    """Muhlisa STT API'ga audio bo'lakni yuboradi.
    Returns: requests.Response or raises."""
    with open(path, "rb") as f:
        return requests.post(
            MUXLISA_URL,
            headers={"x-api-key": MUXLISA_KEY},
            files=[("audio", ("audio.wav", f, "audio/wav"))],
            data={"language": "uz"},
            timeout=timeout,
        )


def _transcribe_chunk_muhlisa(chunk_path, max_retries=7):
    """Bitta bo'lakni Muhlisa AI orqali transkripsiya qiladi.
    7 marta retry — uzun audio chunklarning xatosini yo'q qilish uchun."""
    last_error = None
    timeouts = [60, 90, 120, 150, 180, 210, 240]
    backoffs = [1, 2, 4, 8, 15, 30, 60]
    for attempt in range(max_retries):
        timeout = timeouts[min(attempt, len(timeouts) - 1)]
        try:
            response = _do_muxlisa_request(chunk_path, timeout)
            if response.status_code == 200:
                return (response.json().get("text") or "").strip(), None
            err_text = response.text or ""
            err_lower = err_text.lower()
            if response.status_code in (401, 402, 403) or any(
                k in err_lower for k in ("balance", "insufficient", "credit", "quota", "unauthorized", "forbidden")
            ):
                # Fatal — retry foydasiz
                return None, f"HTTP {response.status_code}: {err_text[:200]}"
            last_error = f"HTTP {response.status_code} (urinish {attempt+1}/{max_retries})"
            logging.warning(f"Muhlisa {last_error}, {backoffs[attempt]}s kutamiz")
        except requests.exceptions.Timeout:
            last_error = f"Timeout ({timeout}s) urinish {attempt+1}/{max_retries}"
            logging.warning(f"Muhlisa timeout, {backoffs[attempt]}s kutamiz")
        except requests.exceptions.ConnectionError as e:
            last_error = f"Connection error: {str(e)[:100]} (urinish {attempt+1}/{max_retries})"
            logging.warning(last_error)
        except Exception as e:
            last_error = str(e)[:200]
        if attempt < max_retries - 1:
            time.sleep(backoffs[attempt])
    return None, last_error or "Noma'lum xato"


def transcribe_muhlisa(file_path, progress_cb=None, failed_ranges_out=None):
    """Muhlisa AI orqali Uzbek audio'ni matnga aylantirish.
    Bo'lak hajmi: 50 sek (Muhlisa 60-sek limitiga moslashish uchun).
    progress_cb(current, total) — har bo'lak tugagach.
    failed_ranges_out: list — yiqilgan vaqt oraliqlari to'ldiriladi.
    """
    # WEBAPP_URL sozlanmagan bo'lsa Web ilova qismi umuman ishlamaydi
    if not WEBAPP_URL:
        out.append(("warning",
                    "WEBAPP_URL sozlanmagan — 'Web ilovani ochish' tugmasi "
                    "berkitildi. Bot Telegram ichida TO'LIQ ishlayveradi "
                    "(audio, video, PDF, tarjima). Web ilova ham kerak bo'lsa "
                    ".env faylga WEBAPP_URL=https://... yozing."))

    if not MUXLISA_KEY:
        raise Exception("MUXLISA_KEY sozlanmagan. Pro Uzbek tarifi uchun Railway env qo'shing.")
    if not have_cmd("ffmpeg"):
        raise Exception("ffmpeg topilmadi.")

    # 1) Audio'ni WAV ga aylantiramiz
    wav_path = convert_to_wav(file_path)

    # 2) 50-sek bo'laklar (overlap 2 sek)
    if progress_cb:
        try: progress_cb(0, 0)
        except Exception: pass
    chunks = split_audio(wav_path)  # [(chunk_path, start_sec, end_sec), ...]
    total = len(chunks)
    if total == 0:
        if wav_path != file_path and os.path.exists(wav_path):
            try: os.remove(wav_path)
            except Exception: pass
        return ""

    if progress_cb:
        try: progress_cb(0, total)
        except Exception: pass

    # 3) Parallel ishlash (4 worker)
    from concurrent.futures import ThreadPoolExecutor, as_completed
    chunk_results = {}
    failed_chunks_muhlisa = []  # FINAL PASS uchun
    ch_lookup = {i + 1: ch for i, ch in enumerate(chunks)}  # idx -> (path, start, end)
    completed = {"count": 0}
    completed_lock = threading.Lock()

    def _process_chunk(idx_data):
        idx, chunk_path, start_sec, end_sec = idx_data
        text, err = _transcribe_chunk_muhlisa(chunk_path)
        # Hallucination tekshiruvi — agar Muhlisa bir so'zda qotib qolsa, fail deb belgilash
        if text and _is_chunk_hallucinated(text, 50):
            logging.warning(f"⚠️ Muhlisa bo'lak {idx} hallucination — fail deb belgilanmoqda")
            return idx, None, "Hallucination", start_sec, end_sec
        return idx, text, err, start_sec, end_sec

    try:
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(_process_chunk, (i + 1, ch[0], ch[1], ch[2])): i + 1
                for i, ch in enumerate(chunks)
            }
            for future in as_completed(futures):
                try:
                    idx, text, err, start_sec, end_sec = future.result()
                except Exception as e:
                    idx = futures[future]
                    text, err = None, str(e)[:200]
                    start_sec, end_sec = 0, 0

                with completed_lock:
                    completed["count"] += 1
                    cur = completed["count"]
                if progress_cb:
                    try: progress_cb(cur, total)
                    except Exception: pass

                if text:
                    chunk_results[idx] = text
                elif err:
                    logging.error(f"Muhlisa bo'lak {idx}/{total} yiqildi: {err}")
                    failed_chunks_muhlisa.append((idx, ch_lookup.get(idx), err))
                    if failed_ranges_out is not None and start_sec >= 0 and end_sec > 0:
                        failed_ranges_out.append((start_sec, end_sec, err))

        # MULTI FINAL PASS — 3 marta, har biri ko'proq kutib
        pass_waits = [30, 60, 180]  # 30s/1min/3min — whisper_pass_waits bilan bir xil
        for pass_num, wait_sec in enumerate(pass_waits, 1):
            if not failed_chunks_muhlisa or len(failed_chunks_muhlisa) >= total:
                break  # Hech narsa qoldimagan yoki hammasi yiqilgan — to'xtatamiz
            logging.warning(f"🔁 Muhlisa FINAL PASS {pass_num}/3: {len(failed_chunks_muhlisa)} bo'lak, {wait_sec}s kutamiz...")
            time.sleep(wait_sec)
            still_failed = []
            for failed_idx, failed_info, _ in failed_chunks_muhlisa:
                if not failed_info:
                    continue
                chunk_path_r, start_r, end_r = failed_info
                try:
                    rtext, rerr = _transcribe_chunk_muhlisa(chunk_path_r)
                    if rtext:
                        chunk_results[failed_idx] = rtext
                        logging.info(f"✅ Muhlisa FINAL PASS {pass_num}: bo'lak {failed_idx} tiklandi")
                        if failed_ranges_out is not None:
                            failed_ranges_out[:] = [r for r in failed_ranges_out if not (r[0] == start_r and r[1] == end_r)]
                    else:
                        still_failed.append((failed_idx, failed_info, rerr))
                except Exception as e:
                    logging.error(f"Muhlisa FINAL PASS {pass_num} xato: {e}")
                    still_failed.append((failed_idx, failed_info, str(e)[:100]))
            failed_chunks_muhlisa = still_failed

        # CROSS-MODEL FALLBACK: Muhlisa hali qila olmagan chunklarni Whisper bilan urinish
        # Bu chunk drop'ni butunlay yo'q qiladi — 2 ta turli AI ishlatamiz.
        # Ilgari bu FAQAT OpenAI kaliti bo'lganda ishlardi. Endi mavjud
        # istalgan multipart STT provayderi ishlatiladi (Groq ham), ya'ni
        # OpenAI'siz ham Muxlisa yiqilgan bo'laklari tiklanadi.
        _form = [a for a in _stt_attempts() if a[1] == "form"]
        if failed_chunks_muhlisa and _form:
            _nom_w, _, _model_w, url_w, headers_w, _ts_w, _lg_w = _form[0]
            logging.warning("🔄 CROSS-MODEL FALLBACK: %s ta Muhlisa bo'lagini "
                            "%s bilan urinamiz...", len(failed_chunks_muhlisa), _nom_w)
            for failed_idx, failed_info, _ in failed_chunks_muhlisa:
                if not failed_info:
                    continue
                chunk_path_r, start_r, end_r = failed_info
                try:
                    wtext, werr = _try_transcribe(chunk_path_r, _model_w, "uz",
                                                  url_w, headers_w, start_r,
                                                  want_timestamps=_ts_w,
                                                  supported_langs=_lg_w)
                    if wtext:
                        chunk_results[failed_idx] = wtext
                        logging.info(f"✅ CROSS-MODEL: bo'lak {failed_idx} Whisper bilan tiklandi")
                        if failed_ranges_out is not None:
                            failed_ranges_out[:] = [r for r in failed_ranges_out if not (r[0] == start_r and r[1] == end_r)]
                except Exception as e:
                    logging.error(f"CROSS-MODEL Whisper xato: {e}")
    finally:
        # Bo'lak fayllarni o'chirish
        for ch in chunks:
            if ch[0] != wav_path and os.path.exists(ch[0]):
                try: os.remove(ch[0])
                except Exception: pass
        if wav_path != file_path and os.path.exists(wav_path):
            try: os.remove(wav_path)
            except Exception: pass

    # Natijalarni tartibda yig'ish
    results = [chunk_results[k] for k in sorted(chunk_results.keys())]
    final_text = " ".join(r for r in results if r).strip()
    # Hallucination tozalash — bir so'z 80 marta qaytarilishini oldini oladi
    final_text = _clean_whisper_hallucination(final_text)
    return final_text


# Muhlisa (~500 so'm/daq) Whisper'dan (~75 so'm/daq) ~7 barobar qimmat.
# Shuning uchun u FAQAT Premium (pro_*) tariflar uchun — ular buning uchun to'lagan.
# Ilgari bepul userlar ham Muhlisa'ga tushardi: har bepul user ~2500 so'm zarar,
# pullik Standart userlar esa arzon engine olardi. Bu teskari mantiq edi.
# Kerak bo'lsa eski holatga qaytarish: MUXLISA_FOR_FREE=1 env qo'shing.
MUXLISA_FOR_FREE = os.getenv("MUXLISA_FOR_FREE", "").strip().lower() in ("1", "true", "yes")


def _transcribe_for_user(user_id, file_path, language="uz", progress_cb=None, failed_ranges_out=None):
    """User tarifiga qarab to'g'ri STT'ga yo'naltiradi.
    PREMIUM tarif (pro_*) + Uzbek → Muhlisa AI (eng yuqori sifat, qimmat).
    Qolgan hamma holat → OpenAI Whisper.
    """
    tariff = get_user_tariff(user_id)
    use_muxlisa = _is_user_pro_tariff(user_id) or (MUXLISA_FOR_FREE and tariff == "free")
    if use_muxlisa and language == "uz" and MUXLISA_KEY:
        logging.info(f"🌟 Muhlisa STT (tarif={tariff}) user_id={user_id}")
        try:
            return transcribe_muhlisa(file_path, progress_cb, failed_ranges_out)
        except Exception as e:
            logging.error(f"Muhlisa STT yiqildi: {e}. OpenAI Whisper fallback...")
    return transcribe_unified(file_path, progress_cb, language, failed_ranges_out)
# === [/PRO UZBEK STT] =================================================


# Eski transcribe() funksiyasi olib tashlandi — endi faqat OpenAI Whisper ishlatamiz.


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



# O'zbek Lotin → Kirill: ko'p belgili (digraf) tokenlar (o'/g' alohida ishlanadi)
_UZ_CYR_MULTI = {
    "sh": "ш", "ch": "ч",
    "yo": "ё", "yu": "ю", "ya": "я", "ye": "е",
    "ts": "ц",
}
# Bir belgili tokenlar ('e' kontekst bo'yicha alohida ishlanadi)
_UZ_CYR_SINGLE = {
    "a": "а", "b": "б", "c": "с", "d": "д", "f": "ф", "g": "г", "h": "ҳ",
    "i": "и", "j": "ж", "k": "к", "l": "л", "m": "м", "n": "н", "o": "о",
    "p": "п", "q": "қ", "r": "р", "s": "с", "t": "т", "u": "у", "v": "в",
    "w": "в", "x": "х", "y": "й", "z": "з",
}


def _apply_cyr_case(latin_tok, cyr):
    """Lotin tokenining katta-kichikligini Kirill ekvivalentiga ko'chiradi."""
    if len(latin_tok) > 1 and latin_tok.isupper():
        return cyr.upper()
    if latin_tok[:1].isupper():
        return cyr[:1].upper() + cyr[1:]
    return cyr


# Kirillga o'tkazishda TEGILMAYDIGAN tokenlar: havola, email, @mention,
# #hashtag va fayl nomlari. Transliteratsiya ularni ISHLATIB BO'LMAYDIGAN
# holga keltiradi: "https://youtu.be/x" -> "ҳттпс://ёуту.бе/х".
# Ma'ruzalarda havola va pochta manzili tez-tez uchraydi.
_PROTECTED_TOKEN_RE = re.compile(
    r"(https?://\S+|www\.\S+"
    r"|[\w.+-]+@[\w-]+\.[\w.-]+"
    r"|[@#][A-Za-z0-9_]{2,}"
    r"|\b[\w-]+\.(?:com|net|org|uz|ru|io|me|pdf|mp3|mp4|txt|jpg|png)\b)",
    re.IGNORECASE,
)


def convert_latin_to_cyrillic(text):
    """O'zbek Lotin alifbosidagi matnni Kirill alifbosiga DETERMINISTIK o'tkazadi.

    Aniq qoidalar jadvali — bir zumda, bepul, hech qanday drift yo'q (GPT emas).
    • o' → ў, g' → ғ (avval, 'yo'q' → йўқ to'g'ri chiqishi uchun)
    • sh → ш, ch → ч, yo/yu/ya → ё/ю/я, ye → е, ts → ц
    • 'e' so'z boshida → э, aks holda → е
    • raqamlar, tinish belgilari, allaqachon kirill bo'lgan belgilar — o'zgarmaydi
    """
    if not text or not text.strip():
        return text

    # 0) Havola/email/@mention'larni HIMOYA qilamiz (yuqoridagi izoh).
    #    Almashtiruvchi ⟦N⟧ - lotin harfi emas, shuning uchun
    #    transliteratsiyadan o'zgarmasdan omon qoladi.
    _protected = []

    def _stash(m):
        _protected.append(m.group(0))
        return "⟦" + str(len(_protected) - 1) + "⟧"

    text = _PROTECTED_TOKEN_RE.sub(_stash, text)

    # 1) Apostroflarni standartlashtirish (tipografik variantlar → ASCII ')
    text = _normalize_uzbek_apostrophes(text)
    for ch in ("ʻ", "ʼ", "‘", "’", "´", "`"):
        text = text.replace(ch, "'")

    # 2) o'/g' ni OLDIN kirillga o'tkazamiz (digraf skanidan oldin)
    text = (text.replace("O'", "Ў").replace("o'", "ў")
                .replace("G'", "Ғ").replace("g'", "ғ"))

    # 3) Chapdan-o'ngga skanlash
    out = []
    i, n = 0, len(text)
    while i < n:
        two = text[i:i + 2].lower()
        if two in _UZ_CYR_MULTI:
            out.append(_apply_cyr_case(text[i:i + 2], _UZ_CYR_MULTI[two]))
            i += 2
            continue
        ch = text[i]
        low = ch.lower()
        if low == "e":
            prev = text[i - 1] if i > 0 else ""
            word_initial = (i == 0) or (not prev.isalpha() and prev not in ("'", "ў", "ғ", "Ў", "Ғ"))
            out.append(_apply_cyr_case(ch, "э" if word_initial else "е"))
            i += 1
            continue
        if low in _UZ_CYR_SINGLE:
            out.append(_apply_cyr_case(ch, _UZ_CYR_SINGLE[low]))
            i += 1
            continue
        # noma'lum belgi (raqam, tinish, kirill, arab, h.k.) — o'zgarmaydi
        out.append(ch)
        i += 1
    result = "".join(out)
    # Himoyalangan tokenlarni joyiga qaytaramiz
    if _protected:
        result = re.sub(
            r"⟦(\d+)⟧",
            lambda mm: _protected[int(mm.group(1))],
            result,
        )
    return result


def make_pdf(text, title="Audio & Konspekt — Matn"):
    """Matnni PDF qiladi va vaqtinchalik fayl yo'lini qaytaradi.
    DejaVuSans yoki Noto Sans Unicode fontidan foydalanadi —
    o'zbek o'/g', arab yozuvi va boshqa Unicode belgilarini to'g'ri ko'rsatadi."""
    text = _normalize_uzbek_apostrophes(text)
    pdf = FPDF()
    pdf.add_page()
    pdf.set_title(title)

    body_font = _find_font()

    if body_font:
        pdf.add_font("Body", "", body_font)
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


def extract_pdf_text(pdf_path, failed_pages_out=None):
    """PDF faylidan matn ajratib oladi.
    Har sahifa alohida ekstrakt qilinadi — bittasi yiqilsa boshqalari saqlanadi.
    failed_pages_out: list pass qilsangiz, yiqilgan sahifa raqamlari to'ldiriladi.
    """
    try:
        reader = pypdf.PdfReader(pdf_path)
        parts = []
        total_pages = len(reader.pages)
        for page_num, page in enumerate(reader.pages, 1):
            # Har sahifa uchun 7 marta urinish — turli usullar bilan
            extracted = None
            for attempt in range(7):
                try:
                    # Har xil ekstrakt parametrlari bilan urinamiz
                    if attempt < 3:
                        t = page.extract_text() or ""
                    elif attempt < 5:
                        # Layout-aware mode (ba'zi PDF'larda yaxshiroq ishlaydi)
                        t = page.extract_text(extraction_mode="layout") or ""
                    else:
                        # Visitor-based extraction (boshqa yo'l)
                        chars = []
                        def visit_text(text, cm, tm, fontDict, fontSize):
                            chars.append(text)
                        try:
                            page.extract_text(visitor_text=visit_text)
                            t = "".join(chars)
                        except Exception:
                            t = page.extract_text() or ""
                    if t and t.strip():
                        extracted = t
                        break
                    if attempt < 6:
                        time.sleep(0.5)
                except Exception as e:
                    if attempt == 6:
                        logging.warning(f"PDF sahifa {page_num}/{total_pages} 7 marta yiqildi: {e}")
                        if failed_pages_out is not None:
                            failed_pages_out.append(page_num)
                    else:
                        time.sleep(0.5)
            if extracted and extracted.strip():
                # Sahifa boshiga marker qo'shamiz (tarjima chog'ida tushib qolsa aniqlash uchun)
                parts.append(extracted.strip())
        full = "\n\n".join(parts)
        logging.info(f"PDF ekstrakt: {total_pages} sahifa, {len(parts)} muvaffaqiyatli, {len(failed_pages_out or [])} yiqilgan")
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


def _concat_mp3(chunk_paths, out_path):
    """Bir nechta MP3 bo'lakni BITTA to'g'ri MP3 faylga birlashtiradi.

    Xom bayt-birlashtirish (write(read())) faylning duration sarlavhasini buzadi —
    Telegram pleer faqat birinchi bo'lak davomiyligini o'qib, audioni o'rtasida
    to'xtatadi. ffmpeg concat demuxer to'g'ri uzluksiz oqim va to'g'ri davomiylik
    yozadi. ffmpeg bo'lmasa yoki xato bo'lsa — xom birlashtirishga qaytadi.
    """
    valid = [p for p in chunk_paths if p and os.path.exists(p) and os.path.getsize(p) > 0]
    if not valid:
        return False
    if len(valid) == 1:
        try:
            shutil.copyfile(valid[0], out_path)
            return True
        except Exception:
            pass

    if have_cmd("ffmpeg"):
        list_file = None
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as lf:
                list_file = lf.name
                for p in valid:
                    safe = p.replace("\\", "/").replace("'", "'\\''")
                    lf.write(f"file '{safe}'\n")
            # -c copy yetarli: hamma bo'lak bir xil edge-tts kodek/bitrate.
            # Xavfsizlik uchun re-encode (libmp3lame) — har doim to'g'ri header beradi.
            result = subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                 "-i", list_file, "-c:a", "libmp3lame", "-q:a", "4", out_path],
                capture_output=True, text=True, timeout=300
            )
            if result.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 100:
                return True
            logging.warning(f"ffmpeg concat xato (rc={result.returncode}): {(result.stderr or '')[:200]}")
        except Exception as e:
            logging.warning(f"ffmpeg concat istisno: {e}")
        finally:
            if list_file:
                try: os.remove(list_file)
                except Exception: pass

    # Fallback — xom bayt-birlashtirish (duration buzilishi mumkin, lekin to'liq)
    try:
        with open(out_path, "wb") as out_f:
            for p in valid:
                with open(p, "rb") as in_f:
                    out_f.write(in_f.read())
        return os.path.getsize(out_path) > 100
    except Exception as e:
        logging.error(f"Xom MP3 birlashtirish xato: {e}")
        return False


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
        """Bitta bo'lakni TTS qiladi va vaqtinchalik fayl yo'lini qaytaradi.
        Edge API beqaror — har bo'lak 3 marta urinib ko'riladi. Aks holda
        yiqilgan bo'lak jimgina tushib qolib, audio 'oxirigacha bormaydi'."""
        async with semaphore:
            for attempt in range(1, 4):
                chunk_path = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False).name
                try:
                    comm = edge_tts.Communicate(ch, voice)
                    await asyncio.wait_for(comm.save(chunk_path), timeout=90)
                    if os.path.exists(chunk_path) and os.path.getsize(chunk_path) > 0:
                        if attempt > 1:
                            logging.info(f"   ✅ bo'lak {idx+1}/{len(chunks)} tayyor ({attempt}-urinish)")
                        else:
                            logging.info(f"   ✅ bo'lak {idx+1}/{len(chunks)} tayyor")
                        return (idx, chunk_path)
                    raise Exception("bo'sh fayl (NoAudioReceived?)")
                except asyncio.TimeoutError:
                    logging.warning(f"   ⏱ bo'lak {idx+1} timeout (90s) — urinish {attempt}/3")
                except Exception as e:
                    logging.warning(f"   ❌ bo'lak {idx+1} xato (urinish {attempt}/3): {e}")
                try: os.remove(chunk_path)
                except Exception: pass
                if attempt < 3:
                    await asyncio.sleep(1.5 * attempt)
            logging.error(f"   ⛔ bo'lak {idx+1}/{len(chunks)} 3 urinishdan keyin ham yiqildi")
            return (idx, None)

    async def _run():
        # 4 ta bo'lak parallel (Edge API rate limit hisobi bilan)
        semaphore = asyncio.Semaphore(4)
        tasks = [_tts_chunk(i, ch, semaphore) for i, ch in enumerate(chunks) if ch]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        # Tartibni saqlab birlashtiramiz
        results.sort(key=lambda x: x[0])
        ok = sum(1 for _, cp in results if cp)
        if ok < len(results):
            logging.warning(f"⚠️ Edge TTS: {len(results)-ok}/{len(results)} bo'lak yiqildi — audio to'liq bo'lmasligi mumkin")
        chunk_files = [cp for idx, cp in results if cp and os.path.exists(cp)]
        # ffmpeg bilan to'g'ri birlashtirish (duration sarlavhasi buzilmaydi)
        _concat_mp3(chunk_files, out_path)
        for cp in chunk_files:
            try: os.remove(cp)
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
    chunk_files = []
    try:
        # Har bir bo'lakni alohida MP3 faylga TTS qilamiz
        for i, ch in enumerate(chunks, 1):
            if not ch:
                continue
            try:
                mp3_bytes = _openai_tts_chunk(ch, voice)
                cf = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False).name
                with open(cf, "wb") as f:
                    f.write(mp3_bytes)
                chunk_files.append(cf)
            except Exception as e:
                logging.warning(f"OpenAI TTS bo'lak {i}/{len(chunks)} xato: {e}")
                # Agar 1 ta bo'lak buzilsa, qolganlari hali yoziladi
                if i == 1:
                    raise  # birinchi bo'lak ham yiqilsa, butun fayl yo'q
        # ffmpeg bilan to'g'ri birlashtirish (duration sarlavhasi buzilmaydi)
        _concat_mp3(chunk_files, out_path)
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
    finally:
        for cf in chunk_files:
            try: os.remove(cf)
            except Exception: pass


def estimate_tts_duration_sec(text):
    """Matndan hosil bo'ladigan audio davomiyligini OLDINDAN baholaydi.

    Nega kerak: ilgari avval TTS to'liq generatsiya qilinar, KEYIN limit
    tekshirilardi. Limitga sig'masa foydalanuvchidan yechilmasdi, lekin
    OpenAI TTS puli allaqachon sarflangan bo'lardi — daqiqasi tugagan
    foydalanuvchi katta matnlarni qayta-qayta yuborib xarajat keltira olardi.

    Baho: ~14 belgi/sekund (o'rtacha nutq tezligi, o'zbek/rus uchun mos).
    Ataylab ehtiyotkor (past) baho — real audio biroz uzunroq chiqishi mumkin,
    yakuniy aniq hisob baribir yuborishdan keyin qilinadi.
    """
    if not text:
        return 0
    return max(1, int(len(text.strip()) / 14))


def make_tts(text, lang=None, force_engine=None):
    """Matnni ovozli MP3 ga aylantiradi.
    Strategiya:
      • O'zbek (uz): Edge TTS (bepul, sifatli, Madina ovozi)
      • Boshqa tillar (ru/en/ar): OpenAI TTS → Edge fallback

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

    # === O'zbek (uz): Edge TTS (bepul, sifatli) ===
    try:
        return make_tts_edge(text, lang)
    except Exception as e:
        logging.warning(f"Edge TTS yiqildi (uz): {e}")
        return None


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

def transcribe_unified(file_path, progress_cb=None, language="uz", failed_ranges_out=None):
    """Audio/video'ni matnga aylantirish — FAQAT Whisper/gpt-4o-transcribe (OpenAI) orqali.

    progress_cb(current, total) — har bo'lak tugagach chaqiriladi.
    failed_ranges_out: list pass qilsangiz, yiqilgan bo'lak vaqt oraliqlari to'ldiriladi:
        [(start_sec, end_sec, error), ...]
    """
    if not _stt_attempts():
        raise Exception("STT provayderi sozlanmagan — GROQ_API_KEY (bepul) "
                        "yoki OPENAI_API_KEY qo'shing.")

    # 1) STT — progress_cb ni transcribe_whisper'ga uzatamiz
    text = transcribe_whisper(file_path, language, progress_cb, failed_ranges_out) or ""

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

WHISPER_CHUNK_SECONDS = 180    # 3 daqiqa per chunk (kichik = hallucination kam, aniqlik yuqori)
WHISPER_CHUNK_OVERLAP = 30     # Har bo'lak oxirgi 30 sek keyingisi bilan birlashadi (qirralar yo'qolmaydi)

# Sifat nazorati: butun provayder zanjiri necha marta takrorlansin.
# Sifatsiz natija yetkazilmaydi — o'rniga qayta urinib ko'riladi.
STT_QUALITY_ROUNDS = max(1, int(os.getenv("STT_QUALITY_ROUNDS", "3")))
STT_ROUND_WAITS = [5, 20, 45]   # turlar orasidagi kutish (soniya)

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
    # NOTE: 'uz' QO'SHMA! Whisper API "unsupported_language" HTTP 400 qaytaradi.
    # O'zbek uchun avto-aniqlash + GPT-4o cleanup ishlatamiz.
}
# Groq'ning whisper-large-v3 o'zbekni QO'LLAB-QUVVATLAYDI va language=uz
# YUBORILMASA o'zbek nutqini ARAB YOZUVIDA qaytaradi (amalda o'lchandi:
# "اسلام علیکم حرمتلی طلباله" = "assalomu alaykum hurmatli talabalar").
# Shuning uchun Groq uchun ro'yxat ALOHIDA — 'uz' bilan.
GROQ_STT_LANGS = WHISPER_SUPPORTED_LANGS | {"uz"}

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
    # Yaxshilangan audio filter:
    # - highpass=80Hz — past chastotali shovqin (vibratsiya, electric hum)
    # - lowpass=12000Hz — yuqori chastotali shovqin (whistle, hiss)
    # - afftdn=nr=12 — FFT noise reduction (shovqin pasaytirish)
    # - loudnorm — normallashtirish (jim/baland ovozni tenglashtirish)
    audio_filter = (
        "highpass=f=80,"
        "lowpass=f=12000,"
        "afftdn=nr=12,"
        "loudnorm=I=-16:LRA=11:TP=-1.5"
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

    # Davomiylikni aniqlaymiz — bo'laklash QARORI uchun (size emas, VAQT muhim).
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

    # === Qadam 2: qisqa audio (<=chunk_seconds VA <=limit) — bitta fayl ===
    # MUHIM: uzun audioni bitta so'rovda yuborish modelni to'liq transkripsiya
    # qilishga majburlamaydi (oxirini tashlab ketadi). Shuning uchun VAQT bo'yicha
    # ham bo'laklaymiz — har bo'lak alohida, ishonchli va to'liq tanilaadi.
    if duration_sec <= chunk_seconds and new_size_mb <= WHISPER_MAX_FILE_MB:
        logging.info(f"   → 1 ta fayl yetarli (dur={duration_sec}s)")
        return [recoded_path]

    # === Qadam 3: uzun yoki katta fayl — vaqt bo'yicha bo'laklash ===
    logging.info(f"   → vaqt bo'yicha bo'laklash (dur={duration_sec}s, {new_size_mb:.1f}MB)")
    return _split_by_time(recoded_path, chunk_seconds, duration_sec)


# Audio qancha bo'lakka bo'linishi mumkin. 180 sek chunk bilan 100 ta = 5 soat.
MAX_AUDIO_CHUNKS = 100


def _split_by_time(file_path, chunk_seconds, total_dur):
    """Audio'ni vaqt bo'yicha bo'laklarga ajratish (overlap bilan).
    Har bo'lak `chunk_seconds + WHISPER_CHUNK_OVERLAP` davom etadi.
    Boshlanish nuqtasi: i * chunk_seconds (overlap'siz).
    Bu — keyingi bo'lak chetida kesilgan so'zlar to'liq saqlanadi.
    Eslatma: file_path AVVAL qayta kodlangan bo'lishi kerak (64kbps mono)."""
    n_chunks = int(total_dur // chunk_seconds) + (1 if total_dur % chunk_seconds > 0 else 0)
    # Xavfsizlik chegarasi: max 100 bo'lak. 180 sek chunk bilan bu = 5 soat.
    # Undan uzun audio KESILADI — buni jimgina qilmaymiz, chaqiruvchi
    # foydalanuvchini ogohlantirishi uchun global holatga yozib qo'yamiz.
    if n_chunks > MAX_AUDIO_CHUNKS:
        covered_sec = MAX_AUDIO_CHUNKS * chunk_seconds
        logging.warning(
            f"⚠️ Audio juda uzun ({total_dur/3600:.1f} soat) — faqat birinchi "
            f"{covered_sec/3600:.1f} soat qayta ishlanadi"
        )
    n_chunks = max(1, min(n_chunks, MAX_AUDIO_CHUNKS))
    chunks = []
    tmp_dir = tempfile.mkdtemp(prefix="whisper_chunks_")
    logging.info(f"🔪 vaqt bo'yicha bo'laklash: {n_chunks} ta bo'lak (overlap {WHISPER_CHUNK_OVERLAP}s)")
    for i in range(n_chunks):
        start = i * chunk_seconds
        # Oxirgi bo'lakda overlap kerak emas; boshqalarda overlap qo'shiladi
        is_last = (i == n_chunks - 1)
        duration = chunk_seconds if is_last else (chunk_seconds + WHISPER_CHUNK_OVERLAP)
        out_path = os.path.join(tmp_dir, f"chunk_{i:03d}.mp3")
        # Fayl allaqachon kodlangan — copy stream tezroq
        cmd = [
            "ffmpeg", "-y", "-v", "error",
            "-ss", str(start),
            "-i", file_path,
            "-t", str(duration),
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
                    "-t", str(duration),
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


# Whisper jim/shovqinli audioda o'zi o'ylab topadigan MASHHUR shablon
# iboralar. Ular BIR MARTA chiqadi (odatda oxirida), shuning uchun takror
# tozalash ularni ushlamaydi va PDF oxirida "Subtitles by the Amara.org
# community" bo'lib qolib ketadi. Ro'yxat ATAYLAB tor: faqat butun gap
# sifatida turgan, hujjatlashtirilgan artefaktlar — qonuniy matn o'chmasin.
_WHISPER_BOILERPLATE = [
    "subtitles by the amara.org community",
    "subtitles by the amara org community",
    "amara.org community",
    "thanks for watching",
    "thank you for watching",
    "thanks for watching!",
    "please subscribe",
    "subscribe to my channel",
    "like and subscribe",
    "see you next time",
    "transcription by eso",
    "translated by",
    "продолжение следует",
    "субтитры создавал",
    "редактор субтитров",
    "спасибо за просмотр",
]


def _strip_whisper_boilerplate(text):
    """Whisper o'ylab topgan shablon iboralarni olib tashlaydi.

    Faqat BUTUN GAP (yoki qator) shablonga to'g'ri kelsa o'chiriladi —
    ibora haqiqiy jumla ichida uchrasa TEGILMAYDI. Bu qonuniy matnni
    yo'qotmaslik uchun ataylab konservativ."""
    if not text:
        return text
    removed = []
    out_lines = []
    for line in text.split("\n"):
        parts = re.split(r"(?<=[.!?])\s+", line)
        keep = []
        for part in parts:
            probe = re.sub(r"[^\w\s.]", "", part.lower()).strip().strip(".").strip()
            # Faqat butun bo'lak shablon bo'lsa o'chiramiz. startswith
            # ATAYLAB qisqa bo'laklar bilan cheklangan (<=90 belgi):
            # uzun paragraf tasodifan shablon bilan boshlansa,
            # qonuniy matn yo'qolib ketmasin.
            is_boiler = probe and any(
                probe == b or (len(probe) <= 90 and probe.startswith(b))
                for b in _WHISPER_BOILERPLATE
            )
            if is_boiler:
                removed.append(part.strip())
                continue
            keep.append(part)
        out_lines.append(" ".join(x for x in keep if x.strip()))
    result = "\n".join(out_lines)
    if removed:
        logging.info("🧹 Whisper shablon iboralari olib tashlandi: %s",
                     "; ".join(removed[:3])[:160])
    return result.strip()


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

    # === 0.5-daraja: shablon artefaktlar (bir marta chiqadi, takror emas) ===
    text = _strip_whisper_boilerplate(text)

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
    if not text or not _has_any_ai_key():
        return text
    # Uzun matn — chunklash kerak.
    # MUHIM: bitta gpt-4o chaqiruvi max 16k token chiqaradi. Uzun matnni butunlay
    # yuborsak, chiqish kesilib darsning OXIRI yo'qoladi (audio ham kalta chiqadi).
    # Shu sabab 9000 belgidan oshsa — bo'laklab tozalaymiz (har bo'lak xavfsiz sig'adi).
    if len(text) > 9000:
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
        logging.info(f"🧹 Uzun matn ({len(text)} belgi) → {len(chunks)} bo'lakda tozalanadi")
        cleaned_parts = []
        for ch in chunks:
            cleaned_parts.append(_cleanup_uzbek_transcript_chunk(ch))
        return "\n\n".join(cleaned_parts)
    return _cleanup_uzbek_transcript_chunk(text)


def _cleanup_uzbek_transcript_chunk(text):
    """Bitta chunk uchun cleanup."""
    if not text or not _has_any_ai_key():
        return text

    logging.info(f"🧹 Uzbek transkripsiyani GPT bilan tozalash ({len(text)} belgi)...")
    # MUHIM (xavfsizlik): bu prompt ATAYLAB konservativ.
    # Ilgari u modelga "if a word makes no sense, REPLACE with sensible Uzbek word",
    # "use context to reconstruct meaning" deb ochiq ruxsat berardi va ayni paytda
    # "output length MUST be close to input" deb talab qilardi — ya'ni model
    # tushunmagan joyni O'YLAB TOPIB to'ldirishga majbur bo'lardi.
    # Bu bot asosan diniy ma'ruzalar (hadis, oyat, ulamo nomlari) bilan ishlaydi;
    # o'ylab topilgan so'z hadis matniga aylanib qolishi mumkin edi va
    # foydalanuvchi buni asl matndan ajrata olmasdi.
    # Endi model FAQAT orfografiya/alifbo/tinish belgilarini tuzatadi,
    # tushunarsiz joyni esa [?] bilan belgilaydi — o'ylab topmaydi.
    system_prompt = (
        "You are a careful Uzbek proofreader working on speech-to-text output of "
        "religious lectures. Your ONLY job is orthography, script and punctuation. "
        "You are NOT allowed to rewrite content or guess missing words.\n\n"

        "═══ WHAT YOU MUST DO ═══\n"
        "1) SCRIPT/SPELLING FIXES ONLY. Whisper often emits Turkish/Kazakh letters "
        "for Uzbek sounds — normalise the CHARACTERS, not the words:\n"
        "   • ş→sh, ç→ch, ı→i, ö→o', ü→u, ğ→g'\n"
        "   • Kazakh қ→q, ң→ng, ы→i, ә→a\n"
        "   • Cyrillic Uzbek → Latin Uzbek (same words, different script)\n"
        "1b) SYSTEMATIC UZBEK SPELLING ERRORS. whisper-large-v3 writes Uzbek "
        "with a Turkic-style spelling. Restore the standard Uzbek form — these "
        "are SPELLING fixes of the SAME word, not word replacements:\n"
        "   • 'a' written where Uzbek has 'o': iqtisadiyat→iqtisodiyot, "
        "bazar→bozor, qanun→qonun, asasi→asosi/asosiy, nazaryasi→nazariyasi, "
        "baladi→bo'ladi, Assalamu→Assalomu, xsablanadi→hisoblanadi, "
        "tamayillari→tamoyillari\n"
        "   • 'w' does not exist in Uzbek Latin: wa→va, mawzu→mavzu\n"
        "   • dropped apostrophe: maruza→ma'ruza, bulaidi→bo'ladi\n"
        "   • wrongly split or merged words: 'Birinchin abadte'→'Birinchi "
        "navbatda', 'onin'→'uning'\n"
        "   Apply this ONLY when the corrected form is an obvious standard "
        "Uzbek word. If unsure, keep the original and mark [?] per rule 7.\n"
        "2) PROPER UZBEK APOSTROPHES: o', g' (not o`, ó, oʻ, ‘).\n"
        "3) ARABIC SCRIPT → standard Uzbek Latin transliteration of well-known "
        "formulas ONLY:\n"
        "   • 'بسم الله' → 'Bismillahir Rohmanir Rohim'\n"
        "   • 'الله اكبر' → 'Allohu akbar', 'سبحان الله' → 'Subhanalloh'\n"
        "   • 'الحمد لله' → 'Alhamdulillah'\n"
        "   If an Arabic passage is NOT a well-known formula, KEEP IT AS IS.\n"
        "4) RELIGIOUS NAMES/TERMS — fix only the SPELLING to the Uzbek standard, "
        "never swap one name for another:\n"
        "   payg'ambar, sallallohu alayhi va sallam, Imom Buxoriy, Imom Muslim, "
        "Imom Shofiy, Imom Abu Hanifa, sahobalar, ulamolar, shariat, hadis, "
        "tafsir, fiqh, aqida, Allohu taolo, inshalloh, alhamdulillah.\n"
        "5) PUNCTUATION and paragraph breaks where sentences clearly end.\n"
        "6) If the SAME phrase repeats 3+ times in a row (a known Whisper glitch), "
        "keep ONE copy.\n\n"

        "═══ WHAT YOU MUST NEVER DO ═══\n"
        "7) NEVER invent, guess or 'reconstruct' words. If a fragment is garbled and "
        "you cannot fix it by spelling alone, KEEP THE ORIGINAL and append [?] "
        "right after it. Example: 'misqamendir[?]'. An unreadable word marked [?] "
        "is CORRECT output — a plausible-sounding invented word is a SERIOUS ERROR.\n"
        "8) NEVER rephrase, modernise or 'improve' grammar. Keep the speaker's own "
        "words and word order, even if colloquial or clumsy.\n"
        "9) NEVER translate, summarise, shorten, expand or add commentary.\n"
        "10) NEVER add sentences that are not in the input. Do not pad the text to "
        "make it longer.\n"
        "11) NEVER change numbers, dates, names, quantities or Qur'an/hadith "
        "quotations in any way.\n\n"

        "═══ EXAMPLES ═══\n"
        "INPUT:  'Şu kişi muhalifni dushman ko'rmaydi'\n"
        "OUTPUT: 'Shu kishi muhalifni dushman ko'rmaydi'\n"
        "  (only letters fixed; 'muhalif' NOT changed to 'muxolif' by guessing)\n\n"
        "INPUT:  'İmom Şofii kelayotganda ediskanlar'\n"
        "OUTPUT: 'Imom Shofiy kelayotganda ediskanlar[?]'\n"
        "  ('ediskanlar' is garbled — marked, NOT replaced with a guess)\n\n"
        "INPUT:  'ele saham dedi'\n"
        "OUTPUT: 'ele saham[?] dedi'\n\n"

        "OUTPUT ONLY the corrected text. No commentary, no preamble, no notes."
    )
    payload = {
        "max_tokens": 16000,
        "temperature": 0.0,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",
             "content": "Clean up this Uzbek transcription:" + chr(10) * 2 + text},
        ],
    }
    # Model nomi ATAYLAB berilmaydi — uni _chat_request provayderga qarab
    # qo'yadi (Gemini Pro -> Flash -> GPT-4o -> Llama, SIFAT tartibida).
    cleaned, err = _chat_request(payload, timeout=300, label="tozalash")
    if err:
        logging.warning("Uzbek cleanup bajarilmadi: %s", err)
        return text
    # Tekshiruv: tozalangan matn juda qisqarib YOKI juda shishib ketmaganmi?
    # (Model ba'zan takror/hallucination bilan matnni bir necha barobar
    #  shishiradi — 8002 -> 44788 belgi kabi. Bunday natija buzuq.)
    if not cleaned:
        logging.warning("Tozalangan matn bo'sh, asl matnni qaytaramiz")
    elif len(cleaned) < len(text) * 0.5:
        logging.warning("Tozalangan matn juda qisqa (%d->%d), asl matnni qaytaramiz",
                        len(text), len(cleaned))
    elif len(cleaned) > len(text) * 1.5:
        logging.warning("Tozalangan matn juda shishgan (%d->%d) — hallucination, "
                        "asl matnni qaytaramiz", len(text), len(cleaned))
    else:
        logging.info("✅ Uzbek matn tozalandi (%d -> %d belgi)", len(text), len(cleaned))
        return cleaned
    return text


def _get_whisper_prompt(source_lang):
    """Whisper'ga kontekst beruvchi prompt qaytaradi.
    Bu so'zlar Whisper'ga 'shu mavzularda gap bo'ladi' deb signal beradi.
    Sifatni 30-40% oshiradi (ayniqsa o'zbek diniy/akademik matnlarda)."""

    # O'zbek tili uchun kontekst — oddiy va xilma-xil so'zlar (takror prompt'da bo'lmasin!)
    # MUHIM: prompt'da bir so'z takror yozilmaslik kerak, aks holda Whisper takror yozadi.
    # Arabcha translit so'zlar ham yo'q (output'ni arab alifbosida qaytarmasligi uchun).
    uz_prompt = (
        "Bu o'zbek tilidagi nutq. Assalomu alaykum, qanday yaxshi yashayapsiz. "
        "Bismillah, alhamdulillah, subhanalloh, inshalloh deb aytamiz. "
        "Bugun maktabda dars o'tdik, talabalar kitob o'qiydi. "
        "Toshkent, Samarqand, Buxoro, Andijon shaharlari xayrli yurt. "
        "Imom Buxoriy, payg'ambar sallallohu alayhi va sallam, sahobalar. "
        "Ulamolar, shariat, hadis, tafsir, fiqh, aqida kabi ilmlar bor. "
        "Otam mehnat qiladi, onam ovqat pishiradi, bola dars tayyorlaydi. "
        "Birinchidan ikkinchidan uchinchidan deb fikr ifodalanadi. "
        "Bu kishi men aytdim ko'rdim eshitdim shu narsani qildim. "
        "Allohga shukur, ko'ngil quvonadi, hayot davom etadi."
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


def _try_transcribe_audio_chat(chunk_path, source_lang, headers):
    """gpt-4o-audio-preview orqali transkripsiya — Whisper'dan yaxshiroq sifat,
    lekin ~5x qimmatroq (~$1.80/soat o'rniga Whisper'ning $0.36/soat).
    Returns: (text yoki None, error yoki None)."""
    try:
        with open(chunk_path, "rb") as f:
            audio_b64 = base64.b64encode(f.read()).decode()
    except Exception as e:
        return None, f"Audio fayl o'qib bo'lmadi: {str(e)[:100]}"

    # Format aniqlash (gpt-4o-audio-preview: wav, mp3, flac, m4a, webm, opus)
    ext = os.path.splitext(chunk_path)[1].lower().lstrip(".")
    fmt = ext if ext in ("wav", "mp3", "flac", "m4a", "webm", "opus") else "mp3"

    system_msg = (
        "You are an expert UZBEK language transcriber. The speaker is speaking "
        "UZBEK — NOT Azerbaijani, NOT Turkish, NOT Kazakh, NOT Turkmen. "
        "Transcribe the audio EXACTLY as spoken into clean, standard Uzbek Latin text.\n\n"
        "CRITICAL ALPHABET RULE: Output ONLY standard Uzbek Latin letters: "
        "a b d e f g h i j k l m n o p q r s t u v x y z, plus the digraphs "
        "o' g' sh ch ng. NEVER use the letters ə ı ş ç ğ ö ü — they DO NOT exist "
        "in Uzbek. If you hear such sounds, write the Uzbek equivalent: "
        "ş→sh, ç→ch, ə→a or e, ı→i, ğ→g', ö→o', ü→u.\n\n"
        "Use correct Uzbek WORDS and grammar, not Azerbaijani/Turkish ones. "
        "Examples: 'bo'lsa' (NOT 'bosa'), 'o'qimoqchi' (NOT 'oqmaqçi'), "
        "'qaytmagan' (NOT 'qayıtməgən'), 'tashqariga' (NOT 'təşqəriyə'), "
        "'kishi' (NOT 'kişi'), 'mazhab' (NOT 'məzhəb'), 'gan/kan' past tense "
        "(NOT '-mış/-miş').\n\n"
        "Do NOT translate, do NOT summarize, do NOT add commentary, do NOT omit "
        "anything. For Quran verses or hadiths in Arabic, transliterate to Uzbek "
        "Latin (e.g., 'Bismillahir Rohmanir Rohim'). "
        "Religious terms: payg'ambar, sallallohu alayhi va sallam (s.a.v.), "
        "alhamdulillah, inshalloh, Allohga shukur, ulamolar, sahobalar, "
        "Imom Buxoriy, Imom Abu Hanifa, Imom Shofiy, mazhab, fiqh, hadis."
    )
    user_text = (
        "Audio'ni STANDART o'zbek lotin alifbosida matn qiling. "
        "Ozarbayjon/turk harflari (ə ı ş ç ğ) ISHLATMANG — faqat o'zbekcha. "
        "Faqat matn, izoh yo'q."
    )

    payload = {
        "model": "gpt-audio",  # gpt-4o-audio-preview GA nomi — eski nom 404 qaytaradi
        "modalities": ["text"],
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": [
                {"type": "text", "text": user_text},
                {"type": "input_audio", "input_audio": {"data": audio_b64, "format": fmt}},
            ]},
        ],
        "max_tokens": 16000,
        "temperature": 0.0,
    }

    url_api = "https://api.openai.com/v1/chat/completions"
    last_error = None
    # 4 urinish: 520/429/5xx vaqtinchalik xatolar uchun — aks holda whisper-1 ga
    # tez tushib, o'zbek matni ozarbayjon/turkchaga adashadi. gpt-audio sifati ustun.
    backoffs = [2, 5, 12, 25]
    for attempt in range(4):
        try:
            resp = requests.post(url_api, headers=headers, json=payload, timeout=600)
            if resp.status_code == 200:
                result = resp.json()
                text = (result["choices"][0]["message"].get("content") or "").strip()
                if text:
                    return _clean_whisper_hallucination(text), None
                return None, "Bo'sh natija"
            elif resp.status_code == 400:
                # 400 — fayl format yoki yaxshi audio emas, qayta urinish foydasiz
                return None, f"HTTP 400: {resp.text[:200]}"
            elif resp.status_code in (429, 500, 502, 503, 504, 520, 522, 524, 529):
                last_error = f"HTTP {resp.status_code}"
                logging.warning(f"gpt-audio {last_error} (urinish {attempt+1}/4), {backoffs[attempt]}s kutamiz")
                if attempt < 3:
                    time.sleep(backoffs[attempt])
            else:
                return None, f"HTTP {resp.status_code}: {resp.text[:200]}"
        except requests.exceptions.Timeout:
            last_error = "Timeout"
        except Exception as e:
            last_error = str(e)[:200]
            if attempt < 1:
                time.sleep(2)
    return None, last_error or "Noma'lum xato"


def _try_transcribe(chunk_path, model, source_lang, url, headers, chunk_offset_sec=0,
                    want_timestamps=None, supported_langs=None):
    """Bitta bo'lakni belgilangan model bilan transkripsiya qilish.
    7 marta retry (HTTP 429/500/502/503/504/timeout/connection errors).
    Backoff: 1s, 2s, 4s, 8s, 15s, 30s, 60s — total ~120s max.
    whisper-1 uchun verbose_json + segments (timestamps) ishlatamiz.
    gpt-4o-transcribe uchun oddiy json (segments yo'q).
    Returnlar: (chunk_text yoki None, error_str yoki None)."""
    # Ilgari bu model NOMIGA qarab hal qilinardi ("whisper-1" bo'lsa vaqt
    # belgilari). Endi provayder ro'yxati aniq aytadi: Groq'ning large-v3 ham
    # segment beradi, lekin nomi boshqa — nomga bog'lanish uni o'tkazib
    # yuborardi. want_timestamps=None bo'lsa eski xatti-harakat saqlanadi.
    if want_timestamps is None:
        want_timestamps = (model == "whisper-1")
    is_whisper1 = want_timestamps
    response_format = "verbose_json" if want_timestamps else "json"
    last_error = None
    # Kuchliroq retry: 7 marta, longer backoff
    backoffs = [1, 2, 4, 8, 15, 30, 60]
    MAX_RETRIES = 7
    for attempt in range(MAX_RETRIES):
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
                # Qaysi tillarni yuborish mumkinligi PROVAYDERGA bog'liq.
                # Bu HAL QILUVCHI: 'uz' yuborilmasa Groq'ning whisper-large-v3
                # o'zbek nutqini ARAB YOZUVIDA qaytaradi (amalda o'lchandi:
                # "اسلام علیکم حرمتلی طلباله" = "assalomu alaykum hurmatli
                # talabalar"). 'uz' yuborilsa lotin yozuvida to'g'ri beradi.
                # OpenAI esa 'uz' ni rad etadi (400 unsupported_language),
                # shuning uchun ro'yxat har provayder uchun ALOHIDA.
                _langs = (WHISPER_SUPPORTED_LANGS if supported_langs is None
                          else supported_langs)
                if source_lang and source_lang != "auto" and source_lang in _langs:
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
            elif resp.status_code in (429, 500, 502, 503, 504):
                last_error = f"HTTP {resp.status_code} (urinish {attempt+1}/{MAX_RETRIES})"
                logging.warning(f"Whisper {last_error}, {backoffs[attempt]}s kutamiz")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(backoffs[attempt])
            else:
                # Boshqa HTTP xato — bu ham retry qilamiz (bot detection, rate limit, etc.)
                last_error = f"HTTP {resp.status_code}"
                if attempt < MAX_RETRIES - 1:
                    time.sleep(backoffs[attempt])
        except requests.exceptions.Timeout:
            last_error = f"Timeout (urinish {attempt+1}/{MAX_RETRIES})"
            logging.warning(f"Whisper timeout, {backoffs[attempt]}s kutamiz")
            if attempt < MAX_RETRIES - 1:
                time.sleep(backoffs[attempt])
        except requests.exceptions.ConnectionError as e:
            last_error = f"Connection error: {str(e)[:100]} (urinish {attempt+1}/{MAX_RETRIES})"
            logging.warning(last_error)
            if attempt < MAX_RETRIES - 1:
                time.sleep(backoffs[attempt])
        except Exception as e:
            last_error = str(e)[:200]
            if attempt < MAX_RETRIES - 1:
                time.sleep(backoffs[attempt])
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
    lines = ["⚠️ <b>Eslatma:</b> quyidagi vaqt oraliqlari transkripsiya qilinmadi:"]
    for s, e in merged:
        lines.append(f"• <code>{_format_time_range(s, e)}</code>")
    lines.append("\n💡 Bu qismlarni qayta olish uchun: audio'ni o'sha vaqtdan kesib qayta yuboring.")
    return "\n".join(lines)


class TypingPing:
    """Telegram'da chat tepasida 'bot yozmoqda...' indikatorini har 4 sek yuborib turadi.
    Telegram chat action 5 sek davom etadi — shuning uchun 4 sek interval.
    Bot ishlamasligi/stuck holatini userdan yashirmasligi uchun foydali.

    Misol:
        ping = TypingPing(user_id)
        ping.start()
        try:
            ... uzun ish ...
        finally:
            ping.stop()
    """
    def __init__(self, chat_id, action="typing", interval=4):
        self.chat_id = chat_id
        self.action = action
        self.interval = interval
        self._stop = threading.Event()
        self._thread = None

    def _loop(self):
        # Darrov yuborib qo'yamiz
        telegram_send_chat_action(self.chat_id, self.action)
        while not self._stop.is_set():
            self._stop.wait(self.interval)
            if self._stop.is_set():
                break
            telegram_send_chat_action(self.chat_id, self.action)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)


def _make_http_progress_cb(user_id, message_id, base_label="🎙 Matn tayyorlanmoqda"):
    """HTTP/WebApp flow uchun progress callback — Telegram xabarini edit qilib turadi.
    Bosqichlar:
      cb(0, 0)  → "🎵 Audio tayyorlanmoqda..." (chunking bosqichi)
      cb(c, N)  → "🎙 Matn tayyorlanmoqda c/N bo'lak..."
    Rate-limited (1.5 sek)."""
    state = {"last": 0.0, "last_text": ""}
    def cb(current, total):
        if total and total > 0:
            text = f"{base_label} {current}/{total} bo'lak..."
        else:
            text = "🎵 Audio fayl tayyorlanmoqda... (30-60 sek)"
        # Bir xil matnni qayta yubormaymiz
        if text == state["last_text"]:
            return
        now = time.time()
        if now - state["last"] < 1.5 and current > 0:
            return  # rate-limit (faqat oraliq chunks uchun)
        state["last"] = now
        state["last_text"] = text
        try:
            telegram_edit_message(user_id, message_id, text)
        except Exception as e:
            logging.debug(f"Progress edit xato: {e}")
    return cb


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


def _join_chunks_dedup_overlap(chunk_results, sorted_keys):
    """Bo'laklarni TARTIBDA yig'adi va qo'shni bo'laklar orasidagi
    OVERLAP takrorini kesadi.

    ffmpeg bo'laklarni 30 sek ustma-ust kesadi (chegaradagi so'z
    yo'qolmasligi uchun), shuning uchun N-bo'lak oxiri N+1 boshida
    qaytariladi. Bu funksiya shu takrorni olib tashlaydi.

    Ilgari bu mantiq transcribe_whisper ichida IKKI MARTA nusxalangan edi
    (FINAL PASS'dan oldin va keyin) — biriga qilingan tuzatish ikkinchisidan
    o'tib ketardi. Alohida funksiya sifatida deterministik sinaladi ham."""
    results = []
    for k in sorted_keys:
        text = chunk_results.get(k)
        if not text:
            continue
        if results and len(text) > 100:
            prev_tail = results[-1][-150:].lower()
            new_head = text[:200].lower()
            best_overlap = 0
            # Eng UZUN mos keluvchi prefiksni izlaymiz (uzundan qisqaga)
            for size in range(min(150, len(new_head)), 20, -5):
                if new_head[:size] in prev_tail:
                    best_overlap = size
                    break
            if best_overlap > 0:
                text = text[best_overlap:].lstrip()
        results.append(text)
    return results


_ARAB_RE = re.compile("[" + chr(0x0600) + "-" + chr(0x06FF) + "]")


def _is_wrong_script(text, expect_lang="uz"):
    """O'zbek lotin kutilganda ARAB YOZUVI qaytsa — natija yaroqsiz.

    Amalda o'lchandi: Groq'ning whisper-large-v3 language parametri
    yuborilmasa o'zbek nutqini arab yozuvida qaytaradi
    ("اسلام علیکم حرمتلی طلباله"). Tovushlar to'g'ri, lekin foydalanuvchi
    uchun butunlay yaroqsiz. language=uz buni hal qiladi, ammo vaqtinchalik
    nosozlikda model yana adashishi mumkin — shuning uchun NATIJANING O'ZI
    ham tekshiriladi va bunday matn sifatsiz deb qayta urinilаdi.
    """
    if not text or expect_lang != "uz":
        return False
    arab = len(_ARAB_RE.findall(text))
    return arab > max(10, len(text) * 0.10)


def _rescue_split(chunk_path, parts=3):
    """Yiqilgan bo'lakni MAYDA qismlarga kesadi (qutqaruv uchun).

    NEGA: hallutsinatsiya odatda bo'lak ichidagi jimlik yoki shovqindan
    boshlanadi va BUTUN bo'lakni buzadi — model bir marta "adashib",
    keyin takroriy axlat yozaveradi. Kichikroq qismlarda u odatda
    to'g'ri ishlaydi, ya'ni matnni yo'qotmasdan qutqarib qolish mumkin.

    Bu foydalanuvchi talabi: konspektda BO'SHLIQ qolmasin.
    """
    try:
        dur = get_duration_or_estimate(chunk_path)
    except Exception:
        dur = 0
    if not dur or dur < 20:
        return []
    step = dur / parts
    base = os.path.splitext(chunk_path)[0]
    out = []
    for i in range(parts):
        start = i * step
        # Oxirgisidan boshqasiga 3s ustma-ustlik — chegarada so'z kesilmasin
        length = step + (3 if i < parts - 1 else 0)
        pth = base + "_qutqaruv" + str(i) + ".mp3"
        cmd = ["ffmpeg", "-y", "-v", "error",
               "-ss", str(round(start, 2)), "-i", chunk_path,
               "-t", str(round(length, 2)),
               "-vn", "-ac", "1", "-ar", "16000",
               "-acodec", "libmp3lame", "-b:a", WHISPER_CHUNK_BITRATE, pth]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=180)
            if os.path.exists(pth) and os.path.getsize(pth) > 1000:
                out.append(pth)
        except Exception as e:
            logging.warning("Qutqaruv qismi %s yaratilmadi: %s", i, e)
    return out


def transcribe_whisper(file_path, source_lang, progress_cb=None, failed_ranges_out=None):
    """OpenAI Whisper API orqali audio'ni matnga aylantirish.
    HAR DOIM avval optimallashtirish (64kbps mono MP3) qilinadi — bu Whisper
    25 MB limitiga moslashish va arzonroq tarmoq trafigi uchun.
    progress_cb(current_chunk, total_chunks) — sync progress callback."""
    if not _stt_attempts():
        raise Exception("STT provayderi sozlanmagan — GROQ_API_KEY (bepul) "
                        "yoki OPENAI_API_KEY qo'shing.")

    try:
        orig_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    except Exception:
        orig_size_mb = 0

    logging.info(f"🎙 Whisper transkripsiya: {file_path} ({orig_size_mb:.1f}MB)")

    # Audio tayyorlash bosqichi haqida user'ga xabar (chunking ham vaqt oladi)
    if progress_cb:
        try: progress_cb(0, 0)  # 0/0 = "audio tayyorlanmoqda" signali
        except Exception: pass

    # Har doim split_audio_for_whisper chaqiramiz — u qayta kodlash va bo'laklashni hal qiladi
    chunks_to_process = split_audio_for_whisper(file_path, WHISPER_CHUNK_SECONDS)
    chunk_dir_to_cleanup = None
    if chunks_to_process and chunks_to_process[0] != file_path:
        chunk_dir_to_cleanup = os.path.dirname(chunks_to_process[0])
        logging.info(f"   → {len(chunks_to_process)} ta bo'lak tayyor")

    # Audio MAX_AUDIO_CHUNKS chegarasiga tegib kesilganmi? Agar shunday bo'lsa,
    # kesilgan oraliqni failed_ranges'ga qo'shamiz — foydalanuvchi qaysi
    # daqiqadan keyingi qism yo'qligini aniq ko'radi. Ilgari bu JIMGINA
    # sodir bo'lar, lekin daqiqa to'liq uzunlik bo'yicha yechilardi.
    if failed_ranges_out is not None and len(chunks_to_process) >= MAX_AUDIO_CHUNKS:
        covered_sec = MAX_AUDIO_CHUNKS * WHISPER_CHUNK_SECONDS
        try:
            real_dur = int(get_duration_or_estimate(file_path))
        except Exception:
            real_dur = 0
        if real_dur > covered_sec + 30:
            failed_ranges_out.append(
                (covered_sec, real_dur, f"audio {covered_sec/3600:.1f} soatdan uzun — kesildi")
            )

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

        # ── SIFAT NAZORATI ──────────────────────────────────────────────
        # Talab: sifatsiz matn HECH QANDAY HOLATDA berilmasin.
        #
        # Ikki xil "yomon" bor va ular BIR XIL EMAS:
        #  1) HALLUTSINATSIYA — model o'ylab topgan takroriy axlat. Buni
        #     yetkazish bermaslikdan YOMONROQ: ma'ruza konspektiga yolg'on
        #     jumla tushadi va foydalanuvchi uni asl matndan ajrata olmaydi.
        #  2) QISQA matn — jim yoki qisqa bo'lakda TABIIY holat. Buni
        #     tashlash esa haqiqiy matnni yo'qotadi.
        # Shuning uchun: axlat hech qachon yetkazilmaydi, qisqa-lekin-toza
        # matn yetkaziladi.
        def _is_junk(text):
            if not text:
                return False
            # Noto'g'ri YOZUV ham axlat: tovushlar to'g'ri bo'lsa ham
            # foydalanuvchi o'qiy olmaydi.
            if _is_wrong_script(text, source_lang):
                logging.warning("Bo'lak %s/%s: NOTO'G'RI YOZUV (arab) — "
                                "yaroqsiz deb belgilandi", idx, total)
                return True
            return _is_chunk_hallucinated(text, WHISPER_CHUNK_SECONDS)

        def _is_good(text):
            return bool(text) and len(text) >= 20 and not _is_junk(text)

        attempts = _stt_attempts()
        if not attempts:
            return idx, None, ("birorta AI kaliti sozlanmagan "
                               "(OPENAI_API_KEY yoki GROQ_API_KEY kerak)")

        clean_candidates, errors = [], []
        # Butun provayder zanjiri BIR NECHA MARTA takrorlanadi: vaqtinchalik
        # nosozlik yoki limit tufayli sifat pasaygan bo'lsa, kutib qayta
        # urinamiz. Bir marta urinib taslim bo'lish sifatni pasaytirardi.
        for rnd in range(1, STT_QUALITY_ROUNDS + 1):
            for nom, kind, model, a_url, a_headers, want_ts, a_langs in attempts:
                if kind == "chat_audio":
                    text, err = _try_transcribe_audio_chat(chunk_path, source_lang,
                                                           a_headers)
                else:
                    text, err = _try_transcribe(
                        chunk_path, model, source_lang, a_url, a_headers,
                        chunk_offset_sec=chunk_offset_sec, want_timestamps=want_ts,
                        supported_langs=a_langs)
                if _is_good(text):
                    if clean_candidates or errors:
                        logging.info("Bo'lak %s/%s %s bilan olindi (%s-tur)",
                                     idx, total, nom, rnd)
                    return idx, text, None
                if text and not _is_junk(text):
                    clean_candidates.append(text)
                    logging.warning("Bo'lak %s/%s %s: qisqa natija, davom etamiz",
                                    idx, total, nom)
                elif text:
                    logging.warning("Bo'lak %s/%s %s: HALLUTSINATSIYA — tashlandi",
                                    idx, total, nom)
                if err:
                    errors.append(str(rnd) + "-tur " + nom + ": " + str(err))
            if rnd < STT_QUALITY_ROUNDS:
                wait = STT_ROUND_WAITS[min(rnd - 1, len(STT_ROUND_WAITS) - 1)]
                logging.warning("🔁 Bo'lak %s/%s: %s-turda sifatli natija yo'q, "
                                "%ss kutib qayta urinamiz...", idx, total, rnd, wait)
                time.sleep(wait)

        # Turlar tugadi. Toza (lekin qisqa) natija bo'lsa — u yetkaziladi.
        if clean_candidates:
            best = max(clean_candidates, key=len)
            logging.warning("Bo'lak %s/%s: qisqa, lekin TOZA natija yetkazildi",
                            idx, total)
            return idx, best, None

        # ── QUTQARUV: bo'lakni maydalab qayta urinish ────────────────
        # Taslim bo'lish o'rniga bo'lakni 3 ga bo'lib qayta o'qiymiz.
        # Konspektda bo'shliq qolmasligi uchun oxirgi imkoniyat.
        _qismlar = _rescue_split(chunk_path)
        if _qismlar:
            logging.warning("🩹 Bo'lak %s/%s QUTQARUV: %s qismga bo'lindi",
                            idx, total, len(_qismlar))
            _olingan = []
            for _pth in _qismlar:
                for nom, kind, model, a_url, a_headers, want_ts, a_langs in attempts:
                    if kind == "chat_audio":
                        _pt, _ = _try_transcribe_audio_chat(_pth, source_lang, a_headers)
                    else:
                        _pt, _ = _try_transcribe(_pth, model, source_lang, a_url,
                                                 a_headers, want_timestamps=False,
                                                 supported_langs=a_langs)
                    if _pt and not _is_junk(_pt):
                        _olingan.append(_pt.strip())
                        break
                try:
                    os.remove(_pth)
                except Exception:
                    pass
            if _olingan:
                logging.info("🩹 Bo'lak %s/%s QUTQARILDI (%s/%s qism)",
                             idx, total, len(_olingan), len(_qismlar))
                return idx, " ".join(_olingan), None

        # Faqat axlat chiqdi yoki umuman javob yo'q — JIM YETKAZMAYMIZ.
        # Bo'lak "yiqilgan" deb belgilanadi va foydalanuvchiga QAYSI daqiqalar
        # tushmagani aytiladi. Yolg'on matndan ochiq bo'shliq yaxshi.
        sabab = " | ".join(errors) if errors else (
            str(STT_QUALITY_ROUNDS) + " turda ham sifat talabiga javob bermadi")
        logging.error("Bo'lak %s/%s SIFAT NAZORATIDAN O'TMADI: %s", idx, total, sabab)
        return idx, None, sabab

    # Bo'laklarga ajratish tugadi — userga xabar (0/N) ko'rsataylik
    if progress_cb:
        try: progress_cb(0, total)
        except Exception: pass

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
    # Bo'laklarni tartibda yig'amiz va overlap'larni dedupe qilamiz
    sorted_keys = sorted(chunk_results.keys())
    results = _join_chunks_dedup_overlap(chunk_results, sorted_keys)

    # MULTI FINAL PASS — yiqilgan bo'laklarni qayta urinish.
    # Kutish vaqtlari qisqartirildi: ilgari [60, 120, 300] edi — bitta bo'lak
    # yiqilsa foydalanuvchi 8 daqiqa ortiqcha kutar, thread esa shuncha vaqt
    # band turardi (navbatdagilar ham kutib qolardi). _try_transcribe ichida
    # allaqachon o'z retry/backoff'i bor, shuning uchun bu yerda uzoq kutish
    # ortiqcha edi.
    chunk_idx_to_path = {idx: path for idx, path in enumerate(chunks_to_process, 1)}
    whisper_pass_waits = [30, 60, 180]  # jami ~4.5 daq: 429-storm'dan chiqishga yetadi, slotni 8 daq band qilmaydi
    for pass_num, wait_sec in enumerate(whisper_pass_waits, 1):
        if not failed_chunks or len(failed_chunks) >= total:
            break
        logging.warning(f"🔁 Whisper FINAL PASS {pass_num}/3: {len(failed_chunks)} bo'lak, {wait_sec}s kutamiz...")
        time.sleep(wait_sec)
        retry_failed = []
        for failed_idx, _ in failed_chunks:
            chunk_path = chunk_idx_to_path.get(failed_idx)
            if not chunk_path:
                continue
            try:
                ridx, rtext, rerr = _process_one_chunk((failed_idx, chunk_path))
                if rtext:
                    chunk_results[ridx] = rtext
                    logging.info(f"✅ Whisper FINAL PASS {pass_num}: bo'lak {ridx} tiklandi")
                    if failed_ranges_out is not None:
                        start_sec = (ridx - 1) * WHISPER_CHUNK_SECONDS
                        end_sec = ridx * WHISPER_CHUNK_SECONDS
                        failed_ranges_out[:] = [r for r in failed_ranges_out if not (r[0] == start_sec and r[1] == end_sec)]
                else:
                    retry_failed.append((failed_idx, rerr))
            except Exception as e:
                retry_failed.append((failed_idx, str(e)[:200]))
        failed_chunks = retry_failed
        logging.info(f"Whisper FINAL PASS {pass_num} tugadi: {len(failed_chunks)} bo'lak hali yiqilgan")

    # MULTI PASS'dan keyin natijalarni qayta yig'ish (yangi tiklangan chunklar bilan)
    sorted_keys = sorted(chunk_results.keys())
    results = _join_chunks_dedup_overlap(chunk_results, sorted_keys)

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
        "max_tokens": 16000,
        "temperature": 0.1,  # past temperatura = aniqroq, kam ijodiy
        "top_p": 0.9,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    # Model nomini _chat_request qo'yadi: Gemini Pro -> GPT-4o -> Gemini Flash
    # -> Llama. Bittasi limitga urilsa (429) keyingisiga DARHOL o'tadi, ya'ni
    # bitta provayderning kunlik kvotasi tugashi tarjimani to'xtatmaydi.
    out, err = _chat_request(payload, timeout=300, label="tarjima")
    if err:
        raise Exception("Tarjima xatosi: " + err)
    return out


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


def translate_with_claude(text, source_lang, progress_cb=None, target_lang="uz",
                          lost_chunks_out=None):
    """Tarjima — OpenAI GPT-4o orqali.
    Uzun matn 3000 so'zlik bo'laklarga ajratiladi va har biri 3 marta urinish bilan
    tarjima qilinadi. Bo'laklarning 30% dan ko'pi yiqilsa — butun tarjima xato.

    lost_chunks_out: ro'yxat bersangiz, yo'qolgan bo'laklar (idx, jami) to'ldiriladi.
      Chaqiruvchi buni foydalanuvchiga ogohlantirish uchun ishlatadi — ilgari
      matnning 30% gacha qismi JIMGINA yo'qolib ketardi va foydalanuvchi
      to'liq tarjima olgan deb o'ylardi.

    source_lang: manba til (yoki 'auto')
    target_lang: hosil til ('uz', 'ru', 'en', 'ar')"""
    if not _has_any_ai_key():
        raise Exception("Matn modeli sozlanmagan — GEMINI_API_KEY, "
                        "GROQ_API_KEY yoki OPENAI_API_KEY qo'shing.")

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
        if lost_chunks_out is not None:
            lost_chunks_out.append((len(failed_chunks), len(chunks)))
    return result


def _format_lost_chunks_text(lost_chunks):
    """Yo'qolgan tarjima bo'laklari haqida foydalanuvchiga ogohlantirish matni."""
    if not lost_chunks:
        return None
    failed, total = lost_chunks[0]
    percent = int(failed / max(1, total) * 100)
    return (
        f"⚠️ Diqqat: tarjimaning {failed}/{total} bo'lagi ({percent}%) "
        f"texnik sabablarga ko'ra tayyorlanmadi.\n\n"
        f"Quyidagi matn TO'LIQ EMAS — taxminan {percent}% qismi yetishmaydi. "
        f"To'liq natija uchun faylni qaytadan yuboring yoki qisqaroq "
        f"bo'laklarga bo'lib yuboring."
    )
# === [/TARJIMA MODULI — API HELPERS] ============================================


# ── BOT HELPERS ─────────────────────────────────────────────────────────────

async def send_result(update, msg, text):
    """Transkripsiya natijasini yetkazish — sync _send_text_card'ga delegatsiya.

    Returns True — natija haqiqatan yetkazilgan bo'lsa (chaqiruvchi shu
    qiymatga qarab tarif daqiqasini yechadi).

    MUHIM: bu funksiya ATAYLAB yupqa wrapper. Ilgari bu yerda _send_text_and_pdf
    bilan deyarli bir xil (lekin sekin farqlanib borayotgan) dublikat delivery
    kodi bor edi — billing-critical mantiq ikki joyda yashardi va bittasiga
    qilingan tuzatish ikkinchisidan o'tib ketardi. Endi yagona yo'l:
    _send_text_card -> _send_text_and_pdf (sifat ogohlantirishi, 2 PDF,
    fallback matn, remember_transcript — hammasi o'sha yerda)."""
    if not text:
        try:
            await msg.edit_text("Matn aniqlanmadi.\n\n💚 Daqiqa hisobingizdan yechilmadi.")
        except Exception:
            pass
        return False
    # Status xabarini olib tashlaymiz — _send_text_card o'zi "Tayyor!" yuboradi
    try:
        await msg.delete()
    except Exception:
        pass
    chat = getattr(update, "effective_chat", None)
    chat_id = chat.id if chat else update.effective_user.id
    return await asyncio.to_thread(
        _send_text_card, chat_id, text, "📝 <b>Matn:</b>", update.effective_user.id
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


async def _transcribe_flow(update, msg, path, language, actual_duration):
    """Umumiy transkripsiya oqimi: pool'da STT -> natija -> billing.

    Uchta Telegram flow (lokal audio, file_id, URL) ilgari shu blokni
    nusxalab yurar edi — billing qoidasi o'zgartirilsa uchta joyni unutmasdan
    tuzatish kerak bo'lardi. Endi bitta joy.
    Busy-guard chaqiruvchi handler ustidagi @busy_guard'da (yuklab olishdan OLDIN)."""
    loop = asyncio.get_running_loop()
    cb = make_progress_cb(loop, msg)
    failed_ranges = []
    text = await _run_heavy(transcribe_unified, path, cb, language, failed_ranges)
    if failed_ranges:
        await update.message.reply_text(_format_failed_ranges_text(failed_ranges), parse_mode="HTML")
    # Daqiqa FAQAT natija haqiqatan yetkazilgan bo'lsa yechiladi
    delivered = await send_result(update, msg, text)
    if delivered and not is_admin(update) and actual_duration > 0:
        add_user_usage(update.effective_user.id, actual_duration)


@busy_guard
async def process_local_audio(update, context, file_path, duration=0, language="uz"):
    # Tarif limiti — barcha tillarda qo'llanadi
    if not await can_process_uzbek(update, duration):
        return

    est = f"{duration // 60} daqiqa {duration % 60} soniya" if duration else "noma'lum"

    # Admin test rejimi — Muxlisa chaqirilmaydi
    if language == "uz" and is_admin(update) and TEST_MODE["on"]:
        await update.message.reply_text(
            f"🧪 *TEST REJIMI* — OpenAI chaqirilmadi (pul ketmadi)\n⏱ {est}",
            parse_mode="Markdown"
        )
        msg = await update.message.reply_text("Test natijasi tayyorlanyapti...")
        await send_result(update, msg, "[TEST REJIMI] Bu sahta natija. OpenAI hisobidan pul yechilmadi. /test buyrug'i bilan o'chirib qo'ying.")
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

        await _transcribe_flow(update, msg, file_path, language, actual_duration)
    except Exception as e:
        logging.error(f"Xato: {e}")
        await msg.edit_text(f"❌ Xato: {str(e)[:300]}")


@busy_guard
async def process_file(update, context, file_id, suffix, duration=0, language="uz"):
    # Tarif limiti — barcha tillarda qo'llanadi
    uid = update.effective_user.id if update.effective_user else None
    uname = (update.effective_user.username if update.effective_user else None) or ""
    logging.info(f"📥 process_file: user_id={uid}, username='{uname}', is_admin={is_admin(update)}, duration={duration}, language={language}")

    # Per-fayl limit tekshiruvi (Standart tariflar uchun)
    if uid and not is_admin(update):
        tariff = get_user_tariff(uid)
        max_file_min = TARIFFS.get(tariff, {}).get("max_file_min")
        if max_file_min and duration > 0 and duration > max_file_min * 60:
            await update.message.reply_text(
                f"⚠️ *Tarif cheklovi:* {TARIFFS[tariff]['name']} tarifida har audio max **{max_file_min} daqiqa** bo'lishi mumkin.\n\n"
                f"Sizning audio'ngiz {duration//60} daq {duration%60} sek.\n\n"
                f"💡 Yechim:\n"
                f"• Audio'ni qisqaroq bo'laklarga ajrating\n"
                f"• Yoki **Premium** tarifga o'ting — cheklov yo'q, eng yuqori sifat: /buy",
                parse_mode="Markdown"
            )
            return

    if not await can_process_uzbek(update, duration):
        return

    est = f"{duration // 60} daqiqa {duration % 60} soniya" if duration else "noma'lum"

    # Admin test rejimi — Muxlisa chaqirilmaydi
    if language == "uz" and is_admin(update) and TEST_MODE["on"]:
        await update.message.reply_text(
            f"🧪 *TEST REJIMI* — OpenAI chaqirilmadi (pul ketmadi)\n⏱ {est}",
            parse_mode="Markdown"
        )
        msg = await update.message.reply_text("Test natijasi tayyorlanyapti...")
        await send_result(update, msg, "[TEST REJIMI] Bu sahta natija. OpenAI hisobidan pul yechilmadi. /test buyrug'i bilan o'chirib qo'ying.")
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

        await _transcribe_flow(update, msg, tmp_path, language, actual_duration)
    except Exception as e:
        logging.error(f"Xato: {e}")
        await msg.edit_text(f"❌ Xato: {str(e)[:300]}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try: os.remove(tmp_path)
            except Exception: pass


@busy_guard
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
            f"🧪 *TEST REJIMI* — Video yuklanmadi, OpenAI chaqirilmadi (pul ketmadi)",
            parse_mode="Markdown"
        )
        msg = await update.message.reply_text("Test natijasi tayyorlanyapti...")
        await send_result(update, msg, "[TEST REJIMI] Bu sahta natija. URL yuklanmadi, OpenAI chaqirilmadi.")
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
        # yt-dlp + ffmpeg — og'ir: umumiy pool orqali (cap + /debug hisobida)
        audio_path = await _run_heavy(download_audio_from_url, url)
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

        await _transcribe_flow(update, msg, audio_path, language, actual_duration)
    except Exception as e:
        logging.error(f"URL xato: {e}")
        await msg.edit_text(f"❌ Xato: {str(e)[:300]}")
    finally:
        if audio_path:
            shutil.rmtree(os.path.dirname(audio_path), ignore_errors=True)


def webapp_keyboard(chat_id=None, username=None):
    # Cache buster. `user=` parametri OLIB TASHLANDI — u autentifikatsiyani
    # chetlab o'tish yo'li edi. Endi user_id faqat imzolangan initData'dan olinadi.
    rows = []
    # WEBAPP_URL sozlanmagan bo'lsa tugmani UMUMAN qo'shmaymiz: bosilganda
    # "sahifa ochilmadi" chiqib, bot butunlay buzuq degan taassurot berardi.
    if WEBAPP_URL:
        rows.append([KeyboardButton(text="🎙 Web ilovani ochish",
                                    web_app=WebAppInfo(url=fresh_webapp_url()))])
    rows += [
        [KeyboardButton(text="🌐 Tarjima")],
        [KeyboardButton(text="📊 Balansim"), KeyboardButton(text="💎 Tariflar")],
        [KeyboardButton(text="💳 Sotib olish"), KeyboardButton(text="❓ Yordam")],
        [KeyboardButton(text="💬 Murojaat"), KeyboardButton(text="🔄 /start")],
    ]
    # Admin tugmalarini ko'rsatish (kosmetik — buyruqlar baribir is_admin bilan himoyalangan)
    if ADMIN_USER_IDS:
        is_admin_user = chat_id in ADMIN_USER_IDS
    else:
        is_admin_user = bool(
            (chat_id is not None and ADMIN_CHAT_ID["id"] is not None and chat_id == ADMIN_CHAT_ID["id"])
            or (username and username.lower().lstrip("@") in ADMIN_USERNAMES)
        )
    if is_admin_user:
        rows.append([KeyboardButton(text="👥 Userlar"), KeyboardButton(text="📖 Buyruqlar")])
        rows.append([KeyboardButton(text="🔐 Admin panel")])

    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


# ── BOT HANDLERS ────────────────────────────────────────────────────────────

def fresh_webapp_url():
    """Cache-buster bilan WebApp URL (user parametri YO'Q — autentifikatsiya
    faqat imzolangan initData orqali). Sozlanmagan bo'lsa bo'sh satr."""
    if not WEBAPP_URL:
        return ""
    sep = "&" if "?" in WEBAPP_URL else "?"
    return f"{WEBAPP_URL}{sep}v={int(time.time())}"


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
        if WEBAPP_URL:
            await context.bot.set_chat_menu_button(
                chat_id=update.effective_chat.id,
                menu_button=MenuButtonWebApp(
                    text="🎙 MNSM",
                    web_app=WebAppInfo(url=fresh_webapp_url()),
                ),
            )
    except Exception as e:
        logging.error(f"Menu button set xato: {e}")

    await update.message.reply_text(
        "🌸 Assalomu alaykum, *{}*!\n\n"
        "Men audio va videolardan *matn va PDF*, PDFdan esa *audio* yasaydigan botman.\n\n"
        "🎯 *Imkoniyatlarim:*\n"
        "• 🎤 Audio/video (har tilda) → 🇺🇿 O'zbek matn\n"
        "• 📄 Lotin va Kirill alifbosida PDF\n"
        "• 📄 O'zbek PDF → 🇺🇿 O'zbek audio MP3\n\n"
        "📥 *Yuborishingiz mumkin:*\n"
        "• Ovozli xabar, audio fayl\n"
        "• Video, dumaloq video\n"
        "• YouTube / TikTok / Instagram havolasi\n"
        "• PDF fayl\n\n"
        "💡 *Tavsiyalar:*\n"
        "• *Aniq, tiniq ovoz* yuboring (shovqin kam bo'lsin)\n"
        "• Bir vaqtda bitta odam gapirsa, sifat yaxshi chiqadi\n\n"
        "⚠️ *Muhim eslatma:* Men botman, inson kabi bo'lolmayman, ammo inson "
        "kabi xato qilishim mumkin. Xato qilishimni oldini olishingiz uchun "
        "eng yaxshi tavsiya: uzun soatlik video/audiolarni menga "
        "*10-20 daqiqalik qilib bo'lib* tashlasangiz, xato qilish ehtimolim "
        "pasayadi. Qanchalik video/audio qisqa bo'lsa, men shunchalik sifatli "
        "matn qilaman, qanchalik uzun bo'lsa xatolik darajam oshadi. Va "
        "audio/video sifati, tiniqligi, so'zlari tushunarligiga ahamiyat "
        "beringlar.\n\n"
        "🎁 *Bonus daqiqalar:* Do'st taklif qilsangiz ikkalangizgayam +5 daqiqa bepul!\n"
        "Tavsiya havolangizni olish: /tavsiya\n\n"
        "Quyidagi tugma orqali *Web ilovani* oching 👇".format(
            md_escape(update.effective_user.first_name)
        ),
        parse_mode="Markdown",
        reply_markup=webapp_keyboard(chat_id=chat_id, username=update.effective_user.username),
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
            # Faqat http(s). Ilgari bu yerda `extract_url(url) or url` edi —
            # ya'ni havola bo'lmagan qiymat ham pastga o'tib ketardi.
            clean_url = extract_url(url)
            if not clean_url:
                await update.message.reply_text(
                    "❌ To'g'ri havola yuboring (http:// yoki https:// bilan boshlanishi kerak)."
                )
                return
            url = clean_url
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


def _pop_translation_state_if(user_id, source, target):
    """Rejimni FAQAT hozirgi qiymati (source, target)ga mos bo'lsa iste'mol
    qiladi. Uzun await'lar (yuklab olish, navbat) davomida user /tarjima
    orqali YANGI rejim tanlagan bo'lishi mumkin — uni o'chirib yubormaymiz."""
    cur = _peek_translation_state(user_id)
    if cur and cur.get("source") == source and (cur.get("target") or "uz") == (target or "uz"):
        _pop_translation_state(user_id)
        return True
    return False


def _peek_translation_state(user_id):
    """Tarjima rejimini O'CHIRMASDAN qaytaradi. Handlerlar yo'nalishni shu
    bilan tanlaydi; holat esa busy_guard MUVAFFAQIYATLI o'tgach, guarded
    funksiya ichida _pop_translation_state bilan iste'mol qilinadi.
    (Ilgari handler pop qilardi — busy rad etilsa user tanlagan tarjima
    rejimi butunlay yo'qolardi.)"""
    if user_id and user_id in pending_translations:
        val = pending_translations.get(user_id)
        if isinstance(val, dict):
            return val
        if isinstance(val, str):
            return {"source": val, "target": "uz"}
    return None


def _save_user_data_async():
    """To'liq JSON saqlashni event loop'ni BLOKLAMASDAN bajarish.
    (_save_user_data disk o'qish + .bak nusxa + yozish — loop'da chaqirilsa
    barcha handlerlar shu vaqtga muzlaydi.)"""
    threading.Thread(target=_save_user_data, daemon=True).start()


def _pop_translation_state(user_id):
    """=== [TARJIMA] User tarjima rejimida bo'lsa {source, target} qaytaradi. ===
    Backward compat: agar eski format (string) bo'lsa, target='uz' deb qaytariladi.
    """
    if user_id and user_id in pending_translations:
        val = pending_translations.pop(user_id, None)
        _save_user_data_async()
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
    state = _peek_translation_state(update.effective_user.id)
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
    state = _peek_translation_state(update.effective_user.id)
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
    state = _peek_translation_state(update.effective_user.id)
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
    state = _peek_translation_state(update.effective_user.id)
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
        # OpenAI Whisper narxi: $0.006/daq ≈ 75 so'm/daq (USD=12500 so'm bilan)
        total_cost = int(total_sec / 60 * 75)
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
        admin_uname_md = md_escape((update.effective_user.username or ""))
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
    carry_min = int(user_bonus_minutes.get(user_id, 0))
    ref_min = int(user_referral_minutes.get(user_id, 0))
    bonus_line = ""
    if ref_min > 0:
        bonus_line += f"🎁 Do'st taklif bonusi: +{ref_min} daqiqa\n"
    if carry_min > 0:
        bonus_line += f"🔄 Ko'chirilgan qoldiq: +{carry_min} daqiqa\n"
    await update.message.reply_text(
        f"📊 *Sizning hisobingiz*\n\n"
        f"🌸 Tarif: *{tariff['name']}* ({tariff['minutes']} daqiqa)\n"
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
            "Endi Audio Whisper API ga yuborilmaydi — pul ketmaydi.\n"
            "Bot sahta natija qaytaradi.\n\n"
            "O'chirish uchun: /test",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "🧪 *Test rejimi O'CHIQ ❌*\n\n"
            "Endi haqiqiy OpenAI STT ishlaydi (balansdan pul yechiladi).",
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
        [InlineKeyboardButton("🎁 Tarif berish (chek so'ramasdan)", callback_data="adm:grant_help")],
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
            label = md_escape(_user_label(uid))
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
        # MUHIM: diskdan to'g'ridan-to'g'ri o'qiymiz (memory bilan farq bo'lsa)
        # Bu user_tariffs memory'da yo'qolgan yoki sync bo'lmagan bo'lsa ham ishlashini ta'minlaydi.
        try:
            _replay_tariff_log()
        except Exception as e:
            logging.warning(f"paid_users replay xato: {e}")
        # Diskdan o'qib memory'ga to'ldirish
        try:
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    disk_data = json.load(f)
                for k, v in (disk_data.get("tariffs") or {}).items():
                    try:
                        uid = int(k)
                        if v in TARIFFS and uid not in user_tariffs:
                            user_tariffs[uid] = v
                            logging.info(f"📂 Disk'dan tariff tiklandi: {uid} → {v}")
                    except Exception:
                        pass
        except Exception as e:
            logging.warning(f"paid_users disk re-read xato: {e}")
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
            label = md_escape(_user_label(uid))
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
            label = md_escape(_user_label(uid))
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

    if action == "grant_help":
        # Admin tarif berish guide — soddaroq, qisqaroq qadamlar
        back = [[InlineKeyboardButton("⬅️ Orqaga", callback_data="adm:back")]]
        await query.edit_message_text(
            "🎁 *Userga tarif berish*\n\n"
            "Chek so'ramasdan, qo'lda tarif berish uchun:\n\n"
            "1️⃣ User'ning ID'ini bilib oling:\n"
            "   • `/user @username` yoki\n"
            "   • Admin sifatida statistikadan ko'rasiz\n\n"
            "2️⃣ Buyruqni yozing:\n"
            "   `/grant <user_id> <tarif_kaliti>`\n\n"
            "*Misol:*\n"
            "   `/grant 629686772 standart`\n"
            "   `/grant 629686772 premium`\n"
            "   `/grant 629686772 pro_max`\n\n"
            "*Tarif kalitlari:*\n"
            "🌿 Oddiy: `basic`, `standart`, `premium`\n"
            "✨ Pro: `pro_standart`, `pro_premium`, `pro_max`\n\n"
            "User darhol tarif oladi, xabar keladi.",
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
    label = md_escape(_user_label(target_id))
    user_tariffs[target_id] = "free"
    user_uzbek_usage[target_id] = 0
    # Dedupe oynasini tozalaymiz — revoke'dan keyin qayta berish qonuniy
    with _grant_lock:
        for k in [k for k in _recent_grants if k[0] == target_id]:
            _recent_grants.pop(k, None)
    _append_tariff_log(target_id, "free", source="revoke")
    _save_user_data()
    back = [[InlineKeyboardButton("⬅️ Panelga qaytish", callback_data="adm:back")]]
    await query.edit_message_text(
        f"✅ *Tarif bekor qilindi*\n\n"
        f"👤 {label}\n"
        f"🆔 `{target_id}`\n"
        f"❌ Eski: {old_tariff['name']}\n"
        f"🌸 Yangi: Bepul (5 daqiqa)\n"
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
                "Hozir 🌸 Bepul tarifdasiz (5 daqiqa).\n"
                "Yangi tarif olish: /tariflar"
            ),
            parse_mode="Markdown",
        )
    except Exception as e:
        logging.warning(f"User'ga ({target_id}) tarif bekor qilish xabari yetmadi: {e}")


async def openai_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: OpenAI xarajatlari (bot ichki statistikasidan hisoblanadi).

    Real xarajat OpenAI dashboard'da: https://platform.openai.com/usage
    """
    if not is_admin(update):
        await update.message.reply_text("⛔ Bu buyruq faqat admin uchun.")
        return

    # Jami daqiqa — Pro tarif (Muhlisa) va Oddiy (Whisper) alohida
    pro_sec = 0
    whisper_sec = 0
    for uid, sec in user_uzbek_usage.items():
        if _is_user_pro_tariff(uid):
            pro_sec += sec
        else:
            whisper_sec += sec
    pro_min = pro_sec / 60.0
    whisper_min = whisper_sec / 60.0
    total_min = pro_min + whisper_min
    active_users = sum(1 for s in user_uzbek_usage.values() if s > 0)

    # Narxlar (2026 holati)
    PRICE_WHISPER_PER_MIN = 0.006          # OpenAI Whisper STT ($)
    PRICE_CLEANUP_OVERHEAD = 0.10          # GPT-4o cleanup (~10% qo'shimcha)
    PRICE_EXTRAS_OVERHEAD = 0.20           # Tarjima + PDF audio (taxmin 20%)
    PRICE_MUHLISA_PER_MIN_UZS = 500        # Muhlisa AI ~500 so'm/daq
    SERVER_PER_MONTH_USD = 5.0             # Railway Hobby $5/oy
    USD_TO_UZS = 12500                     # taxminiy kurs

    # OpenAI xarajat
    whisper_cost_usd = whisper_min * PRICE_WHISPER_PER_MIN
    cleanup_cost_usd = whisper_cost_usd * PRICE_CLEANUP_OVERHEAD
    extras_cost_usd = whisper_cost_usd * PRICE_EXTRAS_OVERHEAD
    openai_cost_usd = whisper_cost_usd + cleanup_cost_usd + extras_cost_usd
    openai_cost_uzs = openai_cost_usd * USD_TO_UZS

    # Muhlisa xarajat (so'mda)
    muhlisa_cost_uzs = pro_min * PRICE_MUHLISA_PER_MIN_UZS

    # Server xarajat (oylik sobit)
    server_cost_uzs = SERVER_PER_MONTH_USD * USD_TO_UZS

    # JAMI (so'mda)
    total_uzs = openai_cost_uzs + muhlisa_cost_uzs + server_cost_uzs

    # Eng faol 5 user
    top_users = sorted(user_uzbek_usage.items(), key=lambda x: -x[1])[:5]
    top_lines = []
    for uid, sec in top_users:
        if sec <= 0:
            continue
        label = _user_label(uid)
        is_pro = _is_user_pro_tariff(uid)
        per_min_uzs = PRICE_MUHLISA_PER_MIN_UZS if is_pro else PRICE_WHISPER_PER_MIN * USD_TO_UZS
        cost_uzs = sec / 60 * per_min_uzs
        top_lines.append(f"  • {label}: {sec/60:.1f} daq (~{cost_uzs:,.0f} so'm)")
    top_text = "\n".join(top_lines) if top_lines else "  (hech kim yo'q)"

    text = (
        f"💰 To'liq xarajat (taxminiy)\n\n"
        f"📊 Foydalanish:\n"
        f"  • Oddiy (Whisper): {whisper_min:.0f} daq\n"
        f"  • Pro (Muhlisa): {pro_min:.0f} daq\n"
        f"  • Jami daqiqa: {total_min:.0f}\n"
        f"  • Faol user: {active_users} ta\n\n"

        f"💸 OpenAI xarajat:\n"
        f"  • STT (Whisper): ${whisper_cost_usd:.2f}\n"
        f"  • Cleanup (GPT-4o): ${cleanup_cost_usd:.2f}\n"
        f"  • Tarjima + PDF audio: ${extras_cost_usd:.2f}\n"
        f"  Jami OpenAI: ${openai_cost_usd:.2f} (≈ {openai_cost_uzs:,.0f} so'm)\n\n"

        f"🌟 Muhlisa AI (Pro tarif):\n"
        f"  • {pro_min:.0f} daq × 500 so'm = {muhlisa_cost_uzs:,.0f} so'm\n\n"

        f"🖥 Server (Railway, oylik sobit):\n"
        f"  • $5/oy × {USD_TO_UZS} = {server_cost_uzs:,.0f} so'm\n\n"

        f"━━━━━━━━━━━━━━\n"
        f"📌 JAMI: ~{total_uzs:,.0f} so'm\n"
        f"━━━━━━━━━━━━━━\n\n"

        f"🔝 Eng faol userlar:\n{top_text}\n\n"

        f"💡 Eslatma: Bu taxminiy. Real OpenAI: platform.openai.com/usage"
    )
    await update.message.reply_text(text)


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: barcha userlar statistikasi (username bilan)."""
    if not is_admin(update):
        await update.message.reply_text("⛔ Bu buyruq faqat admin uchun.")
        return
    if not user_uzbek_usage and not user_info:
        await update.message.reply_text("📊 Hozircha foydalanuvchilar bot'ni ishlatmagan.")
        return
    lines = ["📊 *Foydalanuvchi statistikasi:*\n"]
    # Userlarni LIFETIME daqiqa bo'yicha tartiblash (grant'da tushmaydigan)
    all_user_ids = set(list(user_uzbek_usage.keys()) + list(user_info.keys()) + list(user_total_usage.keys()))
    user_data_list = [(uid, user_total_usage.get(uid, user_uzbek_usage.get(uid, 0))) for uid in all_user_ids]
    user_data_list.sort(key=lambda x: x[1], reverse=True)
    for user_id, lifetime_sec in user_data_list[:30]:
        current_sec = user_uzbek_usage.get(user_id, 0)
        label = _user_label(user_id)
        # Markdown'da xavfsiz qilamiz (underscore, asterisk)
        safe_label = md_escape(label)
        tariff_key = get_user_tariff(user_id)
        tariff_name = TARIFFS.get(tariff_key, TARIFFS["free"])["name"]
        # Jami ishlatgan | joriy davr | tarif
        lines.append(
            f"• {safe_label}\n"
            f"  `{user_id}` — jami: {lifetime_sec/60:.1f} daq (joriy: {current_sec/60:.1f}) — {tariff_name}"
        )
    total_lifetime = sum(user_total_usage.get(uid, user_uzbek_usage.get(uid, 0)) for uid in all_user_ids)
    total_current = sum(user_uzbek_usage.values())
    lines.append(
        f"\n*Jami:* {len(all_user_ids)} ta user\n"
        f"⏱ Umumiy ishlatilgan (lifetime): *{total_lifetime/60:.1f} daqiqa*\n"
        f"📊 Joriy davr (grant'dan keyin): {total_current/60:.1f} daqiqa"
    )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def revoke_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: /revoke <user_id> — foydalanuvchining tarifini bekor qilish.
    Foydalanuvchi Bepul tarifga qaytariladi (5 daqiqa). Test uchun bergan tariflarni qaytarish uchun."""
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
    safe_label = md_escape(label)
    # Bepul tarifga qaytarish + daqiqalarni tiklash
    user_tariffs[target_id] = "free"
    user_uzbek_usage[target_id] = 0
    # Dedupe oynasini tozalaymiz — revoke'dan keyin qayta berish qonuniy
    with _grant_lock:
        for k in [k for k in _recent_grants if k[0] == target_id]:
            _recent_grants.pop(k, None)
    _append_tariff_log(target_id, "free", source="revoke")
    _save_user_data()
    await update.message.reply_text(
        f"✅ *Tarif bekor qilindi*\n\n"
        f"👤 Foydalanuvchi: {safe_label}\n"
        f"🆔 ID: `{target_id}`\n"
        f"❌ Eski tarif: {old_tariff['name']} ({old_tariff['minutes']} daq)\n"
        f"🌸 Yangi tarif: 🌸 Bepul (5 daqiqa)\n"
        f"⏱ Ishlatilgan: 0 daqiqa (tiklandi)",
        parse_mode="Markdown"
    )
    # Foydalanuvchiga ham xabar (ixtiyoriy — yumshoqroq)
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=(
                "ℹ️ *Tarifingiz yangilandi*\n\n"
                "Hozir 🌸 Bepul tarifdasiz (5 daqiqa).\n"
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
    uname_safe = md_escape(uname) if uname != "(yo'q)" else uname
    fname_safe = md_escape(full_name) if full_name else "(yo'q)"
    # Telegram URL (agar username bor bo'lsa)
    profile_url = f"https://t.me/{uname}" if uname not in ("(yo'q)", "") else None
    text = (
        f"👤 *Foydalanuvchi ma'lumoti*\n\n"
        f"🆔 ID: `{target_id}`\n"
        f"👤 Ism: *{fname_safe}*\n"
        f"📛 Username: @{uname_safe}\n"
        f"🌐 Til kodi: {lang_code}\n\n"
        f"🌸 Tarif: *{tariff['name']}* ({tariff['minutes']} daqiqa)\n"
        f"⏱ Ishlatilgan: *{used_sec/60:.1f} daqiqa*\n"
        f"📉 Qoldiq: *{max(0, tariff['minutes']*60 - used_sec)/60:.1f} daqiqa*\n\n"
        f"📅 Birinchi marta: {fs}\n"
        f"🕐 Oxirgi marta: {ls}\n\n"
        f"💡 Tarif berish: `/grant {target_id} <tarif>`\n"
        f"💬 Xabar yuborish: `/reply {target_id} <xabar>`"
    )
    # Tarif berish tugmalari — admin chek so'ramasdan tarif beradi
    grant_buttons = []
    grant_keys = ["basic", "standart", "premium", "pro_standart", "pro_premium", "pro_max"]
    row = []
    for k in grant_keys:
        if k not in TARIFFS:
            continue
        t = TARIFFS[k]
        # Qisqa nom (emoji + tarif so'zi)
        short_name = t["name"]
        row.append(InlineKeyboardButton(short_name, callback_data=f"approve:{target_id}:{k}"))
        if len(row) == 2:
            grant_buttons.append(row)
            row = []
    if row:
        grant_buttons.append(row)
    # Bekor qilish va profil tugmalari
    grant_buttons.append([InlineKeyboardButton("🚫 Tarifni bekor qilish (free)", callback_data=f"approve:{target_id}:free")])
    if profile_url:
        grant_buttons.append([InlineKeyboardButton(f"💬 @{uname} bilan yozish", url=profile_url)])

    text += "\n\n🎁 *Tarif berish:* pastdagi tugmadan tanlang."
    await update.message.reply_text(
        text, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(grant_buttons),
    )


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
    bonus_current = int(user_referral_minutes.get(user_id, 0))
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
    """Tarif tugmalari ko'rsatadi — 2 kategoriya: Standart va Premium.
    Joriy tarif tugamagan bo'lsa ham yangi tarif olish mumkin — qolgan daqiqalar
    yangi tarifga ko'chiriladi (yo'qolmaydi)."""
    user_id = None
    if hasattr(message_obj, "from_user") and message_obj.from_user:
        user_id = message_obj.from_user.id
    elif hasattr(message_obj, "chat") and message_obj.chat:
        user_id = message_obj.chat.id

    # Joriy tarifda qolgan daqiqalar — bloklamaymiz, balki yangi tarifga
    # ko'chirilishini eslatamiz (qoldiq yo'qolmaydi).
    carryover_note = ""
    if user_id:
        current_tariff = get_user_tariff(user_id)
        if current_tariff != "free":
            t = TARIFFS.get(current_tariff, {})
            used = get_user_usage_sec(user_id) / 60
            limit = (t.get("minutes", 0) + get_user_bonus_min(user_id))
            remaining = max(0, limit - used)
            if remaining > 0.5:  # 30 soniyadan ko'p qolgan
                carryover_note = (
                    f"♻️ *Qoldiq saqlanadi:* joriy *{t.get('name', current_tariff)}* "
                    f"tarifingizda *{remaining:.1f} daqiqa* qolgan — yangi tarif "
                    f"olsangiz, bu daqiqalar yo'qolmaydi, yangisiga *qo'shiladi*.\n\n"
                )

    standart_keys = ["basic", "standart", "premium"]
    premium_keys = ["pro_standart", "pro_premium", "pro_max"]
    buttons = []
    for key in standart_keys + premium_keys:
        if key in TARIFFS and TARIFFS[key].get("price", 0) > 0:
            t = TARIFFS[key]
            hrs = t["minutes"] // 60
            label = f"{t['name']} • {hrs} soat • {t['price']:,} so'm"
            buttons.append([InlineKeyboardButton(label, callback_data=f"buy:{key}")])
    text = (
        carryover_note +
        "💎 *Bizda 2 xil tarif bor:*\n\n"
        "💚 *Standart* — arzon\n"
        "👑 *Premium* — eng yuqori sifat\n\n"
        "Tanlagan tarifingiz uchun to'lov ma'lumotlari ko'rinadi.\n"
        "💳 Click / Payme / Paynet / Uzcard / Humo orqali to'lashingiz mumkin.\n\n"
        "📸 To'lov chekini botga yuborgach tarifingiz tasdiqlanadi."
    )
    if hasattr(message_obj, "edit_message_text"):
        try:
            await message_obj.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))
        except BadRequest as e:
            if "not modified" not in str(e).lower():
                raise
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
            f"⏱ Limit: *{t['minutes']} daqiqa* ({t['minutes']//60} soat)\n"
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
        f"{t['minutes']} daqiqa ({t['minutes']//60} soat) "
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

    # force=True — real to'lov HAR DOIM hisobga olinadi. Foydalanuvchi bir xil
    # tarifni ketma-ket ikki marta sotib olsa, ikkalasi ham berilishi kerak.
    # Takrorlanishni Telegram o'zi provider_payment_charge_id bilan kafolatlaydi.
    _activate_tariff_with_carryover(target_id, tariff_key, source="telegram_pay", force=True)
    _save_user_data()

    t = TARIFFS[tariff_key]
    await update.message.reply_text(
        f"✅ *To'lov muvaffaqiyatli!*\n\n"
        f"🌸 Tarif: *{t['name']}*\n"
        f"⏱ Limit: *{t['minutes']} daqiqa* ({t['minutes']//60} soat)\n"
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


async def _send_chek_for_manual_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User 'Men to'ladim' bosmasdan chek yuborganda — adminga manual tarif
    tanlash imkoniyati bilan yuboramiz. Admin tarif tugmalaridan birini bosadi."""
    user = update.effective_user
    if not user:
        return
    if not ADMIN_CHAT_ID["id"]:
        await update.message.reply_text(
            "✅ Chek qabul qilindi.\n\n"
            "⚠️ Lekin tarifni avval `/buy` orqali tanlashingiz kerak edi.\n"
            "Iltimos /buy yozing va tarif tanlang."
        )
        return

    photo = update.message.photo[-1] if update.message.photo else None
    if not photo:
        return

    username_raw = f"@{user.username}" if user.username else (user.first_name or "noma'lum")
    # Plain text — Markdown xatosi yo'q (username'da _ bo'lishi mumkin)
    caption = (
        f"⚠️ Manual tasdiqlash kerak\n\n"
        f"👤 Foydalanuvchi: {username_raw}\n"
        f"🆔 ID: {user.id}\n\n"
        f"User chek yubordi LEKIN tarif tanlamagan.\n"
        f"Quyidagi tugmalardan tarifni tanlang va tasdiqlang:"
    )

    # Faqat sotuvchi tariflar uchun tugma
    visible_keys = ["basic", "standart", "premium", "pro_standart", "pro_premium", "pro_max"]
    buttons = []
    for key in visible_keys:
        if key not in TARIFFS or TARIFFS[key].get("price", 0) == 0:
            continue
        t = TARIFFS[key]
        label = f"✅ {t['name']} • {t['price']:,} so'm"
        buttons.append([InlineKeyboardButton(label, callback_data=f"approve:{user.id}:{key}")])
    buttons.append([InlineKeyboardButton("❌ Rad etish", callback_data=f"reject:{user.id}:manual")])

    try:
        await context.bot.send_photo(
            chat_id=ADMIN_CHAT_ID["id"],
            photo=photo.file_id,
            caption=caption,
            reply_markup=InlineKeyboardMarkup(buttons),
        )
    except Exception as e:
        logging.error(f"Manual chek admin'ga yuborishda xato: {e}")
        return

    await update.message.reply_text(
        "✅ Chek qabul qilindi.\n\n"
        "Admin tekshirib tarif beradi. Odatda 5-30 daqiqa ichida xabar olasiz."
    )


async def _send_admin_commands_list(update):
    """Admin uchun barcha buyruqlar ro'yxati (kategoriyalar bo'yicha)."""
    text = (
        "📖 ADMIN BUYRUQLARI RO'YXATI\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"

        "👥 USER BOSHQARUVI\n"
        "/stats — barcha userlar ro'yxati (top 30)\n"
        "/user <id> — user ma'lumoti + tarif tugmalari\n"
        "/grant <id> <tarif> — tarif berish\n"
        "/revoke <id> — tarifni bekor qilish (Bepulga)\n"
        "/reset <id> — daqiqalarni tiklash\n"
        "/refund <id> — pul qaytarish + Pro Uzbek taklif\n\n"

        "💰 TO'LOV SOZLAMALARI\n"
        "/setcard <karta> — to'lov karta raqami\n"
        "/setholder <ism> — karta egasi ismi\n\n"

        "📊 STATISTIKA & DEBUG\n"
        "/openai — OpenAI xarajat taxminiy hisob\n"
        "/debug — persistence (data fayl holati)\n"
        "/admin — to'liq admin panel\n\n"

        "💾 BACKUP & TIKLASH\n"
        "/backup — data faylni Telegram'ga yuborish\n"
        "/restore — eski backup'dan tiklash (faylga reply qiling)\n\n"

        "💬 ALOQA & TEST\n"
        "/reply <id> <matn> — userga javob yuborish\n"
        "/test — test rejimini yoqish/o'chirish\n\n"

        "👤 ODDIY USER UCHUN\n"
        "/start — botni ishga tushirish\n"
        "/balance — sizning balans\n"
        "/tariflar — tariflar ro'yxati\n"
        "/buy — tarif sotib olish\n"
        "/tavsiya — do'st taklif (referral)\n"
        "/tarjima — xorijiy tildan tarjima\n"
        "/feedback — murojaat\n"
        "/help — yordam\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━\n\n"

        "📝 TARIF KALITLARI (/grant uchun):\n\n"

        "Oddiy (Whisper):\n"
        "  basic — 💚 Boshlang'ich (3 soat / 60k)\n"
        "  standart — 💙 Standart (10 soat / 150k)\n"
        "  premium — 💜 Premium (25 soat / 300k)\n\n"

        "Pro (Muhlisa AI — Uzbek sifat):\n"
        "  pro_standart — ⭐ Pro Standart (3 soat / 170k)\n"
        "  pro_premium — 👑 Pro Premium (6 soat / 300k)\n"
        "  pro_max — 💎 Pro Pro (10 soat / 500k)\n\n"

        "free — 🌸 Bepul (5 daq)\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━\n\n"

        "💡 MISOLLAR:\n\n"
        "/grant 94184684 pro_max\n"
        "/revoke 190612268\n"
        "/refund 8744070680\n"
        "/user 629686772\n\n"

        "💡 TIP: chek xabarini bot'ga forward qilsangiz, tarif tugmalari avto chiqadi."
    )
    await update.message.reply_text(text)


async def _show_restore_grant_buttons(update, context, target_id, original_caption=""):
    """Admin eski chek'ni forward qilganda — tarif berish tugmalari bilan javob.
    Eski chek caption'idan tarif nomini topishga harakat qiladi (auto-suggest)."""
    # Tarif nomini topishga harakat — auto suggest uchun
    suggested_key = None
    if "Boshlang'ich" in original_caption:
        suggested_key = "basic"
    elif "Pro Standart" in original_caption or "✨" in original_caption:
        suggested_key = "pro_standart"
    elif "Pro Premium" in original_caption:
        suggested_key = "pro_premium"
    elif "Pro Pro" in original_caption or "💎" in original_caption:
        suggested_key = "pro_max"
    elif "Premium" in original_caption:
        suggested_key = "premium"
    elif "Standart" in original_caption:
        suggested_key = "standart"

    # User nomini olish (agar caption'da bo'lsa)
    username = "(noma'lum)"
    m = re.search(r"Foydalanuvchi:\s*([^\n]+)", original_caption)
    if m:
        username = m.group(1).strip().replace("`", "").replace("*", "")

    # Tarif tugmalari
    visible_keys = ["basic", "standart", "premium", "pro_standart", "pro_premium", "pro_max"]
    buttons = []
    row = []
    for key in visible_keys:
        if key not in TARIFFS:
            continue
        t = TARIFFS[key]
        emoji = "⭐ " if key == suggested_key else ""
        label = f"{emoji}{t['name']}"
        row.append(InlineKeyboardButton(label, callback_data=f"approve:{target_id}:{key}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("❌ Bekor qilish", callback_data="adm:back")])

    suggest_hint = f"\n\n💡 Tavsiya: {TARIFFS[suggested_key]['name']}" if suggested_key else ""
    # Plain text — Markdown xatosi yo'q (username'da _ bo'lishi mumkin)
    await update.message.reply_text(
        f"🔍 Eski chek aniqlandi!\n\n"
        f"👤 {username}\n"
        f"🆔 ID: {target_id}\n"
        f"{suggest_hint}\n\n"
        f"Pastdagi tugmadan tarifni tanlang:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User chek (rasm) yuborganda — agar to'lov kutilayotgan bo'lsa adminga uzatamiz.
    Agar user 'Men to'ladim' bosmagan bo'lsa ham — adminga manual tasdiqlash uchun yuboramiz.
    Agar ADMIN forward qilgan eski chek bo'lsa — user_id avtomat aniqlanib tarif tugmalari ko'rsatiladi."""
    user_id = update.effective_user.id if update.effective_user else None

    # === [ADMIN RESTORE] Admin eski chek'ni forward qilgan bo'lsa — auto-detect ===
    if user_id and is_admin(update):
        caption = update.message.caption or ""
        # Eski chek pattern: "🆔 ID: 12345" yoki "🆔 ID: `12345`"
        m = re.search(r"🆔\s*ID:\s*`?(\d{5,})`?", caption)
        if m:
            target_id = int(m.group(1))
            await _show_restore_grant_buttons(update, context, target_id, caption)
            return

    # Atomik pop — bir vaqtning o'zida ikkita rasm yuborilsa, faqat bittasi qabul qilinadi
    tariff_key = None
    with _save_lock:
        if context.user_data:
            tariff_key = context.user_data.pop("awaiting_payment_for", None)
        if not tariff_key and user_id in pending_payments:
            tariff_key = pending_payments.pop(user_id, None)
    if not tariff_key or tariff_key not in TARIFFS:
        # User 'Men to'ladim' bosmasdan chek yuborgan bo'lishi mumkin —
        # adminga manual tarif tanlash bilan yuboramiz (xato bo'lib qolmasin)
        await _send_chek_for_manual_approval(update, context)
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
    username_safe = md_escape(username_raw)
    tariff_name_safe = md_escape(t['name'])

    caption = (
        f"💸 *Yangi to'lov cheki*\n\n"
        f"👤 Foydalanuvchi: {username_safe}\n"
        f"🆔 ID: `{user.id}`\n"
        f"🌸 Tarif: *{tariff_name_safe}*\n"
        f"⏱ Limit: {t['minutes']} daqiqa\n"
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
                f"⏱ Limit: {t['minutes']} daqiqa\n"
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
    """Callback adminmi tekshirish — is_admin bilan bir xil qoida."""
    user = getattr(query, "from_user", None)
    if _is_admin_user(user):
        return True
    # ADMIN_USER_IDS sozlanmagan bo'lsa, saqlangan admin chat_id ham qabul qilinadi
    if not ADMIN_USER_IDS and user and ADMIN_CHAT_ID["id"] and user.id == ADMIN_CHAT_ID["id"]:
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
    # Reject uchun tariff_key kerak emas, ammo approve uchun TARIFFS'da bo'lishi shart
    if action == "approve" and tariff_key not in TARIFFS:
        await query.answer("❌ Bu tarif endi mavjud emas.", show_alert=True)
        return
    t = TARIFFS.get(tariff_key, {"name": "tarif", "minutes": 0, "price": 0})

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
        # Markdown yiqildi (masalan, username'da _ bor edi va Telegram saqlangan
        # matnda escape'lar yo'q) — PLAIN matn bilan qayta urinamiz, status
        # admin uchun baribir ko'rinsin (* belgilarisiz).
        plain_suffix = suffix.replace("*", "")
        try:
            if query.message.caption is not None:
                await query.edit_message_caption(
                    caption=(query.message.caption or "") + plain_suffix)
                return True
            if query.message.text is not None:
                await query.edit_message_text(
                    text=(query.message.text or "") + plain_suffix)
                return True
        except Exception as e:
            logging.debug(f"plain edit ham xato: {e}")
        try:
            # Tugmalarni olib tashlash (eng kam mumkin)
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        return False

    if action == "approve":
        carry = _activate_tariff_with_carryover(target_id, tariff_key, source="approve")
        if carry is None:
            # Takroriy bosish — tarif allaqachon berilgan, ikkinchi marta bermaymiz
            await query.answer(
                f"ℹ️ Bu tarif allaqachon berilgan ({t['name']}). "
                f"Ikkinchi marta berilmadi.\n"
                f"Ikkinchi TO'LOV bo'lsa: /grant {target_id} {tariff_key} force",
                show_alert=True,
            )
            await _update_admin_message("\n\n↩️ *Takroriy bosish e'tiborsiz qoldirildi*")
            return
        _save_user_data()
        await _send_backup_snapshot_to_admin(context.bot, source=f"approve {target_id}={tariff_key}")
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
                    f"⏱ Limit: *{t['minutes']} daqiqa* ({t['minutes']//60} soat)\n\n"
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


async def refund_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: norozi mijozga pul qaytarish + Pro Uzbek taklif xabarini yuborish.
    Foydalanish: /refund <user_id>
    Bot user'ga uzr xabari va Pro Uzbek tariff tavsiyasini yuboradi.
    Pulni admin alohida qaytaradi (karta orqali)."""
    if not is_admin(update):
        await update.message.reply_text("⛔ Bu buyruq faqat admin uchun.")
        return
    args = (update.message.text or "").split()
    if len(args) < 2:
        await update.message.reply_text(
            "*Foydalanish:*\n"
            "`/refund <user_id>`\n\n"
            "*Misol:*\n"
            "`/refund 629686772`\n\n"
            "Bot user'ga uzr xabari yuboradi va Pro Uzbek tarif tavsiyasi.\n"
            "Pulni siz alohida qaytarasiz (karta orqali).",
            parse_mode="Markdown",
        )
        return
    try:
        target_id = int(args[1])
    except ValueError:
        await update.message.reply_text("❌ user_id raqam bo'lishi kerak.")
        return

    # User tarifini bilamiz (refund vaqtidagi holatda)
    old_tariff_key = get_user_tariff(target_id)
    old_tariff = TARIFFS.get(old_tariff_key, TARIFFS["free"])

    refund_msg = (
        "🙏 *Sizdan uzr so'raymiz*\n\n"
        f"Ko'rinishidan, *{old_tariff['name']}* tarifida olgan matn sifati past chiqdi. "
        "Bu Whisper STT'ning O'zbek diniy/akademik kontentdagi cheklovi.\n\n"
        "💰 *Pulingiz qaytariladi* (admin tez orada karta orqali yuboradi).\n\n"
        "✨ *Eng yaxshi yechim — Pro Uzbek tarifi:*\n"
        "• Maxsus O'zbek STT (Muhlisa AI) — sifat 2x yuqori\n"
        "• Arab oyatlari va diniy terminlar yaxshiroq aniqlaydi\n"
        "• 3 soat 170,000 so'm dan boshlanadi\n\n"
        "Tarif sotib olish: /tariflar yoki /buy"
    )

    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=refund_msg,
            parse_mode="Markdown",
        )
        # Tarif bekor qilamiz — user qayta sotib olishi mumkin
        user_tariffs[target_id] = "free"
        user_uzbek_usage[target_id] = 0
        _save_user_data()
        await update.message.reply_text(
            f"✅ User `{target_id}`'ga uzr xabari + Pro tavsiya yuborildi.\n"
            f"Tarifi *{old_tariff['name']}* → *Bepul*'ga qaytarildi.\n\n"
            f"⚠️ *Pulni siz alohida qaytaring* (karta orqali).",
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text(
            f"❌ User'ga xabar yuborilmadi: {str(e)[:200]}",
        )


async def grant_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: foydalanuvchiga tarif berish.
    Foydalanish: /grant <user_id> <free|standart|premium|pro>"""
    if not is_admin(update):
        await update.message.reply_text("⛔ Bu buyruq faqat admin uchun.")
        return
    args = (update.message.text or "").split()
    if len(args) < 3:
        await update.message.reply_text(
            "/grant <id> <tarif>\n\n"
            "Tariflar:\n"
            "• pro_standart — ⭐ 3 soat\n"
            "• pro_premium — 👑 6 soat\n"
            "• pro_max — 💎 10 soat\n"
            "• free — 🌸 Bepul\n\n"
            "Misol: /grant 94184684 pro_max"
        )
        return
    try:
        target_id = int(args[1])
    except ValueError:
        await update.message.reply_text("❌ ID raqam bo'lishi kerak.")
        return
    tariff_key = args[2].lower()
    if tariff_key not in TARIFFS:
        await update.message.reply_text(
            f"❌ '{tariff_key}' yo'q.\n\n"
            f"Mavjud: pro_standart, pro_premium, pro_max, free"
        )
        return
    # Yangi tarif berilganda ishlatilganlar tiklanadi + qoldiq daqiqa ko'chiriladi
    # `force` — ataylab qayta berish (deduplikatsiyani chetlab o'tish)
    force = len(args) > 3 and args[3].lower() in ("force", "majburiy")
    carry = _activate_tariff_with_carryover(
        target_id, tariff_key, source="grant_cmd", force=force
    )
    if carry is None:
        await update.message.reply_text(
            f"ℹ️ Bu tarif shu foydalanuvchiga yaqinda ({GRANT_DEDUPE_WINDOW_SEC // 60} daqiqa "
            f"ichida) allaqachon berilgan — takroriy berilmadi.\n\n"
            f"Ataylab qayta bermoqchi bo'lsangiz:\n"
            f"`/grant {target_id} {tariff_key} force`",
            parse_mode="Markdown",
        )
        return
    _save_user_data()
    await _send_backup_snapshot_to_admin(context.bot, source=f"grant {target_id}={tariff_key}")
    t = TARIFFS[tariff_key]
    await update.message.reply_text(
        f"✅ *Tarif berildi!*\n\n"
        f"👤 User ID: `{target_id}`\n"
        f"🌸 Tarif: {t['name']}\n"
        f"⏱ Limit: {t['minutes']} daqiqa\n"
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
                 f"⏱ Limit: {t['minutes']} daqiqa\n\n"
                 f"Hisobingizni ko'rish: /balance",
            parse_mode="Markdown"
        )
    except Exception as e:
        logging.warning(f"Userga ({target_id}) tarif xabari yuborilmadi: {e}")


async def backup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: data faylni adminga Telegram orqali yuborish (manual backup).
    Foydalanish: /backup — fayl darrov yuboriladi."""
    if not is_admin(update):
        await update.message.reply_text("⛔ Bu buyruq faqat admin uchun.")
        return
    if not os.path.exists(DATA_FILE):
        await update.message.reply_text(f"❌ Fayl topilmadi: `{DATA_FILE}`", parse_mode="Markdown")
        return
    try:
        file_size = os.path.getsize(DATA_FILE)
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"user_data_backup_{ts}.json"
        with open(DATA_FILE, "rb") as f:
            await context.bot.send_document(
                chat_id=update.effective_user.id,
                document=f,
                filename=filename,
                caption=(
                    f"💾 *Backup* — `{ts}`\n\n"
                    f"📊 Userlar: {len(user_uzbek_usage)}\n"
                    f"💎 Paid: {sum(1 for t in user_tariffs.values() if t != 'free')}\n"
                    f"📏 O'lcham: {file_size:,} bayt\n\n"
                    f"⚠️ Saqlang! Data yo'qolsa /restore orqali tiklaysiz."
                ),
                parse_mode="Markdown",
            )
    except Exception as e:
        await update.message.reply_text(f"❌ Backup yuborish xato: {str(e)[:300]}")


async def restore_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: backup faylni yuborib data'ni tiklash.
    Foydalanish: backup faylga reply qilib /restore yozing."""
    if not is_admin(update):
        await update.message.reply_text("⛔ Bu buyruq faqat admin uchun.")
        return
    # Reply qilingan xabarda document bo'lishi kerak
    reply = update.message.reply_to_message
    if not reply or not reply.document:
        await update.message.reply_text(
            "*Foydalanish:*\n\n"
            "1. /backup yozing — bot data faylini yuboradi\n"
            "2. Backup faylga reply qilib /restore yozing\n"
            "3. Bot eski data'ni tiklaydi (joriy data yo'qoladi)\n\n"
            "⚠️ *Diqqat:* tiklashdan oldin joriy /backup qiling.",
            parse_mode="Markdown",
        )
        return
    try:
        # Faylni yuklab olish
        tg_file = await context.bot.get_file(reply.document.file_id)
        import io, json as _json
        bio = io.BytesIO()
        await tg_file.download_to_memory(bio)
        bio.seek(0)
        raw_text = bio.read().decode("utf-8")
        # JSON parse tekshiruv
        parsed = _json.loads(raw_text)
        if not isinstance(parsed, dict) or "usage" not in parsed:
            await update.message.reply_text("❌ Fayl noto'g'ri formatda (user_data.json emas).")
            return
        # Faylni yozish
        with _save_lock:
            os.makedirs(os.path.dirname(DATA_FILE) or ".", exist_ok=True)
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                f.write(raw_text)
        # Xotirani tiklash
        user_uzbek_usage.clear()
        user_tariffs.clear()
        user_info.clear()
        pending_payments.clear()
        pending_translations.clear()
        last_transcripts.clear()
        user_bonus_minutes.clear()
        user_referral_minutes.clear()
        user_referrals.clear()
        user_referral_claimed.clear()
        # Saqlash keshi endi eskirgan — /restore ataylab kamroq ma'lumot
        # yuklashi mumkin, keyingi saqlash haqiqiy fayl bilan solishtirsin
        _last_written_counts["ready"] = False
        _load_user_data()

        # MUHIM: tariff_log.jsonl append-only va get_user_tariff uni JSON'dan
        # USTUN qo'yadi. Shuning uchun log'ga tegmasak, backup'dagi tarif darrov
        # log tomonidan qayta yozilardi — ya'ni /restore tarifni pasaytira olmasdi.
        # Backup holatini log'ga yakuniy yozuv sifatida qo'shamiz.
        reconciled, absent_paid = await asyncio.to_thread(
            _reconcile_tariff_log_with_memory, "restore"
        )

        await update.message.reply_text(
            f"✅ *Data tiklandi!*\n\n"
            f"👥 Userlar: *{len(user_uzbek_usage)}*\n"
            f"💎 Paid: *{sum(1 for t in user_tariffs.values() if t != 'free')}*\n"
            f"🗂 Jurnal moslashtirildi: *{reconciled}* ta yozuv"
            + (f"\n⚠️ {len(absent_paid)} ta PULLIK user backup'da yo'q — tegilmadi: `{', '.join(str(u) for u in absent_paid[:20])}`"
               if absent_paid else "") +
            f"\n\n"
            f"Tekshirish: /stats",
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Tiklash xato: {str(e)[:300]}")


# Auto-backup OLIB TASHLANDI — user talabi: faqat /backup so'ralganda
# Data avtomat /data/user_data.json + .bak'ga saqlanadi (kod ichida)
# Backup fayl Telegram'ga FAQAT /backup yozilganda yuboriladi


async def debug_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: persistence va saqlash holatini tekshirish."""
    if not is_admin(update):
        await update.message.reply_text("⛔ Bu buyruq faqat admin uchun.")
        return
    file_exists = os.path.exists(DATA_FILE)
    file_size = os.path.getsize(DATA_FILE) if file_exists else 0
    card_status = "sozlangan" if runtime_settings.get("payment_card") else "yo'q"
    lines = [
        "🔧 Debug — persistence holati",
        "",
        f"📁 DATA_FILE: {DATA_FILE}",
        f"📂 Fayl mavjud: {'✅' if file_exists else '❌'}",
        f"📏 Fayl o'lchami: {file_size} bayt",
        "",
        "💾 Xotirada:",
        f"• user_uzbek_usage: {len(user_uzbek_usage)} ta user",
        f"• user_tariffs: {len(user_tariffs)} ta user",
        f"• user_info: {len(user_info)} ta user",
        f"• pending_payments: {len(pending_payments)} ta user",
        f"• admin_chat_id: {ADMIN_CHAT_ID['id']}",
        f"• payment_card: {card_status}",
        f"• last_transcripts (RAM): {len(last_transcripts)} ta",
        "",
        "🚦 Navbat:",
        f"• Ishlayapti: {_job_stats['running']} / {MAX_CONCURRENT_JOBS}",
        f"• Kutmoqda: {_job_stats['queued']} / {MAX_QUEUED_JOBS}",
        f"• Faol thread: {threading.active_count()}",
        "",
        ("⛔ Sozlama ogohlantirishlari: "
         + (str(len(STARTUP_WARNINGS)) + " ta" if STARTUP_WARNINGS else "yo'q")),
    ] + [f"  • [{lv}] {m}" for lv, m in STARTUP_WARNINGS] + [
        "",
        "🔐 Sozlamalar:",
        f"• ADMIN_USER_IDS: {sorted(ADMIN_USER_IDS) or 'sozlanmagan (username fallback!)'}",
        "• Muxlisa bepulga: " + ("ha" if MUXLISA_FOR_FREE else "yo'q"),
        f"• Max yuklama: {MAX_UPLOAD_MB} MB",
        "",
    ]
    if user_uzbek_usage:
        top = sorted(user_uzbek_usage.items(), key=lambda x: x[1], reverse=True)[:5]
        lines.append("Eng ko'p ishlatganlar:")
        for uid, sec in top:
            tariff = TARIFFS.get(user_tariffs.get(uid, "free"), TARIFFS["free"])
            tariff_name = tariff['name']
            lines.append(f"• {uid} — {sec/60:.1f} / {tariff['minutes']} daq ({tariff_name})")
    # Plain text — Markdown'siz, parse xatosi yo'q
    await update.message.reply_text("\n".join(lines))


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
        state = _peek_translation_state(update.effective_user.id)
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
        state = _peek_translation_state(update.effective_user.id)
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
    process_pdf_translation_for_user chaqiriladi (submit_job orqali).

    busy_guard EMAS: atomik belgini submit_job qo'yadi (ish tugaguncha ushlab
    turadi). Bu yerda faqat ADVISORY tekshiruv — band bo'lsa PDF'ni yuklab
    o'tirmaymiz (Telegram PDF ≤20MB, xavf kichik). Tarjima rejimi FAQAT
    submit qabul qilingandan keyin iste'mol qilinadi."""
    user_id = update.effective_user.id
    if not _is_admin_user(update.effective_user) and _is_user_processing(user_id):
        await update.message.reply_text(BUSY_MESSAGE)
        return
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
        # Umumiy navbat orqali — cap, duplicate himoyasi va navbat cheklovi bilan.
        # (Ilgari bu yo'l xom threading.Thread ochib, hamma cheklovni chetlab o'tardi.)
        _chat = getattr(update, "effective_chat", None)
        accepted = submit_job(
            user_id, process_pdf_translation_for_user,
            (user_id, tmp_path, source_lang, target_lang, "latin",
             _chat.id if _chat else user_id),
            label="pdf-tarjima-tg", cleanup_path=tmp_path,
        )
        if not accepted:
            return  # submit_job sababini yozdi; tarjima rejimi saqlanib qoldi
        # Ish qabul qilindi — endi rejimni iste'mol qilamiz (shartli: oradagi
        # await'larda user boshqa rejim tanlagan bo'lsa, unikini o'chirmaymiz)
        _pop_translation_state_if(user_id, source_lang, target_lang)
    except Exception as e:
        logging.error(f"PDF tarjima yuklash xato: {e}")
        await update.message.reply_text(
            f"❌ PDF tayyorlashda xato: {str(e)[:200]}\n\n💚 Daqiqa hisobingizdan yechilmadi."
        )
        if tmp_path and os.path.exists(tmp_path):
            try: os.remove(tmp_path)
            except Exception: pass


@busy_guard
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

        text = await _run_heavy(extract_pdf_text, tmp_path)
        if not text or not text.strip():
            await msg.edit_text("❌ PDF dan matn topilmadi (skanlangan rasm bo'lishi mumkin).")
            return

        # MUHIM: limit TTS'dan OLDIN — aks holda limitga sig'masa ham TTS
        # xarajati sarflanardi.
        if not is_admin(update):
            if not await can_process_uzbek(update, estimate_tts_duration_sec(text)):
                await msg.delete()
                return

        tts_path = await _run_heavy(make_tts, text)
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

        send_dur = actual_duration
        if send_dur <= 0:
            try: send_dur = int(await asyncio.to_thread(get_duration_or_estimate, tts_path))
            except Exception: send_dur = 0
        with open(tts_path, "rb") as f:
            await update.message.reply_voice(
                voice=f, caption="🔊 PDF ovoz shaklida",
                duration=send_dur if send_dur > 0 else None)
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
@busy_guard
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
        original_text = await _run_heavy(transcribe_whisper, file_path, source_lang, None, failed_ranges)
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
            lost_chunks = []
            translated = await _run_heavy(
                translate_with_claude, original_text, source_lang, None, target_lang, lost_chunks
            )
            if lost_chunks:
                await update.message.reply_text(_format_lost_chunks_text(lost_chunks))
            audio_lang = target_lang
        if not translated or not translated.strip():
            await msg.edit_text("❌ Tarjima bo'sh qaytdi.")
            return

        # 4) Natija — matn (PDF tugma orqali) + audio
        await msg.delete()
        tgt_label = TRANSLATION_TARGETS.get(target_lang, "🇺🇿 O'zbekcha")
        src_label = TRANSLATION_LANGS.get(source_lang, source_lang) if source_lang else "🌐 Avto"
        header = f"🌐 <b>Tarjima ({html.escape(src_label)} → {html.escape(tgt_label)}):</b>"
        _chat = getattr(update, "effective_chat", None)
        delivered = await asyncio.to_thread(
            _send_text_card,
            _chat.id if _chat else update.effective_user.id,
            translated, header, update.effective_user.id,
        )

        # 5) Tarif daqiqalari — faqat natija yetkazilgan bo'lsa
        if delivered and not is_admin(update) and actual_duration > 0:
            add_user_usage(update.effective_user.id, actual_duration * TRANSLATION_MULTIPLIER)
    except Exception as e:
        logging.error(f"Tarjima xato: {e}")
        await msg.edit_text(f"❌ Tarjima xato: {str(e)[:300]}")


@busy_guard
async def process_translation_from_file_id(update, context, file_id, suffix, duration_sec, source_lang, target_lang="uz"):
    """File_id orqali kelgan audio/video uchun wrapper.

    @busy_guard SHU yerda — yuklab olish guard ichida bo'lsin (ikki marta
    yuborilgan video ikki marta to'liq yuklab olinmasin). Ichkaridagi
    process_translation ham guard'langan, lekin _busy_owner contextvar
    tufayli o'zimizni bloklamaydi (re-entrant)."""
    tmp_path = None
    try:
        file = await context.bot.get_file(file_id)
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp_path = tmp.name
        await file.download_to_drive(tmp_path)
        await process_translation(update, context, tmp_path, duration_sec, source_lang, target_lang)
        # Rejim FAQAT oqim yakunlangach iste'mol qilinadi (shartli — oradagi
        # await'larda user yangi rejim tanlagan bo'lsa, unga tegilmaydi).
        # JobQueueFullError (BaseException) bu qatorga yetmasdan o'tib ketadi —
        # navbat to'la bo'lsa rejim saqlanadi va user bemalol qayta yuboradi.
        _pop_translation_state_if(update.effective_user.id, source_lang, target_lang)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try: os.remove(tmp_path)
            except Exception: pass
# === [/TARJIMA MODULI — ASOSIY WORKFLOW] =======================================


@busy_guard
async def text_to_voice(update, context, text):
    """Berilgan matnni ovozli MP3 ga aylantirib yuboradi.
    Tarif limiti qo'llanadi — natija audio davomiyligi ishlatilgan daqiqaga qo'shiladi."""
    # Adminda limit yo'q. MUHIM: limit TTS'dan OLDIN tekshiriladi — aks holda
    # daqiqasi tugagan foydalanuvchi cheksiz OpenAI TTS xarajati keltira olardi.
    if not is_admin(update):
        estimated_sec = estimate_tts_duration_sec(text)
        if not await can_process_uzbek(update, estimated_sec):
            return

    msg = await update.message.reply_text("🔊 Matn ovozga aylantirilmoqda...")
    tts_path = None
    try:
        tts_path = await _run_heavy(make_tts, text)
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
        send_dur = actual_duration
        if send_dur <= 0:
            try: send_dur = int(await asyncio.to_thread(get_duration_or_estimate, tts_path))
            except Exception: send_dur = 0
        with open(tts_path, "rb") as f:
            await update.message.reply_voice(
                voice=f, caption="🔊 Matn ovoz shaklida",
                duration=send_dur if send_dur > 0 else None)

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
                text=f"💬 *Xizmatdan javob:*\n\n{md_escape(text)}",
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
                    "💬 Murojaat", "🔄 /start", "/start",
                    "👥 Userlar", "🎁 Tarif berish", "🔐 Admin panel"):
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
    # === Admin tugmalari ===
    if text == "👥 Userlar":
        await stats_cmd(update, context)
        return
    if text == "📖 Buyruqlar":
        if is_admin(update):
            await _send_admin_commands_list(update)
        else:
            await update.message.reply_text("⛔ Bu tugma faqat admin uchun.")
        return
    if text == "🎁 Tarif berish":
        # Legacy — agar eski keyboard'da bo'lsa
        if is_admin(update):
            await _send_admin_commands_list(update)
        else:
            await update.message.reply_text("⛔ Bu tugma faqat admin uchun.")
        return
    if text == "🔐 Admin panel":
        await admin_panel_cmd(update, context)
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
        reply_markup=webapp_keyboard(chat_id=update.effective_user.id, username=update.effective_user.username),
    )


async def audit_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: ma'lumot saqlash holatini tekshirish (persistent volume etc)."""
    if not is_admin(update):
        await update.message.reply_text("⛔ Faqat admin uchun.")
        return
    lines = ["🔍 AUDIT\n"]
    # DATA_FILE
    lines.append(f"📂 DATA_FILE: {DATA_FILE}")
    if os.path.exists(DATA_FILE):
        sz = os.path.getsize(DATA_FILE)
        lines.append(f"   ✅ Mavjud, hajmi: {sz:,} bayt")
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                disk_data = json.load(f)
            disk_tariffs = disk_data.get('tariffs') or {}
            lines.append(f"   🔹 Tariflar (disk): {len(disk_tariffs)}")
            # Har paid user'ni ko'rsatamiz
            for k, v in disk_tariffs.items():
                if v != "free":
                    lines.append(f"      • {k} → {v}")
            lines.append(f"   🔹 Usage (disk): {len(disk_data.get('usage') or {})}")
            lines.append(f"   🔹 User info (disk): {len(disk_data.get('user_info') or {})}")
        except Exception as e:
            lines.append(f"   ❌ O'qishda xato: {e}")
    else:
        lines.append("   ❌ FAYL YO'Q!")

    # TARIFF_LOG_FILE
    lines.append(f"\n📝 TARIFF_LOG_FILE: {TARIFF_LOG_FILE}")
    if os.path.exists(TARIFF_LOG_FILE):
        sz = os.path.getsize(TARIFF_LOG_FILE)
        log_entries = []
        try:
            with open(TARIFF_LOG_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entry = json.loads(line)
                            log_entries.append(entry)
                        except Exception:
                            pass
        except Exception:
            pass
        lines.append(f"   ✅ Mavjud, hajmi: {sz:,} bayt, qatorlar: {len(log_entries)}")
        # Har bir log entry'ni ko'rsatish
        for entry in log_entries:
            lines.append(f"   • {entry.get('uid')} → {entry.get('tariff')} ({entry.get('src', '?')})")
    else:
        lines.append("   ❌ LOG FAYL YO'Q!")

    # Memory
    lines.append(f"\n🧠 Memory:")
    lines.append(f"   🔹 Tariflar (memory): {len(user_tariffs)}")
    lines.append(f"   🔹 Usage (memory): {len(user_uzbek_usage)}")
    lines.append(f"   🔹 User info (memory): {len(user_info)}")
    paid_count = sum(1 for t in user_tariffs.values() if t != "free")
    lines.append(f"   💎 Paid (memory): {paid_count}")

    # Volume tekshirish
    lines.append(f"\n💾 Persistent volume:")
    if DATA_FILE.startswith("/data"):
        lines.append("   ✅ /data yo'l ishlatilyapti")
        # /data papkasi mavjudmi
        if os.path.isdir("/data"):
            try:
                files = os.listdir("/data")
                lines.append(f"   📁 /data ichida: {len(files)} fayl")
                for f in files[:10]:
                    lines.append(f"      • {f}")
            except Exception as e:
                lines.append(f"   ❌ /data o'qishda: {e}")
        else:
            lines.append("   ⚠️ /data papka YO'Q! (volume mount qilinmagan)")
    else:
        lines.append(f"   ⚠️ /data emas: {DATA_FILE} — bu ephemeral bo'lishi mumkin!")

    await update.message.reply_text("\n".join(lines))


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
                f"👤 Kim: {md_escape(username)}\n"
                f"🆔 ID: `{user_id}`\n\n"
                f"💬 Xabar:\n{md_escape(msg_text)}\n\n"
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
            text=f"💬 *Xizmatdan javob:*\n\n{md_escape(msg_text)}",
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

    # Target har doim O'zbek (klient talabi) - target tanlash bosqichi olib tashlandi
    pending_translations[user_id] = {"source": choice, "target": "uz"}
    _save_user_data()
    src_label = TRANSLATION_LANGS[choice]

    await query.edit_message_text(
        f"✅ *Tarjima sozlandi*\n\n"
        f"📚 Manba: *{src_label}*\n"
        f"🎯 Natija: 🇺🇿 O'zbek tilida\n\n"
        f"📥 Endi quyidagilardan birini yuboring:\n"
        f"• 🎤 Ovozli xabar / audio fayl\n"
        f"• 🎬 Video / dumaloq video\n"
        f"• 📄 PDF fayl\n\n"
        f"💡 1 daqiqa = 1 daqiqa tarifdan ayriladi.\n"
        f"Bekor qilish: /cancel",
        parse_mode="Markdown",
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

    # PDF/TXT — matn kerak. Matnlar faqat RAM'da (24 soat), bot qayta
    # ishga tushsa yo'qoladi — bu normal, chunki natija allaqachon PDF
    # ko'rinishida yuborilgan.
    record = last_transcripts.get(user_id)
    if not record or not record.get("text"):
        await context.bot.send_message(
            chat_id=user_id,
            text="⚠️ Saqlangan matn topilmadi — 24 soatdan oshgan yoki bot"
                 " yangilangan bo'lishi mumkin.\n"
                 "Iltimos audio/videoni qayta yuboring.",
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

def _tg_ok(resp, what=""):
    """Telegram javobi haqiqatan muvaffaqiyatlimi. requests javobi HTTP 200
    bo'lsa ham `ok:false` bo'lishi mumkin — ikkalasini ham tekshiramiz."""
    if resp is None:
        return False
    try:
        if resp.status_code != 200:
            logging.error(f"Telegram {what} HTTP {resp.status_code}: {resp.text[:300]}")
            return False
        if not resp.json().get("ok"):
            logging.error(f"Telegram {what} ok=false: {resp.text[:300]}")
            return False
        return True
    except Exception as e:
        logging.error(f"Telegram {what} javobini o'qib bo'lmadi: {e}")
        return False


def telegram_send_message(chat_id, text):
    """Telegram API ga to'g'ridan to'g'ri HTTP — alohida loop'dan xavfsiz.
    Returns True — barcha bo'laklar yetkazilgan bo'lsa."""
    if not text:
        return False
    all_ok = True
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        for i in range(0, len(text), 4000):
            chunk = text[i:i+4000]
            resp = requests.post(url, data={"chat_id": chat_id, "text": chunk}, timeout=60)
            if not _tg_ok(resp, "sendMessage"):
                all_ok = False
    except Exception as e:
        logging.error(f"Telegram send error: {e}")
        return False
    return all_ok


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
    """Returns True — hujjat haqiqatan yetkazilgan bo'lsa."""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
        with open(file_path, 'rb') as f:
            files = {"document": (filename or os.path.basename(file_path), f, "application/pdf")}
            data = {"chat_id": chat_id}
            if caption:
                data["caption"] = caption
            resp = requests.post(url, data=data, files=files, timeout=120)
        return _tg_ok(resp, "sendDocument")
    except Exception as e:
        logging.error(f"Telegram document send error: {e}")
        return False


def telegram_send_voice(chat_id, file_path, caption=None):
    """Voice/audio yuboradi. Katta fayl (> 1 MB) bo'lsa sendAudio orqali yuboriladi
    (sendVoice 1 MB lik chegaraga ega, uzun audio uchun mos emas)."""
    try:
        size_mb = 0
        try:
            size_mb = os.path.getsize(file_path) / (1024 * 1024)
        except Exception:
            pass

        # Davomiylikni aniqlab, Telegram'ga uzatamiz — pleer audioni to'liq
        # (oxirigacha) o'ynashi uchun. Aks holda ba'zi mijozlar erta to'xtaydi.
        duration = 0
        try:
            duration = int(get_duration_or_estimate(file_path))
        except Exception:
            duration = 0

        # Katta fayl uchun sendAudio (1 MB dan oshsa)
        if size_mb > 1.0:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendAudio"
            with open(file_path, 'rb') as f:
                files = {"audio": ("audio.mp3", f, "audio/mpeg")}
                data = {"chat_id": chat_id, "title": "Audio"}
                if duration > 0:
                    data["duration"] = duration
                if caption:
                    data["caption"] = caption
                resp = requests.post(url, data=data, files=files, timeout=300)
                return _tg_ok(resp, "sendAudio")
        # Kichik fayl uchun sendVoice
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendVoice"
        with open(file_path, 'rb') as f:
            files = {"voice": ("voice.mp3", f, "audio/mpeg")}
            data = {"chat_id": chat_id}
            if duration > 0:
                data["duration"] = duration
            if caption:
                data["caption"] = caption
            resp = requests.post(url, data=data, files=files, timeout=300)
        return _tg_ok(resp, "sendVoice")
    except Exception as e:
        logging.error(f"Telegram voice/audio send error: {e}")
        return False


def _unclear_marker_note(text):
    """[?] belgilari bo'lsa, ular nimani anglatishini tushuntiruvchi qator.

    Bot tushunmagan so'zni o'ylab topmaydi, [?] bilan belgilaydi — foydalanuvchi
    qayerni asl audio bilan solishtirish kerakligini bilishi uchun."""
    if not text:
        return ""
    count = text.count("[?]")
    if not count:
        return ""
    return (
        f"\n\n❓ Matnda {count} ta [?] belgisi bor — bu joylarni bot aniq "
        f"eshitmadi va taxmin qilmadi. Iltimos asl audio bilan solishtiring."
    )


def _quick_quality_label(text):
    """Matn sifatini taxminiy bahosi (audio davomiyligisiz, faqat matn asosida).
    Returns: (emoji, label) yoki None — agar matn yaxshi bo'lsa hech narsa demaslik."""
    if not text or len(text) < 50:
        return None
    words = text.split()
    if len(words) < 20:
        return None
    # Unique word ratio
    unique = set(w.lower().strip(".,!?\"'") for w in words)
    unique_ratio = len(unique) / len(words)
    # Eng ko'p uchragan so'z foizi
    freq = {}
    for w in words:
        wl = w.lower().strip(".,!?\"'")
        if len(wl) > 2:
            freq[wl] = freq.get(wl, 0) + 1
    max_word_ratio = max(freq.values()) / len(words) if freq else 0

    if unique_ratio < 0.12 or max_word_ratio > 0.25:
        return ("🔴", "Sifat past — audio'ni qisqaroq qismlarga bo'lib qayta yuboring")
    if unique_ratio < 0.20:
        return ("🟡", "O'rta sifat — ba'zi joylar noto'g'ri bo'lishi mumkin")
    return None  # Yaxshi sifat, user'ga eslatma kerak emas


def _send_quality_warning(user_id, text):
    """Agar matn sifati past bo'lsa user'ga oldindan ogohlantirish."""
    label = _quick_quality_label(text)
    if not label:
        return
    emoji, msg = label
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": user_id,
            "text": f"{emoji} {msg}",
        }, timeout=15)
    except Exception as e:
        logging.debug(f"Quality warning yuborish xato: {e}")


def _send_text_card(chat_id, text, header="📝 <b>Matn:</b>", remember_uid=None):
    """Matnni 2 ta PDF (Lotin + Kirill) qilib avtomat yuborish.
    Audio transkripsiya VA PDF tarjima uchun ishlatiladi.
    Sync — async kontekstda ham xavfsiz ishlaydi (requests orqali).

    chat_id — natija YUBORILADIGAN chat (guruhda ishlatilsa guruhning o'zi;
    ilgari bu yerga user_id berilardi va guruhdagi so'rov natijasi user'ning
    shaxsiy chatiga ketardi). remember_uid — matn keshining egasi (default: chat).

    Returns True — natija haqiqatan yetkazilgan bo'lsa (billing shunga qarab)."""
    # Sifat tekshiruvi va ogohlantirish (faqat past sifat)
    _send_quality_warning(chat_id, text)
    return _send_text_and_pdf(chat_id, text, remember_uid=remember_uid)


def _send_pdf_variant(user_id, text, filename, caption, title=None):
    """Bitta PDF yasab yuboradi. Returns True — faqat Telegram tasdiqlagan bo'lsa."""
    pdf_path = None
    try:
        pdf_path = make_pdf(text) if title is None else make_pdf(text, title=title)
    except Exception as e:
        logging.error(f"PDF yasashda xato ({filename}): {e}")
        return False
    try:
        return telegram_send_document(user_id, pdf_path, filename=filename, caption=caption)
    finally:
        if pdf_path and os.path.exists(pdf_path):
            try: os.remove(pdf_path)
            except Exception: pass


def _send_text_and_pdf(user_id, text, remember_uid=None):
    """2 ta PDF yuboradi (Lotin + Kirill).

    Returns True — kamida BITTA PDF haqiqatan yetkazilgan bo'lsa.
    MUHIM: chaqiruvchi shu qiymatga qarab daqiqa yechadi. Ilgari bu funksiya
    hamma xatoni yutib yuborardi va foydalanuvchi hech nima olmasa ham
    daqiqasi yechilardi.
    text — Lotin alifbosida bo'lishi kutiladi."""
    word_count = len(text.split())
    char_count = len(text)
    telegram_send_message(
        user_id,
        f"✅ Transkripsiya tayyor!\n\n"
        f"📊 {word_count:,} ta so'z • {char_count:,} ta belgi\n\n"
        f"📥 2 ta PDF yuboriladi (Lotin va Kirill)..."
        + _unclear_marker_note(text)
    )

    # 1) Lotin PDF
    latin_ok = _send_pdf_variant(
        user_id, text, "mnsm-lotin.pdf", "📄 Lotin alifbosida"
    )
    if not latin_ok:
        logging.error(f"Lotin PDF yetkazilmadi (user {user_id})")

    # 2) Kirill PDF
    cyrillic_ok = False
    try:
        cyrillic_text = convert_latin_to_cyrillic(text)
        cyrillic_ok = _send_pdf_variant(
            user_id, cyrillic_text, "mnsm-kirill.pdf", "📄 Кирилл алифбосида",
            title="Audio & Konspekt — Кирилл",
        )
    except Exception as e:
        logging.error(f"Kirill PDF xato: {e}")
    if not cyrillic_ok:
        telegram_send_message(
            user_id, "⚠️ Kirill PDF tayyorlashda muammo bo'ldi."
        )

    # Hech qaysi PDF yetkazilmadi — matnni hech bo'lmaganda xabar sifatida beramiz.
    # Shu ham yiqilsa, chaqiruvchi daqiqani yechmaydi.
    if not latin_ok and not cyrillic_ok:
        logging.error(f"⛔ Hech qanday PDF yetkazilmadi (user {user_id}) — matn bilan urinamiz")
        fallback_ok = telegram_send_message(user_id, text)
        if not fallback_ok:
            telegram_send_message(
                user_id,
                "❌ Natijani yetkazib bo'lmadi (texnik nosozlik).\n\n"
                "💚 Daqiqa hisobingizdan yechilmadi. Iltimos qayta urinib ko'ring."
            )
            return False

    # Oxirgi matnni RAM'da eslab qolamiz (diskka yozilmaydi)
    remember_transcript(remember_uid if remember_uid is not None else user_id, text)
    return True


# ── HTTP/THREAD CONTEXT UCHUN LIMIT TEKSHIRUVI ─────────────────────────────
# WebApp orqali yuborilgan fayllar Update obyektisiz thread'da ishlanadi.
# Shu sababli user_id asosida ishlaydigan alohida limit funksiyasi kerak.

def _is_admin_id(user_id):
    """user_id admin'ga tegishlimi (limit tekshiruvini chetlab o'tish uchun).
    ADMIN_USER_IDS sozlangan bo'lsa faqat shu ro'yxat hisobga olinadi."""
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return False
    if ADMIN_USER_IDS:
        return uid in ADMIN_USER_IDS
    return ADMIN_CHAT_ID["id"] is not None and uid == ADMIN_CHAT_ID["id"]


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

        # MUHIM: limit TTS'dan OLDIN — aks holda limitga sig'masa ham
        # OpenAI/Edge TTS xarajati sarflanardi (foydalanuvchidan yechilmasdi).
        if not _is_admin_id(user_id):
            if not check_limit_by_user_id(user_id, estimate_tts_duration_sec(text)):
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

        # success FAQAT audio haqiqatan yetkazilgan bo'lsa True
        success = telegram_send_voice(user_id, tts_path, caption="🔊 PDF ovoz shaklida")
        if not success:
            telegram_send_message(
                user_id,
                "❌ Audio yuborib bo'lmadi (fayl juda katta yoki tarmoq nosozligi).\n\n"
                "💚 Daqiqa hisobingizdan yechilmadi."
            )

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
    output_alphabet: 'latin' yoki 'cyrillic' — O'zbek matni alifbosi.

    Eslatma: duplicate-click himoyasi va _unmark_processing endi submit_job
    ichida — barcha og'ir oqimlar (tarjima, URL, PDF) uchun bir xil ishlaydi."""
    success = False  # natija userga yetkazilganmi
    typing = TypingPing(user_id)
    typing.start()
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

        status_msg_id = telegram_send_message_returning_id(user_id, "🎙 Matn tayyorlanmoqda...")
        progress_cb = _make_http_progress_cb(user_id, status_msg_id) if status_msg_id else None
        failed_ranges = []
        # Paid tarif + Uzbek = Muhlisa native STT, aks holda OpenAI Whisper
        text = _transcribe_for_user(user_id, file_path, language=language, progress_cb=progress_cb, failed_ranges_out=failed_ranges)
        if status_msg_id:
            try: telegram_delete_message(user_id, status_msg_id)
            except Exception: pass
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
                # _send_text_and_pdf LOTIN matndan ikkala alifboda PDF yasaydi.
                # Oldindan Kirillga o'girish MUMKIN EMAS: ikkinchi konversiya
                # matnni buzadi va "Lotin" nomli PDF aslida Kirill chiqadi.
                # success FAQAT natija haqiqatan yetkazilgan bo'lsa True bo'ladi
                success = _send_text_and_pdf(user_id, text)
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
        # _unmark_processing submit_job'ning finally blokida (barcha oqim uchun)
        typing.stop()
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
            lost_chunks = []
            try:
                translated = translate_with_claude(
                    original_text, source_lang, None, target_lang, lost_chunks
                )
                if lost_chunks:
                    telegram_send_message(user_id, _format_lost_chunks_text(lost_chunks))
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
            # Ikkala alifbo PDF'i baribir yuboriladi — oldindan konversiya YO'Q
            header = f"🌐 <b>Tarjima ({html.escape(src_label)} → {html.escape(tgt_label)}):</b>"
            # success FAQAT natija haqiqatan yetkazilgan bo'lsa True
            success = _send_text_card(user_id, translated, header=header)

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
            lost_chunks = []
            try:
                logging.info(f"   → GPT tarjima: {detected} → {target_lang}")
                translated = translate_with_claude(
                    original_text, detected, None, target_lang, lost_chunks
                )
                logging.info(f"   ✅ Tarjima tayyor: {len(translated)} belgi")
                if lost_chunks:
                    telegram_send_message(user_id, _format_lost_chunks_text(lost_chunks))
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


def process_pdf_translation_for_user(user_id, pdf_path, source_lang="auto", target_lang="uz", output_alphabet="latin", chat_id=None):
    """PDF'ni xorijiy tildan tanlangan tilga tarjima qilib audio + PDF chiqarish.
    XAVFSIZ TO'LOV: faqat audio MUVAFFAQIYATLI yuborilgandan keyin daqiqa yechiladi.
    PROGRESS: Telegram'da 'bot yozmoqda...' indikatori ishlaydi.
    output_alphabet: 'latin' yoki 'cyrillic' — O'zbek matn alifbosi (target=uz uchun).
    chat_id — natija yuboriladigan chat (guruh bo'lishi mumkin); limit/billing
    baribir user_id bo'yicha."""
    chat_id = chat_id or user_id
    success = False
    estimated_audio_sec = 0
    progress = ProgressIndicator(chat_id, action="typing")
    progress.start()
    try:
        # 1) PDF dan matn ajratish
        try:
            original_text = extract_pdf_text(pdf_path)
        except Exception as e:
            telegram_send_message(
                chat_id,
                f"❌ PDF o'qib bo'lmadi: {str(e)[:200]}\n\n💚 Daqiqa hisobingizdan yechilmadi."
            )
            return
        if not original_text or not original_text.strip():
            telegram_send_message(
                chat_id,
                "❌ PDF dan matn topilmadi (skanlangan rasm bo'lishi mumkin).\n\n💚 Daqiqa hisobingizdan yechilmadi."
            )
            return
        # 2) PDF uzunligi (so'z) tarif uchun — taxminiy 1 so'z = 0.4 sek audio
        word_count = len(original_text.split())
        estimated_audio_sec = max(60, int(word_count * 0.4))  # kamida 1 daqiqa
        if not _is_admin_id(user_id):
            if not check_limit_by_user_id(user_id, estimated_audio_sec):
                return
        telegram_send_message(chat_id, "⏳ Biroz kuting, PDF tarjima qilinmoqda...")
        # 3) GPT tarjima (agar source != target bo'lsa)
        lost_chunks = []
        try:
            src = source_lang if (source_lang and source_lang != target_lang) else "auto"
            translated = translate_with_claude(
                original_text, src, None, target_lang, lost_chunks
            )
            if lost_chunks:
                telegram_send_message(chat_id, _format_lost_chunks_text(lost_chunks))
        except Exception as e:
            logging.error(f"PDF GPT tarjima xato: {e}")
            telegram_send_message(
                chat_id,
                f"❌ Tarjima xato: {str(e)[:200]}\n\n💚 Daqiqa hisobingizdan yechilmadi."
            )
            return
        if not translated or not translated.strip():
            telegram_send_message(
                chat_id,
                "❌ Tarjima bo'sh qaytdi.\n\n💚 Daqiqa hisobingizdan yechilmadi."
            )
            return
        # 4) Natija — matn + PDF + audio (target tilda)
        tgt_label = TRANSLATION_TARGETS.get(target_lang, "🇺🇿 O'zbekcha")
        # Ikkala alifbo PDF'i baribir yuboriladi — oldindan konversiya YO'Q
        header = f"🌐 <b>PDF tarjima ({html.escape(tgt_label)}):</b>"
        # success FAQAT natija haqiqatan yetkazilgan bo'lsa True
        success = _send_text_card(chat_id, translated, header=header, remember_uid=user_id)

        # 5) Audio — endi avtomat YO'Q (klient talabi). Alohida xizmat sifatida bo'ladi keyin.

        # 6) Tarif daqiqalari
        if success and not _is_admin_id(user_id) and estimated_audio_sec > 0:
            add_user_usage(user_id, estimated_audio_sec)
    except Exception as e:
        logging.error(f"process_pdf_translation_for_user xato: {e}")
        telegram_send_message(
            chat_id,
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
            lost_chunks = []
            try:
                translated = translate_with_claude(
                    original_text, source_lang, None, target_lang, lost_chunks
                )
                if lost_chunks:
                    telegram_send_message(user_id, _format_lost_chunks_text(lost_chunks))
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
        # Ikkala alifbo PDF'i baribir yuboriladi — oldindan konversiya YO'Q
        header = f"🌐 <b>Tarjima ({html.escape(src_label)} → {html.escape(tgt_label)}):</b>"
        # success FAQAT natija haqiqatan yetkazilgan bo'lsa True
        success = _send_text_card(user_id, translated, header=header)
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
    typing = TypingPing(user_id)  # chat tepasida 'yozmoqda...' indikatori
    typing.start()
    try:
        # Limit dastlabki tekshiruvi (davomiylik hali noma'lum)
        if not check_limit_by_user_id(user_id, 0):
            return

        telegram_send_message(user_id, f"📌 Qabul qilindi:\n🔗 {url}")
        # Status xabari — edit qilib stage bo'yicha yangilanadi
        status_msg_id = telegram_send_message_returning_id(user_id, "📥 Video yuklanmoqda...")
        try:
            audio_path = download_audio_from_url(url)
        except Exception as e:
            if status_msg_id:
                telegram_edit_message(user_id, status_msg_id, f"❌ Video yuklanmadi: {str(e)[:200]}")
            else:
                telegram_send_message(user_id, f"❌ Video yuklanmadi: {str(e)[:200]}")
            return

        # Yuklab olingach real davomiylikni aniqlaymiz
        actual_duration = 0
        if not _is_admin_id(user_id):
            try:
                actual_duration = int(get_duration_or_estimate(audio_path))
            except Exception:
                actual_duration = 0
            if not check_limit_by_user_id(user_id, actual_duration):
                if status_msg_id:
                    telegram_edit_message(user_id, status_msg_id, "❌ Limit yetmadi.")
                return

        if status_msg_id:
            telegram_edit_message(user_id, status_msg_id, "✅ Yuklandi. 🎙 Matn tayyorlanmoqda...")
        progress_cb = _make_http_progress_cb(user_id, status_msg_id) if status_msg_id else None
        failed_ranges = []
        # Paid tarif + Uzbek = Muhlisa native STT, aks holda OpenAI Whisper
        text = _transcribe_for_user(user_id, audio_path, language=language, progress_cb=progress_cb, failed_ranges_out=failed_ranges)

        # Status xabarini o'chiramiz (matn yetkazilgach kerak emas)
        if status_msg_id:
            try:
                telegram_delete_message(user_id, status_msg_id)
            except Exception:
                pass

        if failed_ranges:
            _send_failed_ranges_notice(user_id, failed_ranges)
        success = False
        if text and text.strip() != "Matn aniqlanmadi.":
            # Oldindan konversiya YO'Q — _send_text_and_pdf ikkala alifboni yuboradi
            success = _send_text_and_pdf(user_id, text)
        else:
            telegram_send_message(
                user_id,
                "❌ Matn aniqlanmadi (audio sifati past bo'lishi mumkin).\n\n"
                "💚 Daqiqa hisobingizdan yechilmadi."
            )

        # Faqat natija yetkazilgan bo'lsa daqiqa yechamiz
        if success and not _is_admin_id(user_id) and actual_duration > 0:
            add_user_usage(user_id, actual_duration)
    except Exception as e:
        logging.error(f"process_url_for_user xato: {e}")
        telegram_send_message(user_id, f"❌ Xato: {str(e)[:300]}")
    finally:
        typing.stop()
        if audio_path:
            shutil.rmtree(os.path.dirname(audio_path), ignore_errors=True)


# === [WEBAPP AUTH] Telegram initData imzosini tekshirish ========================
# MUHIM: user_id NI HECH QACHON klient tanasidan olmaymiz. Telegram WebApp
# `initData` qatorini bot token bilan imzolaydi; imzoni serverda tekshirib,
# user_id ni FAQAT imzolangan ma'lumotdan olamiz. Aks holda istalgan odam
# boshqa foydalanuvchining daqiqalarini yoqib yuborishi mumkin edi.
#
# Algoritm (Telegram rasmiy hujjati):
#   secret_key = HMAC_SHA256(key="WebAppData", msg=BOT_TOKEN)
#   hash       = HMAC_SHA256(key=secret_key, msg=data_check_string)
# data_check_string — `hash` va `signature` dan tashqari barcha maydonlar
# "key=value" ko'rinishida, kalit bo'yicha saralanib "\n" bilan birlashtirilgan.

# initData replay oynasi. Default 24h — Telegram WebApp'ni yopmasdan uzoq
# ishlatadigan foydalanuvchilar (uzun mikrofon sessiyalari) yozuvini yubora
# olishi uchun. Qisqartirish xavfsizroq, lekin ochiq turgan WebApp'dan kelgan
# so'rov auth'dan yiqilib, YOZUV YO'QOLADI — shuning uchun default konservativ,
# qisqartirish esa ongli qaror sifatida env orqali: INIT_DATA_MAX_AGE_HOURS=6
INIT_DATA_MAX_AGE = int(os.getenv("INIT_DATA_MAX_AGE_HOURS", "24")) * 3600


def _verify_init_data(init_data):
    """initData qatorini tekshiradi. Returns: user_id (int) yoki None.

    None qaytsa — imzo yaroqsiz, eskirgan yoki umuman yo'q."""
    if not init_data or not isinstance(init_data, str):
        return None
    try:
        # parse_qsl: qiymatlar avtomatik URL-decode qilinadi
        pairs = urllib.parse.parse_qsl(init_data, keep_blank_values=True, strict_parsing=False)
    except Exception:
        return None
    if not _WEBAPP_SECRET:
        return None   # DEGRADED: token yo'q, imzoni tekshirib bo'lmaydi
    fields = dict(pairs)
    received_hash = fields.pop("hash", "")
    # `signature` (Telegram'ning yangi Ed25519 imzosi) data_check_string'ga kirmaydi
    fields.pop("signature", None)
    if not received_hash:
        return None

    data_check_string = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    expected_hash = hmac.new(
        _WEBAPP_SECRET, data_check_string.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        logging.warning("🚫 WebApp initData imzosi mos kelmadi")
        return None

    # Eskirganini rad etamiz (replay himoyasi)
    try:
        auth_date = int(fields.get("auth_date", "0"))
    except (TypeError, ValueError):
        auth_date = 0
    if auth_date <= 0 or (time.time() - auth_date) > INIT_DATA_MAX_AGE:
        logging.warning(f"🚫 WebApp initData eskirgan (auth_date={auth_date})")
        return None

    try:
        user_obj = json.loads(fields.get("user") or "{}")
        user_id = int(user_obj.get("id"))
    except Exception:
        logging.warning("🚫 WebApp initData ichida user.id topilmadi")
        return None
    return user_id


def _auth_error_response():
    return web.json_response(
        {"error": "auth", "message": (
            "Foydalanuvchi tasdiqlanmadi. Iltimos botda /start yuboring va "
            "Web ilovani tugma orqali qayta oching."
        )},
        status=401,
        headers=cors_headers(),
    )
# === [/WEBAPP AUTH] ============================================================


async def handle_webapp_audio(request):
    """WebApp mikrofon yozuvi (base64). === [TARJIMA] translation_lang qo'llab-quvvatlanadi ==="""
    try:
        data = await request.json()
        # === [WEBAPP AUTH] user_id faqat imzolangan initData'dan ===
        user_id = _verify_init_data(data.get("init_data"))
        if not user_id:
            return _auth_error_response()
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
        if not audio_data:
            return web.json_response({"error": "audio yo'q"}, status=400, headers=cors_headers())
        ext = format_hint.split("/")[-1].split(";")[0] if "/" in format_hint else format_hint
        if not ext.startswith('.'):
            ext = '.' + ext
        tmp_path = save_base64_audio(audio_data, ext)
        # === [TARJIMA] Tarjima faqat source != target bo'lsa (upload/url bilan bir xil).
        # Ilgari bu guard yo'q edi: uz->uz mikrofon yozuvi tarjima pipeline'idan
        # o'tib, oddiy STT o'rniga 2x narxda hisoblanardi.
        if translation_lang and translation_lang != target_lang:
            accepted = submit_job(user_id, process_translation_for_user,
                       (user_id, tmp_path, translation_lang, target_lang), label="tarjima",
                       cleanup_path=tmp_path)
        else:
            # Upload yo'li bilan bir xil: clamp YO'Q — 'ar'/'auto' ham o'tadi,
            # process_audio_for_user Whisper orqali barcha tillarni biladi
            stt_lang = translation_lang if translation_lang else language
            accepted = submit_job(user_id, process_audio_for_user,
                       (user_id, tmp_path, stt_lang), label="audio", cleanup_path=tmp_path)
        if not accepted:
            # WebApp toast'i ham xatoni ko'rsatsin (ilgari confetti chiqardi!)
            return web.json_response(
                {"error": "busy", "message": BUSY_MESSAGE}, status=429, headers=cors_headers())
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
        init_data = ""  # === [WEBAPP AUTH] imzolangan Telegram ma'lumoti ===
        translation_lang = ""  # === [TARJIMA] source ===
        target_lang = "uz"      # === [TARJIMA] target — default uzbek ===
        pdf_audio_lang = ""     # === [PDF→MP3] alohida audio rejimi (faqat audio chiqsin) ===
        output_alphabet = "latin"  # === [ALIFBO] O'zbek matni Lotin yoki Kirill ===
        while True:
            part = await reader.next()
            if part is None:
                break
            if part.name == "init_data":
                init_data = (await part.text()).strip()
            elif part.name == "user_id":
                # Klient yuborgan user_id E'TIBORGA OLINMAYDI (faqat initData ishonchli)
                await part.text()
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
                # === [WEBAPP AUTH] Faylni O'QIShDAN OLDIN imzoni tekshiramiz ===
                # index.html init_data'ni fayldan oldin qo'shadi, shuning uchun
                # bu yerga yetganda u allaqachon bizda bo'ladi.
                user_id = _verify_init_data(init_data)
                if not user_id:
                    return _auth_error_response()
                file_name = part.filename or "upload.bin"
                # Butun faylni RAM'ga o'qimaymiz — bo'lak-bo'lak diskka yozamiz.
                # (512 MB'lik serverda 200 MB'lik video OOM qilardi.)
                ext = os.path.splitext(file_name)[1].lower() or ".bin"
                written = 0
                too_big = False
                with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                    tmp_path = tmp.name
                    while True:
                        block = await part.read_chunk(1024 * 1024)
                        if not block:
                            break
                        written += len(block)
                        if written > MAX_UPLOAD_BYTES:
                            too_big = True
                            break
                        # Diskka yozish thread'da — sekin disk katta yuklamada
                        # boshqa HTTP so'rovlarni (index, /url) muzlatmasin
                        await asyncio.to_thread(tmp.write, block)
                if too_big or written == 0:
                    try: os.remove(tmp_path)
                    except Exception: pass
                    if too_big:
                        return web.json_response(
                            {"error": "too_large",
                             "message": f"Fayl juda katta (maksimum {MAX_UPLOAD_MB} MB). "
                                        f"Iltimos videoni qismlarga bo'lib yuboring."},
                            status=413, headers=cors_headers())
                    return web.json_response({"error": "fayl bo'sh"}, status=400, headers=cors_headers())
                file_data = True  # fayl diskda — pastdagi tekshiruv uchun belgi
        if not user_id:
            return _auth_error_response()
        if not file_data:
            return web.json_response({"error": "fayl yo'q"}, status=400, headers=cors_headers())
        # === [PDF → MP3] WebApp PDF flow — faqat audio chiqsin (matn yo'q) ===
        if ext == ".pdf" and pdf_audio_lang:
            accepted = submit_job(user_id, process_pdf_audio_only,
                       (user_id, tmp_path, pdf_audio_lang), label="pdf-mp3", cleanup_path=tmp_path)
        # === [TARJIMA] PDF + translation_lang -> PDF tarjima (har doim O'zbek tiliga) ===
        elif ext == ".pdf" and translation_lang:
            # PDF tarjima uchun target HAR DOIM O'zbek (klient talabi)
            accepted = submit_job(user_id, process_pdf_translation_for_user,
                       (user_id, tmp_path, translation_lang, "uz", output_alphabet),
                       label="pdf-tarjima", cleanup_path=tmp_path)
        # PDF tarjimasiz — oddiy PDF -> ovoz (default O'zbekcha)
        elif ext == ".pdf":
            accepted = submit_job(user_id, process_pdf_for_user, (user_id, tmp_path),
                       label="pdf-audio", cleanup_path=tmp_path)
        # Audio/video + translation_lang -> tarjima (faqat source != target bo'lsa)
        elif translation_lang and translation_lang != target_lang:
            accepted = submit_job(user_id, process_translation_for_user,
                       (user_id, tmp_path, translation_lang, target_lang, output_alphabet),
                       label="tarjima", cleanup_path=tmp_path)
        # Oddiy audio/video -> oddiy STT (source==target yoki til tanlanmagan)
        else:
            stt_lang = translation_lang if translation_lang else language
            accepted = submit_job(user_id, process_audio_for_user,
                       (user_id, tmp_path, stt_lang, output_alphabet), label="audio",
                       cleanup_path=tmp_path)
        if not accepted:
            # Rad etildi (band/navbat to'la) — WebApp toast'i xatoni ko'rsatsin,
            # ilgari bu holatda ham "ok" + confetti chiqardi
            return web.json_response(
                {"error": "busy", "message": BUSY_MESSAGE}, status=429, headers=cors_headers())
        return web.json_response({"status": "ok"}, headers=cors_headers())
    except Exception as e:
        logging.error(f"HTTP upload xatosi: {e}")
        return web.json_response({"error": str(e)}, status=500, headers=cors_headers())


async def handle_webapp_url_post(request):
    """WebApp dan URL yuborish (YouTube/Instagram/TikTok). === [TARJIMA] translation_lang ==="""
    try:
        data = await request.json()
        # === [WEBAPP AUTH] user_id faqat imzolangan initData'dan ===
        user_id = _verify_init_data(data.get("init_data"))
        if not user_id:
            return _auth_error_response()
        # MUHIM: faqat http(s) havola. extract_url None qaytarsa — rad etamiz,
        # aks holda yt-dlp'ga "--config-location=..." kabi qiymat o'tib ketardi.
        url = extract_url((data.get("url") or "").strip())
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
        if not url:
            return web.json_response(
                {"error": "url", "message": "To'g'ri havola yuboring (http:// yoki https:// bilan)."},
                status=400, headers=cors_headers())
        # === [TARJIMA] Tarjima rejimi (source + target) ===
        # MUHIM: agar source == target (masalan, Uz->Uz) tarjimasiz oddiy STT
        if translation_lang and translation_lang != target_lang:
            accepted = submit_job(user_id, process_url_translation_for_user,
                       (user_id, url, translation_lang, target_lang, output_alphabet), label="url-tarjima")
        else:
            # Oddiy transkripsiya — manba til tanlangan bo'lsa shuni ishlatamiz
            stt_lang = translation_lang if translation_lang else language
            accepted = submit_job(user_id, process_url_for_user,
                       (user_id, url, stt_lang, output_alphabet), label="url")
        if not accepted:
            return web.json_response(
                {"error": "busy", "message": BUSY_MESSAGE}, status=429, headers=cors_headers())
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


# Startup'da aniqlangan sozlama muammolari — /health'da ham ko'rsatiladi.
# NEGA: bu sessiyada BOT_TOKEN yo'qligi soatlab sir bo'lib qoldi. Xuddi
# shunday JIM ishlaydigan boshqa nosozliklar ham bor edi — masalan /data
# volume mount qilinmasa, tariflar HAR DEPLOY'DA yo'qoladi va buni hech kim
# aytmaydi. Endi hammasi startup'da baland ovozda e'lon qilinadi.
STARTUP_WARNINGS = []


def _startup_config_audit():
    """Jim ishlaydigan noto'g'ri sozlamalarni topib, ro'yxat qaytaradi.
    Har element: (daraja, xabar). Daraja: 'critical' | 'warning'."""
    out = []

    # OPENAI_API_KEY endi MAJBURIY emas — Groq/Gemini uni almashtiradi.
    # Faqat OpenAI TTS unga bog'liq; qolgani quyida tekshiriladi.
    if not _ensure_openai_key():
        out.append(("warning",
                    "OPENAI_API_KEY yo'q — premium OpenAI TTS ishlamaydi "
                    "(matn va tarjima Groq/Gemini orqali ishlayveradi, "
                    "ovoz bepul Edge TTS bilan beriladi)."))

    if not ADMIN_USER_IDS:
        out.append(("warning",
                    "ADMIN_USER_ID yo'q — admin faqat username bo'yicha "
                    "aniqlanadi. Username bo'shatilsa, uni boshqa odam "
                    "egallab admin bo'lib qolishi mumkin."))

    if not have_cmd("ffmpeg"):
        out.append(("critical",
                    "ffmpeg topilmadi — audio/video umuman qayta ishlanmaydi."))

    # DATA_FILE yoziladimi va DOIMIYMI — eng jim yo'qotish manbai
    data_dir = os.path.dirname(DATA_FILE) or "."
    try:
        os.makedirs(data_dir, exist_ok=True)
        probe = os.path.join(data_dir, ".write_probe")
        with open(probe, "w") as f:
            f.write("x")
        os.remove(probe)
    except Exception as e:
        out.append(("critical",
                    f"DATA_FILE yozib bo'lmaydi ({data_dir}): {e} — "
                    f"tariflar va hisob SAQLANMAYDI."))
    else:
        on_platform = bool(os.getenv("RAILWAY_PUBLIC_DOMAIN")
                           or os.getenv("RAILWAY_PROJECT_ID")
                           or os.getenv("FLY_APP_NAME"))
        # MUHIM: yo'l NOMI hech narsani isbotlamaydi — _resolve_data_file()
        # Railway'da uni majburan "/data" qiladi. Haqiqiy savol: bu katalog
        # rostdan MOUNT qilingan volume'mi? Mount bo'lmasa — konteyner ichidagi
        # vaqtinchalik disk, ya'ni tariflar har deploy'da yo'qoladi.
        if on_platform:
            try:
                mounted = os.path.ismount(data_dir)
            except Exception:
                mounted = True   # aniqlay olmasak, bezovta qilmaymiz
            if not mounted:
                out.append(("critical",
                            f"{data_dir} MOUNT QILINGAN VOLUME EMAS — tariflar va "
                            f"hisob HAR DEPLOY'DA YO'QOLADI. Railway: Settings -> "
                            f"Volumes -> Mount path = {data_dir}"))

    # Matn modeli umuman bormi (tozalash va tarjima shunga bog'liq)
    if not _chat_attempts():
        out.append(("critical",
                    "Matn modeli kaliti YO'Q — tozalash va tarjima ISHLAMAYDI. "
                    "GEMINI_API_KEY (bepul: aistudio.google.com/apikey) yoki "
                    "GROQ_API_KEY (bepul: console.groq.com) qo'shing."))
    if not _stt_attempts():
        out.append(("critical",
                    "STT kaliti YO'Q — audio/video matnga AYLANMAYDI. "
                    "GROQ_API_KEY (bepul) yoki OPENAI_API_KEY qo'shing."))
    elif not GROQ_API_KEY and not GEMINI_API_KEY:
        out.append(("warning",
                    "Bepul zaxira provayder yo'q — asosiy provayder limitga "
                    "urilsa yoki yiqilsa xizmat to'xtaydi. GROQ_API_KEY va "
                    "GEMINI_API_KEY kartasiz bepul, zaxira bo'lib turadi."))

    if not MUXLISA_KEY:
        out.append(("warning",
                    "MUXLISA_KEY yo'q — Premium tarif ham OpenAI Whisper "
                    "orqali ishlaydi (o'zbek sifati pastroq bo'lishi mumkin)."))

    if not (runtime_settings.get("payment_card") or PAYMENT_CARD):
        out.append(("warning",
                    "To'lov kartasi sozlanmagan — /buy oqimi chala. "
                    "Tuzatish: /setcard <raqam> va /setholder <ism>."))

    return out


async def handle_health(request):
    """Holat endpointi — deploy tirikligini va sozlanganini bir so'rovda
    aniqlash uchun (tools/live_check.py shundan foydalanadi)."""
    running, queued = _job_slots_info()
    payload = {
        "status": "degraded" if DEGRADED_REASON else "ok",
        "reason": DEGRADED_REASON or None,
        "jobs": {"running": running, "queued": queued,
                 "max_concurrent": MAX_CONCURRENT_JOBS, "max_queued": MAX_QUEUED_JOBS},
        "admin_configured": bool(ADMIN_USER_IDS),
        "openai_configured": bool(OPENAI_API_KEY),
        "data_file": DATA_FILE,
        "warnings": [{"level": lv, "message": m} for lv, m in STARTUP_WARNINGS],
    }
    return web.json_response(payload, status=503 if DEGRADED_REASON else 200,
                             headers=cors_headers())


@web.middleware
async def degraded_middleware(request, handler):
    """DEGRADED rejimda /health va statik'dan boshqa hamma narsa 503 +
    SABAB. Bot sozlanmagan bo'lsa hech qanday ish qabul qilinmaydi."""
    if DEGRADED_REASON and request.path not in ("/health",):
        if request.method == "OPTIONS":
            return await handler(request)
        return web.json_response(
            {"error": "degraded", "message": DEGRADED_REASON},
            status=503, headers=cors_headers())
    return await handler(request)


async def run_http_server():
    # client_max_size — MAX_UPLOAD_BYTES + multipart sarlavhalari uchun kichik zaxira
    web_app = web.Application(client_max_size=MAX_UPLOAD_BYTES + 8 * 1024 * 1024)
    web_app.middlewares.append(degraded_middleware)
    web_app.router.add_get('/health', handle_health)
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

    if DEGRADED_REASON:
        # Bot ishga tushirilmaydi, lekin jarayon TIRIK qoladi va HTTP server
        # tashxis beradi. Aks holda platformada deployment yo'qoladi va
        # egasi "Application not found" degan sirli javobni ko'rardi.
        threading.Thread(target=run_http_server_thread, daemon=True).start()
        logging.error("⛔ DEGRADED REJIM: %s", DEGRADED_REASON)
        print(f"⛔ DEGRADED: {DEGRADED_REASON}", flush=True)
        print(f"   Tashxis: http://0.0.0.0:{HTTP_PORT}/health", flush=True)
        while True:
            time.sleep(60)
            logging.error("⛔ Hali ham DEGRADED: %s", DEGRADED_REASON)

    # Saqlangan usage va tariflarni yuklash
    _load_user_data()

    # Jim ishlaydigan noto'g'ri sozlamalarni BALAND OVOZDA e'lon qilamiz
    try:
        STARTUP_WARNINGS.extend(_startup_config_audit())
    except Exception as e:
        logging.warning(f"Config audit xato: {e}")
    if STARTUP_WARNINGS:
        crit = sum(1 for lv, _ in STARTUP_WARNINGS if lv == "critical")
        print("=" * 62, flush=True)
        print(f"SOZLAMA OGOHLANTIRISHLARI: {len(STARTUP_WARNINGS)} ta "
              f"({crit} ta jiddiy)", flush=True)
        for lv, msg in STARTUP_WARNINGS:
            mark = "⛔" if lv == "critical" else "⚠️"
            print(f"  {mark} {msg}", flush=True)
            (logging.error if lv == "critical" else logging.warning)("%s %s", mark, msg)
        print("Batafsil: GET /health", flush=True)
        print("=" * 62, flush=True)
    else:
        logging.info("✅ Sozlamalar auditi toza")

    # MUHIM: Tariff log'dan tiklash — JSON eski/buzilgan bo'lsa ham tarif yo'qolmaydi
    try:
        _replay_tariff_log()
    except Exception as e:
        logging.error(f"❌ Tariff log replay xato: {e}")

    # Eslatma: bu yerda ilgari 2026-05 dagi bir martalik migratsiyalar bor edi
    # (30 ta foydalanuvchi tarifi/usage'i kodga qattiq yozilgan). Ular olib
    # tashlandi — marker fayl volume bilan birga o'chsa MIGRATSIYA QAYTA
    # ISHLAB, uch oylik eski usage qiymatlarini tiklab qo'yardi. Ma'lumot
    # yo'qolsa endi /restore (Telegram'dagi backup fayl) ishlatiladi.

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

    # concurrent_updates: PTB default holatda update'larni KETMA-KET ishlaydi —
    # ya'ni bitta uzun transkripsiya paytida /start ham, /balance ham javobsiz
    # qolardi. Og'ir ishlar endi umumiy pool (3 slot) va busy_guard bilan
    # cheklangani uchun parallel update'lar xavfsiz. 32 — yengil handlerlar
    # uchun yetarli yuqori, xotira uchun xavfsiz past chegara.
    app = Application.builder().token(BOT_TOKEN).concurrent_updates(32).build()
    bot_app = app

    async def _setup_commands(application):
        # Jiddiy sozlama muammolari bo'lsa — adminga xabar (jim qolmasin)
        crit = [m for lv, m in STARTUP_WARNINGS if lv == "critical"]
        if crit and ADMIN_CHAT_ID["id"]:
            try:
                await application.bot.send_message(
                    chat_id=ADMIN_CHAT_ID["id"],
                    text="⛔ Startup: jiddiy sozlama muammolari\n\n"
                         + "\n".join(f"• {m}" for m in crit[:8])
                         + "\n\nBatafsil: /debug",
                )
            except Exception as e:
                logging.warning(f"Startup ogohlantirish yuborilmadi: {e}")

        # Startup replay pullik tarifni o'zgartirgan bo'lsa — adminga xabar
        # (jimgina pasayish mijoz shikoyatigacha sezilmay qolmasin)
        if _replay_downgrades and ADMIN_CHAT_ID["id"]:
            try:
                lines = ["⚠️ Startup: jurnal quyidagi PULLIK tariflarni o'zgartirdi:"]
                for uid, old_t, new_t in _replay_downgrades[:20]:
                    lines.append(f"• {uid}: {old_t} → {new_t}")
                lines.append("")
                lines.append("Noto'g'ri bo'lsa: /grant <id> <tarif> force")
                await application.bot.send_message(
                    chat_id=ADMIN_CHAT_ID["id"], text="\n".join(lines)
                )
            except Exception as e:
                logging.warning(f"Replay-downgrade xabari yuborilmadi: {e}")
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
    app.add_handler(CommandHandler("audit", audit_cmd))
    app.add_handler(CommandHandler("lang", lang_command))
    app.add_handler(CommandHandler("balance", balance_cmd))
    app.add_handler(CommandHandler("tariflar", tariflar_cmd))
    app.add_handler(CommandHandler("buy", buy_cmd))
    app.add_handler(CommandHandler("tavsiya", tavsiya_cmd))
    app.add_handler(CommandHandler("openai", openai_cmd))
    app.add_handler(CommandHandler("test", test_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("reset", reset_cmd))
    app.add_handler(CommandHandler("grant", grant_cmd))
    app.add_handler(CommandHandler("refund", refund_cmd))
    app.add_handler(CommandHandler("backup", backup_cmd))
    app.add_handler(CommandHandler("restore", restore_cmd))
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
