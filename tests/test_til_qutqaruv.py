"""TIL QUTQARUVI va DALIL HIMOYASI — ultraPRO sifat himoyalari.

AMALDA BO'LGAN XATO (2026-09-01): foydalanuvchi bot tilini ruscha qilib
qo'ygan, audio esa o'zbekcha edi. Whisper language=ru bilan o'zbek nutqini
tovushiga qarab ruscha harflarda yozdi:

    "Менге битте сноу постыны ботке юбор баттенлары бленд"

detect_text_lang buni kirill deb "ru" tasnifladi, tarjimon axlatdan
"ma'no" to'qidi, foydalanuvchi PDF'da ma'nosiz matn oldi.

Ikkinchi himoya — DALIL MATNI: ma'ruzalarda ustoz Qur'on oyatlari va
nahv/sarf misollarini keltiradi. Tozalovchi model ularni "buzuq o'zbekcha"
deb o'ylab o'zbek so'zlariga "tuzatishi" yoki oyatni YODDAN "to'g'rilashi"
eng og'ir xato: dalil matni buziladi va foydalanuvchi buni sezmaydi.

Tarmoq talab qilinmaydi.
"""
import os
import sys

os.environ["BOT_TOKEN"] = "111111:FAKE_TIL"
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


print("[1] FONETIK O'ZBEK ANIQLAGICHI")
# Haqiqiy o'lchovdan olingan namuna (2026-09-01, serverda)
fonetik = ("Менге битте сноу постыны ботке юбор баттенлары бленд. "
           "Пест сфаты бет. Энтер босамыз. Вэ кузепамыз. Мэнэ бу хазыр. "
           "Иштэп кэй чикерэк. Ахырды бискейн. Сазламэлэрны мустахкэмнэр. "
           "Харкэнэ иштэйдэгэн кайдэн берпойамыз. Кузетишлэр учун бопты "
           "дэймиз энди шуны курамиз бирге ва натижасини курсатамиз сизга "
           "хамма нарса тайёр болганда яна бир бор текшерамиз хаммасини")
check("fonetik o'zbek ANIQLANADI", bot._fonetik_ozbek_shubhasi(fonetik) is True)

# Haqiqiy ruscha transkript (o'sha videoning ruscha qismidan)
ruscha = ("Начинаем. В основном, они пишут посты, а потом пишут аудио, "
          "и в результате они начинают выставлять посты в канал, то есть "
          "в блог. Кто пишет эти посты? Вы можете написать посты "
          "максимально, если вы хотите, чтобы они были максимально "
          "классическими, вы можете их написать категориями, вы можете "
          "написать и это будет очень хорошо для нас и для вас тоже")
check("haqiqiy ruscha TEGILMAYDI", bot._fonetik_ozbek_shubhasi(ruscha) is False)

check("kalta matnda hukm yo'q (xato qutqaruv ham zarar)",
      bot._fonetik_ozbek_shubhasi("Менге битте сноу") is False)
check("lotin matn tegilmaydi",
      bot._fonetik_ozbek_shubhasi("Bugun dars juda yaxshi o'tdi " * 20) is False)
check("bo'sh matn yiqilmaydi", bot._fonetik_ozbek_shubhasi("") is False)
check("None yiqilmaydi", bot._fonetik_ozbek_shubhasi(None) is False)

print("[2] QUTQARUV OQIMI — transcribe_unified")
_asl_tw = bot.transcribe_whisper
_asl_stt = bot._stt_attempts
_asl_clean = bot._cleanup_uzbek_transcript
_chaqiruvlar = []


def _soxta_whisper(fp, lang, cb=None, failed=None):
    _chaqiruvlar.append(lang)
    if lang == "ru":
        return fonetik
    return "Bugun darsimizda nahv qoidalarini ko'rib chiqamiz. " * 10


