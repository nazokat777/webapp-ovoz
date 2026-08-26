"""Matn qayta ishlash quvuri — sof funksiyalar testi.

Nega kerak: qolgan testlar infratuzilmani (auth, navbat, billing) tekshiradi.
Bu yerdagi funksiyalar esa HAR BIR foydalanuvchi natijasiga bevosita ta'sir
qiladi — ulardagi xato jimgina har bir transkript va PDF'ni buzadi.
Tarmoq YO'Q: hammasi sof funksiyalar.
"""
import os
import sys

os.environ["BOT_TOKEN"] = "111111:FAKE_TEXT_TEST"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

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


c = bot.convert_latin_to_cyrillic

print("\n[T1] Lotin -> Kirill: asosiy qoidalar")
for latin, cyr in [
    ("salom", "салом"),
    ("o'zbek", "ўзбек"),
    ("g'alaba", "ғалаба"),
    ("yo'q", "йўқ"),
    ("shahar", "шаҳар"),
    ("choy", "чой"),
    ("yozuv", "ёзув"),
    ("yulduz", "юлдуз"),
    ("yaxshi", "яхши"),
    ("qishloq", "қишлоқ"),
    ("Xurshid", "Хуршид"),
    ("tsement", "цемент"),
]:
    got = c(latin)
    check(f"{latin} -> {cyr}", got == cyr, f"oldi: {got}")

print("\n[T2] 'e' qoidasi va bosh harflar")
check("so'z boshida e -> э", c("eshik") == "эшик", c("eshik"))
check("so'z ichida e -> е", c("kel") == "кел", c("kel"))
check("bosh harf digraf", c("Shahar") == "Шаҳар", c("Shahar"))
check("BOSH HARF digraf", c("SHAHAR") == "ШАҲАР", c("SHAHAR"))

print("\n[T3] Tegilmasligi kerak bo'lganlar")
check("raqamlar", "2026" in c("2026-yil"), c("2026-yil"))
check("tinish belgilari", c("a, b!") .endswith("!"), c("a, b!"))
check("allaqachon kirill o'zgarmaydi", c("Салом дунё") == "Салом дунё")
check("bo'sh matn", c("") == "")
check("faqat probel", c("   ") == "   ")
check("[?] markeri saqlanadi", "[?]" in c("so'z[?] keyin"), c("so'z[?] keyin"))

print("\n[T4] HAVOLA/EMAIL himoyasi (transliteratsiya ularni buzardi)")
cases = [
    "https://youtu.be/aBc_123",
    "http://example.com/path?a=1",
    "www.example.uz",
    "test@mail.ru",
    "@Nazokat_571",
    "#darslik",
    "hujjat.pdf",
    "audio.mp3",
]
for tok in cases:
    got = c(f"matn {tok} davomi")
    check(f"saqlandi: {tok}", tok in got, f"oldi: {got}")

check("havola atrofidagi matn TARJIMA qilinadi",
      c("https://a.uz saytini oching").endswith("сайтини очинг"),
      c("https://a.uz saytini oching"))
check("bir nechta havola", c("a https://x.uz b https://y.uz c").count("https://") == 2,
      c("a https://x.uz b https://y.uz c"))

print("\n[T5] Idempotentlik (ikki marta o'tsa buzilmasin)")
for t in ["o'zbek tili", "https://a.uz salom", "test@mail.ru bor", "Салом"]:
    check(f"barqaror: {t[:22]}", c(c(t)) == c(t), f"{c(t)!r} != {c(c(t))!r}")

print("\n[T6] _normalize_uzbek_apostrophes")
n = bot._normalize_uzbek_apostrophes
check("backtick -> apostrof", n("o`zbek") == "o'zbek", n("o`zbek"))
check("g` -> g'", n("g`alaba") == "g'alaba", n("g`alaba"))
check("bo'sh xavfsiz", n("") == "")

print("\n[T7] _merge_failed_ranges / _format_time_range")
mr = bot._merge_failed_ranges
check("qo'shni oraliqlar birlashadi", len(mr([(0, 10, "e"), (10, 20, "e")])) == 1,
      mr([(0, 10, "e"), (10, 20, "e")]))
check("uzoq oraliqlar alohida", len(mr([(0, 10, "e"), (100, 110, "e")])) == 2)
check("bo'sh -> bo'sh", mr([]) == [])
ft = bot._format_time_range
check("vaqt formati", ":" in ft(65, 130), ft(65, 130))

