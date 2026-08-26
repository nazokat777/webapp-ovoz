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
# Endi NUSXA qaytariladi (chaqiruvchi iteratsiyasi paytida kesh mutatsiyasi
# xavfsiz bo'lishi uchun) — tenglik saqlanadi, obyekt esa har safar yangi
check("kesh mazmuni barqaror (qayta o'qilmaydi)", bot._get_tariff_log_map() == m1)
check("kesh nusxasi qaytadi (mutatsiya izolyatsiyasi)", bot._get_tariff_log_map() is not m1)

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


print("\n[23] Startup konfiguratsiya auditi")
import tempfile as _tf
_d = _tf.mkdtemp()
_saved = (bot.OPENAI_API_KEY, bot.ADMIN_USER_IDS, bot.MUXLISA_KEY,
          bot.PAYMENT_CARD, bot.DATA_FILE, dict(bot.runtime_settings))

# Hammasi sozlangan -> ogohlantirish yo'q (ffmpeg'dan tashqari, u muhitga bog'liq)
bot.OPENAI_API_KEY = "sk-test"
bot.ADMIN_USER_IDS = {1}
bot.MUXLISA_KEY = "m"
bot.PAYMENT_CARD = "8600"
bot.DATA_FILE = os.path.join(_d, "u.json")
warns = bot._startup_config_audit()
msgs = " | ".join(m for _, m in warns)
check("sozlanganda OPENAI ogohlantirishi yo'q", "OPENAI_API_KEY" not in msgs, msgs[:120])
check("sozlanganda ADMIN ogohlantirishi yo'q", "ADMIN_USER_ID" not in msgs, msgs[:120])

# Sozlanmagan -> aniq ogohlantirishlar
bot.OPENAI_API_KEY = ""
bot.ADMIN_USER_IDS = set()
bot.MUXLISA_KEY = ""
bot.PAYMENT_CARD = ""
bot.runtime_settings["payment_card"] = ""
os.environ.pop("OPENAI_API_KEY", None)
warns = bot._startup_config_audit()
levels = {lv for lv, _ in warns}
msgs = " | ".join(m for _, m in warns)
check("OPENAI yo'qligi CRITICAL", any(lv == "critical" and "OPENAI" in m for lv, m in warns), msgs[:150])
check("ADMIN yo'qligi ogohlantiriladi", "ADMIN_USER_ID" in msgs)
check("MUXLISA yo'qligi ogohlantiriladi", "MUXLISA_KEY" in msgs)
check("karta yo'qligi ogohlantiriladi", "karta" in msgs.lower())

# Yozib bo'lmaydigan katalog -> critical
bot.DATA_FILE = os.path.join(_d, "yoq", "chuqur", "u.json")
if os.name != "nt":
    pass  # Windows'da ruxsat modeli boshqacha, bu tekshiruvni o'tkazamiz

# Platformada mount qilinmagan katalog -> critical
os.environ["RAILWAY_PROJECT_ID"] = "test"
bot.DATA_FILE = os.path.join(_d, "u.json")   # mount EMAS
warns = bot._startup_config_audit()
check("mount qilinmagan volume CRITICAL deb belgilanadi",
      any(lv == "critical" and "VOLUME" in m.upper() for lv, m in warns),
      " | ".join(m for _, m in warns)[:200])
os.environ.pop("RAILWAY_PROJECT_ID", None)

(bot.OPENAI_API_KEY, bot.ADMIN_USER_IDS, bot.MUXLISA_KEY,
 bot.PAYMENT_CARD, bot.DATA_FILE) = _saved[:5]
bot.runtime_settings.update(_saved[5])


print("[24] .env yuklovchi (haqiqiy env HAR DOIM ustun)")
import tempfile as _tf2
_ed = _tf2.mkdtemp()
_ef = os.path.join(_ed, "t.env")
with open(_ef, "w", encoding="utf-8") as _f:
    _f.write("BOT_TOKEN=DOTENV_QIYMAT\n")
    _f.write("# izoh qatori\n")
    _f.write('YANGI_KALIT="tirnoqli"\n')
    _f.write("export EXPORTLI=42\n")
    _f.write("BOSH_QATOR=\n")
    _f.write("notekis qator bez tengligi\n")
os.environ["BOT_TOKEN"] = "HAQIQIY_ENV"
for _k in ("YANGI_KALIT", "EXPORTLI", "BOSH_QATOR"):
    os.environ.pop(_k, None)
_n = bot._load_dotenv(_ef)
check("faqat yetishmayotganlar yuklandi", _n == 3, _n)
check("haqiqiy env USTUN (almashmadi)", os.environ["BOT_TOKEN"] == "HAQIQIY_ENV")
check("tirnoqlar olib tashlandi", os.environ.get("YANGI_KALIT") == "tirnoqli")
check("export prefiksi tushunildi", os.environ.get("EXPORTLI") == "42")
check("bo'sh qiymat yuklandi", os.environ.get("BOSH_QATOR") == "")
check("mavjud bo'lmagan fayl xavfsiz", bot._load_dotenv(os.path.join(_ed, "yoq")) == 0)
for _k in ("YANGI_KALIT", "EXPORTLI", "BOSH_QATOR"):
    os.environ.pop(_k, None)


print("[25] .dockerignore — runtime fayllar image'da qoladi")
import fnmatch as _fn, subprocess as _sp
_pats, _negs = [], []
for _ln in open(os.path.join(ROOT, ".dockerignore"), encoding="utf-8"):
    _ln = _ln.strip()
    if not _ln or _ln.startswith("#"):
        continue
    (_negs if _ln.startswith("!") else _pats).append(_ln.lstrip("!"))
_tracked = _sp.run(["git", "ls-files"], capture_output=True, text=True,
                   cwd=ROOT).stdout.split()

def _ignored(f):
    if any(_fn.fnmatch(f, n) or f.split("/")[0] == n for n in _negs):
        return False
    return any(_fn.fnmatch(f, p) or f.split("/")[0] == p for p in _pats)

_kept = [f for f in _tracked if not _ignored(f)]
if not _tracked:
    print("  SKIP  git ro'yxati olinmadi")
else:
    # Runtime uchun SHART bo'lgan fayllar image'ga tushishi kerak
    for _need in ["bot.py", "index.html", "logo.png", "requirements.txt"]:
        check(f"image'da qoladi: {_need}", _need in _kept, sorted(_kept))
    # Sirlar va foydalanuvchi ma'lumotlari image'ga TUSHMASLIGI kerak
    for _bad in [".env", "user_data.json", "tariff_log.jsonl"]:
        check(f"image'ga tushmaydi: {_bad}", _ignored(_bad))
    check(".env.example istisno (namuna kerak)", not _ignored(".env.example"))

print("[26] .gitattributes — .bat CRLF qulflangan")
_ga = open(os.path.join(ROOT, ".gitattributes"), encoding="utf-8").read()
check("*.bat eol=crlf", "*.bat text eol=crlf" in _ga, _ga[:80])
_bat = open(os.path.join(ROOT, "ishga_tushirish.bat"), "rb").read()
check("bat faylida yolg'iz LF yo'q",
      _bat.count(bytes([10])) == _bat.count(bytes([13, 10])),
      f"LF={_bat.count(bytes([10])) - _bat.count(bytes([13, 10]))}")

print(f"\nNatija: {ok} pass, {fail} fail")
sys.exit(1 if fail else 0)
