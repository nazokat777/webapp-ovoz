"""Qisman qayta ishlash va DAVOM ETTIRISH.

MUAMMO: bepul tarifda kunlik 60 daqiqa, institut ma'ruzasi esa 2-3 soat.
Ilgari bunday fayl BUTUNLAY rad etilardi — foydalanuvchi hech narsa
olmasdi va nima qilishni bilmasdi.

Endi: qolgan limit qancha bo'lsa shuncha qismi qayta ishlanadi, qayerda
to'xtagani aytiladi, ertaga /davom AYNAN o'sha joydan davom ettiradi.

ffmpeg bo'lmasa kesish sinovlari SKIP bo'ladi, qolgani ishlaydi.
"""
import os
import subprocess
import sys
import tempfile
import time

os.environ["BOT_TOKEN"] = "111111:FAKE_DAVOM"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import bot  # noqa: E402

ok = fail = skip = 0
U = 995001
_tmp = tempfile.mkdtemp(prefix="davom_test_")


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print("  PASS  " + name)
    else:
        fail += 1
        print("  FAIL  " + name + "  " + str(extra))


def tozala():
    bot.user_daily_usage.pop(U, None)
    bot.user_uzbek_usage.pop(U, None)
    bot.user_total_usage.pop(U, None)
    bot.davom_holati.pop(U, None)


_eski_save = bot._save_user_data
bot._save_user_data = lambda: None
bot.user_tariffs[U] = "free"

