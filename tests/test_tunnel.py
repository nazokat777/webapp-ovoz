"""Web ilova tunnelini avtomatik ko'tarish mantig'i.

NEGA MUHIM: bot lokal ishlaganda Web ilova FAQAT tunnel orqali ochiladi.
Tunnel tushsa bot ishlayveradi, lekin "Web ilovani ochish" tugmasi o'lik
sahifaga olib boradi — foydalanuvchi butun bot buzuq deb o'ylaydi.
Amalda aynan shunday bo'ldi, shuning uchun mantiq sinaladi.

Tarmoq va haqiqiy ngrok talab qilinmaydi.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import tunnel_start as ts  # noqa: E402

ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print("  PASS  " + name)
    else:
        fail += 1
        print("  FAIL  " + name + "  " + str(extra))


_asl = {
    "_env": ts._env,
    "_ngrok": ts._ngrok_yoli,
    "_ish": ts._allaqachon_ishlayaptimi,
    "popen": ts.subprocess.Popen,
}

_ishga_tushdi = []


def _soxta_popen(cmd, **kw):
    _ishga_tushdi.append(cmd)
    return object()


def sozla(url, port="8000", ngrok="C:\ngrok.exe", tirik=None):
    ts._env = lambda n: {"WEBAPP_URL": url, "HTTP_PORT": port,
                         "PORT": ""}.get(n, "")
    ts._ngrok_yoli = lambda: ngrok
    ts._allaqachon_ishlayaptimi = lambda: (tirik or [])
    ts.subprocess.Popen = _soxta_popen
    _ishga_tushdi.clear()


try:
    print("[1] Tunnel KERAK EMAS holatlari")
    sozla("")
    check("WEBAPP_URL bo'sh -> 0, ko'tarilmaydi",
          ts.main() == 0 and not _ishga_tushdi)
    sozla("https://mening-serverim.uz")
    check("oddiy server manzili -> 0, ko'tarilmaydi",
          ts.main() == 0 and not _ishga_tushdi, _ishga_tushdi)

    print("[2] Tunnel KERAK — ko'tariladi")
    sozla("https://abc.ngrok-free.dev")
    kod = ts.main()
    check("ngrok manzili -> ko'tarildi", kod == 0 and len(_ishga_tushdi) == 1,
          (kod, _ishga_tushdi))
    if _ishga_tushdi:
        cmd = _ishga_tushdi[0]
        check("buyruqda 'http' va port bor",
              "http" in cmd and "8000" in cmd, cmd)
        check("domen WEBAPP_URL dan olindi (protokolsiz)",
              "--domain=abc.ngrok-free.dev" in cmd, cmd)
        check("manzilda // qolmadi", not any("//" in str(c) for c in cmd), cmd)

    print("[3] Port sozlamasi hurmat qilinadi")
    sozla("https://abc.ngrok-free.dev", port="9999")
    ts.main()
    check("boshqa port ishlatildi", "9999" in _ishga_tushdi[0], _ishga_tushdi)

    print("[4] Takroriy ko'tarilish OLDINI OLINADI")
    sozla("https://abc.ngrok-free.dev", tirik=["https://abc.ngrok-free.dev"])
    kod = ts.main()
    check("allaqachon ishlayotgan bo'lsa qayta ko'tarilmaydi",
          kod == 0 and not _ishga_tushdi, (kod, _ishga_tushdi))

    print("[5] Nosozlik holatlari ANIQ xabar beradi")
    sozla("https://abc.ngrok-free.dev", tirik=["https://boshqa.ngrok-free.dev"])
    kod = ts.main()
    check("BOSHQA manzil bilan ishlayotgan ngrok -> 1 (jim qolmaydi)",
          kod == 1 and not _ishga_tushdi, (kod, _ishga_tushdi))
    sozla("https://abc.ngrok-free.dev", ngrok="")
    kod = ts.main()
    check("ngrok o'rnatilmagan -> 1", kod == 1 and not _ishga_tushdi, kod)

    print("[6] Ko'tarilmasa ham bot TO'XTAMASLIGI kerak")
    # .bat 'if errorlevel 1' bilan faqat OGOHLANTIRADI, to'xtatmaydi —
    # Telegram tomonidagi hamma narsa tunnelsiz ham ishlayveradi.
    bat = open(os.path.join(ROOT, "ishga_tushirish.bat"),
               encoding="utf-8").read()
    check("skript tunnelni chaqiradi", "tunnel_start.py" in bat)
    check("xato bo'lsa faqat ogohlantiradi, GOTO qilmaydi",
          "if errorlevel 1 echo" in bat and
          "if errorlevel 1 goto" not in bat.split("tunnel_start.py")[1][:200],
          "tunnel xatosi botni to'xtatmasligi kerak")
finally:
    ts._env = _asl["_env"]
    ts._ngrok_yoli = _asl["_ngrok"]
    ts._allaqachon_ishlayaptimi = _asl["_ish"]
    ts.subprocess.Popen = _asl["popen"]

print("[7] Takroriy nusxa qo'riqchisi")
# Telegram bitta tokenga BITTA poller ruxsat beradi. Ikkinchi nusxa
# ko'tarilsa IKKALASI ham 409 Conflict oladi va bot hech kimga javob
# bermay qoladi — "yana bir marta ishga tushiray" degan zararsiz harakat
# butun xizmatni o'ldiradi.
import already_running as ar  # noqa: E402

_asl_open = ar.urllib.request.urlopen


class _Javob:
    def __init__(self, body):
        self._b = body.encode("utf-8")

    def read(self, n=None):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


try:
    def _yopiq(*a, **k):
        raise OSError("connection refused")

    ar.urllib.request.urlopen = _yopiq
    _ishlayapti, _ = ar.tekshir("8000")
    check("javob yo'q -> ishga tushirish mumkin", _ishlayapti is False)
    check("main() 0 qaytaradi", ar.main() == 0)

    ar.urllib.request.urlopen = lambda *a, **k: _Javob(
        chr(123) + '"status": "ok", "warnings": [1, 2]' + chr(125))
    _ishlayapti, _taf = ar.tekshir("8000")
    check("javob bor -> ishlayapti deb aniqlanadi", _ishlayapti is True, _taf)
    check("tafsilotda holat ko'rsatiladi", "ok" in _taf, _taf)
    check("main() 1 qaytaradi (skript to'xtaydi)", ar.main() == 1)

    # DEGRADED (503): jarayon TIRIK, sozlamasi chala — baribir ikkinchi
    # nusxa ko'tarmaslik kerak
    def _503(*a, **k):
        raise ar.urllib.error.HTTPError("u", 503, "degraded", None, None)

    ar.urllib.request.urlopen = _503
    _ishlayapti, _taf = ar.tekshir("8000")
    check("DEGRADED (503) ham 'ishlayapti' hisoblanadi", _ishlayapti is True, _taf)

    ar.urllib.request.urlopen = lambda *a, **k: _Javob("bu json emas")
    _ishlayapti, _ = ar.tekshir("8000")
    check("buzuq javob ham tiriklik belgisi", _ishlayapti is True)
finally:
    ar.urllib.request.urlopen = _asl_open

print("[8] Skript qo'riqchini TO'G'RI ishlatadi")
_bat = open(os.path.join(ROOT, "ishga_tushirish.bat"), encoding="utf-8").read()
check("skript qo'riqchini chaqiradi", "already_running.py" in _bat)
# Farq ATAYLAB: tunnelsiz bot ishlayveradi (faqat ogohlantirish),
# ikkinchi nusxa esa zarar keltiradi (to'liq to'xtatish).
_keyin = _bat.split("already_running.py")[1][:200]
check("takroriy nusxa topilsa ishga tushirish TO'XTAYDI",
      "goto :allaqachon" in _keyin, _keyin[:80])
check("to'xtash sababi tushuntiriladi",
      ":allaqachon" in _bat and "TO'XTATILDI" in _bat)


print("[9] Nazoratchi — vaqtinchalik nosozlikdan tiklanish")
# Bot Telegram bilan aloqa uzilganda BUTUNLAY o'lib qolardi:
#     telegram.error.TimedOut -> exited with code 1
# Tarmoq nosozligi o'tkinchi, lekin jarayon o'lgani uchun xizmat
# nazoratsiz to'xtardi va buni faqat mijoz shikoyat qilganda bilinardi.
sys.path.insert(0, os.path.join(ROOT, "tools"))
import nazoratchi as nz  # noqa: E402

_asl_ishga = nz.ishga_tushir
_asl_kutish = nz.KUTISH
nz.KUTISH = [0, 0, 0, 0, 0]   # sinov tez bo'lsin
try:
    # Normal to'xtash (Ctrl+C yoki toza chiqish) — qayta urinmaydi
    _n = {"soni": 0}

    def _normal():
        _n["soni"] += 1
        return 0, 5.0

    nz.ishga_tushir = _normal
    check("normal to'xtashda qayta urinilmaydi",
          nz.main() == 0 and _n["soni"] == 1, _n)

    # Doim TEZ yiqilsa — sozlama xatosi, cheksiz aylanmaslik kerak
    _t = {"soni": 0}

    def _tez():
        _t["soni"] += 1
        return 1, 2.0

    nz.ishga_tushir = _tez
    _kod = nz.main()
    check("tez yiqilishlar CHEKLANADI (cheksiz aylanish yo'q)",
          _t["soni"] == nz.MAX_TEZ_YIQILISH, _t)
    check("sozlama xatosida nolga teng bo'lmagan kod", _kod == 1, _kod)

    # UZOQ ishlab keyin yiqilsa — o'tkinchi nosozlik, hisob TOZALANADI
    # va bot chegaradan ko'p marta tiklanaveradi
    _u = {"soni": 0}

    def _uzoq():
        _u["soni"] += 1
        if _u["soni"] >= 12:
            return 0, 100.0
        return 1, 300.0

    nz.ishga_tushir = _uzoq
    nz.main()
    check("uzoq ishlagandan keyingi yiqilish CHEGARAGA kirmaydi",
          _u["soni"] > nz.MAX_TEZ_YIQILISH, _u)
finally:
    nz.ishga_tushir = _asl_ishga
    nz.KUTISH = _asl_kutish

print("[10] Skript nazoratchi orqali ishga tushiradi")
_bat2 = open(os.path.join(ROOT, "ishga_tushirish.bat"), encoding="utf-8").read()
check("nazoratchi chaqiriladi", "nazoratchi.py" in _bat2)
check("bot.py TO'G'RIDAN-TO'G'RI chaqirilmaydi",
      "%PYEXE% bot.py" not in _bat2,
      "to'g'ridan-to'g'ri chaqirilsa TimedOut'da xizmat to'xtaydi")

print("[11] Skriptdagi HAMMA yo'l haqiqatan mavjud")
# Bu tekshiruv teskari slash buzilishini ushlaydi: heredoc orqali
# yozilganda "tools\tunnel_start.py" dagi \t TABULYATSIYAGA aylanib
# ketgan va qator jimgina buzilgan edi. Endi avtomatik ushlanadi.
import re as _re2
_yollar = _re2.findall(r'"(tools[\\\\/][A-Za-z_0-9]+\.py)"', _bat2)
check("skriptda kamida 4 ta vosita chaqiriladi", len(_yollar) >= 4, _yollar)
_yoq = [y for y in _yollar
        if not os.path.exists(os.path.join(ROOT, y.replace("\\", os.sep)))]
check("har bir yo'l mavjud faylga ishora qiladi", not _yoq, _yoq)
_tab = [l for l in _bat2.split("\n") if "\t" in l]
check("skriptda yashirin TAB yo'q (buzilgan yo'l belgisi)", not _tab, _tab[:2])
print("\nNatija: " + str(ok) + " pass, " + str(fail) + " fail")
sys.exit(1 if fail else 0)