bot.transcribe_whisper = _soxta_whisper
bot._stt_attempts = lambda: [("soxta",)]
bot._cleanup_uzbek_transcript = lambda t: "[TOZALANDI] " + t
try:
    _chaqiruvlar.clear()
    natija = bot.transcribe_unified("/tmp/yoq.wav", language="ru")
    check("ru natijasi fonetik -> uz bilan qayta o'qildi",
          _chaqiruvlar == ["ru", "uz"], _chaqiruvlar)
    check("yakuniy matn o'zbekcha nusxa",
          "nahv qoidalarini" in natija, natija[:80])
    check("qutqarilgan matn O'ZBEK TOZALASHIDAN o'tdi",
          natija.startswith("[TOZALANDI]"),
          "qutqaruvdan keyin language=uz bo'lishi kerak")

    # Haqiqiy ruscha audio — qutqaruv ISHGA TUSHMASLIGI kerak
    def _soxta_ruscha(fp, lang, cb=None, failed=None):
        _chaqiruvlar.append(lang)
        return ruscha

    bot.transcribe_whisper = _soxta_ruscha
    _chaqiruvlar.clear()
    natija = bot.transcribe_unified("/tmp/yoq.wav", language="ru")
    check("haqiqiy ruschada qayta o'qish YO'Q",
          _chaqiruvlar == ["ru"], _chaqiruvlar)
    check("ruscha matn o'zgarmagan", "Начинаем" in natija)

    # Qutqaruv bo'sh qaytarsa asl natija saqlanadi
    def _soxta_bosh(fp, lang, cb=None, failed=None):
        _chaqiruvlar.append(lang)
        return fonetik if lang == "ru" else ""

    bot.transcribe_whisper = _soxta_bosh
    _chaqiruvlar.clear()
    natija = bot.transcribe_unified("/tmp/yoq.wav", language="ru")
    check("qutqaruv bo'sh qaytarsa asl matn qoladi (hech bo'lmasa nimadir)",
          "Менге" in natija, natija[:60])
finally:
    bot.transcribe_whisper = _asl_tw
    bot._stt_attempts = _asl_stt
    bot._cleanup_uzbek_transcript = _asl_clean

print("[3] DALIL HIMOYASI — tozalash promptida")
with open(os.path.join(ROOT, "bot.py"), encoding="utf-8") as f:
    manba = f.read()
_p = manba.find('"You are a careful Uzbek proofreader')
check("tozalash prompti topildi", _p > 0)
_prompt = manba[_p:_p + 9000]
check("Qur'on iqtibosi YODDAN tuzatilmaydi",
      "FROM MEMORY" in _prompt,
      "model oyatni kanonik shaklga 'to'g'rilab' yuborishi mumkin edi")
check("arabcha so'z o'zbekchaga aylantirilmaydi",
      "similar-looking Uzbek" in _prompt)
check("nahv/sarf atamalari ro'yxati bor",
      "mubtado" in _prompt and "i'rob" in _prompt and "majrur" in _prompt)
check("tuslash mashqi takror-tozalashdan himoyalangan",
      "conjugation drill" in _prompt,
      "zaraba zarabaa... ni dedupe o'chirib yuborishi mumkin edi")
check("arabcha dalil misoli promptda ko'rsatilgan",
      "qolallohu" in _prompt)

print("[4] _dedupe_repeated_words SARF MASHQINI O'CHIRMAYDI")
# Tuslash shakllari har xil — aynan takror emas, o'chirilmasligi kerak.
mashq = "zaraba zarabaa zarabuu zarabat zarabataa zarabna"
check("tuslash shakllari saqlanadi",
      bot._dedupe_repeated_words(mashq).strip() == mashq,
      bot._dedupe_repeated_words(mashq))

print("[5] SIFAT KUTISHI — limitda turbo'ga tushmaslik")
# Jonli natijada ko'rildi (2026-09-02): large-v3 5s limitga urildi va
# deyarli hamma bo'lak turbo bilan o'qildi ("мюрид" -> "муром", nomlar
# buzuq). Endi eng sifatli provayder qisqa limitda bo'lsa KUTILADI.
check("eng sifatli provayder qisqa limitda -> kutiladi",
      bot._sifat_uchun_kutiladimi(0, 5) is True)
check("chegara ichida ham kutiladi",
      bot._sifat_uchun_kutiladimi(0, bot.STT_SIFAT_KUTISH_MAKS) is True)
