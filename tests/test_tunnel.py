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

print("\nNatija: " + str(ok) + " pass, " + str(fail) + " fail")
sys.exit(1 if fail else 0)
