"""Manba tilini aniqlash va o'zbekchaga yo'naltirish.

MUAMMO (foydalanuvchi shikoyati): rus tilidagi YouTube videosidan RUS
tilida matn keldi. Bot esa "har qanday tildagi audio/video -> O'ZBEK
matn" deb va'da beradi. Sabab: havola va audio oqimlarida TARJIMA
BOSQICHI umuman yo'q edi — manba tili o'zbek deb taxmin qilinardi.

NEGA TIL MATNDAN ANIQLANADI, AUDIODAN EMAS:
Whisper'ga language=uz berilsa, u javobda ham "Uzbek" deb qaytaradi —
audio aslida ruscha bo'lsa ham. Bu amalda o'lchandi:
    ingliz audio + language=uz  -> javobda "Uzbek", matn INGLIZCHA
    o'zbek audio, til berilmagan -> javobda "Persian", ARAB yozuvida
Ya'ni provayderning til maydoni ishonchsiz. Chiqqan MATN esa yolg'on
gapirmaydi.

Tarmoq talab qilinmaydi — tarjima soxta funksiya bilan almashtiriladi.
"""
import os
import sys

os.environ["BOT_TOKEN"] = "111111:FAKE_LANG"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import bot  # noqa: E402

ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print("  PASS  " + name)
    else:
        fail += 1
        print("  FAIL  " + name + "  " + str(extra))


UZ = ("Assalomu alaykum, hurmatli talabalar. Bugungi ma'ruzamiz mavzusi "
      "iqtisodiyot nazariyasi va uning asosiy tamoyillari haqida bo'ladi. "
      "Birinchi navbatda talab va taklif qonuni haqida gaplashamiz.")
# Aynan foydalanuvchi rasmidagi matn
RU = ("Вы можете абсолютно сделать мотивированные видео для ваших "
      "фейсбук-каналов, и именно это мы будем делать в этом видео. "
      "Я покажу вам шаг за шагом, как вы можете получить мотивацию.")
EN = ("Today we will learn how to make faceless videos using artificial "
      "intelligence. First you need a script, and then you generate the "
      "voice for the video.")

print("[1] Matn tilini aniqlash")
check("o'zbek matni", bot.detect_text_lang(UZ) == "uz", bot.detect_text_lang(UZ))
check("rus matni (rasmdagi)", bot.detect_text_lang(RU) == "ru",
      bot.detect_text_lang(RU))
check("ingliz matni", bot.detect_text_lang(EN) == "en", bot.detect_text_lang(EN))
check("bo'sh matn xavfsiz", bot.detect_text_lang("") == "other")
check("None xavfsiz", bot.detect_text_lang(None) == "other")
check("juda qisqa matn -> other", bot.detect_text_lang("salom") == "other")
check("raqamlar xavfsiz", bot.detect_text_lang("123 456 789") == "other")

print("[2] O'zbek matniga TEGILMAYDI (behuda tarjima yo'q)")
_chaqirildi = []
_asl_tr = bot.translate_with_claude
_asl_send = bot.telegram_send_message
bot.translate_with_claude = lambda *a, **k: _chaqirildi.append(a) or "TARJIMA"
bot.telegram_send_message = lambda *a, **k: None
try:
    natija = bot.ensure_uzbek_text(1, UZ)
    check("o'zbek matni o'zgarishsiz qaytdi", natija == UZ)
    check("tarjima UMUMAN chaqirilmadi", _chaqirildi == [], _chaqirildi)

    print("[3] Rus va ingliz matni TARJIMA QILINADI")
    _chaqirildi.clear()
    natija = bot.ensure_uzbek_text(1, RU)
    check("rus matni tarjimaga yuborildi", len(_chaqirildi) == 1, _chaqirildi)
    check("natija tarjima", natija == "TARJIMA", natija)
    _chaqirildi.clear()
    bot.ensure_uzbek_text(1, EN)
    check("ingliz matni ham tarjimaga yuborildi", len(_chaqirildi) == 1)

    print("[4] Foydalanuvchi XABARDOR qilinadi")
    _xabarlar = []
    bot.telegram_send_message = lambda uid, t, **k: _xabarlar.append(t)
    bot.ensure_uzbek_text(1, RU)
    check("tarjima haqida xabar yuborildi", len(_xabarlar) == 1, _xabarlar)
    check("xabarda manba tili aytiladi",
          "rus" in (_xabarlar[0] if _xabarlar else ""), _xabarlar)
    _xabarlar.clear()
    bot.ensure_uzbek_text(1, UZ)
    check("o'zbek matnida xabar YO'Q", _xabarlar == [], _xabarlar)

    print("[5] Tarjima yiqilsa ASL MATN yo'qolmaydi")
    # Yarim ish bermaganidan manba tilidagi to'liq matn yaxshi
    def _yiqiladi(*a, **k):
        raise RuntimeError("provayder yiqildi")

    bot.translate_with_claude = _yiqiladi
    _xabarlar.clear()
    natija = bot.ensure_uzbek_text(1, RU)
    check("asl matn qaytdi (yo'qolmadi)", natija == RU, natija[:40])
    check("foydalanuvchi ogohlantirildi",
          any("Tarjima bajarilmadi" in x for x in _xabarlar), _xabarlar)

    bot.translate_with_claude = lambda *a, **k: ""
    natija = bot.ensure_uzbek_text(1, RU)
    check("bo'sh tarjimada ham asl matn qaytadi", natija == RU)
