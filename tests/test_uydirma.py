"""WHISPER UYDIRMALARI — sukunatda o'ylab topilgan iboralarni tozalash.

AMALDA BO'LGAN XATO (2026-09-01): 43 daqiqalik YouTube videosi matnida
"Subtitrlarni DimaTorzok tayyorladi" iborasi O'NLAB marta chiqdi, ba'zi
vaqt belgilari esa bo'sh qoldi. Videoda bunday gap umuman yo'q — bu
Whisper'ning sukunat va musiqa joylarida qaytaradigan yodlangan iborasi.

Uch sabab bor edi:
  1. Ro'yxatda faqat "субтитры создавал" bor edi; "сделал", "делал",
     "подготовил" variantlari o'tib ketardi
  2. Filtr FAQAT tarjimadan oldin ishlardi — o'zbekchaga aylangan uydirma
     umuman tekshirilmasdi
  3. Uydirma o'chgach vaqt belgisi yolg'iz qolib, PDF'da bo'sh qator
     bo'lib chiqardi

Tarmoq talab qilinmaydi.
"""
import os
import sys

os.environ["BOT_TOKEN"] = "111111:FAKE_UYD"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

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
        print("  PASS  " + name)
    else:
        fail += 1
        print("  FAIL  " + name + "  " + str(extra))


print("[1] UYDIRMA VARIANTLARI — hammasi o'chishi kerak")
# Whisper bir xil uydirmani o'nlab shaklda beradi; ro'yxat yetarli emas edi.
for xom in [
    "Субтитры создавал DimaTorzok",
    "Субтитры сделал DimaTorzok",
    "Субтитры делал DimaTorzok",
    "Субтитры подготовил DimaTorzok",
    "Редактор субтитров А.Иванов",
    "Продолжение следует.",
    "Спасибо за просмотр!",
    "Subtitles by the Amara.org community",
    # Tarjimadan KEYINGI shakllari — ilgari bular umuman tekshirilmasdi
    "Subtitrlarni DimaTorzok tayyorladi",
    "Subtitrlar DimaTorzok tomonidan tayyorlandi",
    "DimaTorzok",
]:
    natija = bot._strip_whisper_boilerplate(xom)
    check("o'chdi: " + xom[:42], natija.strip() == "", repr(natija))

print("[2] HAQIQIY MATN SAQLANADI")
# Eng yomon natija — uydirma bilan birga haqiqiy gapni ham o'chirish.
haqiqiy = [
    "Bugun biz sun'iy intellekt agentlari haqida gaplashamiz.",
    "Obsidian bu oddiy desktop dastur. U nima sodir bo'layotganini ko'rsatadi.",
    "Videoga subtitr qo'shish uchun maxsus dastur kerak bo'ladi va biz "
    "buni keyingi darsda batafsil ko'rib chiqamiz.",
    "Продолжение этого проекта мы обсудим отдельно.",
    # Bu ikkitasi naqsh juda keng bo'lganda kesilib ketgan edi
    "Videoni ko'rganingiz uchun rahmat aytamiz va darsni davom ettiramiz.",
    "Kanalga obuna bo'ling degan gapni ustoz aytdilar va dars davom etdi.",
]
for matn in haqiqiy:
    natija = bot._strip_whisper_boilerplate(matn)
    check("saqlandi: " + matn[:42], natija.strip() == matn.strip(), repr(natija))

print("[3] GAP ORTIDAN YOPISHGAN UYDIRMA")
# PDF'dagi haqiqiy holat: uydirma haqiqiy gapning ortidan kelgan.
xom = ("Obsidian buni shunchaki bema'nilik deb hisoblaydi. "
       "Subtitrlarni DimaTorzok tayyorladi")
natija = bot._strip_whisper_boilerplate(xom)
check("uydirma qismi o'chdi", "DimaTorzok" not in natija, natija)
check("haqiqiy gap qoldi", "bema'nilik" in natija, natija)

print("[3b] REGRESSIYA (2026-09-02, jonli logdan): butun gap o'chib ketardi")
# Uydirma haqiqiy gapga NUQTASIZ yopishib kelganda butun parcha bitta
# bo'lak sanalib, DARSNING MAZMUNI uydirma bilan birga o'chgan edi.
xom = ("Имам Раббани говорит, что сила, Субтитры делал DimaTorzok")
natija = bot._strip_whisper_boilerplate(xom)
check("uydirma o'chdi (yopishgan)", "DimaTorzok" not in natija, natija)
check("DARS MAZMUNI SAQLANDI (regressiya edi!)",
      "Имам Раббани говорит" in natija, repr(natija))

