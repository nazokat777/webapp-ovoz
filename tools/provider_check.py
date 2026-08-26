"""Sozlangan AI kalitlarini HAQIQIY API'da tekshiradi.

Nega kerak: kalit noto'g'ri bo'lsa bot buni faqat birinchi audio kelganda
biladi — foydalanuvchi kutib turadi va xato oladi. Bu skript kalitlarni
oldindan, bir soniyada tekshiradi.

Foydalanish:
    python tools/provider_check.py

Chiqish kodi: 0 — kamida bitta STT va bitta matn modeli ishlayapti.
"""
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _load_env():
    """bot.py ni import qilmasdan .env ni o'qish (import og'ir va nojo'ya)."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        ".env")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            if k.startswith("export "):
                k = k[7:].strip()
            if k and k not in os.environ:
                os.environ[k] = v.strip().strip('"').strip("'")


# Groq'ning Cloudflare himoyasi "python-urllib" User-Agent'ini BLOKLAYDI
# (403, error code 1010) va bu KALIT YAROQSIZ degan yolg'on xulosaga olib
# borardi. Brauzer UA bilan o'sha kalit 200 qaytaradi — amalda o'lchandi.
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "Chrome/120 Safari/537.36")


def _get(url, headers, timeout=20):
    h = {"User-Agent": _UA}
    h.update(headers)
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as f:
            return f.status, f.read(400).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read(300).decode("utf-8", "replace")
    except Exception as e:
        return None, str(e)[:150]


def _post(url, headers, body, timeout=25):
    data = json.dumps(body).encode("utf-8")
    h = {"User-Agent": _UA}
    h.update(headers)
    h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as f:
            return f.status, f.read(400).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read(300).decode("utf-8", "replace")
    except Exception as e:
        return None, str(e)[:150]


def main():
    _load_env()
    oa = os.getenv("OPENAI_API_KEY", "").strip()
    gq = os.getenv("GROQ_API_KEY", "").strip()
    gm = os.getenv("GEMINI_API_KEY", "").strip()
    mx = os.getenv("MUXLISA_KEY", "").strip()

    stt_ok = chat_ok = False
    print("AI provayderlari tekshirilmoqda...\n")

    def natija(nom, holat, izoh=""):
        belgi = "[OK]  " if holat else "[XATO]"
        print(" " + belgi + " " + nom.ljust(26) + izoh)

    # ── STT ──────────────────────────────────────────────────────────
    print("AUDIO -> MATN:")
    if gq:
        code, body = _get("https://api.groq.com/openai/v1/models",
                          {"Authorization": "Bearer " + gq})
        good = code == 200
        stt_ok = stt_ok or good
        natija("Groq (whisper-large-v3)", good,
               "" if good else "HTTP " + str(code) + " " + body[:70])
    else:
        natija("Groq", False, "kalit yo'q (bepul: console.groq.com)")

    if oa:
        code, body = _get("https://api.openai.com/v1/models",
                          {"Authorization": "Bearer " + oa})
        good = code == 200
        stt_ok = stt_ok or good
        natija("OpenAI (gpt-audio)", good,
               "" if good else "HTTP " + str(code) + " " + body[:70])
    else:
        natija("OpenAI", False, "kalit yo'q")

    if mx:
        # Audiosiz POST: 400 = kalit QABUL qilindi, 401/403 = kalit yaroqsiz
        code, body = _post("https://service.muxlisa.uz/api/v2/stt",
                           {"x-api-key": mx}, {})
        good = code not in (401, 403, None)
        natija("Muxlisa (premium, o'zbek)", good,
               "" if good else "HTTP " + str(code) + " " + body[:70])
    else:
        natija("Muxlisa", False, "kalit yo'q (premium tarif uchun)")

    # ── MATN MODELI ──────────────────────────────────────────────────
    print("\nTARJIMA / TOZALASH:")
    kichik = {"messages": [{"role": "user", "content": "salom"}], "max_tokens": 5}
    for nom, kalit, url, model in (
            ("Gemini 2.5 Flash", gm,
             "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
             "gemini-2.5-flash"),
            ("Groq qwen3.8-27b", gq,
             "https://api.groq.com/openai/v1/chat/completions",
             "qwen/qwen3.8-27b"),
            ("OpenAI gpt-4o", oa,
             "https://api.openai.com/v1/chat/completions", "gpt-4o")):
        if not kalit:
            natija(nom, False, "kalit yo'q")
            continue
        body_req = dict(kichik)
        body_req["model"] = model
        code, body = _post(url, {"Authorization": "Bearer " + kalit}, body_req)
        good = code == 200
        chat_ok = chat_ok or good
        natija(nom, good, "" if good else "HTTP " + str(code) + " " + body[:70])

    print("")
    if stt_ok and chat_ok:
        print("XULOSA: bot to'liq ishlaydi.")
        return 0
    if not stt_ok:
        print("XULOSA: audio matnga AYLANMAYDI — Groq yoki OpenAI kaliti kerak.")
    if not chat_ok:
        print("XULOSA: tarjima/tozalash ISHLAMAYDI — Gemini, Groq yoki "
              "OpenAI kaliti kerak.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
