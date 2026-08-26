"""Deploy tekshiruvi — build konfiguratsiyasi + ishlab turgan server.

Foydalanish:
    python tools/live_check.py                      # default Railway URL
    python tools/live_check.py https://boshqa.url   # boshqa deploy
    SKIP_PREFLIGHT=1 python tools/live_check.py     # faqat server tekshiruvi

BOT_TOKEN env bo'lsa, Telegram API holati ham tekshiriladi (ixtiyoriy).

Hech narsani O'ZGARTIRMAYDI: faqat o'qish so'rovlari. Auth'siz POST'lar
ataylab rad etilishi KUTILADI — bu himoya ishlayotganini isbotlaydi.
"""
import io
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = (sys.argv[1] if len(sys.argv) > 1
        else "https://webapp-ovoz-production.up.railway.app").rstrip("/")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {name}")
    else:
        fail += 1
        print(f"  FAIL  {name}  {extra}")


def req(method, path, body=None, base=None):
    url = (base or BASE) + path
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json", "User-Agent": "live-check"})
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return None, str(e)


def _vtuple(v):
    out = []
    for part in v.split("."):
        num = ""
        for ch in part:
            if ch.isdigit():
                num += ch
            else:
                break
        out.append(int(num) if num else 0)
    return tuple(out)


def preflight():
    """Build UMUMAN muvaffaqiyatli bo'la oladimi.

    Yiqilgan build = deployment yo'q = Railway 'Application not found'.
    Shuning uchun bu tekshiruv serverdan OLDIN turadi: agar bu yerda xato
    bo'lsa, server tekshiruvlarining yiqilishi tabiiy."""
    print("[0] Build konfiguratsiyasi")
    try:
        reqs = [l.strip() for l in io.open(os.path.join(ROOT, "requirements.txt"),
                                          encoding="utf-8") if l.strip()]
    except Exception as e:
        check("requirements.txt o'qildi", False, str(e))
        reqs = []
    for line in reqs:
        if ">=" in line:
            name, want = line.split(">=", 1)
        else:
            name, want = line, None
        name = name.strip()
        st, body = req("GET", f"/pypi/{urllib.parse.quote(name)}/json",
                       base="https://pypi.org")
        if st != 200:
            check(f"pip: {name}", False, "PyPI'da topilmadi -> BUILD YIQILADI")
            continue
        cur = json.loads(body)["info"]["version"]
        good = (not want) or _vtuple(cur) >= _vtuple(want.strip())
        check(f"pip: {line}", good, f"PyPI'dagi eng yangisi {cur} -> BUILD YIQILADI")

    # Dockerfile'dagi apt paketlari (RUN apt-get install bloki)
    try:
        lines = io.open(os.path.join(ROOT, "Dockerfile"), encoding="utf-8").read().splitlines()
    except Exception:
        lines = []
    pkgs, inside = [], False
    for ln in lines:
        t = ln.strip()
        if t.startswith("RUN apt-get"):
            inside = True
            continue
        if inside:
            cand = t.rstrip("\\").strip()
            if not cand or cand.startswith("#"):
                continue
            if cand.startswith("&&") or cand.startswith("RUN "):
                inside = False
                continue
            if all(c.isalnum() or c in "-.+" for c in cand):
                pkgs.append(cand)
            if not ln.rstrip().endswith("\\"):
                inside = False
    for pkg in pkgs:
        st, _ = req("GET", f"/bookworm/{pkg}", base="https://packages.debian.org")
        check(f"apt: {pkg}", st == 200, "Debian bookworm'da yo'q -> BUILD YIQILADI")


if os.getenv("SKIP_PREFLIGHT", "").strip().lower() not in ("1", "true", "yes"):
    preflight()
    print()

print(f"Server: {BASE}")
print()

print("[1] Holat (/health)")
st_h, body_h = req("GET", "/health")
if st_h == 200:
    hj = json.loads(body_h)
    check("/health -> 200 (bot sozlangan)", hj.get("status") == "ok", hj)
    check("admin sozlangan", hj.get("admin_configured") is True,
          "ADMIN_USER_ID env yo'q — username fallback xavfsiz emas")
    check("OpenAI kaliti bor", hj.get("openai_configured") is True,
          "OPENAI_API_KEY yo'q — STT/tarjima ishlamaydi")
    print(f"        navbat: {hj.get('jobs')}")
    print(f"        data_file: {hj.get('data_file')}")
    warns = hj.get("warnings") or []
    crit = [w for w in warns if w.get("level") == "critical"]
    check("jiddiy sozlama muammosi yo'q", not crit,
          " || ".join(w.get("message", "") for w in crit))
    for w in warns:
        if w.get("level") != "critical":
            print(f"        ⚠️ {w.get('message')}")
