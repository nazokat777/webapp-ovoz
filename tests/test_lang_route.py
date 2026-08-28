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
print("[8] Manba tilini ANIQLASH bosqichi (ikki karra tarjimaga qarshi)")
# O'LCHANGAN XATTI-HARAKAT:
#   rus audio + language=uz  -> Whisper uni INGLIZCHAGA o'giradi
#      keyin o'zbekchaga tarjima => rus -> ingliz -> o'zbek (ikki karra,
#      aniqlik yo'qoladi)
#   o'zbek audio, til berilmagan -> "Fors" deb ARAB yozuvida
# Shuning uchun BITTA bo'lakda til aniqlanadi, keyin to'g'ri til
# majburlanadi. Arab yozuvi = o'zbek noto'g'ri aniqlangan degani.
_tw = [k for n, k in _bloklar if n == "transcribe_whisper"]
check("transcribe_whisper til aniqlash bosqichiga ega",
      bool(_tw) and "MANBA TILINI ANIQLASH" in _tw[0])
check("aniqlashda til MAJBURLANMAYDI (supported_langs=set())",
      bool(_tw) and "supported_langs=set()" in _tw[0],
      "aks holda aniqlash ma'nosiz bo'ladi")
check("arab yozuvi o'zbek deb qabul qilinadi",
      bool(_tw) and "_is_wrong_script" in _tw[0])
check("aniqlash JOB boshiga bir marta (bo'lak boshiga emas)",
      bool(_tw) and _tw[0].count("MANBA TILINI ANIQLASH") == 1)
check("aniqlash yiqilsa transkripsiya TO'XTAMAYDI",
      bool(_tw) and "o'tkazib yuborildi" in _tw[0],
      "til aniqlanmasa ham matn olinishi kerak")


print("[9] Tarjima bo'lagi hajmi — matn YO'QOLMASLIGI uchun")
# O'LCHOV (taxmin emas): model uzun matnni tarjima qilish o'rniga
# QISQARTIRIB yuboradi.
#     2400 so'z bir chaqiruvda ->  115 so'z (5%)
#      600 so'z bir chaqiruvda ->  638 so'z (106%)
# Ilgari chegara 3000 edi va 12 daqiqalik videoning 70% i JIMGINA
# yo'qolardi — foydalanuvchi to'liq konspekt olgan deb o'ylardi.
check("bo'lak hajmi xavfsiz chegarada", bot.CLAUDE_CHUNK_WORDS <= 1000,
      bot.CLAUDE_CHUNK_WORDS)
check("bo'lak hajmi juda mayda ham emas (ortiqcha chaqiruv)",
      bot.CLAUDE_CHUNK_WORDS >= 300, bot.CLAUDE_CHUNK_WORDS)

print("[10] Uzun matn tarjimasi: TARTIB, TO'LIQLIK, PARALLELLIK")
import threading as _th3

_asl_gpt = bot._gpt_translate_with_retry
_faol2 = {"hozir": 0, "cho_qqi": 0}
_lk2 = _th3.Lock()


def _soxta_gpt(chunk, src, tgt):
    with _lk2:
        _faol2["hozir"] += 1
        _faol2["cho_qqi"] = max(_faol2["cho_qqi"], _faol2["hozir"])
    _real_sleep2(0.05)
    with _lk2:
        _faol2["hozir"] -= 1
    return "[T]" + chunk


import time as _t3
_real_sleep2 = _t3.sleep
bot._gpt_translate_with_retry = _soxta_gpt
try:
    _soz = " ".join("w" + str(i) for i in range(2000))
    _yoq2 = []
    _natija2 = bot.translate_with_claude(_soz, "ru", None, "uz", _yoq2)
    check("uzun matn bo'laklandi", _natija2.count("[T]") >= 3,
          _natija2.count("[T]"))
    check("PARALLEL bajarildi", _faol2["cho_qqi"] > 1, _faol2["cho_qqi"])
    # Soxta tarjimon "[T]" ni birinchi so'zga YOPISHTIRIB qaytaradi,
    # shuning uchun birinchi token "[T]w0" bo'ladi
    check("birinchi so'z BOSHIDA", _natija2.split()[0] == "[T]w0",
          _natija2.split()[:3])
    check("oxirgi so'z OXIRIDA", _natija2.split()[-1] == "w1999",
          _natija2.split()[-3:])
    check("HECH BIR so'z yo'qolmadi",
          all(("w" + str(i)) in _natija2 for i in (0, 700, 1400, 1999)))
    check("yo'qolgan bo'lak yo'q", _yoq2 == [], _yoq2)

    print("[11] QISQARIB qolgan bo'lak ushlanadi va qayta urinmiladi")
    _urinish = {"n": 0}

    def _qisqartiruvchi(chunk, src, tgt):
        _urinish["n"] += 1
        # Birinchi urinishda qisqartirib yuboradi, ikkinchisida to'g'ri
        if _urinish["n"] % 2 == 1:
            return " ".join(chunk.split()[:5])
        return "[T]" + chunk

    bot._gpt_translate_with_retry = _qisqartiruvchi
    _yoq3 = []
    _n3 = bot.translate_with_claude(_soz, "ru", None, "uz", _yoq3)
    check("qisqargan bo'lak QAYTA urinildi",
          _urinish["n"] > len(_soz.split()) // bot.CLAUDE_CHUNK_WORDS,
          _urinish["n"])
    check("qayta urinishdan keyin matn to'liq",
          "w1999" in _n3 and "w0" in _n3, _n3[-40:])

    print("[12] Doim qisqartirsa — yo'qolgan bo'lak E'LON QILINADI")
    bot._gpt_translate_with_retry = lambda c, s, t: " ".join(c.split()[:3])
    _yoq4 = []
    try:
        _n4 = bot.translate_with_claude(_soz, "ru", None, "uz", _yoq4)
        _xato4 = None
    except Exception as e:
        _n4, _xato4 = None, str(e)
    check("30% dan ko'p yiqilsa ANIQ istisno (jim qisqa matn emas)",
          _xato4 is not None and "yiqildi" in _xato4.lower(), _xato4)
finally:
    bot._gpt_translate_with_retry = _asl_gpt
print("\nNatija: " + str(ok) + " pass, " + str(fail) + " fail")
sys.exit(1 if fail else 0)
