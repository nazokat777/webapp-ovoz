"""Sozlama o'qish va tekshirish — JIM NOSOZLIKLAR shu yerda ushlanadi.

Bu to'plam aynan "bot ishlamayapti, sababi ko'rinmayapti" turkumidagi
xatolarni qamrab oladi:

  * .env BOM bilan saqlangan (Windows Notepad) -> BOT_TOKEN jimgina yo'qoladi
  * WEBAPP_URL sozlangan, lekin kod uni tashlab yuboradi -> tugma boshqa
    (o'lik) saytga olib boradi
  * WEBAPP_URL yo'q -> tugma o'lik manzilga ishora qiladi

Tarmoq talab qilinmaydi.
"""
import os
import subprocess
import sys
import tempfile

os.environ["BOT_TOKEN"] = "111111:FAKE_ENVCHK"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import bot          # noqa: E402
import env_check    # noqa: E402

ok = fail = 0
BOM = chr(65279)
_tmp = tempfile.mkdtemp(prefix="envchk_")


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print("  PASS  " + name)
    else:
        fail += 1
        print("  FAIL  " + name + "  " + str(extra))


def write_env(name, text, bom=False):
    p = os.path.join(_tmp, name)
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write((BOM if bom else "") + text)
    return p


print("[1] .env BOM bilan saqlangan bo'lsa ham o'qiladi")
# Windows Notepad UTF-8 ni BOM bilan saqlashi mumkin. Ilgari bot .env ni
# oddiy "utf-8" bilan o'qir, birinchi kalit "<BOM>BOT_TOKEN" bo'lib qolar va
# JIMGINA e'tiborsiz qolardi -> bot DEGRADED rejimga tushardi, foydalanuvchi
# esa .env to'g'ri to'ldirilganini ko'rib turardi.
_p = write_env("bom.env", "BOT_TOKEN=BOMLI_TOKEN\nOPENAI_API_KEY=sk-bomli\n", bom=True)
for _k in ("BOT_TOKEN", "OPENAI_API_KEY"):
    os.environ.pop(_k, None)
bot._load_dotenv(_p)
check("BOM'li faylda BOT_TOKEN o'qildi",
      os.environ.get("BOT_TOKEN") == "BOMLI_TOKEN", os.environ.get("BOT_TOKEN"))
check("BOM kalit nomiga yopishib qolmadi",
      not any(k.startswith(BOM) for k in os.environ), "BOM'li kalit bor")

print("[2] env_check bot bilan BIR XIL tahlil qiladi")
# Ular ajralib ketsa tekshiruv yolg'on gapiradi.
_tricky = ("# izoh\n"
           "export EXPORTLI=42\n"
           "TIRNOQLI=\"qiymat\"\n"
           "APOSTROFLI='ikkinchi'\n"
           "BOSH=\n"
           "tengliksiz qator\n"
           "  BO_SHLIQLI  =  atrofda  \n")
_p2 = write_env("tricky.env", "BOT_TOKEN=T\n" + _tricky, bom=True)
_parsed = env_check.parse_dotenv(_p2)
for _k in ("EXPORTLI", "TIRNOQLI", "APOSTROFLI", "BOSH", "BO_SHLIQLI", "BOT_TOKEN"):
    os.environ.pop(_k, None)
bot._load_dotenv(_p2)
_mos = {k: v for k, v in _parsed.items() if k != "BOT_TOKEN"}
_farq = [(k, v, os.environ.get(k)) for k, v in _mos.items() if os.environ.get(k) != v]
check("hamma kalit bir xil tahlil qilindi", not _farq, _farq)
check("export prefiksi", _parsed.get("EXPORTLI") == "42", _parsed.get("EXPORTLI"))
check("tirnoq olib tashlandi", _parsed.get("TIRNOQLI") == "qiymat")
check("bo'sh qiymat", _parsed.get("BOSH") == "")
check("tengliksiz qator tashlandi", "tengliksiz qator" not in _parsed)

print("[3] env_check chiqish kodlari (.bat shu kodlarga tayanadi)")
_chk = os.path.join(ROOT, "tools", "env_check.py")


