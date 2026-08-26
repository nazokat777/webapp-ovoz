"""Uchdan-uchga HTTP testlari — HAQIQIY aiohttp server ustida.

Nega kerak: qolgan testlar funksiyalarni to'g'ridan-to'g'ri chaqiradi.
Bu yerda esa server rostdan ko'tariladi va so'rovlar tarmoq orqali boradi —
route'lar, HMAC tekshiruvi, status kodlar va dispatch mantig'i birgalikda
tekshiriladi. Tashqi tarmoq YO'Q: faqat 127.0.0.1, Telegram/OpenAI chaqirilmaydi.
"""
import hashlib
import hmac
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

TOKEN = "111111:FAKE_E2E_TOKEN"
os.environ["BOT_TOKEN"] = TOKEN
os.environ["ADMIN_USER_ID"] = "111"


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


PORT = _free_port()
os.environ["HTTP_PORT"] = str(PORT)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bot  # noqa: E402

ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {name}")
    else:
        fail += 1
        print(f"  FAIL  {name}  {extra}")


def sign(user_id, auth_date=None, token=TOKEN):
    """Haqiqiy Telegram initData imzosini yasash."""
    fields = {
        "auth_date": str(int(auth_date if auth_date is not None else time.time())),
        "query_id": "AAE2E",
        "user": json.dumps({"id": user_id, "first_name": "E2E"}, separators=(",", ":")),
    }
    dcs = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    import urllib.parse
    return urllib.parse.urlencode(fields)


def req(method, path, body=None):
    url = f"http://127.0.0.1:{PORT}{path}"
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


# Ishlarni HAQIQATAN bajarmaymiz — faqat qabul qilinganini yozib olamiz
submitted = []
bot.submit_job = lambda user_id, target, args=(), label="ish", cleanup_path=None: (
    submitted.append({"user_id": user_id, "target": getattr(target, "__name__", str(target)),
                      "args": args, "label": label}) or True)
# Telegram'ga chiqmaymiz
bot.telegram_send_message = lambda *a, **k: True

threading.Thread(target=bot.run_http_server_thread, daemon=True).start()
for _ in range(50):
    try:
        req("GET", "/")
        break
    except Exception:
        time.sleep(0.1)

print("\n[E2E-1] Sahifa va statik")
st, body = req("GET", "/")
check("GET / -> 200", st == 200, f"status={st}")
check("index.html mazmuni", "initData" in body)
st, _ = req("GET", "/yoq-fayl.png")
check("mavjud bo'lmagan rasm -> 404", st == 404, f"status={st}")
# Muhimi STATUS emas, MAZMUN: manba kod hech qanday holatda berilmasin.
# (405 keladi — OPTIONS catch-all yo'lni taniydi, GET esa ruxsat etilmagan.)
for _p in ("/bot.py", "/user_data.json", "/tariff_log.jsonl", "/.env", "/Dockerfile"):
    st, b = req("GET", _p)
    check(f"maxfiy fayl berilmadi: {_p}",
          st in (403, 404, 405) and "BOT_TOKEN" not in b and "import " not in b,
          f"status={st} body={b[:60]}")

print("\n[E2E-2] HMAC auth — RAD ETILISHI kutiladi")
for name, payload in [
    ("init_data yo'q", {"url": "https://youtu.be/a"}),
    ("bo'sh init_data", {"url": "https://youtu.be/a", "init_data": ""}),
    ("soxta init_data", {"url": "https://youtu.be/a", "init_data": "user=%7B%22id%22%3A5%7D&hash=dead"}),
    ("eski uslub user_id", {"url": "https://youtu.be/a", "user_id": 777}),
]:
    st, b = req("POST", "/url", payload)
    check(f"{name} -> 401", st == 401, f"status={st} {b[:80]}")

st, b = req("POST", "/url", {"url": "https://youtu.be/a",
                             "init_data": sign(5, token="999:BOSHQA")})
check("boshqa token bilan imzo -> 401", st == 401, f"status={st}")
st, b = req("POST", "/url", {"url": "https://youtu.be/a",
                             "init_data": sign(5, auth_date=time.time() - bot.INIT_DATA_MAX_AGE - 60)})
check("eskirgan imzo -> 401", st == 401, f"status={st}")

# user_id ni almashtirishga urinish
tampered = sign(5).replace("%22id%22%3A5", "%22id%22%3A6")
st, b = req("POST", "/url", {"url": "https://youtu.be/a", "init_data": tampered})
check("user_id almashtirish -> 401", st == 401, f"status={st}")

print("\n[E2E-3] To'g'ri imzo — QABUL qilinadi")
submitted.clear()
st, b = req("POST", "/url", {"url": "https://youtu.be/abc", "init_data": sign(4242)})
check("to'g'ri imzo -> 200", st == 200, f"status={st} {b[:80]}")
check("ish navbatga qo'yildi", len(submitted) == 1, submitted)
check("user_id IMZODAN olindi (klientdan emas)",
      submitted and submitted[0]["user_id"] == 4242, submitted)

# Klient boshqa user_id yubormoqchi — e'tiborga olinmasligi kerak
submitted.clear()
st, _ = req("POST", "/url", {"url": "https://youtu.be/abc", "user_id": 9999,
                             "init_data": sign(4242)})
check("klient user_id'si e'tiborsiz qoldirildi",
      st == 200 and submitted and submitted[0]["user_id"] == 4242, submitted)

print("\n[E2E-4] URL validatsiyasi (imzo to'g'ri bo'lsa ham)")
submitted.clear()
for bad in ["--config-location=/tmp/x", "shunchaki matn", "file:///etc/passwd", ""]:
    st, _ = req("POST", "/url", {"url": bad, "init_data": sign(4242)})
    label = bad[:28] if bad else "(bosh)"
    check(f"rad: {label} -> 400", st == 400, f"status={st}")
check("hech biri navbatga tushmadi", not submitted, submitted)

print("\n[E2E-5] Mikrofon oqimi: uz->uz tarjima EMAS (2x hisob bo'lmasin)")
submitted.clear()
st, _ = req("POST", "/audio", {"init_data": sign(4242), "audio": "AAAA",
                              "format": "audio/webm",
                              "translation_lang": "uz", "target_lang": "uz"})
check("uz->uz -> oddiy STT", st == 200 and submitted
      and submitted[0]["target"] == "process_audio_for_user", submitted)
submitted.clear()
st, _ = req("POST", "/audio", {"init_data": sign(4242), "audio": "AAAA",
                              "format": "audio/webm",
                              "translation_lang": "ru", "target_lang": "uz"})
check("ru->uz -> tarjima", st == 200 and submitted
      and submitted[0]["target"] == "process_translation_for_user", submitted)

print("\n[E2E-6] Rad etilgan ish -> 429 (WebApp confetti chiqarmasin)")
bot.submit_job = lambda *a, **k: False
st, b = req("POST", "/url", {"url": "https://youtu.be/abc", "init_data": sign(4242)})
check("submit rad etsa -> 429", st == 429, f"status={st}")
check("sabab xabari bor", "message" in json.loads(b), b[:100])

print("\n[E2E-7] CORS/OPTIONS")
st, _ = req("OPTIONS", "/url")
check("OPTIONS -> 204", st == 204, f"status={st}")

print(f"\nNatija: {ok} pass, {fail} fail")
sys.exit(1 if fail else 0)
