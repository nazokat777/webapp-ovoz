"""TARMOQ UZILISHIGA CHIDAMLILIK.

MUAMMO 1 (ko'rinadigan): uy internetida aloqa bir soniyaga uzilsa konsolga
40 qatorlik httpx.ReadError traceback'i chiqadi. Bot aslida o'lmaydi —
python-telegram-bot polling xatosini CHEKSIZ qayta uradi (max_retries=-1).
Lekin egasi bunday devorni ko'rib "bot buzildi" deb o'ylaydi. Amalda
shunday bo'ldi.

MUAMMO 2 (ko'rinmaydigan, jiddiyroq): run_polling() ning
bootstrap_retries qiymati sukut bo'yicha 0 — ya'ni ISHGA TUSHISH
lahzasidagi tarmoq nosozligi botni DARROV o'ldiradi. Nazoratchi qayta
ko'taradi, lekin ketma-ket 5 ta tez yiqilishdan keyin butunlay to'xtaydi.
Ya'ni kompyuter uyqudan uyg'onib, Wi-Fi hali ulanmagan paytda bot
ishga tushsa — bot bir necha daqiqada o'ladi va O'ZI qaytmaydi.

Tarmoq talab qilinmaydi.
"""
import logging
import os
import sys

os.environ["BOT_TOKEN"] = "111111:FAKE_TARMOQ"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import bot  # noqa: E402
from telegram.error import (  # noqa: E402
    BadRequest, Conflict, Forbidden, InvalidToken, NetworkError, TimedOut,
)

ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print("  PASS  " + name)
    else:
        fail += 1
        print("  FAIL  " + name + "  " + str(extra))


# ── Log chaqiruvlarini ushlab olamiz ───────────────────────────────────────
_yozildi = []
_asl_warn = logging.warning
_asl_err = logging.error


def _tut(daraja):
    def _f(msg, *a, **k):
        _yozildi.append({"daraja": daraja, "msg": str(msg),
                         "args": a, "exc_info": k.get("exc_info")})
    return _f


def chaqir(exc):
    _yozildi.clear()
    logging.warning = _tut("warning")
    logging.error = _tut("error")
    try:
        bot._polling_xato_cb(exc)
    finally:
        logging.warning = _asl_warn
        logging.error = _asl_err
    return _yozildi[0] if _yozildi else None


print("[1] O'TKINCHI TARMOQ XATOSI — jim, bir qatorda")
# Bular PTB tomonidan cheksiz qayta uriladi, bot o'lmaydi.
# Konsolni traceback bilan to'ldirish faqat egasini qo'rqitadi.
for nom, xato in [
    ("NetworkError (httpx.ReadError shunga aylanadi)",
     NetworkError("httpx.ReadError: ")),
    ("TimedOut", TimedOut()),
]:
    y = chaqir(xato)
    check(nom + " -> warning", y is not None and y["daraja"] == "warning", y)
    check(nom + " -> traceback YO'Q",
          y is not None and not y.get("exc_info"), y)

print("[2] HAQIQIY XATO — to'liq ko'rinishi SHART")
# Bularni jimgina yutish eng yomon natija: sabab yashirin qoladi.
for nom, xato in [
    ("BadRequest (NetworkError merosxo'ri — tuzoq!)", BadRequest("xato so'rov")),
    ("InvalidToken (token buzuq)", InvalidToken()),
    ("Conflict (ikkita nusxa ishlayapti)", Conflict("terminated by other")),
    ("Forbidden (bloklangan)", Forbidden("bot bloklangan")),
]:
    y = chaqir(xato)
    check(nom + " -> error", y is not None and y["daraja"] == "error", y)
    check(nom + " -> traceback BOR", y is not None and bool(y.get("exc_info")), y)

print("[3] XATO CALLBACK O'ZI YIQILMASLIGI KERAK")
# network_retry_loop hujjati: on_err_cb xato tashlasa BUTUN LOOP TO'XTAYDI.
# Ya'ni bu yerdagi kichik xato botni o'ldirardi.
try:
    logging.warning = _tut("warning")
    logging.error = _tut("error")
    bot._polling_xato_cb(None)
    bot._polling_xato_cb("satr, Exception emas")
    natija = True
except Exception as e:
    natija = False
    print("     " + repr(e))
finally:
    logging.warning = _asl_warn
    logging.error = _asl_err
check("kutilmagan qiymatda ham yiqilmaydi", natija)

print("[4] ISHGA TUSHISHDAGI TARMOQ NOSOZLIGI")
with open(os.path.join(ROOT, "bot.py"), encoding="utf-8") as f:
    manba = f.read()

check("run_polling bo'sh chaqirilmaydi",
      "app.run_polling()" not in manba,
      "bootstrap_retries=0 -> ishga tushishdagi uzilish botni o'ldiradi")
check("bootstrap qayta urinishi sozlangan",
      "bootstrap_retries=" in manba)
check("qayta urinish soni yetarli (uyqudan uyg'onish uchun daqiqalar kerak)",
      bot.BOOTSTRAP_URINISH >= 10, bot.BOOTSTRAP_URINISH)
check("cheksiz EMAS (abadiy yarim tirik qolmasin)",
      bot.BOOTSTRAP_URINISH > 0, bot.BOOTSTRAP_URINISH)
# run_polling() error_callback parametrini QABUL QILMAYDI — u ichida o'zi
# yasab, xatoni process_error orqali botning error handler'iga yuboradi.
# Ya'ni yagona ulanish nuqtasi _error_handler.
_eh = manba.find("async def _error_handler")
check("_error_handler mavjud", _eh >= 0)
check("polling xatosi _polling_xato_cb orqali o'tadi",
      "_polling_xato_cb(err)" in manba[_eh:_eh + 900],
      "aks holda traceback devori qaytadi")
check("eski shovqinli chaqiruv olib tashlandi",
      'logging.error(f"Handler xatosi: {err}", exc_info=err)' not in manba)

print(f"\nJami: {ok} PASS, {fail} FAIL")
sys.exit(1 if fail else 0)