try:
    print("[1] Vaqt matni — foydalanuvchi ko'radigan shakl")
    check("45 sek -> 1 daqiqa", bot._vaqt_matni(45) == "1 daqiqa")
    check("1 soat", bot._vaqt_matni(3600) == "1 soat")
    check("1 soat 5 daqiqa", bot._vaqt_matni(3900) == "1 soat 5 daqiqa")
    check("3 soat", bot._vaqt_matni(10800) == "3 soat")

    print("[2] Qolgan limit hisobi")
    tozala()
    check("yangi bepul user -> 60 daqiqa",
          bot.qolgan_limit_sec(U) == 60 * 60, bot.qolgan_limit_sec(U))
    bot.add_user_usage(U, 50 * 60)
    check("50 daqiqa sarflagach -> 10 daqiqa",
          bot.qolgan_limit_sec(U) == 10 * 60, bot.qolgan_limit_sec(U))
    tozala()

    print("[3] Rad etish sabablari ANIQ aytiladi")
    tozala()
    bot.add_user_usage(U, 60 * 60)
    r = bot.limitga_moslash(U, "yoq.mp3", 10800, 0, "havola", "u")
    check("limit tugagan -> limit_tugadi", r.get("sabab") == "limit_tugadi", r)
    x = bot.limit_rad_xabari("limit_tugadi", U)
    check("xabarda ERTAGA yangilanishi aytiladi", "ertaga" in x.lower(), x[:80])
    check("kunlik tarifda /tariflar ga yo'naltirilmaydi",
          "/tariflar" not in x, x[:80])

    tozala()
    bot.add_user_usage(U, 58 * 60)          # 2 daqiqa qoldi
    r = bot.limitga_moslash(U, "yoq.mp3", 10800, 0, "havola", "u")
    check("juda kam qolgan -> juda_kam", r.get("sabab") == "juda_kam", r)
    check("qancha qolgani xabarda bor",
          "2 daqiqa" in bot.limit_rad_xabari("juda_kam", U, r.get("qolgan", 0)),
          bot.limit_rad_xabari("juda_kam", U, r.get("qolgan", 0))[:90])
    tozala()

    print("[4] Xabar matni — qayerda to'xtagani tushunarli")
    m = bot.qisman_xabar({"qisman": True, "uzunlik": 3600, "keyingi": 3600},
                         10800, 0)
    check("boshidan boshlanganda 'boshidan' deyiladi", "boshidan" in m, m[:70])
    check("qolgan vaqt aytiladi", "2 soat" in m, m)
    check("/davom eslatiladi", "/davom" in m, m)
    m2 = bot.qisman_xabar({"qisman": True, "uzunlik": 3600, "keyingi": 7200},
                          10800, 3600)
    check("davomida boshlanish nuqtasi ko'rsatiladi", "1 soat dan" in m2, m2[:70])
    check("to'liq bo'lsa xabar YO'Q",
          bot.qisman_xabar({"qisman": False}, 100, 0) is None)

    if not bot.have_cmd("ffmpeg"):
        print("\n[SKIP] ffmpeg yo'q — kesish sinovlari o'tkazilmadi")
        skip += 1
    else:
        print("[5] HAQIQIY audio bilan: 3 kunlik davom ettirish")
        # 30 daqiqalik audio, kunlik limit 10 daqiqa qilib modellaymiz
        AUDIO = os.path.join(_tmp, "uzun.mp3")
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
             "-i", "sine=frequency=300:duration=1800",
             "-ac", "1", "-ar", "16000", AUDIO], capture_output=True)
        JAMI = int(bot.get_duration_or_estimate(AUDIO))
        check("sinov audiosi yaratildi", JAMI > 1700, JAMI)

        _eski_min = bot.DAVOM_MIN_SEK
        bot.DAVOM_MIN_SEK = 60
        try:
            # 1-KUN: 50 daqiqa sarflangan, 10 daqiqa qolgan
            tozala()
            bot.add_user_usage(U, 50 * 60)
            r1 = bot.limitga_moslash(U, AUDIO, JAMI, 0, "fayl", AUDIO)
            check("1-kun: qisman ishlandi", r1.get("qisman") is True, r1)
            check("1-kun: 10 daqiqa kesildi",
                  abs(r1["uzunlik"] - 600) < 5, r1.get("uzunlik"))
            check("1-kun: kesilgan fayl haqiqatan 10 daqiqa",
                  abs(bot.get_duration_or_estimate(r1["path"]) - 600) < 5)
            check("1-kun: holat SAQLANDI", U in bot.davom_holati)
            check("1-kun: keyingi nuqta 600 sek",
                  bot.davom_holati[U]["keyingi"] == r1["keyingi"] == 600,
                  bot.davom_holati.get(U))
            check("1-kun: manba fayli saqlandi",
                  os.path.exists(bot.davom_holati[U]["qiymat"]),
                  bot.davom_holati[U]["qiymat"])

            # 2-KUN: limit yangilandi (kunlik hisob tozalanadi)
            bot.user_daily_usage.pop(U, None)
            bot.add_user_usage(U, 50 * 60)      # yana 10 daqiqa qoldi
            h = bot.davom_holati[U]
            r2 = bot.limitga_moslash(U, h["qiymat"], h["jami"], h["keyingi"],
                                     "fayl", h["qiymat"])
            check("2-kun: yana qisman", r2.get("qisman") is True, r2)
            check("2-kun: 600 dan 1200 gacha",
                  r2["keyingi"] == 1200, r2.get("keyingi"))
            check("2-kun: kesilgan qism 10 daqiqa",
                  abs(bot.get_duration_or_estimate(r2["path"]) - 600) < 5)

            # 3-KUN: yana 10 daqiqa limit, qolgani ham 10 daqiqa
            bot.user_daily_usage.pop(U, None)
            bot.add_user_usage(U, 50 * 60)
            h = bot.davom_holati[U]
            r3 = bot.limitga_moslash(U, h["qiymat"], h["jami"], h["keyingi"],
                                     "fayl", h["qiymat"])
            check("3-kun: OXIRGI qism, qisman EMAS",
                  r3.get("qisman") is False, r3)
            check("3-kun: qolgan hammasi olinadi",
                  abs(r3["uzunlik"] - 600) < 30, r3.get("uzunlik"))
            check("3-kun: davom nuqtasi yo'q (tugadi)",
                  r3.get("keyingi") is None, r3.get("keyingi"))
        finally:
            bot.DAVOM_MIN_SEK = _eski_min

    print("[6] Eski fayllarni tozalash (disk to'lib qolmasin)")
    bot._davom_papka()
    eski = os.path.join(bot.DAVOM_DIR, "sinov_eski.mp3")
    with open(eski, "wb") as f:
        f.write(b"x" * 100)
    qadim = time.time() - (bot.DAVOM_TTL_KUN + 1) * 86400
    os.utime(eski, (qadim, qadim))
    bot.davom_tozalash()
    check("muddati o'tgan fayl o'chirildi", not os.path.exists(eski))

    yangi = os.path.join(bot.DAVOM_DIR, "sinov_yangi.mp3")
    with open(yangi, "wb") as f:
        f.write(b"x" * 100)
    bot.davom_tozalash()
    check("yangi faylga tegilmaydi", os.path.exists(yangi))
    os.remove(yangi)

    print("[7] Holat o'chirilishi")
    tozala()
    bot.davom_saqlash(U, "havola", "https://y.be/x", 600, 1800, "sinov")
    check("holat yozildi", U in bot.davom_holati)
    bot.davom_ochirish(U)
    check("holat o'chirildi", U not in bot.davom_holati)

    print("[8] Oqimlar qisman ishlashni QO'LLAYDI (struktura auditi)")
    src = open(os.path.join(ROOT, "bot.py"), encoding="utf-8").read()
    # UCHALA oqim ham qamrab olinishi SHART. Ilgari ensure_uzbek_text
    # ikkita oqimga qo'shilib, uchinchisi unutilgan edi va foydalanuvchi
    # yana xato natija olgan edi — o'sha xato takrorlanmasin.
    for _nom in ("process_url", "process_audio_for_user", "process_url_for_user"):
        _i = src.index("def " + _nom)
        _j = src.find(chr(10) + "def ", _i + 10)
        _kod = src[_i:_j if _j > 0 else _i + 30000]
        check(_nom + " limitga moslaydi", "limitga_moslash" in _kod)
        check(_nom + " qisman xabarni YUBORADI",
              "qisman_matn" in _kod and _kod.count("qisman_matn") >= 3,
              _kod.count("qisman_matn"))
    check("/davom buyrug'i ro'yxatga olingan",
          'CommandHandler("davom", davom_cmd)' in src)
    check("davom holati SAQLANADI (qayta ishga tushirishdan omon)",
          '"davom_holati"' in src)
finally:
    bot._save_user_data = _eski_save
    tozala()
    bot.user_tariffs.pop(U, None)
    try:
        import shutil
        shutil.rmtree(_tmp, ignore_errors=True)
        for n in os.listdir(bot.DAVOM_DIR):
            if n.startswith(str(U)) or n.startswith("sinov_"):
                os.remove(os.path.join(bot.DAVOM_DIR, n))
    except Exception:
        pass

    print("[9] Foydalanuvchi /davom haqida BILISHI kerak")
    # Hech kim bilmaydigan funksiya yarim qurilgan funksiya
    check("Telegram buyruqlar ro'yxatida bor",
          'BotCommand("davom"' in src)
    check("/help matnida eslatiladi", "/davom" in src.split("def help_cmd")[1][:1500])
    check("uzun ma'ruza haqida izoh bor",
          "Uzun ma'ruza" in src.split("def help_cmd")[1][:1500])
    check("tariflar matnida ham eslatiladi",
          "/davom bilan davom etadi" in src)
    check("qisman xabar /davom ni ko'rsatadi",
          "/davom* buyrug" in src)

print("\nNatija: " + str(ok) + " pass, " + str(fail) + " fail, " + str(skip) + " skip")
sys.exit(1 if fail else 0)
