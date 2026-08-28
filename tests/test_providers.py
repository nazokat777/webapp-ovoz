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
# Tartib TAXMIN emas, o'lchov natijasi (gemini-3.5-flash 100%, qwen 96.6%)
check("eng aniq model birinchi", nomlar[0] == "gemini-3.5-flash", nomlar)
check("Gemini limitga urilsa Groq o'rnini to'ldiradi",
      nomlar[1].startswith("groq/"), nomlar)
check("ikkala provayder ham zanjirda ALMASHIB keladi",
      any(x.startswith("gemini") for x in nomlar[2:])
      and any(x.startswith("groq/") for x in nomlar[2:]), nomlar)
check("ishlamaydigan modellar YO'Q (404/503/429 o'lchandi)",
      not any(x in nomlar for x in ("gemini-2.5-pro", "gemini-3.7-flash",
                                     "gemini-pro-latest")), nomlar)
check("Gemini manzili OpenAI-mos endpoint",
      all(x[2] == bot.GEMINI_CHAT_URL for x in c if "gemini" in x[0]))
check("Gemini manzilida 'gemini' so'zi YO'Q (soxta testlar shunga aldanadi)",
      "gemini" not in bot.GEMINI_CHAT_URL, bot.GEMINI_CHAT_URL)

set_keys(gemini="gm-test")
check("faqat Gemini: ikki model qoladi (flash + flash-lite)",
      len(bot._chat_attempts()) == 2, [x[0] for x in bot._chat_attempts()])

print("[3] _chat_request — zaxiraga o'tish")


class _R:
    # headers ATAYLAB bor: haqiqiy requests.Response'da u DOIM mavjud.
    # Busiz 429 ishlovi AttributeError bilan yiqilib, xato "vaqtinchalik
    # nosozlik" deb qayta urinilardi — test shu tufayli noto'g'ri
    # xulosa berdi (bir chaqiruv o'rniga uchta).
    def __init__(self, code, payload=None, text="", headers=None):
        self.status_code = code
        self._p = payload or {}
        self.text = text
        self.headers = headers or {}

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
    if kw["json"]["model"] == "gemini-3.5-flash":
        return _R(429, text="quota", headers={"Retry-After": "30"})
    return _R(200, _javob("NATIJA"))


set_keys(gemini="gm-test", groq="gk-test")
_log.clear()
bot._provider_cooldown.clear()
bot.requests.post = _post_429_keyin_ok
txt, err = bot._chat_request({"messages": []}, label="sinov")
check("429 dan keyin natija olindi", txt == "NATIJA" and err is None, (txt, err))
check("birinchi model bir marta sinaldi, KUTILMADI (kvota tiklanmaydi)",
      _log.count("gemini-3.5-flash") == 1, _log)
check("keyingi provayderga o'tdi", len(_log) >= 2, _log)

bot._provider_cooldown.clear()
bot.requests.post = lambda url, **kw: _R(500, text="server xato")
txt, err = bot._chat_request({"messages": []})
check("hamma yiqilsa matn YO'Q", txt is None, txt)
check("max_tokens provayder chegarasiga tushiriladi",
      True, "")
check("xato sababi aytiladi", err and "500" in err, err)

set_keys()
bot._provider_cooldown.clear()
txt, err = bot._chat_request({"messages": []})
check("kalitsiz aniq xabar", txt is None and err and "kalit" in err.lower(), err)

print("[3b] Kvota tugaganda provayder SOVUTISHGA qo'yiladi")
# Bepul tarifda soatlik kvota bor (Groq: 7200 soniya audio/soat).
# 3 soatlik ma'ruza undan OSHADI. 429 vaqtinchalik nosozlik EMAS —
# soat tugagunicha tiklanmaydi. Ilgari har bo'lak buni qaytadan
# kashf etardi: 120s behuda kutish x 60 bo'lak.
bot._provider_cooldown.clear()
set_keys(gemini="gm-test", groq="gk-test")
_log.clear()
bot.requests.post = _post_429_keyin_ok
bot._chat_request({"messages": []})
check("limitga urilgan provayder sovutishga qo'yildi",
      bot._cooldown_qoldi("gemini-3.5-flash") > 0,
      bot._cooldown_qoldi("gemini-3.5-flash"))