def run_check(path):
    env = dict(os.environ)
    # Haqiqiy env qiymatlari natijani buzmasin
    for k in ("BOT_TOKEN", "OPENAI_API_KEY", "WEBAPP_URL"):
        env.pop(k, None)
    r = subprocess.run([sys.executable, _chk, path], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", env=env)
    return r.returncode


check("to'liq .env -> 0",
      run_check(write_env("ok.env", "BOT_TOKEN=t\nOPENAI_API_KEY=sk-x\n")) == 0)
check("BOT_TOKEN bo'sh -> 2",
      run_check(write_env("notok.env", "BOT_TOKEN=\nOPENAI_API_KEY=sk-x\n")) == 2)
check("BOT_TOKEN yo'q -> 2",
      run_check(write_env("yoq.env", "OPENAI_API_KEY=sk-x\n")) == 2)
check("OPENAI kalit bo'sh -> 3",
      run_check(write_env("nokey.env", "BOT_TOKEN=t\nOPENAI_API_KEY=\n")) == 3)
check("fayl yo'q -> 4", run_check(os.path.join(_tmp, "umuman_yoq.env")) == 4)
check("BOM'li to'liq .env -> 0",
      run_check(write_env("okbom.env", "BOT_TOKEN=t\nOPENAI_API_KEY=sk-x\n",
                          bom=True)) == 0)

print("[4] WEBAPP_URL — aniq sozlangan qiymat USTUN")
_saqla = {k: os.environ.get(k) for k in ("WEBAPP_URL", "RAILWAY_PUBLIC_DOMAIN")}


def resolve(webapp=None, railway=None):
    for k, v in (("WEBAPP_URL", webapp), ("RAILWAY_PUBLIC_DOMAIN", railway)):
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    return bot._resolve_webapp_url()


# Ilgari `"ngrok" not in manual` sharti bor edi: ngrok manzili JIMGINA
# tashlanar va kod qattiq yozilgan Railway manziliga qaytardi.
check("ngrok manzili ENDI hurmat qilinadi",
      resolve(webapp="https://abc.ngrok-free.dev") == "https://abc.ngrok-free.dev",
      resolve(webapp="https://abc.ngrok-free.dev"))
check("oddiy manzil ishlaydi",
      resolve(webapp="https://mysite.example") == "https://mysite.example")
check("oxirgi slash olib tashlanadi",
      resolve(webapp="https://mysite.example/") == "https://mysite.example")
check("aniq qiymat Railway domenidan USTUN",
      resolve(webapp="https://aniq.example", railway="rw.up.railway.app")
      == "https://aniq.example")
check("faqat Railway domeni bo'lsa u ishlatiladi",
      resolve(railway="rw.up.railway.app") == "https://rw.up.railway.app")
check("hech narsa yo'q -> BO'SH (o'lik manzil EMAS)", resolve() == "",
      repr(resolve()))

print("[5] Sozlanmagan WEBAPP_URL -> tugma KO'RSATILMAYDI")
_eski = bot.WEBAPP_URL
try:
    bot.WEBAPP_URL = ""
    _kb = bot.webapp_keyboard(chat_id=1)
    _matnlar = [b.text for row in _kb.keyboard for b in row]
    _webapps = [b for row in _kb.keyboard for b in row if getattr(b, "web_app", None)]
    check("o'lik Web ilova tugmasi yo'q", not _webapps, _matnlar)
    check("qolgan tugmalar joyida", "🌐 Tarjima" in _matnlar and
          "📊 Balansim" in _matnlar, _matnlar)
    check("fresh_webapp_url bo'sh satr", bot.fresh_webapp_url() == "")

    bot.WEBAPP_URL = "https://bor.example"
    _kb2 = bot.webapp_keyboard(chat_id=1)
    _wa = [b for row in _kb2.keyboard for b in row if getattr(b, "web_app", None)]
    check("sozlangan bo'lsa tugma BOR", len(_wa) == 1, len(_wa))
    check("tugma URL to'g'ri", _wa and _wa[0].web_app.url.startswith(
          "https://bor.example?v="), _wa and _wa[0].web_app.url)
finally:
    bot.WEBAPP_URL = _eski
    for k, v in _saqla.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v

try:
    import shutil
    shutil.rmtree(_tmp, ignore_errors=True)
except Exception:
    pass

print("\nNatija: " + str(ok) + " pass, " + str(fail) + " fail")
sys.exit(1 if fail else 0)
