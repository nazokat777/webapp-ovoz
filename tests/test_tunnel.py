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


print("\nNatija: " + str(ok) + " pass, " + str(fail) + " fail")
sys.exit(1 if fail else 0)
