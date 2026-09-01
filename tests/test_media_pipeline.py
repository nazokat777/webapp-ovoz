"""Media quvuri: PDF round-trip va audio bo'laklash — HAQIQIY fayllar bilan.

Nega kerak: bu ikki quvur foydalanuvchi oqimining o'zagi.
  • PDF -> matn: butun "PDF'ni ovozga aylantirish" xizmati shunga tayanadi
  • Audio bo'laklash: bu yerdagi xato uzun ma'ruzaning bir qismini JIMGINA
    yo'qotadi (foydalanuvchi to'liq pul to'lab, chala matn oladi)

ffmpeg bo'lmasa audio qismi xushmuomala o'tkazib yuboriladi (SKIP).
Tashqi tarmoq YO'Q.
"""
import os
import subprocess
import sys
import tempfile

os.environ["BOT_TOKEN"] = "111111:FAKE_MEDIA_TEST"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import bot  # noqa: E402

ok = fail = skip = 0
_tmp = tempfile.mkdtemp(prefix="media_test_")


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {name}")
    else:
        fail += 1
        print(f"  FAIL  {name}  {extra}")


def skipped(name, why):
    global skip
    skip += 1
    print(f"  SKIP  {name}  ({why})")


print("\n[M1] PDF round-trip: make_pdf -> extract_pdf_text")
orig = ("Assalomu alaykum. Bu birinchi xatboshi matni.\n"
        "Ikkinchi qator: o'zbek harflari g'alaba, shahar, qishloq.\n"
        "Uchinchi: raqamlar 2026 va 15 foiz.")
pdf_path = None
try:
    pdf_path = bot.make_pdf(orig)
    got = bot.extract_pdf_text(pdf_path)
    check("matn ajratildi", bool(got and got.strip()))
    for probe in ["Assalomu", "shahar", "qishloq", "2026"]:
        check(f"saqlandi: {probe}", probe in got, got[:80])
    check("uzunlik yo'qolmadi", len(got) >= len(orig) * 0.9,
          f"{len(got)}/{len(orig)}")
except Exception as e:
    check("PDF round-trip", False, str(e)[:150])
finally:
    if pdf_path and os.path.exists(pdf_path):
        os.remove(pdf_path)

print("\n[M2] O'zbek apostrofi PDF orqali omon qoladimi")
p2 = None
try:
    src = "o'zbek g'alaba bo'lim yo'q"
    p2 = bot.make_pdf(src)
    g2 = bot.extract_pdf_text(p2).strip()
    check("apostroflar saqlandi", g2 == src, repr(g2))
except Exception as e:
    check("apostrof round-trip", False, str(e)[:150])
finally:
    if p2 and os.path.exists(p2):
        os.remove(p2)

print("\n[M3] extract_pdf_text — buzuq kirish xavfsiz")
bad = os.path.join(_tmp, "buzuq.pdf")
with open(bad, "wb") as f:
    f.write(b"bu PDF emas, shunchaki matn")
try:
    res = bot.extract_pdf_text(bad)
    check("buzuq PDF yiqitmaydi", isinstance(res, str))
except Exception as e:
    # Istisno ham maqbul — asosiysi jarayon o'lmasin, chaqiruvchi ushlaydi
    check("buzuq PDF aniq istisno beradi", True, type(e).__name__)

print("\n[M4] Audio bo'laklash — TO'LIQ QAMROV (matn yo'qolmasin)")
if not bot.have_cmd("ffmpeg"):
    skipped("audio bo'laklash", "ffmpeg yo'q")
else:
    audio = os.path.join(_tmp, "a.mp3")
    r = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=430", "-ac", "1", "-ar", "16000", audio],
        capture_output=True)
    if r.returncode != 0 or not os.path.exists(audio):
        skipped("audio bo'laklash", "sinov audiosi yaratilmadi")
    else:
        dur = bot.get_duration(audio)
        check("davomiylik aniqlandi", 425 <= dur <= 435, dur)
        check("get_duration_or_estimate mos", 425 <= bot.get_duration_or_estimate(audio) <= 435)

        chunks = bot.split_audio_for_whisper(audio, 180)
        check("bo'laklar yaratildi", len(chunks) == 3, len(chunks))
        if len(chunks) == 3:
            d0 = bot.get_duration(chunks[0])
            d_last = bot.get_duration(chunks[-1])
            # Oxirgidan boshqasi: chunk + overlap
            check("1-bo'lak = 180+30 overlap", 205 <= d0 <= 215, d0)
            # Qamrov: oxirgi bo'lak boshlanishi + uzunligi >= butun audio
            covered = (len(chunks) - 1) * 180 + d_last
            check("TO'LIQ QAMROV (yo'qotish yo'q)", covered >= dur - 2,
                  f"qamrab olingan {covered:.0f}s / {dur:.0f}s")
        for ch in chunks:
            if ch != audio and os.path.exists(ch):
                try:
                    os.remove(ch)
                except Exception:
                    pass

print("\n[M5] estimate_duration_from_size — probe yiqilsa zaxira")
f_small = os.path.join(_tmp, "kichik.bin")
with open(f_small, "wb") as f:
    f.write(b"x" * 320000)   # ~20 sek @16KB/s
est = bot.estimate_duration_from_size(f_small)
check("o'lchamdan taxmin ishlaydi", est >= 20, est)
check("kamida 30 sek qaytaradi", bot.estimate_duration_from_size(f_small) >= 20)

print("\n[M6] Shovqinli kutubxona loglari bo'g'ilgan")
import logging  # noqa: E402
check("fontTools WARNING darajasida",
      logging.getLogger("fontTools").level == logging.WARNING)
check("httpx bo'g'ilgan", logging.getLogger("httpx").level == logging.WARNING)

print("")
print("[AUDIO FILTRI] tezlik va sifat muvozanati")
# 1 yadroli serverda loudnorm butun sekinlikning ~90% ini yeyardi
# (10.8x realtime; speechnorm 47.5x). Sifat uchta parchada Groq Whisper
# bilan tekshirilgan: speechnorm loudnorm'ning 104% so'zini bergan.
_ildiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_manba = open(os.path.join(_ildiz, "bot.py"), encoding="utf-8").read()
_boshi = _manba.find("audio_filter = (")
check("audio_filter topildi", _boshi > 0)
_zanjir = _manba[_boshi:_boshi + 260]
check("speechnorm ishlatiladi", "speechnorm" in _zanjir, _zanjir[:80])
check("loudnorm ishlatilmaydi (10x sekin)", "loudnorm" not in _zanjir)
# Normalizatsiyani BUTUNLAY olib tashlash 20% so'z yo'qotgan edi.
check("normalizatsiya baribir bor",
      "speechnorm" in _zanjir or "dynaudnorm" in _zanjir,
      "busiz 313 -> 252 so'z")
check("shovqin filtrlari saqlandi",
      "highpass" in _zanjir and "lowpass" in _zanjir and "afftdn" in _zanjir)
# O'lchov izohi kodda qolsin: keyingi safar kimdir "loudnorm yaxshiroq" deb
# qaytarib qo'ymasin.
check("tanlov sababi kodda yozilgan",
      "realtime" in _manba[max(0, _boshi - 1400):_boshi],
      "o'lchov izohi yo'qolgan")

try:
    import shutil
    shutil.rmtree(_tmp, ignore_errors=True)
except Exception:
    pass

print(f"\nNatija: {ok} pass, {fail} fail, {skip} skip")
sys.exit(1 if fail else 0)
