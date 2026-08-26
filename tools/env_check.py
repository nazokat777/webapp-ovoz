"""'.env' faylini bot ishga tushishidan OLDIN tekshiradi.

NEGA KERAK: sozlama xatosi bo'lsa bot DEGRADED rejimga tushib, hech kimga
javob bermay jim turadi — sabab faqat logda qoladi. Bu skript sababni
ishga tushirish paytida, tushunarli tilda aytadi.

MUHIM: bu yerdagi tahlil bot.py'dagi _load_dotenv bilan AYNAN bir xil
bo'lishi shart. Ular ajralib ketsa tekshiruv yolg'on gapiradi
(tests/test_env_check.py ikkalasining mosligini sinaydi).

Chiqish kodi:
  0 - hammasi joyida
  2 - BOT_TOKEN yo'q/bo'sh   (bot UMUMAN ishlamaydi)
  3 - OPENAI_API_KEY yo'q/bo'sh (audio -> matn ishlamaydi)
  4 - .env fayli umuman yo'q
"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def parse_dotenv(path):
    """bot.py'dagi _load_dotenv bilan bir xil qoidalar."""
    out = {}
    # utf-8-sig: Notepad BOM qo'shsa ham birinchi kalit buzilmasin
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            if key.startswith("export "):
                key = key[7:].strip()
            out[key] = val.strip().strip('"').strip("'")
    return out


def main(argv):
    path = argv[1] if len(argv) > 1 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")

    if not os.path.exists(path):
        print("[!] .env fayli topilmadi.")
        return 4

    try:
        env = parse_dotenv(path)
    except Exception as e:
        print("[!] .env o'qib bo'lmadi: " + str(e))
        return 4

    # Haqiqiy muhit o'zgaruvchisi .env'dan ustun turadi (bot.py ham shunday)
    def val(k):
        return (os.environ.get(k) or env.get(k) or "").strip()

    if not val("BOT_TOKEN"):
        print("[!] BOT_TOKEN bo'sh yoki yo'q.")
        return 2
    if not val("OPENAI_API_KEY"):
        print("[!] OPENAI_API_KEY bo'sh yoki yo'q.")
        return 3

    print("[OK] .env tekshirildi: BOT_TOKEN va OPENAI_API_KEY joyida.")
    if not val("WEBAPP_URL"):
        print("     (WEBAPP_URL yo'q - Web ilova tugmasi berkitiladi, "
              "qolgan hamma narsa ishlaydi)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
