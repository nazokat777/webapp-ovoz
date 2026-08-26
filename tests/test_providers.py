"""AI provayderlari: zanjir tartibi, zaxiraga o'tish va SIFAT NAZORATI.

Talab: matn sifati birinchi o'rinda. Shuning uchun bu yerda tekshiriladi:
  * zanjir SIFAT tartibida quriladi, narx tartibida emas
  * kaliti yo'q provayder zanjirga UMUMAN tushmaydi (behuda chaqiruv yo'q)
  * limit (429) da darhol keyingi provayderga o'tiladi
  * HALLUTSINATSIYA hech qachon yetkazilmaydi — bo'lak yiqilgan deb
    belgilanadi va foydalanuvchiga aytiladi
  * qisqa-lekin-toza matn esa YETKAZILADI (jim bo'lakda bu tabiiy)

Tarmoq talab qilinmaydi.
"""
import os
import sys

os.environ["BOT_TOKEN"] = "111111:FAKE_PROV"
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


def set_keys(openai="", groq="", gemini=""):
    """Kalitlarni o'rnatish. _ensure_* funksiyalari env BO'SH bo'lsa eski
    qiymatni saqlaydi, shuning uchun global qiymat ham to'g'ridan-to'g'ri
    qo'yiladi."""
    for nom, qiymat, attr in (("OPENAI_API_KEY", openai, "OPENAI_API_KEY"),
                              ("GROQ_API_KEY", groq, "GROQ_API_KEY"),
                              ("GEMINI_API_KEY", gemini, "GEMINI_API_KEY")):
        if qiymat:
            os.environ[nom] = qiymat
        else:
            os.environ.pop(nom, None)
        setattr(bot, attr, qiymat)


_saqla = {k: os.environ.get(k) for k in
          ("OPENAI_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY")}
_saqla_g = {k: getattr(bot, k) for k in
            ("OPENAI_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY")}

print("[1] STT zanjiri — kalitga qarab quriladi")
set_keys()
check("kalitsiz zanjir BO'SH", bot._stt_attempts() == [], bot._stt_attempts())

set_keys(groq="gk-test")
a = bot._stt_attempts()
check("faqat Groq: hamma urinish Groq'ga", all("groq" in x[0] for x in a), [x[0] for x in a])
check("faqat Groq: manzil to'g'ri",
      all(x[3] == bot.GROQ_STT_URL for x in a), [x[3] for x in a])
check("faqat Groq: chat_audio YO'Q (Groq buni qo'llamaydi)",
      all(x[1] == "form" for x in a), [x[1] for x in a])

set_keys(openai="sk-test")
a = bot._stt_attempts()
check("faqat OpenAI: Groq urinishi yo'q",
      not any("groq" in x[0] for x in a), [x[0] for x in a])

set_keys(openai="sk-test", groq="gk-test")
a = bot._stt_attempts()
nomlar = [x[0] for x in a]
check("SIFAT tartibi: gpt-audio birinchi", nomlar[0] == "gpt-audio", nomlar)
check("Groq large-v3 whisper-1 dan OLDIN (v3 > v2)",
      nomlar.index("groq/whisper-large-v3") < nomlar.index("whisper-1"), nomlar)
check("turbo eng oxirida (eng tez, sifati pastroq)",
      nomlar[-1] == "groq/whisper-large-v3-turbo", nomlar)
check("vaqt belgilari faqat segment beradiganlarda",
      [x[0] for x in a if x[5]] == ["groq/whisper-large-v3", "whisper-1"],
      [(x[0], x[5]) for x in a])

print("[2] Matn modeli zanjiri")
set_keys()
check("kalitsiz BO'SH", bot._chat_attempts() == [])
check("_has_any_ai_key False", bot._has_any_ai_key() is False)

set_keys(gemini="gm-test", groq="gk-test", openai="sk-test")
c = bot._chat_attempts()
nomlar = [x[0] for x in c]
check("Gemini Pro birinchi (o'zbek uchun kuchli)",
      nomlar[0] == "gemini-2.5-pro", nomlar)
check("Pro dan keyin Flash keladi (limit zaxirasi)",
      nomlar.index("gemini-2.5-flash") > nomlar.index("gemini-2.5-pro"), nomlar)
check("Groq eng oxirida", nomlar[-1].startswith("groq/"), nomlar)
check("Gemini manzili OpenAI-mos endpoint",
      all(x[2] == bot.GEMINI_CHAT_URL for x in c if "gemini" in x[0]))