print("\n[T8] _is_output_quality_acceptable")
q = bot._is_output_quality_acceptable
check("bo'sh matn rad", q("", 60) is False)
check("juda qisqa rad", q("salom", 60) is False)
good = " ".join(f"soz{i}" for i in range(200))
check("normal matn qabul", q(good, 60) is True)
check("bitta so'z takrori rad", q("salom " * 200, 600) is False)
check("5 daq audio uchun juda kam so'z rad",
      q(" ".join(f"w{i}" for i in range(20)), 600) is False)

print("\n[T9] _unclear_marker_note / _quick_quality_label")
check("[?] sanaladi", "3 ta [?]" in bot._unclear_marker_note("a[?] b[?] c[?]"))
check("[?] yo'q -> bo'sh", bot._unclear_marker_note("toza") == "")

print("\n[T10] detect_lang")
d = bot.detect_lang
check("kirill -> ru", d("Привет как дела друзья мои") == "ru", d("Привет как дела друзья мои"))
check("o'zbek belgilari -> uz", d("o'zbek tili shirin") == "uz")
check("bo'sh -> uz", d("") == "uz")

print("\n[T11] make_pdf — haqiqiy PDF yasaladi")
pdf_path = None
try:
    pdf_path = bot.make_pdf("Salom dunyo. O'zbek matni: g'alaba, shahar.")
    check("PDF fayli yaratildi", pdf_path and os.path.exists(pdf_path))
    size = os.path.getsize(pdf_path) if pdf_path else 0
    check("PDF bo'sh emas", size > 500, f"{size} bayt")
    with open(pdf_path, "rb") as f:
        head = f.read(5)
    check("to'g'ri PDF sarlavhasi", head == b"%PDF-", head)
    cyr = bot.make_pdf(c("Salom dunyo"), title="Kirill")
    check("kirill PDF ham yaratildi", cyr and os.path.getsize(cyr) > 500)
    for _p in (pdf_path, cyr):
        try:
            os.remove(_p)
        except Exception:
            pass
except Exception as e:
    check("make_pdf ishladi", False, str(e)[:150])


print("[T12] Whisper shablon artefaktlari (bir marta chiqadi, takror emas)")
_real = ("Assalomu alaykum. Bugungi darsimizda Imom Buxoriy hazratlarining "
         "hayotlari haqida gaplashamiz. U kishi 810-yilda tug'ilganlar.")
for junk in ["Subtitles by the Amara.org community", "Thanks for watching!",
             "Thank you for watching.",
             "Продолжение следует...",
             "Спасибо за просмотр!"]:
    out = bot._clean_whisper_hallucination(_real + " " + junk)
    check("olib tashlandi: " + junk[:34],
          junk.rstrip(".!").lower() not in out.lower(), out[-70:])
    check("asl matn saqlandi: " + junk[:22], "Imom Buxoriy" in out)
print("")
print("[T13] Shablon filtri QONUNIY matnni o'chirmasin")
for t in [
    "Videoni ko'rganingiz uchun rahmat aytamiz va darsni davom ettiramiz bugun.",
    "Kanalga obuna bo'ling degan gapni ustoz aytdilar va dars davom etdi shunda.",
    "Bugun biz translated by iborasining ma'nosini o'rganamiz va misol ko'ramiz.",
]:
    full = t + " " + _real
    out = bot._clean_whisper_hallucination(full)
    check("saqlandi: " + t[:40], len(out) >= len(full) * 0.95, str(len(out)) + "/" + str(len(full)))
print("")
print("[T14] _dedupe_repeated_words — qonuniy takror saqlanadi")
for name, t in [("diniy zikr", "Allohu akbar Allohu akbar Allohu akbar"),
                ("ta'kid", "juda juda muhim"),
                ("sanoq", "bir ikki uch bir ikki uch")]:
    out = bot._dedupe_repeated_words(t)
    check(name + " tegilmadi", len(out.split()) == len(t.split()),
          str(len(t.split())) + " -> " + str(len(out.split())))
check("haqiqiy hallucination kesiladi",
      len(bot._dedupe_repeated_words("salom " * 40).split()) <= 5)
print("")
print("[T15] _is_chunk_hallucinated — haqiqiy matn tashlanmasin")
check("ma'ruza matni saqlanadi", bot._is_chunk_hallucinated(_real, 600) is False)
check("qisqa haqiqiy gap saqlanadi",
      bot._is_chunk_hallucinated("Hozir tanaffus qilamiz.", 600) is False)
check("uzun haqiqiy matn saqlanadi",
      bot._is_chunk_hallucinated(" ".join("soz" + str(i) for i in range(300)), 600) is False)
check("bir so'z 40 marta -> hallucination",
      bot._is_chunk_hallucinated("salom " * 40, 600) is True)
print("")
print(f"\nNatija: {ok} pass, {fail} fail")
sys.exit(1 if fail else 0)
