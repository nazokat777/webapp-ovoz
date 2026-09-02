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

print(f"\nJami: {ok} PASS, {fail} FAIL")
sys.exit(1 if fail else 0)
