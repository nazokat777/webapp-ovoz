"""13-18 bosqichlar uchun sinovlar."""
import os, sys, time, json, tempfile, threading

os.environ["BOT_TOKEN"] = "123456:TEST"
os.environ["ADMIN_USER_ID"] = "111"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bot

ok = fail = 0
def check(name, cond, extra=""):
    global ok, fail
    if cond: ok += 1; print(f"  PASS  {name}")
    else: fail += 1; print(f"  FAIL  {name} {extra}")

d = tempfile.mkdtemp()
bot.DATA_FILE = os.path.join(d, "user_data.json")
bot.TARIFF_LOG_FILE = os.path.join(d, "tariff_log.jsonl")
bot._tariff_log_cache.update({"mtime": None, "size": None, "map": {}})

def reset():
    for c in (bot.user_tariffs, bot.user_uzbek_usage, bot.user_bonus_minutes,
              bot.user_referral_minutes, bot._recent_grants):
        c.clear()

print("\n[13] Grant idempotentligi")
reset()
c1 = bot._activate_tariff_with_carryover(500, "basic", source="approve")
check("1-grant qabul qilindi", c1 == 0, c1)
check("tarif o'rnatildi", bot.user_tariffs[500] == "basic")
c2 = bot._activate_tariff_with_carryover(500, "basic", source="approve")
check("2-grant (takroriy) rad etildi", c2 is None, c2)
check("bonus o'zgarmadi", bot.user_bonus_minutes.get(500, 0) == 0,
      bot.user_bonus_minutes.get(500))
c3 = bot._activate_tariff_with_carryover(500, "basic", source="approve", force=True)
check("force bilan o'tadi", c3 is not None)
# Boshqa tarif — dedupe kaliti boshqa, o'tishi kerak
c4 = bot._activate_tariff_with_carryover(500, "premium", source="approve")
check("boshqa tarif bloklanmaydi", c4 is not None)

print("\n[13b] Carryover ikki barobar bo'lmasligi")
reset()
bot._activate_tariff_with_carryover(600, "basic", source="t")   # 180 daq
bot.add_user_usage(600, 60 * 60)                                 # 60 daq ishlatdi
before = bot.get_user_limit_sec(600) // 60
dup = bot._activate_tariff_with_carryover(600, "basic", source="t")
check("takroriy grant limitni oshirmadi",
      dup is None and bot.get_user_limit_sec(600) // 60 == before,
      f"{before} -> {bot.get_user_limit_sec(600)//60}")

print("\n[14] restore ↔ tariff log moslashtirish")
reset()
bot._append_tariff_log(700, "pro_max", source="approve")
bot._tariff_log_cache.update({"mtime": None, "size": None, "map": {}})
check("log'da pro_max", bot.get_user_tariff(700) == "pro_max")
# Backup tiklandi deb faraz: xotirada endi bu user yo'q
bot.user_tariffs.clear()
n = bot._reconcile_tariff_log_with_memory(source="restore")
check("moslashtirish yozuv qo'shdi", n >= 1, n)
check("endi log ham free", bot.get_user_tariff(700) == "free",
      bot.get_user_tariff(700))

print("\n[15] last_transcripts — RAM, diskka yozilmaydi")
bot.last_transcripts.clear()
bot.remember_transcript(1, "salom dunyo")
check("RAM'da bor", bot.last_transcripts[1]["text"] == "salom dunyo")
bot._save_user_data()
saved = json.load(open(bot.DATA_FILE, encoding="utf-8"))
check("JSON'da last_transcripts YO'Q", "last_transcripts" not in saved,
      list(saved.keys()))
# TTL va hajm chegarasi
bot.last_transcripts.clear()
bot.last_transcripts[99] = {"text": "eski", "ts": time.time() - 90000}
bot.remember_transcript(100, "yangi")
check("eskirgan tozalandi", 99 not in bot.last_transcripts)
bot.last_transcripts.clear()
for i in range(bot.LAST_TRANSCRIPTS_MAX + 25):
    bot.last_transcripts[i] = {"text": "x", "ts": time.time() - (1000 - i)}
bot.remember_transcript(99999, "oxirgi")
check(f"hajm <= {bot.LAST_TRANSCRIPTS_MAX}",
      len(bot.last_transcripts) <= bot.LAST_TRANSCRIPTS_MAX, len(bot.last_transcripts))
check("eng yangisi saqlandi", 99999 in bot.last_transcripts)

print("\n[16] Job navbati")
bot._job_stats.update({"running": 0, "queued": 0})
done = []
gate = threading.Event()
def slow(tag):
    gate.wait(5); done.append(tag)
accepted = [bot.submit_job(1, slow, (i,), label="t") for i in range(5)]
check("hammasi qabul qilindi (navbat limitidan kam)", all(accepted))
time.sleep(0.4)
run, q = bot._job_slots_info()
check(f"bir vaqtda <= {bot.MAX_CONCURRENT_JOBS} ishlayapti",
      run <= bot.MAX_CONCURRENT_JOBS, f"running={run}")
gate.set()
for _ in range(60):
    if len(done) == 5: break
    time.sleep(0.1)
check("hamma ish yakunlandi", len(done) == 5, len(done))
run, q = bot._job_slots_info()
check("hisoblagichlar 0 ga qaytdi", (run, q) == (0, 0), (run, q))

print("\n[16b] Navbat to'lganda rad etish + fayl tozalash")
bot._job_stats.update({"running": 0, "queued": bot.MAX_QUEUED_JOBS})
tmpf = os.path.join(d, "rad.tmp")
open(tmpf, "w").write("x")
res = bot.submit_job(1, lambda: None, (), label="t", cleanup_path=tmpf)
check("to'la navbat rad etadi", res is False)
time.sleep(0.2)
check("vaqtinchalik fayl o'chirildi", not os.path.exists(tmpf))
bot._job_stats.update({"running": 0, "queued": 0})

print("\n[17] Retry kutish vaqti")
src = open(r"D:\webapp ovoz\bot.py", encoding="utf-8").read()
check("whisper_pass_waits qisqartirildi", "whisper_pass_waits = [15, 45, 90]" in src)

print("\n[18] O'lik kod tozalandi")
for name in ("_uzbek_transcription_quality", "_is_fatal_error", "GOOGLE_LANG",
             "_sr_recognizer", "ARABIC_FONT_CANDIDATES", "_restore_lost_paid_users",
             "_cleanup_mixed_uzbek_arabic"):
    check(f"{name} yo'q", not hasattr(bot, name))
check("speech_recognition import qilinmagan", "speech_recognition" not in sys.modules)
reqs = open(r"D:\webapp ovoz\requirements.txt", encoding="utf-8").read()
check("requirements'da SpeechRecognition yo'q", "SpeechRecognition" not in reqs)
check("nixpacks.toml o'chirildi", not os.path.exists(r"D:\webapp ovoz\nixpacks.toml"))
check("hardcoded user ID yo'q", "8128034276" not in src)

print(f"\nNatija: {ok} pass, {fail} fail")
sys.exit(1 if fail else 0)