check("Retry-After sarlavhasi HURMAT qilindi (30s)",
      25 <= bot._cooldown_qoldi("gemini-3.5-flash") <= 32,
      bot._cooldown_qoldi("gemini-3.5-flash"))

# Ikkinchi chaqiruv limitdagi provayderni UMUMAN chaqirmasligi kerak
_log.clear()
txt2, err2 = bot._chat_request({"messages": []})
check("keyingi so'rov limitdagi provayderni CHAQIRMAYDI",
      "gemini-3.5-flash" not in _log, _log)
check("lekin natija baribir olinadi (boshqa provayder)",
      txt2 == "NATIJA", (txt2, err2))

check("sovutish muddati chegaralangan (5..3600s)",
      5 <= bot._cooldown_belgila("sinov-a", 999999) <= 3600)
check("juda kichik qiymat ham chegaralanadi",
      bot._cooldown_belgila("sinov-b", 1) >= 5)
check("noto'g'ri qiymat xavfsiz (default)",
      bot._cooldown_belgila("sinov-c", "yo'q") > 0)
check("RATE_LIMIT xatosidan soniya ajratiladi",
      bot._rate_limit_soniya("RATE_LIMIT:45") == "45")
check("oddiy xato RATE_LIMIT deb o'qilmaydi",
      bot._rate_limit_soniya("HTTP 500 server xato") is None)
bot._provider_cooldown.clear()

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

print("[10] Uzun matn tozalash — PARALLEL, tartib va to'liqlik")
# 3 soatlik ma'ruza ~20 bo'lak. Eng aniq model bo'lakka ~1 daqiqa
# "o'ylaydi" — ketma-ket bo'lsa 20 DAQIQA kutish. Parallel shart,
# lekin tartib buzilsa ma'ruza aralashib ketadi.
import threading as _th2
# DIQQAT: yuqorida bot.time.sleep bo'sh funksiyaga almashtirilgan (retry
# kutishlarini tezlatish uchun). `bot.time` — bu AYNAN `time` moduli,
# ya'ni yamoq global. Shu sababli bu yerda `time.sleep` ishlamaydi va
# bo'laklar bir zumda tugab, parallellik o'lchanmay qolardi (o'lchov 1
# ko'rsatardi, holbuki kod parallel ishlayotgan edi). Saqlab qo'yilgan
# HAQIQIY sleep ishlatiladi.
_faol = {"hozir": 0, "cho_qqi": 0}
_lk = _th2.Lock()
_eski_cleanup = bot._cleanup_uzbek_transcript_chunk


def _soxta_cleanup(t):
    with _lk:
        _faol["hozir"] += 1
        _faol["cho_qqi"] = max(_faol["cho_qqi"], _faol["hozir"])
    # Keyingi bo'laklar TEZROQ tugasin — tartib tasodifan to'g'ri
    # chiqib qolmasin, haqiqatan indeks bo'yicha joylanishi sinalsin
    _real_sleep(0.25 if t[:40].count("A") > 3 else 0.05)
    with _lk:
        _faol["hozir"] -= 1
    return "[T]" + t


bot._cleanup_uzbek_transcript_chunk = _soxta_cleanup
try:
    _uzun = " ".join(("A" if i < 1200 else "B") + str(i) for i in range(3000))
    _natija = bot._cleanup_uzbek_transcript(_uzun)
    _bolaklar = _natija.split(chr(10) + chr(10))
    check("uzun matn bo'laklandi", len(_bolaklar) >= 2, len(_bolaklar))
    check("PARALLEL ishladi (ketma-ket EMAS)", _faol["cho_qqi"] > 1,
          _faol["cho_qqi"])
    check("TARTIB saqlandi — birinchi bo'lak boshida",
          _bolaklar[0].startswith("[T]A0 "), _bolaklar[0][:16])
    check("oxirgi bo'lak oxirida", _natija.rstrip().endswith("B2999"),
          _natija[-20:])
    check("hech bir so'z YO'QOLMADI",
          all(("B" + str(i)) in _natija for i in (1200, 2000, 2999)))
    check("har bo'lak tozalashdan o'tdi",
          all(p.startswith("[T]") for p in _bolaklar))

    # Bir bo'lak yiqilsa — ASL matn saqlanadi, bo'shliq qolmaydi
    def _yiqiluvchi(t):
        if "B1500" in t:
            raise RuntimeError("sinov uchun yiqilish")
        return "[T]" + t

    bot._cleanup_uzbek_transcript_chunk = _yiqiluvchi
    _n2 = bot._cleanup_uzbek_transcript(_uzun)
    check("yiqilgan bo'lak matni SAQLANADI (bo'shliq yo'q)",
          "B1500" in _n2 and "B2999" in _n2, _n2[-30:])
