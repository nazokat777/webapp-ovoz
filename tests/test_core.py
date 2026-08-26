"""Tuzatilgan mantiq uchun smoke testlar (tarmoqsiz, API chaqirilmaydi)."""
import os, sys, json, time, tempfile

os.environ["BOT_TOKEN"] = "123456:TEST"
os.environ["ADMIN_USER_ID"] = "111, 222"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bot

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ok = fail = 0
def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1; print(f"  PASS  {name}")
    else:
        fail += 1; print(f"  FAIL  {name} {extra}")

print("\n[1] ADMIN_USER_IDS parsing")
check("vergul bilan 2 ta admin", bot.ADMIN_USER_IDS == {111, 222}, bot.ADMIN_USER_IDS)
check("_is_admin_id(111)", bot._is_admin_id(111) is True)
check("_is_admin_id(999)", bot._is_admin_id(999) is False)
check("_is_admin_id('111') string ham", bot._is_admin_id("111") is True)
check("_is_admin_id(None)", bot._is_admin_id(None) is False)

class U:
    def __init__(s, uid, uname=None): s.id, s.username = uid, uname
check("ID sozlangan -> username admin QILMAYDI",
      bot._is_admin_user(U(999, "nazokat_571")) is False)
check("ID mos -> admin", bot._is_admin_user(U(222)) is True)

print("\n[2] estimate_tts_duration_sec")
check("bo'sh -> 0", bot.estimate_tts_duration_sec("") == 0)
check("1400 belgi ~100 sek", 90 <= bot.estimate_tts_duration_sec("x" * 1400) <= 110)
check("har doim musbat", bot.estimate_tts_duration_sec("ab") >= 1)

print("\n[3] _tg_ok")
class R:
    def __init__(s, code, body): s.status_code, s.text = code, json.dumps(body)
    def json(s): return json.loads(s.text)
check("200 + ok:true -> True", bot._tg_ok(R(200, {"ok": True}), "t") is True)
check("200 + ok:false -> False", bot._tg_ok(R(200, {"ok": False}), "t") is False)
check("400 -> False", bot._tg_ok(R(400, {"ok": False}), "t") is False)
check("None -> False", bot._tg_ok(None, "t") is False)

print("\n[4] _format_lost_chunks_text")
txt = bot._format_lost_chunks_text([(3, 10)])
check("yo'qolgan bo'laklar matni bor", txt and "3/10" in txt and "30%" in txt, txt)
check("bo'sh ro'yxat -> None", bot._format_lost_chunks_text([]) is None)

print("\n[22] md_escape — Markdown buzilmasin")
check("_ qochiriladi", bot.md_escape("Ali_Vali") == r"Ali\_Vali", bot.md_escape("Ali_Vali"))
check("* qochiriladi", bot.md_escape("Nodira*") == r"Nodira\*")
check("` qochiriladi", bot.md_escape("a`b") == r"a\`b")
check("[ qochiriladi", bot.md_escape("[Bek]") == r"\[Bek]")
check("bo'sh -> bo'sh satr", bot.md_escape("") == "" and bot.md_escape(None) == "")
check("oddiy matn o'zgarmaydi", bot.md_escape("Salom dunyo") == "Salom dunyo")
check("raqam ham ishlaydi", bot.md_escape(123) == "123")
src_bot = open(os.path.join(ROOT, "bot.py"), encoding="utf-8").read()
check("qo'lda escape zanjirlari qolmadi",
      src_bot.count('.replace("_", "\\\\_")') <= 1)  # faqat ADMIN_CONTACT_MD

print("\n[5] _unclear_marker_note")
check("[?] yo'q -> bo'sh", bot._unclear_marker_note("toza matn") == "")
check("[?] bor -> sanaydi", "2 ta [?]" in bot._unclear_marker_note("a[?] b[?]"))

print("\n[6] download_audio_from_url — sxema tekshiruvi")
for bad in ["--config-location=/tmp/x", "file:///etc/passwd", "-o/tmp/x", "ftp://x"]:
    try:
        bot.download_audio_from_url(bad)
        check(f"rad etildi: {bad}", False, "istisno bo'lmadi")
    except Exception as e:
        check(f"rad etildi: {bad}", "http" in str(e).lower())

print("\n[7] extract_url — /url endpoint uchun")
check("oddiy matn -> None", bot.extract_url("--exec=rm -rf /") is None)
check("https -> qaytaradi", bot.extract_url("qara https://youtu.be/abc ok") == "https://youtu.be/abc")

print("\n[8] tariff log kesh")
d = tempfile.mkdtemp()
bot.TARIFF_LOG_FILE = os.path.join(d, "tariff_log.jsonl")
bot._tariff_log_cache.update({"mtime": None, "size": None, "map": {}})
bot.user_tariffs.clear()
check("fayl yo'q -> {}", bot._get_tariff_log_map() == {})
bot._append_tariff_log(555, "pro_max", source="test")
check("yozilgach o'qiladi", bot._get_tariff_log_map().get(555) == "pro_max")
check("get_user_tariff log'dan tiklaydi", bot.get_user_tariff(555) == "pro_max")
bot._append_tariff_log(555, "free", source="revoke")
bot.user_tariffs.pop(555, None)
check("revoke keyin free", bot.get_user_tariff(555) == "free")
m1 = bot._get_tariff_log_map()
check("kesh bir xil obyekt (qayta o'qimadi)", bot._get_tariff_log_map() is m1)

print("\n[9] MAX_UPLOAD / MAX_AUDIO_CHUNKS")
check("MAX_UPLOAD_BYTES = 300MB", bot.MAX_UPLOAD_BYTES == 300 * 1024 * 1024)
check("MAX_AUDIO_CHUNKS = 100", bot.MAX_AUDIO_CHUNKS == 100)
check("5 soat qamrov", bot.MAX_AUDIO_CHUNKS * bot.WHISPER_CHUNK_SECONDS == 18000)

print("\n[10] Muxlisa marshruti")
bot.MUXLISA_KEY = "fake"
bot.user_tariffs.clear()
bot._tariff_log_cache.update({"mtime": None, "size": None, "map": {}})
bot.TARIFF_LOG_FILE = os.path.join(d, "empty.jsonl")
check("MUXLISA_FOR_FREE default False", bot.MUXLISA_FOR_FREE is False)
bot.user_tariffs[10] = "pro_max"
bot.user_tariffs[11] = "premium"
def _is_pro(uid):
    t = bot.get_user_tariff(uid)
    return t.startswith("pro_") or t == "pro"
check("pro_max -> pro", _is_pro(10) is True)
check("premium (standart) -> pro emas", _is_pro(11) is False)

print(f"\nNatija: {ok} pass, {fail} fail")
sys.exit(1 if fail else 0)
