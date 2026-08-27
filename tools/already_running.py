"""Bot allaqachon ishlayaptimi — tekshiradi.

NEGA KERAK: Telegram bitta tokenga BITTA poller ruxsat beradi. Ikkinchi
nusxa ko'tarilsa ikkalasi ham `409 Conflict` oladi va bot HECH KIMGA
javob bermay qoladi. Ya'ni "yana bir marta ishga tushiray" degan
zararsiz harakat butun xizmatni to'xtatadi.

Shuning uchun ishga tushirishdan OLDIN tekshiriladi.

Chiqish kodi:
  0 - yo'l ochiq, ishga tushirish mumkin
  1 - allaqachon ishlayapti (ikkinchi nusxa KERAK EMAS)
"""
import json
import os
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _port():
    for nom in ("HTTP_PORT", "PORT"):
        v = os.environ.get(nom, "").strip()
        if v:
            return v
    path = os.path.join(ROOT, ".env")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("HTTP_PORT=") or line.startswith("PORT="):
                        v = line.partition("=")[2].strip().strip('"').strip("'")
                        if v:
                            return v
        except Exception:
            pass
    return "8000"


def tekshir(port=None):
    """Returns (ishlayaptimi, tafsilot)."""
    port = port or _port()
    url = "http://127.0.0.1:" + str(port) + "/health"
    try:
        with urllib.request.urlopen(url, timeout=4) as f:
            raw = f.read(4000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        # 503 = DEGRADED rejim: jarayon TIRIK, sozlamasi chala
        return True, "javob berdi (HTTP " + str(e.code) + ")"
    except Exception:
        return False, ""
    try:
        d = json.loads(raw)
        holat = d.get("status", "?")
        ogoh = len(d.get("warnings") or [])
        return True, "holat=" + str(holat) + ", ogohlantirish=" + str(ogoh)
    except Exception:
        return True, "javob berdi"


def main():
    ishlayapti, tafsilot = tekshir()
    if not ishlayapti:
        print("[OK] Bot ishlamayapti — ishga tushirish mumkin.")
        return 0
    print("[!] BOT ALLAQACHON ISHLAYAPTI (" + tafsilot + ")")
    print("")
    print("    Ikkinchi nusxa ko'tarilsa Telegram 409 Conflict beradi va")
    print("    IKKALASI HAM javob bermay qoladi.")
    print("")
    print("    Agar eski nusxani to'xtatmoqchi bo'lsangiz: uning oynasida")
    print("    Ctrl+C bosing, keyin bu skriptni qaytadan ishga tushiring.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