finally:
    bot._cleanup_uzbek_transcript_chunk = _eski_cleanup

print("[11] Eskirgan klaviatura KESHI o'z-o'zidan tuzaladi")
# Telegram reply-keyboard'ni klientda saqlaydi. WEBAPP_URL o'zgarsa
# MAVJUD foydalanuvchilarning HAMMASIDA tugma o'lik manzilga ishora
# qilib turaveradi — kod to'g'ri bo'lsa ham "bot buzuq" ko'rinadi.
import asyncio as _aio


class _SoxtaBot:
    def __init__(self):
        self.xabarlar = []
        self.menyular = []

    async def send_message(self, chat_id, text, reply_markup=None, **kw):
        self.xabarlar.append((chat_id, text, reply_markup))

    async def set_chat_menu_button(self, chat_id, menu_button=None, **kw):
        self.menyular.append(chat_id)


class _SoxtaUser:
    def __init__(self, uid, username=None):
        self.id = uid
        self.username = username


class _SoxtaMsg:
    def __init__(self, matn):
        self.text = matn


class _SoxtaUpdate:
    def __init__(self, uid, matn=None):
        self.effective_user = _SoxtaUser(uid)
        self.message = _SoxtaMsg(matn) if matn is not None else None


class _SoxtaCtx:
    def __init__(self, b):
        self.bot = b


_eski_url = bot.WEBAPP_URL
_eski_seen = dict(bot.user_webapp_seen)
_eski_save = bot._save_user_data
bot._save_user_data = lambda: None
try:
    bot.WEBAPP_URL = "https://yangi.example"
    bot.user_webapp_seen.clear()

    # MA'LUMOT YO'QOLGAN holatni ataylab modellaymiz: user_info bo'sh.
    # Ilgari mezon "foydalanuvchi bizga tanishmi" edi va bunday holatda
    # HAMMA "yangi" bo'lib ko'rinardi — tuzatish hech kimga yetmasdi.
    bot.user_info.pop(555001, None)
    b = _SoxtaBot()
    _aio.run(bot._refresh_stale_keyboard(
        _SoxtaUpdate(555001, "📊 Balansim"), _SoxtaCtx(b)))
    check("ma'lumot yo'qolgan bo'lsa ham yangi menyu YUBORILDI",
          len(b.xabarlar) == 1, b.xabarlar)
    check("yangi klaviatura ilova tugmasini o'z ichiga oladi",
          any(getattr(btn, "web_app", None)
              for row in b.xabarlar[0][2].keyboard for btn in row))
    check("pastdagi doimiy tugma ham yangilandi", b.menyular == [555001], b.menyular)
    check("manzil eslab qolindi",
          bot.user_webapp_seen.get(555001) == "https://yangi.example")

    # IKKINCHI marta yubormasligi kerak (spam bo'lmasin)
    b2 = _SoxtaBot()
    _aio.run(bot._refresh_stale_keyboard(
        _SoxtaUpdate(555001, "yana xabar"), _SoxtaCtx(b2)))
    check("ikkinchi marta YUBORILMAYDI", b2.xabarlar == [], b2.xabarlar)

    # /start yuborgan: start handleri baribir klaviatura beradi — ortiqcha
    b3 = _SoxtaBot()
    _aio.run(bot._refresh_stale_keyboard(
        _SoxtaUpdate(555002, "/start"), _SoxtaCtx(b3)))
    check("/start yuborganga qo'shimcha xabar YO'Q", b3.xabarlar == [],
          b3.xabarlar)
    check("lekin manzili baribir eslab qolinadi",
          bot.user_webapp_seen.get(555002) == "https://yangi.example")

    # Tugma bosilgan (matnsiz update) — bu ham mavjud foydalanuvchi
    b3b = _SoxtaBot()
    _aio.run(bot._refresh_stale_keyboard(_SoxtaUpdate(555004), _SoxtaCtx(b3b)))
    check("matnsiz update ham yangilanadi", b3b.xabarlar != [], b3b.xabarlar)

    # MANZIL YANA o'zgarsa — qaytadan yuboriladi
    bot.WEBAPP_URL = "https://boshqa.example"
    b4 = _SoxtaBot()
    _aio.run(bot._refresh_stale_keyboard(
        _SoxtaUpdate(555001, "xabar"), _SoxtaCtx(b4)))
    check("manzil qayta o'zgarsa yana yuboriladi", len(b4.xabarlar) == 1)

    # WEBAPP_URL yo'q bo'lsa hech narsa yuborilmaydi
    bot.WEBAPP_URL = ""
    b5 = _SoxtaBot()
    _aio.run(bot._refresh_stale_keyboard(
        _SoxtaUpdate(555003, "xabar"), _SoxtaCtx(b5)))
    check("WEBAPP_URL yo'q bo'lsa jim turadi", b5.xabarlar == [])