check("juda uzoq limit -> kutilmaydi (haqiqiy kvota tugashi)",
      bot._sifat_uchun_kutiladimi(0, bot.STT_SIFAT_KUTISH_MAKS + 1) is False)
check("pastroq provayder uchun kutilmaydi",
      bot._sifat_uchun_kutiladimi(1, 5) is False)
check("cooldown yo'q bo'lsa kutilmaydi",
      bot._sifat_uchun_kutiladimi(0, 0) is False)
_m = open(os.path.join(ROOT, "bot.py"), encoding="utf-8").read()
check("chunk loopi kutish funksiyasini ishlatadi",
      "_sifat_uchun_kutiladimi(i_att, _qoldi)" in _m)
check("kutishdan keyin cooldown QAYTA o'qiladi",
      "boshqa oqim uzaytirgan" in _m)

print("[5b] ISHONCH PROBE'I — Whisper'ning o'z ishonchi bo'yicha til tanlash")
# O'lchandi (2026-09-03): o'zbek darsi ruscha rejimda 44.7% yordamchi
# so'z bilan TO'QILGAN ravon ruscha berdi — stopword tekshiruvi ojiz.
# Whisper'ning o'z ishonchi esa aniq ajratdi:
#     ru: logprob=-0.662 siqilish=2.21 (322 so'z)  uz: -0.515 1.75 (365)
#     ru: logprob=-1.183 siqilish=2.12 (284 so'z)  uz: -0.629 1.68 (382)
check("o'zbek dars, 1-namuna -> uz",
      bot._til_tanlash("ru", (-0.662, 2.21, 322), (-0.515, 1.75, 365)) == "uz")
check("o'zbek dars, 2-namuna -> uz",
      bot._til_tanlash("ru", (-1.183, 2.12, 284), (-0.629, 1.68, 382)) == "uz")
# Haqiqiy ruscha audio: ru ishonchliroq, siqilish normal -> ru qoladi
check("haqiqiy ruscha -> ru qoladi",
      bot._til_tanlash("ru", (-0.30, 1.50, 300), (-0.90, 1.60, 280)) == "ru")
# Teng ishonch (farq chegaradan kichik) -> so'ralgan til qoladi
check("farq kichik -> so'ralgan til qoladi",
      bot._til_tanlash("ru", (-0.50, 1.50, 300), (-0.45, 1.55, 300)) == "ru")
# uz ishonchli-yu, matni kambag'al (so'z 80% dan kam) -> almashtirilmaydi
check("uz kambag'al bo'lsa almashtirilmaydi",
      bot._til_tanlash("ru", (-0.70, 1.80, 300), (-0.40, 1.60, 150)) == "ru")
# Siqilish uydirma chegarasida (>=2.0) va uz siqilishi past -> uz
check("uydirma siqilishi -> uz",
      bot._til_tanlash("en", (-0.55, 2.30, 300), (-0.60, 1.70, 290)) == "uz")
check("o'lchov yo'q -> so'ralgan til", bot._til_tanlash("ru", None, (-0.5, 1.5, 300)) == "ru")
check("uz so'ralganda probe tegmaydi", bot._til_tanlash("uz", (-0.5, 1.5, 3), (-0.9, 3.0, 1)) == "uz")
check("probe transcribe_whisper'ga ulangan",
      "_til_tanlash(source_lang, _s, _u)" in _m)
check("probe bo'lak O'RTASIDAN oladi (boshi arabcha matn/musiqa bo'ladi)",
      "chunks_to_process[len(chunks_to_process) // 3]" in _m)
check("til almashsa o'zbek tozalash ham ishlaydi",
      'detect_text_lang(text) == "uz"' in _m)

