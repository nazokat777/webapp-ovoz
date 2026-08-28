"""AVTOMATIK KUNLIK ZAXIRA — ma'lumot bazasini adminning Telegramiga yuborish.

NEGA MUHIM: 2026-08-29 da DigitalOcean droplet to'lanmagan qarz uchun butunlay
o'chirildi va foydalanuvchi bazasi u bilan birga ketdi. Hosting provayderining
"Backups" xizmati bunda yordam bermaydi — u droplet bilan birga o'chadi.
Yagona ishonchli nusxa — foydalanuvchining telefonidagi nusxa.

Shuning uchun bu yerda ikki narsa qattiq tekshiriladi:
  1. Zaxira SIFATSIZ holatda yuborilmaydi (bo'sh fayl, admin yo'q)
  2. Zaxira UNUTILMAYDI — main() haqiqatan oqimni ishga tushiradi

Tarmoq talab qilinmaydi: Telegram chaqiruvi soxtalashtiriladi.
"""
import os
import sys
import tempfile

os.environ["BOT_TOKEN"] = "111111:FAKE_ZAXIRA"
os.environ["ADMIN_USER_ID"] = "700001"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import bot  # noqa: E402

ok = fail = 0
_tmp = tempfile.mkdtemp(prefix="zaxira_test_")


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print("  PASS  " + name)
    else:
        fail += 1
        print("  FAIL  " + name + "  " + str(extra))


# ── Sinov muhiti: HAQIQIY user_data.json ga TEGMAYMIZ ──────────────────────
_ASL_DATA_FILE = bot.DATA_FILE
_ASL_SEND_DOC = bot.telegram_send_document
_ASL_ADMINS = set(bot.ADMIN_USER_IDS)
_ASL_CHAT = bot.ADMIN_CHAT_ID.get("id")

SOXTA_DATA = os.path.join(_tmp, "user_data.json")
bot.DATA_FILE = SOXTA_DATA

_yuborilgan = []


def _soxta_send_doc(chat_id, file_path, filename=None, caption=None,
                    mime="application/pdf", parse_mode=None):
    _yuborilgan.append({"chat_id": chat_id, "path": file_path,
                        "filename": filename, "caption": caption, "mime": mime})
    return True


bot.telegram_send_document = _soxta_send_doc


def tozala(mazmun='{"usage": {}}'):
    _yuborilgan.clear()
    bot._zaxira_holat["kun"] = None
    for nom in ("user_data.json", "zaxira_oxirgi.txt"):
        try:
            os.remove(os.path.join(_tmp, nom))
        except OSError:
            pass
    if mazmun is not None:
        with open(SOXTA_DATA, "w", encoding="utf-8") as f:
            f.write(mazmun)


print("[1] SANA MANTIG'I — qachon zaxira kerak")
tozala()
check("hech qachon yuborilmagan -> kerak", bot.zaxira_kerakmi() is True)

bugun = bot.bugungi_kun()
bot._zaxira_kun_belgila(bugun)
check("bugun yuborilgan -> kerak emas", bot.zaxira_kerakmi(bugun) is False)

bot._zaxira_holat["kun"] = None          # faylni o'qishga majburlaymiz
check("sana FAYLDAN o'qiladi (restart'dan keyin ham)",
      bot.zaxira_kerakmi(bugun) is False)
check("holat fayli DATA_FILE yonida (server /data volume ichida saqlanadi)",
      os.path.dirname(bot._zaxira_holat_fayli()) == os.path.dirname(SOXTA_DATA),
      bot._zaxira_holat_fayli())

tozala()
bot._zaxira_kun_belgila("2020-01-01")
check("eski sana -> kerak", bot.zaxira_kerakmi(bugun) is True)

check("kun farqi to'g'ri sanaladi",
      bot._zaxira_kunlar_farqi("2026-08-01", "2026-08-29") == 28,
      bot._zaxira_kunlar_farqi("2026-08-01", "2026-08-29"))
check("oy chegarasi orqali ham to'g'ri",
      bot._zaxira_kunlar_farqi("2026-02-27", "2026-03-02") == 3,
      bot._zaxira_kunlar_farqi("2026-02-27", "2026-03-02"))

# Buzuq sana ma'lumotsiz qoldirmasligi kerak — shubha bo'lsa YUBORADI.
tozala()
bot._zaxira_kun_belgila("axlat-sana")
bot._zaxira_holat["kun"] = None
check("buzuq sana -> zaxira baribir yuboriladi (xavfsiz tomonga og'ish)",
      bot.zaxira_kerakmi(bugun) is True)

print("[2] YOMON HOLATDA YUBORMASLIK")
tozala(mazmun=None)                       # fayl umuman yo'q
check("fayl yo'q -> yuborilmaydi", bot.zaxira_yubor("sinov") is False)
check("hech narsa jo'natilmadi", _yuborilgan == [])

tozala(mazmun="")                         # bo'sh fayl
check("bo'sh fayl -> yuborilmaydi", bot.zaxira_yubor("sinov") is False)
check("bo'sh fayl jo'natilmadi", _yuborilgan == [])

tozala()
bot.ADMIN_USER_IDS.clear()
bot.ADMIN_CHAT_ID["id"] = None
check("admin yo'q -> yiqilmaydi, False qaytaradi",
      bot.zaxira_yubor("sinov") is False)
bot.ADMIN_USER_IDS.update(_ASL_ADMINS)