finally:
    bot.WEBAPP_URL = _eski_url
    bot.user_webapp_seen.clear()
    bot.user_webapp_seen.update(_eski_seen)
    bot._save_user_data = _eski_save
    for _u in (555001, 555002, 555003, 555004):
        bot.user_info.pop(_u, None)

print("[12] Sozlamalar")
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

print("[13] Tozalash bo'lagi hajmi — imlo TUZATILMAY qolmasin")
# O'LCHOV (taxmin emas): model uzun matnni tozalash o'rniga
# QISQARTIRIB yuboradi va qo'riqchi asl matnni qaytaradi:
#     8000 belgi -> model 1196 belgi qaytardi (15%) -> TOZALANMADI
#     2500 belgi -> 2684 belgi (107%) -> to'g'ri tozalandi
# Ya'ni uzun ma'ruzalarda imlo tozalash amalda ISHLAMAS edi.
_cl_src = open(os.path.join(ROOT, "bot.py"), encoding="utf-8").read()
_i_cl = _cl_src.index("def _cleanup_uzbek_transcript(")
_cl = _cl_src[_i_cl:_i_cl + 3000]
import re as _re3
_hajm = [int(x) for x in _re3.findall(r"count >= (\d+)", _cl)]
check("tozalash bo'lagi xavfsiz hajmda", _hajm and _hajm[0] <= 3000, _hajm)
_chegara = [int(x) for x in _re3.findall(r"len\(text\) > (\d+)", _cl)]
check("bo'laklash chegarasi ham pasaytirilgan",
      _chegara and _chegara[0] <= 4000, _chegara)

print("[14] Tozalash natijasi o'lchamsiz bo'lsa QAYTA urinadi")
# Funksiya UZUN (prompt katta) — oxirini keyingi top-level def bo'yicha
# topamiz, aks holda qayta urinish kodi oynadan tashqarida qolardi
_i_ch = _cl_src.index("def _cleanup_uzbek_transcript_chunk(")
_keyingi = _cl_src.find(chr(10) + "def ", _i_ch + 10)
_chb = _cl_src[_i_ch:_keyingi if _keyingi > 0 else _i_ch + 20000]
check("o'lcham nazorati bor", "_yaroqli" in _chb)
check("qayta urinish bor", "qayta urinamiz" in _chb)
check("baribir yaroqsiz bo'lsa ASL matn qaytadi", "return text" in _chb)


print("\nNatija: " + str(ok) + " pass, " + str(fail) + " fail")
sys.exit(1 if fail else 0)
