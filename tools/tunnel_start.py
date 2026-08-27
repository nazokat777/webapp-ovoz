"""WEBAPP_URL ngrok manzili bo'lsa tunnelni ko'taradi.

NEGA KERAK: bot lokal ishlaganda Web ilova faqat tunnel orqali ochiladi.
Tunnel tushib qolsa bot ishlayveradi, lekin "Web ilovani ochish" tugmasi
o'lik sahifaga olib boradi va foydalanuvchi butun bot buzuq deb o'ylaydi
(amalda shunday bo'ldi). Shuning uchun bot bilan BIRGA ko'tariladi.

Foydalanish:
    python tools/tunnel_start.py

Chiqish kodi: 0 — tunnel kerak emas yoki ko'tarildi; 1 — kerak, lekin
bo'lmadi (sabab chop etiladi).
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _env(name):
    """.env dan o'qish — bot.py bilan bir xil qoidalar (BOM ham hisobga olinadi)."""
    v = os.environ.get(name, "").strip()
    if v:
        return v
    path = os.path.join(ROOT, ".env")
    if not os.path.exists(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, val = line.partition("=")
                if k.strip() == name:
                    return val.strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def _ngrok_yoli():
    """ngrok.exe ni topish: PATH, keyin odatiy joylar."""
    from shutil import which
    p = which("ngrok")
    if p:
        return p
    nomzodlar = [
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "ngrok", "ngrok.exe"),
        os.path.join(os.environ.get("USERPROFILE", ""), "ngrok.exe"),
        os.path.join(os.environ.get("USERPROFILE", ""), "Downloads", "ngrok.exe"),
    ]
    for c in nomzodlar:
        if c and os.path.isfile(c):
            return c
    return ""


def _allaqachon_ishlayaptimi():
    """ngrok o'zining 4040 portida boshqaruv API'sini ochadi."""
    try:
        with urllib.request.urlopen(
                "http://127.0.0.1:4040/api/tunnels", timeout=3) as f:
            d = json.load(f)
        return [t.get("public_url") for t in d.get("tunnels", [])]
    except Exception:
        return []


def main():
    url = _env("WEBAPP_URL")
    port = _env("HTTP_PORT") or _env("PORT") or "8000"

    if not url:
        print("[i] WEBAPP_URL sozlanmagan — tunnel kerak emas.")
        return 0
    if "ngrok" not in url:
        print("[i] WEBAPP_URL ngrok emas (" + url + ") — tunnel kerak emas.")
        return 0

    tirik = _allaqachon_ishlayaptimi()
    if any(url.rstrip("/") in (t or "") for t in tirik):
        print("[OK] Tunnel allaqachon ishlayapti: " + url)
        return 0
    if tirik:
        print("[!] ngrok ishlayapti, lekin BOSHQA manzil bilan: " + str(tirik))
        print("    Kerakli manzil: " + url)
        print("    Eski ngrok oynasini yoping va qaytadan urinib ko'ring.")
        return 1

    exe = _ngrok_yoli()
    if not exe:
        print("[!] ngrok topilmadi. Web ilova ochilmaydi (bot ishlayveradi).")
        print("    O'rnatish: https://ngrok.com/download")
        return 1

    domen = url.split("//", 1)[-1].strip("/")
    cmd = [exe, "http", port, "--domain=" + domen]
    try:
        # Alohida oynada, botdan mustaqil ishlasin
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        subprocess.Popen(cmd, creationflags=flags) if flags else subprocess.Popen(cmd)
        print("[OK] Tunnel ishga tushirildi: " + url + "  (port " + port + ")")
        return 0
    except Exception as e:
        print("[!] Tunnel ko'tarilmadi: " + str(e)[:120])
        return 1


if __name__ == "__main__":
    sys.exit(main())
