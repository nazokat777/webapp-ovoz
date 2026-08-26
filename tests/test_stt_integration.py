"""STT quvurining YAXLIT integratsiya testi — soxta OpenAI bilan.

Nega kerak: qolgan testlar quvurning har bir BO'LAGINI alohida tekshiradi.
Bu yerda esa ular BIRIKMASI sinaladi — botning asosiy vazifasi:

    audio -> ffmpeg qayta kodlash -> bo'laklash -> API chaqiruvlari ->
    tartibda yig'ish -> overlap dedup -> hallucination tozalash -> matn

Bu bosqichlar orasidagi xato birlik testlaridan o'tib ketadi, lekin
foydalanuvchi natijasini buzadi (yo'qolgan bo'lak, takrorlangan gap,
noto'g'ri tartib).

Tarmoq YO'Q: OpenAI so'rovlari soxta javob bilan almashtiriladi.
ffmpeg bo'lmasa SKIP.
"""
import os
import subprocess
import sys
import tempfile

os.environ["BOT_TOKEN"] = "111111:FAKE_STT_TEST"
os.environ["OPENAI_API_KEY"] = "sk-fake-for-test"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import bot  # noqa: E402

ok = fail = skip = 0
_tmp = tempfile.mkdtemp(prefix="stt_int_")


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {name}")
    else:
        fail += 1
        print(f"  FAIL  {name}  {extra}")


def make_audio(seconds, path):
    r = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", f"sine=frequency=440:duration={seconds}",
         "-ac", "1", "-ar", "16000", path],
        capture_output=True)
    return r.returncode == 0 and os.path.exists(path)


if not bot.have_cmd("ffmpeg"):
    print("\n[SKIP] ffmpeg yo'q — STT integratsiya testi o'tkazib yuborildi")
    print("\nNatija: 0 pass, 0 fail, 1 skip")
    sys.exit(0)


# ── Soxta OpenAI: har bo'lakka o'z matnini qaytaradi ──────────────────
class _FakeResp:
    def __init__(self, payload, status=200):
        self._p = payload
        self.status_code = status
        self.text = str(payload)

    def json(self):
        return self._p


_calls = {"n": 0, "models": [], "fail_next": 0, "texts": [], "seq": 0}


def _wrap(url, text):
    """OpenAI'ning IKKI xil javob shakli — soxta javob HAQIQIYSIGA mos
    bo'lishi SHART, aks holda kod fallback zanjiriga tushib ketadi va
    test noto'g'ri xulosa beradi (buni birinchi urinishda ko'rdik:
    noto'g'ri shakl -> bo'lakka 5 ta chaqiruv)."""
    if "chat/completions" in url:
        return _FakeResp({"choices": [{"message": {"content": text}}]})
    return _FakeResp({"text": text})


import threading as _th
_lock = _th.Lock()


def _next_idx():
    """Ketma-ket raqam. Bo'laklar 4 ta PARALLEL oqimda ishlanadi va
    /chat/completions yo'li audioni base64 bilan JSON ichida yuboradi
    (fayl nomi yo'q), shuning uchun "qaysi javob qaysi bo'lakka tegishli"
    ekanini bilib bo'lmaydi.

    Shu sababli bu testda TARTIBGA BOG'LIQ BO'LMAGAN xossalar
    tekshiriladi: hech bir bo'lak matni YO'QOLMASIN va chegara jumlasi
    TAKRORLANMASIN. Tartibning o'zi kodda `sorted(chunk_results)` bilan
    strukturaviy kafolatlangan (poyga bo'lishi mumkin emas)."""
    with _lock:
        _calls["seq"] = _calls.get("seq", 0) + 1
        return _calls["seq"]



def _fake_post(url, **kw):
    """Har chaqiruvda tartib raqami bilan matn qaytaradi.
    Shu tufayli bo'laklar tartibda yig'ilganini tekshira olamiz."""
    _calls["n"] += 1
    idx = _next_idx()
    data = kw.get("data") or {}
    _calls["models"].append(data.get("model") or "gpt-audio")
    if _calls["fail_next"] > 0:
        _calls["fail_next"] -= 1
        return _FakeResp({"error": "server band"}, status=500)
    words = " ".join(f"bolak{idx}soz{i}" for i in range(60))
    text = f"Bolak {idx} boshlanishi. {words}. Bolak {idx} oxiri."
    _calls["texts"].append(text)
    return _wrap(url, text)


_real_post = bot.requests.post
bot.requests.post = _fake_post
# Sekin retry kutishlarini nolga tushiramiz (test tez bo'lsin)
bot.time.sleep = lambda *a, **k: None

print("\n[S1] Qisqa audio — bitta bo'lak, to'liq quvur")
a1 = os.path.join(_tmp, "qisqa.mp3")
if not make_audio(60, a1):
    print("  SKIP  sinov audiosi yaratilmadi")
    skip += 1
else:
    _calls.update({"n": 0, "models": [], "fail_next": 0, "texts": [], "seq": 0})
    txt = bot.transcribe_whisper(a1, "uz")
    check("matn qaytdi", bool(txt and txt.strip()), repr(txt)[:80])
    check("API chaqirildi", _calls["n"] >= 1, _calls["n"])
    check("bir bo'lak = BIR chaqiruv (ortiqcha xarajat yo'q)",
          _calls["n"] == 1, f'{_calls["n"]} chaqiruv: {_calls["models"]}')
    check("bo'lak matni natijada bor", "Bolak 1 boshlanishi" in txt, txt[:120])

