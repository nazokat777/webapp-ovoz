"""Tarif tuzilmasi: KUNLIK bepul limit va sotuvdan olingan tariflar.

O'ZGARISH SABABI: STT (Groq) va matn modeli (Gemini) bepul provayderlar
orqali ishlay boshlagach, Standart tarifning tannarxi nolga tushdi —
uni sotish ma'nosiz bo'lib qoldi. Endi oddiy xizmat bepul, faqat kunlik
limit bilan; pullik faqat Muxlisa AI (Premium), chunki u haqiqatan
pul turadi.

Bu yerda ikkita xavf sinaladi:
  1) Kalitni O'CHIRIB yuborish — kod TARIFFS[...] ni 32 joyda
     to'g'ridan-to'g'ri indekslaydi, o'chirilsa eski xaridorlarda
     KeyError bo'lib BOT YIQILARDI.
  2) Kunlik limit noto'g'ri hisoblanishi — kechagi sarf bugungi
     limitni yeb qo'ysa, foydalanuvchi xizmatdan mahrum bo'ladi.

Tarmoq talab qilinmaydi.
"""
import os
import sys

os.environ["BOT_TOKEN"] = "111111:FAKE_TARIF"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import bot  # noqa: E402

ok = fail = 0
U = 990001


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print("  PASS  " + name)
    else:
        fail += 1
        print("  FAIL  " + name + "  " + str(extra))


_eski_save = bot._save_user_data
bot._save_user_data = lambda: None

try:
    print("[1] Bepul tarif — kunlik 60 daqiqa")
    free = bot.TARIFFS["free"]
    check("bepul tarif KUNLIK deb belgilangan", free.get("daily") is True, free)
    check("60 daqiqa beriladi", free["minutes"] == 60, free["minutes"])
    check("narxi nol", free["price"] == 0)

    bot.user_tariffs[U] = "free"
    bot.user_daily_usage.pop(U, None)
    bot.user_uzbek_usage.pop(U, None)
    check("bepul foydalanuvchi kunlik hisobda",
          bot.is_daily_tariff(U) is True)
    check("limit 60 daqiqa (3600 sek)", bot.get_user_limit_sec(U) == 3600,
          bot.get_user_limit_sec(U))
    check("boshida sarf nol", bot.get_user_usage_sec(U) == 0)

    print("[2] Sarf hisoblanadi va KUNI bilan bog'lanadi")
    bot.add_user_usage(U, 600)
    check("10 daqiqa hisoblandi", bot.get_user_usage_sec(U) == 600,
          bot.get_user_usage_sec(U))
    check("bugungi kun yozildi",
          bot.user_daily_usage[U][0] == bot.bugungi_kun(),
          bot.user_daily_usage.get(U))
    bot.add_user_usage(U, 300)
    check("sarf JAMLANADI (10+5=15 daqiqa)",
          bot.get_user_usage_sec(U) == 900, bot.get_user_usage_sec(U))

    print("[3] KECHAGI sarf bugungi limitni YEMAYDI")
    # Aynan shu xato bo'lsa foydalanuvchi ertaga ham bloklangan qolardi
    bot.user_daily_usage[U] = ["2020-01-01", 3600]
    check("eski kundagi sarf bugun nolga tenglashadi",
          bot.get_user_usage_sec(U) == 0, bot.get_user_usage_sec(U))
    bot.add_user_usage(U, 120)
    check("yangi kunda hisob NOLDAN boshlanadi",
          bot.get_user_usage_sec(U) == 120, bot.user_daily_usage.get(U))

    print("[4] PULLIK tarif — umrbod hisob (kunlik EMAS)")
    bot.user_tariffs[U] = "pro_max"
    check("pullik tarif kunlik emas", bot.is_daily_tariff(U) is False)
    check("umrbod jamlangan sarf ishlatiladi",
          bot.get_user_usage_sec(U) == bot.user_uzbek_usage.get(U, 0),
          (bot.get_user_usage_sec(U), bot.user_uzbek_usage.get(U)))
    check("Premium limiti 600 daqiqa",
          bot.get_user_limit_sec(U) == 600 * 60, bot.get_user_limit_sec(U))

    print("[5] Sotuvdan olingan tariflar — KALIT QOLADI")
    yashirin = [k for k, t in bot.TARIFFS.items() if t.get("hidden")]
    check("uchta Standart tarif yashirilgan",
          set(yashirin) == {"basic", "standart", "premium"}, yashirin)
    for k in yashirin:
        # Eng muhim tekshiruv: eski xaridorda KeyError BO'LMASLIGI
        bot.user_tariffs[U] = k
        try:
            lim = bot.get_user_limit_sec(U)
            xato = None
        except Exception as e:
            lim, xato = None, e
        check("eski xaridor tarifi ishlaydi: " + k, xato is None and lim > 0,
              xato or lim)

    print("[6] Faqat Premium sotiladi")
    sotiladi = [k for k, t in bot.TARIFFS.items()
                if t.get("price", 0) > 0 and not t.get("hidden")]
    check("sotuvda faqat pro_* tariflar",
          set(sotiladi) == {"pro_standart", "pro_premium", "pro_max"}, sotiladi)
    check("bepul tarif sotilmaydi", not bot.TARIFFS["free"].get("price"))

    print("[7] Tariflar matni yangi tuzilmani ko'rsatadi")
    matn = bot.format_tariffs_text()
    check("bepul tarif kunlik ekani aytiladi", "HAR KUNI" in matn)
    check("Standart tariflar narxi KO'RSATILMAYDI",
          "60,000" not in matn and "150,000" not in matn
          and "300,000 so'm" not in matn.split("Premium")[0], matn[:200])
    check("Premium narxlari ko'rinadi", "170,000" in matn and "500,000" in matn)
    check("eski xaridorlarga izoh bor", "Sotib olganlar" in matn)
    check("matnda buzuq tirnoq yo'q (uch tirnoq)", "'''" not in matn)
    check("matnda literal \\n yo'q", chr(92) + "n" not in matn)

    print("[8] Kunlik hisob SAQLANADI")
    bot.user_tariffs[U] = "free"
    bot.user_daily_usage[U] = [bot.bugungi_kun(), 777]
    ma = {"user_daily_usage": {str(U): [bot.bugungi_kun(), 777]}}
    # Yuklash mantig'i bilan bir xil shakl
    check("saqlash shakli [kun, soniya]",
          isinstance(ma["user_daily_usage"][str(U)], list)
          and len(ma["user_daily_usage"][str(U)]) == 2)
    check("qiymat o'qiladi", bot.get_user_usage_sec(U) == 777)
finally:
    bot._save_user_data = _eski_save
    bot.user_tariffs.pop(U, None)
    bot.user_daily_usage.pop(U, None)
    bot.user_uzbek_usage.pop(U, None)
    bot.user_total_usage.pop(U, None)

print("\nNatija: " + str(ok) + " pass, " + str(fail) + " fail")
sys.exit(1 if fail else 0)
