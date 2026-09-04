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

print("[4b] YONMA-YON TAKROR GAPLAR (overlap ulash joyidan)")
# PDF'da ko'rildi (2026-09-02): bo'laklar 30s ustma-ust bilan ulanganda
# bitta gap ikki marta chiqib qolgan.
xom = ("Biz sizning huzurimizga kelganingizdan juda xursandmiz. "
       "Biz sizning huzurimizga kelganingizdan juda xursandmiz. "
       "Dars davom etadi.")
natija = bot._yonma_yon_takror_gaplarni_yig(xom)
check("aynan takror gap bittaga tushdi",
      natija.count("huzurimizga kelganingizdan") == 1, natija)
check("keyingi gap saqlandi", "Dars davom etadi." in natija, natija)

# Vaqt belgisi bilan boshlangan nusxa ham taniladi
xom = ("Bugun muhim mavzuni boshlaymiz, e'tibor bering. "
       "[03:30] Bugun muhim mavzuni boshlaymiz, e'tibor bering.")
natija = bot._yonma_yon_takror_gaplarni_yig(xom)
check("vaqt belgili nusxa ham yig'ildi",
      natija.count("muhim mavzuni boshlaymiz") == 1, natija)

# HIMOYA: qisqa zikr va ta'kid takrorlari qonuniy — tegilmaydi
for saqlanishi_kerak in [
    "Allohu akbar. Allohu akbar. Allohu akbar.",
    "Yo'q. Yo'q. Bu boshqa masala.",
]:
    natija = bot._yonma_yon_takror_gaplarni_yig(saqlanishi_kerak)
    check("qisqa takror saqlandi: " + saqlanishi_kerak[:26],
          natija.strip() == saqlanishi_kerak.strip(), natija)

# HIMOYA: biroz FARQLI gaplar ta'kid bo'lishi mumkin — tegilmaydi
xom = ("Bugun biz ta'limni o'zgartirish haqida gapiramiz albatta. "
       "Bugun biz ta'limni o'zgartirish haqida gapirib beramiz albatta.")
natija = bot._yonma_yon_takror_gaplarni_yig(xom)
check("biroz farqli gaplar TEGILMAYDI",
      natija.strip() == xom.strip(), natija)
check("bo'sh matnda yiqilmaydi", bot._yonma_yon_takror_gaplarni_yig("") == "")

print("[5] YAKUNIY TOZALASH — ikkalasi birga")
xom = ("[00:00] Salom, do'stlar. Subtitrlarni DimaTorzok tayyorladi\n"
       "[00:54] Subtitrlarni DimaTorzok tayyorladi\n"
       "[01:24] Bugun blog haqida gaplashamiz.")
natija = bot.yakuniy_tozalash(xom)
check("uydirma yo'q", "DimaTorzok" not in natija, natija)
check("bo'shab qolgan [00:54] ham o'chdi", "[00:54]" not in natija, natija)
check("haqiqiy matn butun",
      "Salom, do'stlar." in natija and "blog haqida" in natija, natija)

print("[5b] TOZALASHDA VAQT BELGILARI YO'QOLMASIN")
# Jonli natija (2026-09-04): model birinchi bo'lakning [00:00]..[05:40]
# belgilarini ko'chirmadi — 6 daqiqa belgisiz qoldi. Endi belgilar
# yo'qolsa bo'lak segment bo'yicha qayta tozalanadi.
_asl_chat = bot._chat_request
_chaqiruv = []
kirish = ("[00:00] Bugun darsimizni boshlaymiz aziz talabalar. "
          "[00:30] Nafs istaklari haqida gaplashamiz bugun. "
          "[01:00] Shayx Zarruq shunday deganlar bu haqda. "
          "[01:30] Endi keyingi mavzuga o'tamiz do'stlar.")


def _belgisiz_model(payload, **kw):
    # Model matnni tozalaydi, lekin BELGILARNI TASHLAB YUBORADI
    _chaqiruv.append(1)
    matn = payload["messages"][-1]["content"].split("\n\n", 1)[-1]
    toza = bot._VAQT_BELGISI_RE.sub("", matn)
    toza = " ".join(toza.split()).replace("aziz", "aziz,")
    return toza, None


bot._chat_request = _belgisiz_model
try:
    _chaqiruv.clear()
    natija = bot._cleanup_uzbek_transcript_chunk(kirish)
    belgilar = bot._VAQT_BELGISI_RE.findall(natija)
    check("barcha 4 belgi saqlandi", belgilar == ["[00:00]", "[00:30]", "[01:00]", "[01:30]"], belgilar)
    check("segment rejimi ishga tushdi (1 + 4 so'rov)", len(_chaqiruv) == 5, len(_chaqiruv))
    check("matn tozalangan (model o'zgarishi bor)", "aziz," in natija, natija[:80])
    check("tartib buzilmadi", natija.index("[00:00]") < natija.index("[01:30]"))

    # Belgilar SAQLANGAN bo'lsa — qo'shimcha so'rov YO'Q
    def _yaxshi_model(payload, **kw):
        _chaqiruv.append(1)
        return payload["messages"][-1]["content"].split("\n\n", 1)[-1], None
    bot._chat_request = _yaxshi_model
    _chaqiruv.clear()
    natija = bot._cleanup_uzbek_transcript_chunk(kirish)
    check("belgilar saqlansa bitta so'rov kifoya", len(_chaqiruv) == 1, len(_chaqiruv))

    # Belgisiz matn (1 ta yoki 0 ta) — tekshiruv aralashmaydi
    bot._chat_request = _belgisiz_model
    _chaqiruv.clear()
    bot._cleanup_uzbek_transcript_chunk("[00:00] Faqat bitta belgi bor bu matnda.")
    check("bitta belgili matnda segment rejimi YO'Q", len(_chaqiruv) == 1, len(_chaqiruv))
finally:
    bot._chat_request = _asl_chat

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