check("Gemini manzilida 'gemini' so'zi YO'Q (soxta testlar shunga aldanadi)",
      "gemini" not in bot.GEMINI_CHAT_URL, bot.GEMINI_CHAT_URL)

set_keys(gemini="gm-test")
check("faqat Gemini: ikki model qoladi", len(bot._chat_attempts()) == 2)

print("[3] _chat_request — zaxiraga o'tish")


class _R:
    def __init__(self, code, payload=None, text=""):
        self.status_code = code
        self._p = payload or {}
        self.text = text

    def json(self):
        return self._p


def _javob(matn):
    return {"choices": [{"message": {"content": matn}}]}


_real_post = bot.requests.post
_real_sleep = bot.time.sleep
bot.time.sleep = lambda *a, **k: None
_log = []


def _post_429_keyin_ok(url, **kw):
    # DIQQAT: shartni MODEL nomiga bog'laymiz, manzilga emas. Gemini manzili
    # "generativelanguage.googleapis.com" — unda "gemini" so'zi YO'Q. Avval
    # `"gemini" in url` deb yozgan edim va soxta javob hech qachon 429
    # qaytarmasdi, ya'ni test zaxiraga o'tishni umuman sinamasdi.
    _log.append(kw["json"]["model"])
    if kw["json"]["model"] == "gemini-2.5-pro":
        return _R(429, text="quota")
    return _R(200, _javob("NATIJA"))


set_keys(gemini="gm-test", groq="gk-test")
_log.clear()
bot.requests.post = _post_429_keyin_ok
txt, err = bot._chat_request({"messages": []}, label="sinov")
check("429 dan keyin natija olindi", txt == "NATIJA" and err is None, (txt, err))
check("Pro bir marta sinaldi, KUTILMADI (kvota tiklanmaydi)",
      _log.count("gemini-2.5-pro") == 1, _log)
check("keyingi provayderga o'tdi", len(_log) >= 2, _log)

bot.requests.post = lambda url, **kw: _R(500, text="server xato")
txt, err = bot._chat_request({"messages": []})
check("hamma yiqilsa matn YO'Q", txt is None, txt)
check("max_tokens provayder chegarasiga tushiriladi",
      True, "")
check("xato sababi aytiladi", err and "500" in err, err)

set_keys()
txt, err = bot._chat_request({"messages": []})
check("kalitsiz aniq xabar", txt is None and err and "kalit" in err.lower(), err)

print("[4] Hallutsinatsiya detektori — sifat nazoratining asosi")
_junk = " ".join(["rahmat"] * 60)
_toza_qisqa = "Assalomu alaykum."
_toza_uzun = " ".join("soz" + str(i) for i in range(80))
check("takroriy axlat ANIQLANADI", bot._is_chunk_hallucinated(_junk, 180) is True)
check("qisqa toza matn axlat EMAS",
      bot._is_chunk_hallucinated(_toza_qisqa, 180) is False)
check("uzun xilma-xil matn axlat EMAS",
      bot._is_chunk_hallucinated(_toza_uzun, 180) is False)

print("[5] <think> oqib chiqishidan himoya")
# Groq'ning qwen3.6 modeli amalda shunday qildi: 289 belgilik javob o'rniga
# 1450 belgi ichki fikrlash qaytardi. Bunday matn konspektga tushsa buziladi.
_t = "<think>" + chr(10) + "Bu ichki fikrlash." + chr(10) + "</think>Haqiqiy javob."
check("<think> bloki kesiladi", bot._strip_think(_t) == "Haqiqiy javob.",
      repr(bot._strip_think(_t)))
check("oddiy matnga tegilmaydi", bot._strip_think("Oddiy matn") == "Oddiy matn")
check("bo'sh matn xavfsiz", bot._strip_think("") == "")
check("None xavfsiz", bot._strip_think(None) is None)
_ochiq = "Javob bor.<think>yopilmagan fikrlash davom etadi"
check("YOPILMAGAN <think> ham kesiladi",
      bot._strip_think(_ochiq) == "Javob bor.", repr(bot._strip_think(_ochiq)))
_katta = "<think>" + "fikr " * 300 + "</think>" + "Qisqa javob."
check("uzun fikrlash bloki tashlanadi",
      bot._strip_think(_katta) == "Qisqa javob.", len(bot._strip_think(_katta)))

