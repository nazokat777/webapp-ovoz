"""Botni kuzatib turadi va kutilmaganda to'xtasa qayta ishga tushiradi.

NEGA KERAK: bot Telegram bilan aloqa VAQTINCHALIK uzilganda butunlay
o'lib qolardi. Amalda shunday bo'ldi:

    telegram.error.TimedOut: Timed out
    [exited with code 1]

Tarmoq nosozligi o'tkinchi hodisa — bir necha soniyadan keyin hammasi
tiklanadi. Lekin jarayon o'lgani uchun xizmat nazoratsiz to'xtab
qolardi va buni faqat mijozlar shikoyat qilganda bilinardi.

Qayta ishga tushirish JARAYON ICHIDA qilinmadi: python-telegram-bot
Application'i bir marta ishlashga mo'ljallangan, uni qayta ko'tarish
yarim tirik holatga olib keladi. Tashqi nazoratchi — sodda va ishonchli.

SOXTA TIKLANISHDAN HIMOYA: agar bot HAR SAFAR tez yiqilsa (masalan
token noto'g'ri), cheksiz aylanish faqat log to'ldiradi. Shuning uchun
qisqa umrli yiqilishlar sanaladi va chegaradan oshsa to'xtatiladi.

Foydalanish:
    python tools/nazoratchi.py
"""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOT = os.path.join(ROOT, "bot.py")

# Bot shuncha soniyadan kam ishlagan bo'lsa — "tez yiqilish" hisoblanadi
TEZ_YIQILISH_SEK = 60
# Ketma-ket shuncha tez yiqilishdan keyin to'xtatamiz
MAX_TEZ_YIQILISH = 5
# Qayta urinishlar orasidagi kutish
KUTISH = [5, 15, 30, 60, 120]

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def ishga_tushir():
    """Botni bir marta ishga tushiradi. Returns (chiqish_kodi, ishlagan_sek)."""
    t0 = time.time()
    try:
        p = subprocess.run([sys.executable, BOT], cwd=ROOT)
        kod = p.returncode
    except KeyboardInterrupt:
        return 0, time.time() - t0
    return kod, time.time() - t0


def main():
    tez_yiqilish = 0
    jami = 0
    print("[nazoratchi] Bot kuzatuv ostida ishga tushirilmoqda.")
    print("[nazoratchi] To'xtatish: Ctrl+C")
    while True:
        kod, ishladi = ishga_tushir()

        if kod == 0:
            print("[nazoratchi] Bot normal to'xtadi. Chiqamiz.")
            return 0

        jami += 1
        if ishladi < TEZ_YIQILISH_SEK:
            tez_yiqilish += 1
        else:
            # Uzoq ishlagan bo'lsa — bu o'tkinchi nosozlik, hisob tozalanadi
            tez_yiqilish = 0

        if tez_yiqilish >= MAX_TEZ_YIQILISH:
            print("")
            print("[nazoratchi] TO'XTATILDI: bot ketma-ket " + str(tez_yiqilish)
                  + " marta tez yiqildi.")
            print("[nazoratchi] Bu tarmoq nosozligi emas — sozlamada xato bor.")
            print("[nazoratchi] Tekshiring:")
            print("             python tools/env_check.py")
            print("             python tools/provider_check.py")
            return 1

        kut = KUTISH[min(tez_yiqilish, len(KUTISH) - 1)]
        print("")
        print("[nazoratchi] Bot kutilmaganda to'xtadi (kod " + str(kod)
              + ", " + str(int(ishladi)) + " sek ishladi).")
        print("[nazoratchi] " + str(kut) + " soniyadan keyin qayta ishga "
              "tushiriladi... (jami qayta urinish: " + str(jami) + ")")
        try:
            time.sleep(kut)
        except KeyboardInterrupt:
            print("[nazoratchi] To'xtatildi.")
            return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("[nazoratchi] To'xtatildi.")
        sys.exit(0)