print("[3] MUVAFFAQIYATLI YUBORISH")
tozala(mazmun='{"usage": {"1": 60}, "tariffs": {"1": "pro_1"}}')
bot.ADMIN_CHAT_ID["id"] = None
natija = bot.zaxira_yubor("sinov")
check("yuborildi", natija is True)
check("aynan bitta admin oldi", len(_yuborilgan) == 1, _yuborilgan)
if _yuborilgan:
    x = _yuborilgan[0]
    check("to'g'ri adminga ketdi", x["chat_id"] == 700001, x["chat_id"])
    check("mime JSON (PDF EMAS — telefonda ochilsin)",
          x["mime"] == "application/json", x["mime"])
    check("fayl nomida sana bor (Telegramda ajratib bo'ladi)",
          bugun in (x["filename"] or ""), x["filename"])
    check("nomi .json bilan tugaydi", (x["filename"] or "").endswith(".json"))
    check("izohda /restore ko'rsatilgan (nima qilishni bilsin)",
          "/restore" in (x["caption"] or ""), x["caption"])
    check("izohda o'chirmaslik ogohlantirishi bor",
          "o'chirmang" in (x["caption"] or "").lower(), x["caption"])
    check("aynan DATA_FILE yuborildi", x["path"] == SOXTA_DATA, x["path"])

print("[4] BIR NECHTA ADMIN")
tozala()
bot.ADMIN_USER_IDS.add(700002)
bot.ADMIN_CHAT_ID["id"] = 700001          # ATAYLAB takror
bot.zaxira_yubor("sinov")
kimlar = sorted(x["chat_id"] for x in _yuborilgan)
check("har bir admin oldi", kimlar == [700001, 700002], kimlar)
check("takror admin IKKI MARTA yubormaydi", len(kimlar) == len(set(kimlar)))
bot.ADMIN_USER_IDS.discard(700002)
bot.ADMIN_CHAT_ID["id"] = None

print("[5] ZAXIRA BOTNI O'LDIRMASLIGI KERAK")
# Yordamchi vazifa asosiy xizmatni yiqitsa — bu zaxiradan ko'ra battar.
tozala()
_asl_kerakmi = bot.zaxira_kerakmi
_asl_sleep = bot.time.sleep


class _Toxta(Exception):
    pass


def _portlaydi(*a, **k):
    raise RuntimeError("ataylab portladi")


_uyqu = {"n": 0}


def _soxta_sleep(sek):
    _uyqu["n"] += 1
    if _uyqu["n"] >= 2:                   # 1-chi = boshlanish kutishi
        raise _Toxta()


bot.zaxira_kerakmi = _portlaydi
bot.time.sleep = _soxta_sleep
try:
    bot._zaxira_loop()
    natija = "toxtamadi"
except _Toxta:
    natija = "yutdi"                      # xato ushlandi, loop davom etdi
except RuntimeError:
    natija = "portladi"                   # xato tashqariga chiqdi = YOMON
finally:
    bot.zaxira_kerakmi = _asl_kerakmi
    bot.time.sleep = _asl_sleep
check("loop ichidagi xato yutiladi, oqim o'lmaydi", natija == "yutdi", natija)

# Diskka yozib bo'lmasa ham HAR YARIM SOATDA spam bo'lmasligi kerak
tozala()
_asl_holat_fayli = bot._zaxira_holat_fayli
bot._zaxira_holat_fayli = lambda: os.path.join(_tmp, "yoq", "yoq", "x.txt")
try:
    bot._zaxira_kun_belgila(bugun)        # yozolmaydi, lekin yiqilmasligi kerak
    check("yozib bo'lmasa ham yiqilmaydi", True)
    check("xotirada eslab qoladi -> takror yubormaydi",
          bot.zaxira_kerakmi(bugun) is False)
except Exception as e:
    check("yozib bo'lmasa ham yiqilmaydi", False, e)
finally:
    bot._zaxira_holat_fayli = _asl_holat_fayli

print("[6] O'CHIRISH IMKONI")
_asl_avto = bot.ZAXIRA_AVTO
bot.ZAXIRA_AVTO = False
check("ZAXIRA_AVTO=0 -> oqim ochilmaydi", bot.zaxira_oqimini_boshla() is None)
bot.ZAXIRA_AVTO = _asl_avto

print("[7] TUZILISH AUDITI — zaxira ULANMAY qolmasin")
# Bu sinov ilgari REAL bo'lgan xato uchun: funksiya yozilgan, lekin
# chaqiruv joyi unutilgan edi va hech kim sezmagan.
with open(os.path.join(ROOT, "bot.py"), encoding="utf-8") as f:
    manba = f.read()

bosh = manba.find("\ndef main(")
tana = manba[bosh:] if bosh >= 0 else ""
check("main() topildi", bosh >= 0)
check("main() zaxira oqimini ISHGA TUSHIRADI",
      "zaxira_oqimini_boshla()" in tana)
check("zaxira oqimi daemon (bot to'xtashiga to'sqinlik qilmaydi)",
      "target=_zaxira_loop, daemon=True" in manba)
check("telegram_send_document mime parametrini qabul qiladi",
      "mime=\"application/pdf\"" in manba and "f, mime)" in manba)

# ── Tozalash ───────────────────────────────────────────────────────────────
bot.DATA_FILE = _ASL_DATA_FILE
bot.telegram_send_document = _ASL_SEND_DOC
bot.ADMIN_CHAT_ID["id"] = _ASL_CHAT
import shutil  # noqa: E402
shutil.rmtree(_tmp, ignore_errors=True)

print(f"\nJami: {ok} PASS, {fail} FAIL")
sys.exit(1 if fail else 0)