xom = ("Субтитры делал DimaTorzok [06:59] Субтитры делал DimaTorzok "
       "[07:29] Я был муридом для человека, который назывался Абдул-Азиз.")
natija = bot.yakuniy_tozalash(xom)
check("ketma-ket uydirmalar o'chdi", "DimaTorzok" not in natija, natija)
check("haqiqiy gap saqlandi", "Я был муридом" in natija, repr(natija))
check("gap oldidagi [07:29] belgisi ham saqlandi", "[07:29]" in natija, natija)
check("bo'shab qolgan [06:59] o'chdi", "[06:59]" not in natija, natija)

# Kesikdan keyin qoldiq harf qolmasin ("Субтитры сдела" kesilib "л" qolishi)
xom = "Субтитры сделал DimaTorzok"
natija = bot._strip_whisper_boilerplate(xom)
check("kesikdan qoldiq harf qolmadi", natija.strip() in ("",), repr(natija))

print("[4] YOLG'IZ VAQT BELGILARI")
xom = "[00:00] Salom dunyo. [04:30] [05:10] Davom etamiz. [07:00]"
natija = bot._yolgiz_vaqt_belgilarini_olib_tashla(xom)
check("bo'sh [04:30] o'chdi", "[04:30]" not in natija, natija)
check("bo'sh [07:00] o'chdi", "[07:00]" not in natija, natija)
check("matnli [00:00] qoldi", "[00:00]" in natija, natija)
check("matnli [05:10] qoldi", "[05:10]" in natija, natija)
check("matn buzilmadi",
      "Salom dunyo." in natija and "Davom etamiz." in natija, natija)
check("bo'sh matnda yiqilmaydi",
      bot._yolgiz_vaqt_belgilarini_olib_tashla("") == "")

print("[5] YAKUNIY TOZALASH — ikkalasi birga")
xom = ("[00:00] Salom, do'stlar. Subtitrlarni DimaTorzok tayyorladi\n"
       "[00:54] Subtitrlarni DimaTorzok tayyorladi\n"
       "[01:24] Bugun blog haqida gaplashamiz.")
natija = bot.yakuniy_tozalash(xom)
check("uydirma yo'q", "DimaTorzok" not in natija, natija)
check("bo'shab qolgan [00:54] ham o'chdi", "[00:54]" not in natija, natija)
check("haqiqiy matn butun",
      "Salom, do'stlar." in natija and "blog haqida" in natija, natija)

print("[6] BARCHA YETKAZISH YO'LLARI TOZALANADI")
# Ilgari filtr faqat Whisper natijasiga qo'llanardi. ensure_uzbek_text
# ichida 5 ta return yo'li bor — bittasi unutilsa xato qaytadi.
_asl = bot._ensure_uzbek_text_ichki
try:
    iflos = "[00:00] Matn bor. Subtitrlarni DimaTorzok tayyorladi\n[09:99]"
    bot._ensure_uzbek_text_ichki = lambda u, t, n=True: iflos
    natija = bot.ensure_uzbek_text(1, "kirish", notify=False)
    check("o'ram tozalashni qo'llaydi", "DimaTorzok" not in natija, natija)
    check("matn saqlandi", "Matn bor." in natija, natija)

    bot._ensure_uzbek_text_ichki = lambda u, t, n=True: ""
    check("bo'sh natijada yiqilmaydi",
          bot.ensure_uzbek_text(1, "x", notify=False) == "")

    bot._ensure_uzbek_text_ichki = lambda u, t, n=True: None
    check("None natijada yiqilmaydi",
          bot.ensure_uzbek_text(1, "x", notify=False) is None)
finally:
    bot._ensure_uzbek_text_ichki = _asl

with open(os.path.join(ROOT, "bot.py"), encoding="utf-8") as f:
    manba = f.read()
check("ensure_uzbek_text yakuniy_tozalash orqali qaytaradi",
      "return yakuniy_tozalash(_ensure_uzbek_text_ichki(" in manba)

print(f"\nJami: {ok} PASS, {fail} FAIL")
sys.exit(1 if fail else 0)
