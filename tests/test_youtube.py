"""YOUTUBE BLOKI — cookies qayerdan olinadi va foydalanuvchiga nima deyiladi.

MUAMMO: bot ma'lumot markazidagi serverga ko'chirilgach YouTube barcha
so'rovlarni "Sign in to confirm you're not a bot" bilan rad eta boshladi.
2026-08-29 da 8 xil player_client sinaldi (default, android, ios, tv,
web_safari, mweb, web_embedded, tv_simply) — HAMMASI bloklandi. Ya'ni bu
vaqtinchalik nosozlik emas va qayta urinish yordam bermaydi.

Ikki narsa tekshiriladi:
  1. Cookies DOIMIY joydan (/data) o'qiladi — ilgari faqat konteyner
     ichidagi /root ga qaralardi va har qayta qurishda yo'qolardi
  2. Xabar foydalanuvchiga YOLG'ON UMID bermaydi va ishlaydigan yo'lni
     ko'rsatadi

Tarmoq talab qilinmaydi.
"""
import os
import sys
import tempfile

os.environ["BOT_TOKEN"] = "111111:FAKE_YT"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import bot  # noqa: E402

ok = fail = 0
_tmp = tempfile.mkdtemp(prefix="yt_test_")


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print("  PASS  " + name)
    else:
        fail += 1
        print("  FAIL  " + name + "  " + str(extra))


def tozala():
    for k in ("YOUTUBE_COOKIES", "YOUTUBE_COOKIES_FILE"):
        os.environ.pop(k, None)


_ASL_JOYLAR = bot.COOKIES_JOYLARI

print("[1] COOKIES QIDIRUV TARTIBI")
check("/data birinchi o'rinda (yagona doimiy papka)",
      bot.COOKIES_JOYLARI[0] == "/data/youtube_cookies.txt",
      bot.COOKIES_JOYLARI)
check("eski /root yo'li ham qoldi (mos kelish uchun)",
      "/root/youtube_cookies.txt" in bot.COOKIES_JOYLARI)

print("[2] MANBALAR")
tozala()
bot.COOKIES_JOYLARI = ()
check("hech narsa yo'q -> None", bot._prepare_cookies_file() is None)

os.environ["YOUTUBE_COOKIES"] = "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tX\t1\n"
yol = bot._prepare_cookies_file()
check("env'dan fayl yaratiladi", yol is not None and os.path.exists(yol), yol)
if yol:
    check("mazmuni yozilgan", "youtube.com" in open(yol, encoding="utf-8").read())
tozala()

tashqi = os.path.join(_tmp, "tashqi_cookies.txt")
open(tashqi, "w").write("x")
os.environ["YOUTUBE_COOKIES_FILE"] = tashqi
check("YOUTUBE_COOKIES_FILE hurmat qilinadi",
      bot._prepare_cookies_file() == tashqi)
os.environ["YOUTUBE_COOKIES_FILE"] = os.path.join(_tmp, "yoq.txt")
check("mavjud bo'lmagan yo'l e'tiborsiz qoldiriladi",
      bot._prepare_cookies_file() is None)
tozala()

# Standart joylar: birinchisi topilsa o'sha qaytadi
birinchi = os.path.join(_tmp, "birinchi.txt")
ikkinchi = os.path.join(_tmp, "ikkinchi.txt")
open(ikkinchi, "w").write("x")
bot.COOKIES_JOYLARI = (birinchi, ikkinchi)
check("birinchi yo'q -> ikkinchisi ishlatiladi",
      bot._prepare_cookies_file() == ikkinchi)
open(birinchi, "w").write("x")
check("birinchi bor -> u ustun turadi",
      bot._prepare_cookies_file() == birinchi)
bot.COOKIES_JOYLARI = _ASL_JOYLAR
tozala()

print("[3] FOYDALANUVCHIGA XABAR — yolg'on umid bermasin")
with open(os.path.join(ROOT, "bot.py"), encoding="utf-8") as f:
    manba = f.read()

_bosh = manba.find('if "sign in" in low or "not a bot" in low')
check("blok xabari topildi", _bosh > 0)
_blok = manba[_bosh:_bosh + 1400]

# Izoh qatorlarini chiqarib tashlaymiz: iborani IZOHDA eslatish mumkin
# (nima olib tashlangani yozilgan), lekin FOYDALANUVCHIGA aytilmasligi kerak.
_kod = "\n".join(q for q in _blok.split("\n")
                 if not q.lstrip().startswith("#"))
check("'keyinroq urining' foydalanuvchiga AYTILMAYDI",
      "keyinroq urining" not in _kod,
      "qayta urinish hech qachon ishlamaydi — bu yolg'on maslahat edi")
check("vaqtinchalik EMASligi aytiladi", "vaqtinchalik emas" in _blok)
check("ishlaydigan yo'l ko'rsatiladi (faylni yuborish)",
      "faylning" in _blok.lower() and "yuboring" in _blok)
check("cookies bor bo'lsa boshqa sabab aytiladi",
      "_prepare_cookies_file()" in _blok and "eskirgan" in _blok,
      "cookies bo'lsa-yu ishlamasa — sabab boshqa")

print("[4] COOKIES DOIMIY DISKDA QOLADI")
# Docker konteyner har qurishda tozalanadi; faqat /data volume saqlanadi.
check("qidiruv yo'llarida /data bor",
      any(j.startswith("/data") for j in bot.COOKIES_JOYLARI))

import shutil  # noqa: E402
shutil.rmtree(_tmp, ignore_errors=True)

print(f"\nJami: {ok} PASS, {fail} FAIL")
sys.exit(1 if fail else 0)