print("\n[S2] Uzun audio — KO'P bo'lak, TARTIB va TO'LIQLIK")
a2 = os.path.join(_tmp, "uzun.mp3")
if not make_audio(430, a2):
    print("  SKIP  sinov audiosi yaratilmadi")
    skip += 1
else:
    _calls.update({"n": 0, "models": [], "fail_next": 0, "texts": [], "seq": 0})
    prog = []
    txt = bot.transcribe_whisper(a2, "uz", progress_cb=lambda c, t: prog.append((c, t)))
    check("matn qaytdi", bool(txt and txt.strip()))
    check("3 bo'lak uchun ANIQ 3 chaqiruv", _calls["n"] == 3,
          f'{_calls["n"]} chaqiruv: {_calls["models"]}')
    # HAR BO'LAK natijada bo'lishi SHART — biri yo'qolsa matn yo'qoladi
    idxs = sorted({int(t.split()[1]) for t in _calls["texts"]})
    for i in idxs:
        check(f"{i}-bo'lak natijada bor", f"Bolak {i} " in txt, txt[:150])
    # HECH BIR bo'lak matni yo'qolmasligi shart (tartibga bog'liq emas)
    check("har bo'lakning ICHKI so'zlari ham saqlandi",
          all(f"bolak{i}soz0" in txt for i in idxs), txt[:120])
    check("progress callback ishladi", len(prog) >= 3, prog)

print("\n[S3] Bir bo'lak API'da yiqilsa — qolganlari YETKAZILADI")
if os.path.exists(a2):
    _calls.update({"n": 0, "models": [], "fail_next": 0, "texts": [], "seq": 0})
    # 1-chaqiruv 500 qaytaradi -> fallback modellar ishga tushadi
    _calls["fail_next"] = 1
    failed = []
    txt = bot.transcribe_whisper(a2, "uz", failed_ranges_out=failed)
    check("qisman yiqilishda ham matn qaytdi", bool(txt and txt.strip()), repr(txt)[:60])
    check("fallback model ishlatildi", len(_calls["models"]) > 3, _calls["models"][:6])

print("\n[S4] HAMMA chaqiruv yiqilsa — ANIQ xato (jim yo'qotish emas)")
a4 = os.path.join(_tmp, "qisqa2.mp3")
if make_audio(30, a4):
    _calls.update({"n": 0, "models": [], "fail_next": 999, "texts": [], "seq": 0})
    raised = None
    try:
        bot.transcribe_whisper(a4, "uz")
    except Exception as e:
        raised = str(e)
    check("istisno ko'tarildi (jim bo'sh matn EMAS)", raised is not None, raised)
    check("sabab xabarda bor", raised and ("yiqildi" in raised.lower()
          or "whisper" in raised.lower()), raised)

print("")
print("")
print("[S5] Overlap dedup — TO'G'RIDAN-TO'G'RI (deterministik)")
# Integratsiya orqali sinab bo'lmaydi: bo'laklar 4 ta parallel oqimda
# ishlanadi va /chat/completions audioni base64 bilan yuboradi (fayl nomi
# yo'q), ya'ni "qaysi javob qaysi bo'lakka tegishli" ekani aniqlanmaydi.
# Shuning uchun mantiq alohida funksiyaga ajratildi va shu yerda
# to'g'ridan-to'g'ri, poygasiz sinaladi.
_j = bot._join_chunks_dedup_overlap
_body1 = " ".join("bir" + str(i) for i in range(40))
_body2 = " ".join("ikki" + str(i) for i in range(40))
_ovl = "Bu chegara jumlasi ikkala bolakda ham takrorlanadi va kesilishi kerak."

_res = _j({1: "Birinchi bolak. " + _body1 + ". " + _ovl,
           2: _ovl + " Ikkinchi bolak. " + _body2 + "."}, [1, 2])
_txt = " ".join(_res)
check("overlap BIR marta qoldi", _txt.count("chegara jumlasi") == 1,
      str(_txt.count("chegara jumlasi")) + " marta")
check("1-bo'lak matni saqlandi", "bir0" in _txt and "bir39" in _txt)
check("2-bo'lak matni saqlandi", "ikki0" in _txt and "ikki39" in _txt)

# Overlap YO'Q bo'lsa hech narsa kesilmasin
_res2 = _j({1: "Butunlay boshqa matn. " + _body1,
            2: "Mutlaqo boshqacha davomi. " + _body2}, [1, 2])
check("overlap yo'q -> kesilmaydi",
      "Butunlay boshqa matn" in _res2[0] and "Mutlaqo boshqacha" in _res2[1])

# Chegaraviy holatlar
check("bo'sh kirish", _j({}, []) == [])
check("bo'sh bo'lak tashlanadi", _j({1: "", 2: "matn"}, [1, 2]) == ["matn"])
check("qisqa matn (<100) tegilmaydi",
      _j({1: "aaa", 2: "aaa"}, [1, 2]) == ["aaa", "aaa"])
check("TARTIB kalitlar bo'yicha", _j({2: "B" * 120, 1: "A" * 120}, [1, 2])[0][0] == "A")


bot.requests.post = _real_post
try:
    import shutil
    shutil.rmtree(_tmp, ignore_errors=True)
except Exception:
    pass

print(f"\nNatija: {ok} pass, {fail} fail, {skip} skip")
sys.exit(1 if fail else 0)