print("[5c] KESILGAN JAVOB (finish_reason=length) — keyingi provayderga o'tish")
# O'lchandi (2026-09-04): gemini-3.5-flash 2700 belgilik tozalashda
# total_tokens=10858, ko'rinadigan javob 326 token — qolgani ichki
# "fikrlash". Javob 884 belgida gap o'rtasida kesildi, lekin MUVAFFAQIYAT
# deb qabul qilindi; qayta urinish yana o'sha modelga borib yana kesildi.
# Keyingi provayder (qwen) 2 soniyada to'liq bajargan edi.
_asl_post = bot.requests.post
_asl_att = bot._chat_attempts
_chaqirilgan = []


class _SoxtaJavob:
    def __init__(self, nom, finish, matn):
        self.status_code = 200
        self._j = {"choices": [{"message": {"content": matn},
                                "finish_reason": finish}]}
        self.text = ""
    def json(self):
        return self._j


def _soxta_post(url, headers=None, json=None, timeout=None, **kw):
    model = (json or {}).get("model", "")
    _chaqirilgan.append(model)
    if "kesuvchi" in model:
        return _SoxtaJavob(model, "length", "Kesilgan matn boshi...")
    return _SoxtaJavob(model, "stop", "To'liq tozalangan matn. " * 20)


bot.requests.post = _soxta_post
bot._chat_attempts = lambda: [
    ("kesuvchi-model", "kesuvchi-model", "http://x/1", {}, 8192),
    ("toliq-model", "toliq-model", "http://x/2", {}, 8192)]
try:
    _chaqirilgan.clear()
    out, err = bot._chat_request({"max_tokens": 16000, "messages": []}, label="sinov")
    check("kesilgan javob QABUL QILINMADI, keyingisiga o'tildi",
          _chaqirilgan == ["kesuvchi-model", "toliq-model"], _chaqirilgan)
    check("to'liq javob qaytdi", out is not None and "To'liq tozalangan" in out, out)
    check("xato yo'q (fallback muvaffaqiyatli)", err is None, err)

    # Faqat kesuvchi provayder bo'lsa — xato qaytadi, kesilgan matn EMAS
    bot._chat_attempts = lambda: [("kesuvchi-model", "kesuvchi-model", "http://x/1", {}, 8192)]
    out, err = bot._chat_request({"max_tokens": 16000, "messages": []}, label="sinov")
    check("yagona provayder kesilsa -> None + sabab",
          out is None and err and "kesildi" in err, (out, err))
finally:
    bot.requests.post = _asl_post
    bot._chat_attempts = _asl_att

check("Gemini chegarasi fikrlash uchun ko'tarilgan (32768)",
      _m.count("32768") >= 2 and '_bearer(gm), 8192' not in _m)

# reasoning_effort FAQAT Gemini'ga, FAQAT env yoqilganda
_yuborilgan = []
def _post_yoz(url, headers=None, json=None, timeout=None, **kw):
    _yuborilgan.append(dict(json or {}))
    return _SoxtaJavob("x", "stop", "Javob matni. " * 10)
_asl_fikr = bot.GEMINI_FIKRLASH
bot.requests.post = _post_yoz
bot._chat_attempts = lambda: [
    ("gemini-3.5-flash", "gemini-3.5-flash", "http://g/1", {}, 32768),
    ("groq/qwen3.8-27b", "qwen/qwen3.8-27b", "http://q/1", {}, 8192)]
try:
    bot.GEMINI_FIKRLASH = ""
    _yuborilgan.clear(); bot._chat_request({"max_tokens": 100, "messages": []}, label="s")
    check("env bo'sh -> reasoning_effort YUBORILMAYDI",
          all("reasoning_effort" not in b for b in _yuborilgan), _yuborilgan)
    bot.GEMINI_FIKRLASH = "low"
    _yuborilgan.clear(); bot._chat_request({"max_tokens": 100, "messages": []}, label="s")
    check("env=low -> Gemini so'rovida reasoning_effort=low",
          _yuborilgan and _yuborilgan[0].get("reasoning_effort") == "low", _yuborilgan)
    # Gemini kesilsa qwen'ga o'tadi — qwen'ga reasoning_effort BERILMAYDI
    def _post_kes(url, headers=None, json=None, timeout=None, **kw):
        _yuborilgan.append(dict(json or {}))
        if "gemini" in (json or {}).get("model", ""):
            return _SoxtaJavob("g", "length", "kesik")
        return _SoxtaJavob("q", "stop", "To'liq. " * 10)
    bot.requests.post = _post_kes
    _yuborilgan.clear(); out, err = bot._chat_request({"max_tokens": 100, "messages": []}, label="s")
    check("qwen so'rovida reasoning_effort YO'Q (Groq rad etardi)",
          len(_yuborilgan) == 2 and "reasoning_effort" not in _yuborilgan[1], _yuborilgan)
    check("Gemini kesilsa qwen to'liq javob beradi", out and "To'liq" in out, out)