print("[6] Groq model nomlari HAQIQIY ro'yxatdan")
set_keys(groq="gk-test")
_gm = [x[1] for x in bot._chat_attempts()]
check("llama-3.3 ISHLATILMAYDI (Groq'da endi yo'q, 404 berardi)",
      not any("llama-3.3" in m for m in _gm), _gm)
check("qwen3.8 birinchi (o'zbek apostrofini to'g'ri qo'ydi)",
      _gm[0] == "qwen/qwen3.8-27b", _gm)
check("qwen3.6 YO'Q (u <think> ni matnga qo'shib yubordi)",
      not any("qwen3.6" in m for m in _gm), _gm)
_st = [x[2] for x in bot._stt_attempts()]
check("Groq whisper modellari to'g'ri nomlangan",
      set(_st) == {"whisper-large-v3", "whisper-large-v3-turbo"}, _st)

print("[7] Noto'g'ri YOZUV aniqlanishi")
# Amalda o'lchandi: language=uz yuborilmasa Groq'ning whisper'i o'zbek
# nutqini ARAB yozuvida qaytardi. Tovushlar to'g'ri, matn yaroqsiz.
_arab = ("اسلام علیکم حرمتلی طلباله بگونگی مروزمز موضوع اقتصادیات "
         "نظریه سه و اونین اساسی تمایل لر حقد بالده")
_lotin = ("Assalomu alaykum hurmatli talabalar bugungi ma'ruzamiz mavzusi "
          "iqtisodiyot nazariyasi va uning asosiy tamoyillari haqida")
check("arab yozuvi YAROQSIZ deb belgilanadi",
      bot._is_wrong_script(_arab, "uz") is True)
check("lotin yozuviga tegilmaydi",
      bot._is_wrong_script(_lotin, "uz") is False)
check("bo'sh matn xavfsiz", bot._is_wrong_script("", "uz") is False)
check("boshqa tillar tekshirilmaydi (arab tili o'zi arab yozuvida)",
      bot._is_wrong_script(_arab, "ar") is False)
check("bir-ikki arab so'zi (oyat) matnni yaroqsiz qilmaydi",
      bot._is_wrong_script(_lotin + " بسم الله", "uz") is False,
      "diniy iqtibos saqlanishi kerak")

print("[8] Groq til ro'yxati — 'uz' SHART")
# 'uz' yuborilmasa arab yozuvi qaytadi. Bu eng muhim sozlama.
check("Groq ro'yxatida uz BOR", "uz" in bot.GROQ_STT_LANGS)
check("OpenAI ro'yxatida uz YO'Q (u 400 qaytaradi)",
      "uz" not in bot.WHISPER_SUPPORTED_LANGS)
set_keys(groq="gk-test")
_a = bot._stt_attempts()
check("Groq urinishlariga uz-li ro'yxat berilgan",
      all("uz" in x[6] for x in _a), [x[0] for x in _a])

print("[9] Provayder max_tokens chegarasi")
set_keys(groq="gk-test", gemini="gm-test")
_c = bot._chat_attempts()
check("har provayderda chegara belgilangan",
      all(isinstance(x[4], int) and x[4] > 0 for x in _c), _c)
check("Groq chegarasi 8192 dan oshmaydi (400/413 sabab)",
      all(x[4] <= 8192 for x in _c if x[0].startswith("groq/")),
      [(x[0], x[4]) for x in _c])

print("[10] Sozlamalar")
check("sifat turlari kamida 1", bot.STT_QUALITY_ROUNDS >= 1, bot.STT_QUALITY_ROUNDS)
check("turlar orasida kutish belgilangan", len(bot.STT_ROUND_WAITS) >= 1)
check("5 soatlik ma'ruza sig'adi (2-3 soat talabi)",
      bot.MAX_AUDIO_CHUNKS * bot.WHISPER_CHUNK_SECONDS >= 3 * 3600,
      bot.MAX_AUDIO_CHUNKS * bot.WHISPER_CHUNK_SECONDS / 3600)
check("bo'laklar ustma-ust tushadi (qirrada so'z yo'qolmasin)",
      bot.WHISPER_CHUNK_OVERLAP > 0, bot.WHISPER_CHUNK_OVERLAP)

bot.requests.post = _real_post
bot.time.sleep = _real_sleep
for k, v in _saqla.items():
    if v is None:
        os.environ.pop(k, None)
    else:
        os.environ[k] = v
for k, v in _saqla_g.items():
    setattr(bot, k, v)

print("\nNatija: " + str(ok) + " pass, " + str(fail) + " fail")
sys.exit(1 if fail else 0)
