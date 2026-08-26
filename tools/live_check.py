"""Deploy'dan keyingi JONLI tekshiruv — ishlab turgan serverga qarshi.

Foydalanish (lokal kompyuterdan):
    python tools/live_check.py                      # default Railway URL
    python tools/live_check.py https://boshqa.url   # boshqa deploy

BOT_TOKEN env o'rnatilgan bo'lsa, Telegram API holati ham tekshiriladi
(ixtiyoriy — tokensiz ham server tekshiruvlari ishlayveradi).

Hech narsani O'ZGARTIRMAYDI: faqat GET/POST o'qish so'rovlari; auth'siz
POST'lar ataylab rad etilishi KUTILADI (himoya ishlayotganini isbotlaydi).
"""
import json
import os
import sys
import urllib.request
import urllib.error

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = (sys.argv[1] if len(sys.argv) > 1 else "https://webapp-ovoz-production.up.railway.app").rstrip("/")
ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {name}")
    else:
        fail += 1
        print(f"  FAIL  {name}  {extra}")


def req(method, path, body=None, headers=None, base=None):
    url = (base or BASE) + path
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method,
                               headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return None, str(e)


print(f"Server: {BASE}\n")

print("[1] WebApp sahifasi")
st, body = req("GET", "/")
check("GET / -> 200", st == 200, f"status={st}")
check("index.html yetkazildi", st == 200 and "initData" in body,
      "sahifada initData ishlovi topilmadi")

print("\n[2] HMAC-auth himoyasi (rad etilishi KUTILADI)")
st, body = req("POST", "/url", {"url": "https://youtu.be/x", "init_data": "soxta"})
check("soxta initData bilan /url -> 401", st == 401, f"status={st} body={body[:120]}")
st, body = req("POST", "/audio", {"audio": "AAAA", "init_data": ""})
check("initData'siz /audio -> 401", st == 401, f"status={st}")
st, body = req("POST", "/url", {"url": "https://youtu.be/x", "user_id": 123})
check("eski uslub (user_id) ham rad -> 401", st == 401,
      f"status={st}  !!! 401 emas = HIMOYA ISHLAMAYAPTI, darhol tekshiring")

print("\n[3] Statik xizmat chegaralari")
st, _ = req("GET", "/../bot.py")
check("path traversal yopiq", st in (403, 404, 400), f"status={st}")
st, _ = req("GET", "/logo.png")
check("ruxsatli statik fayl ochiq", st == 200, f"status={st}")

token = os.getenv("BOT_TOKEN", "").strip()
if token:
    print("\n[4] Telegram API (BOT_TOKEN env orqali)")
    api = f"https://api.telegram.org/bot{token}"
    st, body = req("GET", "/getMe", base=api)
    okj = st == 200 and json.loads(body).get("ok")
    check("getMe ishlaydi (token amal qiladi)", bool(okj), f"status={st}")
    if okj:
        print("        bot: @" + json.loads(body)["result"].get("username", "?"))
    st, body = req("GET", "/getWebhookInfo", base=api)
    if st == 200:
        url = json.loads(body).get("result", {}).get("url", "")
        check("webhook YO'Q (polling rejimi)", url == "",
              f"webhook o'rnatilgan: {url} — polling bilan to'qnashadi!")
else:
    print("\n[4] BOT_TOKEN env yo'q — Telegram API tekshiruvi o'tkazib yuborildi")
    print("    (xohlasangiz: set BOT_TOKEN=... && python tools/live_check.py)")

print(f"\n{'='*46}")
print(("✅ Hammasi joyida" if not fail else f"❌ {fail} ta muammo") + f"  ({ok} pass)")
sys.exit(1 if fail else 0)