elif st_h == 503:
    hj = json.loads(body_h) if body_h.startswith("{") else {}
    check("/health javob berdi", True)
    check("DEGRADED emas", False,
          "SABAB: " + str(hj.get("reason") or hj.get("message") or body_h[:120]))
else:
    check("/health javob berdi", False, f"status={st_h}")

print()
print("[2] WebApp sahifasi")
st_root, body_root = req("GET", "/")
check("GET / -> 200", st_root == 200, f"status={st_root}")
check("index.html yetkazildi", st_root == 200 and "initData" in (body_root or ""),
      "sahifada initData ishlovi topilmadi")

print()
print("[3] HMAC-auth himoyasi (rad etilishi KUTILADI)")
st, body = req("POST", "/url", {"url": "https://youtu.be/x", "init_data": "soxta"})
check("soxta initData bilan /url -> 401", st == 401, f"status={st} {body[:90]}")
st, _ = req("POST", "/audio", {"audio": "AAAA", "init_data": ""})
check("initData'siz /audio -> 401", st == 401, f"status={st}")
st, _ = req("POST", "/url", {"url": "https://youtu.be/x", "user_id": 123})
check("eski uslub (user_id) ham rad -> 401", st == 401,
      f"status={st}  (agar server tirik bo'lsa-yu 401 kelmasa — DARHOL tekshiring)")

print()
print("[4] Statik xizmat")
st, _ = req("GET", "/../bot.py")
check("path traversal yopiq", st in (400, 403, 404, 405), f"status={st}")
st, b = req("GET", "/bot.py")
check("manba kod berilmaydi", "BOT_TOKEN" not in (b or ""), "KOD OSHKOR BO'LDI!")
st, _ = req("GET", "/logo.png")
check("ruxsatli statik fayl ochiq", st == 200, f"status={st}")

token = os.getenv("BOT_TOKEN", "").strip()
print()
if token:
    print("[5] Telegram API (BOT_TOKEN env orqali)")
    api = f"https://api.telegram.org/bot{token}"
    st, body = req("GET", "/getMe", base=api)
    good = st == 200 and json.loads(body).get("ok")
    check("getMe ishlaydi (token amal qiladi)", bool(good), f"status={st}")
    if good:
        print("        bot: @" + json.loads(body)["result"].get("username", "?"))
    st, body = req("GET", "/getWebhookInfo", base=api)
    if st == 200:
        wh = json.loads(body).get("result", {}).get("url", "")
        check("webhook YO'Q (polling rejimi)", wh == "",
              f"webhook o'rnatilgan: {wh} — polling bilan to'qnashadi!")
else:
    print("[5] BOT_TOKEN env yo'q — Telegram API tekshiruvi o'tkazib yuborildi")

if st_root == 404 and "Application not found" in (body_root or ""):
    print()
    print("!" * 62)
    print("TASHXIS: Railway domeni faol deployment'ga bog'lanmagan.")
    print("Bu BOT xatosi EMAS — Railway edge javobi: kod ishga tushmagan")
    print("YOKI servis/domen mavjud emas.")
    print()
    print("MUHIM: BOT_TOKEN yo'qligi endi bu holatni KELTIRIB CHIQARMAYDI —")
    print("bot DEGRADED rejimda tirik qolib, /health orqali sabab aytadi.")
    print("Demak sabab boshqa joyda:")
    print("  1) Servis o'chirilgan, nomi yoki domeni o'zgargan")
    print("  2) Railway hisobi / billing to'xtatilgan")
    print("  3) Build yiqilgan — yuqoridagi [0] bo'limga qarang")
    print("     ([0] toza bo'lsa, build konfiguratsiyasi aybdor emas)")
    print("  4) Deploy hali tugamagan (1-2 daqiqa kuting va qayta ishga tushiring)")
    print()
    print("Qadam: Railway → Deployments → oxirgi deploy LOGI.")
    print("       Servis va domen mavjudligini Settings'da tekshiring.")
    print("!" * 62)

print()
print("=" * 46)
print(("✅ Hammasi joyida" if not fail else f"❌ {fail} ta muammo") + f"  ({ok} pass)")
sys.exit(1 if fail else 0)