finally:
    bot.GEMINI_FIKRLASH = _asl_fikr
    bot.requests.post = _asl_post
    bot._chat_attempts = _asl_att

print("[6] TARJIMA — parafraza taqiqlandi, asl matn ham yuboriladi")
# Foydalanuvchi shikoyati (2026-09-02): "gaplarini o'zgartirib tashlagan".
# Eski promptdagi "literary style" va "IDIOMS" qoidalari modelga gapni
# qayta yozishga ruxsat berardi.
# Izohda eski qoidalar tarix sifatida eslatiladi — PROMPT matnining
# o'zini tekshiramiz (izoh qatorlari chiqarib tashlanadi).
_bs = _m.find("base_system = (")
_prompt_kodi = "\n".join(q for q in _m[_bs:_bs + 2500].split("\n")
                         if not q.lstrip().startswith("#"))
check("'literary style' ruxsati promptdan olib tashlandi",
      "literary style" not in _prompt_kodi)
check("'IDIOMS' almashtirish ruxsati promptdan olib tashlandi",
      "use equivalent expressions" not in _prompt_kodi)
check("tarjima o'zini TRANSKRIPT tarjimoni deb biladi",
      "VERBATIM TRANSCRIPT" in _m)
check("gaplarni birlashtirish/parafraza taqiqlangan",
      "Do NOT merge, split, reorder or paraphrase" in _m)
check("buzuq gapni 'tuzatish' taqiqlangan (ma'no to'qish eng og'ir xato)",
      "NEVER 'repair'" in _m)
check("vaqt belgilari joyida qoladi",
      "copy them unchanged" in _m)

# Asl matn yetkazilishi — xulq darajasida
_asl_tr = bot.translate_with_claude
_asl_pdf = getattr(bot, "_send_pdf_variant")
_asl_msg = bot.telegram_send_message
_pdflar = []
ruscha_matn = ("Сегодня мы говорим о важной теме. " * 40).strip()
try:
    bot.translate_with_claude = (
        lambda text, source_lang, progress_cb=None, target_lang="uz",
        lost_chunks_out=None: "Bugun muhim mavzu haqida gaplashamiz. " * 40)
    bot._send_pdf_variant = (
        lambda uid, matn, fayl, izoh, **k: _pdflar.append(
            {"fayl": fayl, "matn": matn, "izoh": izoh}) or True)
    bot.telegram_send_message = lambda *a, **k: True
    natija = bot.ensure_uzbek_text(1, ruscha_matn, notify=True)
    check("tarjima qaytdi", "Bugun muhim mavzu" in (natija or ""), natija)
    check("asl matn PDF yuborildi", len(_pdflar) == 1, _pdflar)
    if _pdflar:
        check("asl matn o'z ichida (ustoz gapi)",
              "Сегодня мы говорим" in _pdflar[0]["matn"])
        check("izohda maqsad tushuntirilgan",
              "solishtirib" in _pdflar[0]["izoh"], _pdflar[0]["izoh"])
    # notify=False (ichki oqimlar) da PDF yuborilmaydi
    _pdflar.clear()
    bot.ensure_uzbek_text(1, ruscha_matn, notify=False)
    check("notify=False da asl PDF yuborilmaydi", _pdflar == [], _pdflar)
finally:
    bot.translate_with_claude = _asl_tr
    bot._send_pdf_variant = _asl_pdf
    bot.telegram_send_message = _asl_msg

print(f"\nJami: {ok} PASS, {fail} FAIL")
sys.exit(1 if fail else 0)
