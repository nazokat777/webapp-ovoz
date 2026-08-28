"""'.env' faylini bot ishga tushishidan OLDIN tekshiradi.

NEGA KERAK: sozlama xatosi bo'lsa bot DEGRADED rejimga tushib, hech kimga
javob bermay jim turadi — sabab faqat logda qoladi. Bu skript sababni
ishga tushirish paytida, tushunarli tilda aytadi.

MUHIM: bu yerdagi tahlil bot.py'dagi _load_dotenv bilan AYNAN bir xil
bo'lishi shart. Ular ajralib ketsa tekshiruv yolg'on gapiradi
(tests/test_env_check.py ikkalasining mosligini sinaydi).

Chiqish kodi:
  0 - hammasi joyida
  2 - BOT_TOKEN yo'q/bo'sh          (bot UMUMAN ishlamaydi)
  3 - AI provayderi yo'q            (audio matnga aylanmaydi)
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

    # AI PROVAYDERLARI — OpenAI endi MAJBURIY EMAS.
    # Ilgari bu yerda faqat OPENAI_API_KEY tekshirilardi va bepul
    # provayderlar sozlangan bo'lsa ham skript keraksiz savol berardi.
    stt = [k for k in ("GROQ_API_KEY", "OPENAI_API_KEY") if val(k)]
    matn = [k for k in ("GEMINI_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY")
            if val(k)]

    if not stt:
        print("[!] Audio matnga aylantiruvchi provayder YO'Q.")
        print("    Kamida bittasi kerak:")
        print("      GROQ_API_KEY   - bepul, kartasiz: console.groq.com")
        print("      OPENAI_API_KEY - pullik")
        return 3
    if not matn:
        print("[!] Matn modeli (tarjima va imlo tozalash) YO'Q.")
        print("    Kamida bittasi kerak:")
        print("      GEMINI_API_KEY - bepul: aistudio.google.com/apikey")
        print("      GROQ_API_KEY   - bepul: console.groq.com")
        return 3

    print("[OK] Sozlamalar joyida.")
    print("     audio -> matn : " + ", ".join(stt))
    print("     matn modeli   : " + ", ".join(matn))
    if not val("MUXLISA_KEY"):
        print("     (MUXLISA_KEY yo'q - Premium tarif oddiy STT bilan ishlaydi)")
    if not val("WEBAPP_URL"):
        print("     (WEBAPP_URL yo'q - Web ilova tugmasi berkitiladi, "
              "qolgani ishlaydi)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