finally:
    bot.translate_with_claude = _asl_tr
    bot.telegram_send_message = _asl_send

print("[7] HAMMA transkripsiya oqimi tarjimadan o'tadi (struktura auditi)")
# Aynan shu xato takrorlanmasin: ensure_uzbek_text ikkita oqimga
# qo'shilgan edi, uchinchisi (_transcribe_flow — Telegram orqali
# yuborilgan havolalar) UNUTILGAN edi va foydalanuvchi yana rus
# tilida matn oldi. Endi audit avtomatik.
import re as _re

_src = open(os.path.join(ROOT, "bot.py"), encoding="utf-8").read().split("\n")
_bosh = [(i, l) for i, l in enumerate(_src) if _re.match(r"^(async )?def ", l)]
_bloklar = []
for _k, (_i, _l) in enumerate(_bosh):
    _j = _bosh[_k + 1][0] if _k + 1 < len(_bosh) else len(_src)
    _nom = _re.sub(r"^(async )?def ([A-Za-z_0-9]+).*", r"\2", _l)
    _bloklar.append((_nom, "\n".join(_src[_i:_j])))

# Quyi darajadagi STT funksiyalarining O'ZI — ular matn yetkazmaydi
_QUYI = {"transcribe_unified", "transcribe_whisper", "transcribe_muhlisa",
         "_transcribe_for_user", "_transcribe_chunk_muhlisa"}
# /tarjima oqimlari: ular foydalanuvchi TANLAGAN tilga o'giradi, majburiy
# o'zbek ularni buzardi (masalan ruschaga tarjima so'ralgan bo'lsa)
_TARJIMA_OQIMI = {"process_translation_for_user", "process_url_translation_for_user"}
_STT_BELGI = ("_run_heavy(transcribe_unified", "_transcribe_for_user(",
              "transcribe_whisper(", "transcribe_unified(")

_yetkazuvchi, _tarjimasiz = [], []
for _nom, _kod in _bloklar:
    if _nom in _QUYI or _nom.startswith("_try"):
        continue
    if not any(m in _kod for m in _STT_BELGI):
        continue
    _yetkazuvchi.append(_nom)
    if _nom in _TARJIMA_OQIMI:
        # O'z tarjimasi bo'lishi SHART
        if "translate_with_claude" not in _kod:
            _tarjimasiz.append(_nom + " (/tarjima oqimi, lekin tarjimasi yo'q)")
        continue
    if "ensure_uzbek_text" not in _kod:
        _tarjimasiz.append(_nom)

check("transkripsiya oqimlari topildi", len(_yetkazuvchi) >= 3, _yetkazuvchi)
check("HAR BIR oqim tarjimadan o'tadi", not _tarjimasiz, _tarjimasiz)
check("Telegram oqimi (_transcribe_flow) qamrab olingan",
      "_transcribe_flow" in _yetkazuvchi, _yetkazuvchi)

# Tarjima event loop'ni MUZLATMASLIGI kerak
_tf = [k for n, k in _bloklar if n == "_transcribe_flow"]
check("async oqimda tarjima alohida oqimda bajariladi",
      bool(_tf) and "run_in_executor" in _tf[0],
      "bloklovchi HTTP so'rov event loop'da bajarilmasin")
print("\nNatija: " + str(ok) + " pass, " + str(fail) + " fail")
sys.exit(1 if fail else 0)
