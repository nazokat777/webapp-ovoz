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
n, absent = bot._reconcile_tariff_log_with_memory(source="restore")
# XAVFSIZLIK: backup'da YO'Q pullik user endi avtomatik 'free' QILINMAYDI —
# u "absent" ro'yxatida qaytadi va jurnal himoyasida qoladi.
check("yozuv qo'shilmadi (mass-downgrade yo'q)", n == 0, n)
check("absent ro'yxatida", 700 in absent, absent)
check("log'da hali pro_max (himoya)", bot.get_user_tariff(700) == "pro_max",
      bot.get_user_tariff(700))
# Backup'da user BOR va farq qilsa — yoziladi (restore pasaytira oladi)
bot.user_tariffs[700] = "basic"
n2, absent2 = bot._reconcile_tariff_log_with_memory(source="restore")
check("backup'dagi farq yozildi", n2 == 1 and 700 not in absent2, (n2, absent2))
bot.user_tariffs.pop(700, None)
bot._tariff_log_cache.update({"mtime": None, "size": None, "map": {}})
check("endi log basic deydi", bot.get_user_tariff(700) == "basic",
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

print("\n[16] Job navbati — parallellik cheklovi")
bot._job_stats.update({"running": 0, "queued": 0})
bot.processing_users.clear()
done = []
gate = threading.Event()
def slow(tag):
    gate.wait(5); done.append(tag)
# HAR BIR ish boshqa foydalanuvchidan — duplicate guard xalaqit qilmasin
accepted = [bot.submit_job(1000 + i, slow, (i,), label="t") for i in range(5)]
check("5 xil userdan hammasi qabul qilindi", all(accepted), accepted)
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
check("processing belgilari tozalandi", not bot.processing_users, bot.processing_users)

print("\n[20] Duplicate-click himoyasi (barcha oqim uchun)")
bot._job_stats.update({"running": 0, "queued": 0})
bot.processing_users.clear()
gate2 = threading.Event()
done2 = []
def slow2():
    gate2.wait(5); done2.append(1)
first = bot.submit_job(2000, slow2, (), label="t")
check("1-ish qabul qilindi", first is True)
dup_tmp = os.path.join(d, "dup.tmp")
open(dup_tmp, "w").write("x")
second = bot.submit_job(2000, slow2, (), label="t", cleanup_path=dup_tmp)
check("2-ish (shu user) rad etildi", second is False)
time.sleep(0.2)
check("rad etilgan ishning fayli o'chirildi", not os.path.exists(dup_tmp))
other = bot.submit_job(2001, slow2, (), label="t")
check("boshqa user bloklanmaydi", other is True)
gate2.set()
for _ in range(60):
    if len(done2) == 2: break
    time.sleep(0.1)
check("tugagach belgi olib tashlandi", not bot._is_user_processing(2000))

print("\n[16b] Navbat to'lganda rad etish + fayl tozalash")
bot._job_stats.update({"running": 0, "queued": bot.MAX_QUEUED_JOBS})
bot.processing_users.clear()
tmpf = os.path.join(d, "rad.tmp")
open(tmpf, "w").write("x")
res = bot.submit_job(3000, lambda: None, (), label="t", cleanup_path=tmpf)
check("to'la navbat rad etadi", res is False)
time.sleep(0.2)
check("vaqtinchalik fayl o'chirildi", not os.path.exists(tmpf))
bot._job_stats.update({"running": 0, "queued": 0})

print("\n[21] Saqlash keshi — xavfsizlik kafolati buzilmagan")
bot.user_tariffs.clear(); bot.user_uzbek_usage.clear(); bot.user_info.clear()
bot._last_written_counts["ready"] = False
bot.user_tariffs.update({1: "basic", 2: "premium"})
bot.user_uzbek_usage.update({1: 10, 2: 20})
bot.user_info.update({1: {"a": 1}, 2: {"a": 2}})
bot._save_user_data()
check("kesh to'ldi", bot._last_written_counts["ready"] is True)
check("kesh sonlari to'g'ri", bot._last_written_counts["tariffs"] == 2)

# O'sish — o'tishi kerak
bot.user_tariffs[3] = "basic"; bot.user_uzbek_usage[3] = 5; bot.user_info[3] = {"a": 3}
bot._save_user_data()
disk = json.load(open(bot.DATA_FILE, encoding="utf-8"))
check("o'sish saqlandi", len(disk["tariffs"]) == 3, len(disk["tariffs"]))

# Kamayish — abort qilib, xotirani diskdan to'ldirishi kerak
bot.user_tariffs.pop(3); bot.user_uzbek_usage.pop(3); bot.user_info.pop(3)
bot._save_user_data()
check("kamayish abort qilindi va tiklandi",
      3 in bot.user_tariffs and len(bot.user_tariffs) == 3, len(bot.user_tariffs))
disk = json.load(open(bot.DATA_FILE, encoding="utf-8"))
check("diskdagi ma'lumot yo'qolmadi", len(disk["tariffs"]) == 3)
check("JSON'da last_transcripts yo'q", "last_transcripts" not in disk)

print("\n[17] Retry kutish vaqti")
src = open(r"D:\webapp ovoz\bot.py", encoding="utf-8").read()
check("whisper_pass_waits qisqartirildi", "whisper_pass_waits = [30, 60, 180]" in src)

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



print("\n[R2] Yangi tur: atomik mark, revoke-dedupe, busy_guard, YT throttle")
# Atomik try-mark
bot.processing_users.clear()
tok1 = bot._try_mark_processing(4000)
check("try_mark 1-marta token (truthy)", bool(tok1), tok1)
check("try_mark 2-marta None", bot._try_mark_processing(4000) is None)
# EGALIK: begona token bilan unmark ISHLAMAYDI
bot._unmark_processing(4000, token=999999)
check("begona token unmark qilolmadi", bot._is_user_processing(4000) is True)
bot._unmark_processing(4000, token=tok1)
check("egasining tokeni unmark qildi", bot._is_user_processing(4000) is False)
tok2 = bot._try_mark_processing(4000)
check("unmark'dan keyin yana token", bool(tok2))
bot._unmark_processing(4000, tok2)

# Grant dedupe: revoke'dan keyin qayta berish o'tadi
reset()
bot._activate_tariff_with_carryover(5000, "basic", source="approve")
check("dup hali bloklaydi", bot._activate_tariff_with_carryover(5000, "basic", source="approve") is None)
# /revoke simulyatsiyasi: tarif free + dedupe kaliti tozalanadi
bot.user_tariffs[5000] = "free"
with bot._grant_lock:
    for k in [k for k in bot._recent_grants if k[0] == 5000]:
        bot._recent_grants.pop(k, None)
c = bot._activate_tariff_with_carryover(5000, "basic", source="approve")
check("revoke'dan keyin qayta grant o'tadi", c is not None, c)
# Dedupe endi SOF vaqt-oynali (holat sharti ATAYLAB yo'q — eskirgan approve
# tugmasi 5 daq ichida boshqa grant ustidan qayta ishlamasin). Kalit
# tozalanmagan bo'lsa, hatto tarif farq qilsa ham dup hisoblanadi:
reset()
bot._activate_tariff_with_carryover(5001, "basic", source="approve")
bot.user_tariffs[5001] = "free"   # revoke, lekin kalit tozalanmagan deb faraz
c2 = bot._activate_tariff_with_carryover(5001, "basic", source="approve")
check("kalit tozalanmagan -> hali dup", c2 is None, c2)

# busy_guard: oddiy async oqim
import asyncio as _aio
class _Msg:
    def __init__(self): self.texts = []
    async def reply_text(self, t, **kw): self.texts.append(t)
class _Upd:
    def __init__(self, uid):
        class U: pass
        self.effective_user = U(); self.effective_user.id = uid
        self.effective_user.username = None
        self.effective_user.first_name = "Test"
        self.effective_user.last_name = ""
        self.effective_user.language_code = "uz"
        self.message = _Msg()
calls = []
@bot.busy_guard
async def _flow(update, context):
    calls.append(1)
    # guard ichida qayta kirish (nested) bloklanmasligi kerak
    return await _inner(update, context)
@bot.busy_guard
async def _inner(update, context):
    calls.append(2)
    return "ok"
async def _scenario():
    u = _Upd(6000)
    r1 = await _flow(u, None)
    # Guard tugagach belgi olib tashlangan bo'lishi kerak
    free_after = not bot._is_user_processing(6000)
    # Band paytda ikkinchi chaqiruv rad etiladi (token sxemasi)
    _tok = bot._try_mark_processing(6000)
    u2 = _Upd(6000)
    r2 = await _flow(u2, None)
    bot._unmark_processing(6000, _tok)
    return r1, free_after, r2, u2.message.texts
r1, free_after, r2, busy_texts = _aio.run(_scenario())
check("busy_guard ichida nested chaqiruv ishlaydi", r1 == "ok" and calls == [1, 2], (r1, calls))
check("guard tugagach belgi olib tashlandi", free_after)
check("band paytda rad + xabar", r2 is None and len(busy_texts) == 1, (r2, busy_texts))

# yt-dlp self-update throttle (real pip chaqirmaymiz)
bot._yt_dlp_last_update["ts"] = bot.time.time()
check("yaqinda yangilangan -> False (throttle)", bot._try_self_update_yt_dlp() is False)

# _run_heavy statistikasi
async def _rh():
    return await bot._run_heavy(lambda a, b: a + b, 2, 3)
check("_run_heavy natija", _aio.run(_rh()) == 5)
run, q = bot._job_slots_info()
check("_run_heavy hisobi 0 ga qaytdi", (run, q) == (0, 0), (run, q))



print("\n[R3] Workflow-topilmalari: navbat cap, JobQueueFullError, tarjima holati")
# _run_heavy navbat to'la bo'lsa JobQueueFullError ko'taradi
bot._job_stats.update({"running": 0, "queued": bot.MAX_QUEUED_JOBS})
async def _rh_full():
    try:
        await bot._run_heavy(lambda: 1)
        return "yiqilmadi"
    except bot.JobQueueFullError:
        return "raised"
check("navbat to'la -> JobQueueFullError", _aio.run(_rh_full()) == "raised")
bot._job_stats.update({"running": 0, "queued": 0})

# busy_guard JobQueueFullError'ni QUEUE_FULL_MESSAGE javobiga aylantiradi
@bot.busy_guard
async def _always_full(update, context):
    raise bot.JobQueueFullError()
async def _scenario_full():
    u = _Upd(7000)
    r = await _always_full(u, None)
    return r, u.message.texts, bot._is_user_processing(7000)
r, texts, still = _aio.run(_scenario_full())
check("queue-full javobi yuborildi", r is None and len(texts) == 1 and "band" in texts[0], texts)
check("belgi tozalandi (queue-full'dan keyin)", still is False)

# Tarjima holati: peek O'CHIRMAYDI, pop o'chiradi
bot.pending_translations.clear()
bot.pending_translations[8000] = {"source": "ru", "target": "uz"}
check("peek holatni qaytaradi", bot._peek_translation_state(8000)["source"] == "ru")
check("peek holatni O'CHIRMADI", 8000 in bot.pending_translations)
check("pop holatni qaytaradi", bot._pop_translation_state(8000)["source"] == "ru")
check("pop holatni o'chirdi", 8000 not in bot.pending_translations)
# eski string format ham
bot.pending_translations[8001] = "en"
check("peek eski format", bot._peek_translation_state(8001) == {"source": "en", "target": "uz"})
bot.pending_translations.clear()

# INIT default konservativ 24h (env qisqartirishi mumkin)
check("INIT_DATA_MAX_AGE default 24h", bot.INIT_DATA_MAX_AGE == 24 * 3600,
      bot.INIT_DATA_MAX_AGE)

# Muxlisa retry ham qisqartirilgan
src2 = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bot.py"), encoding="utf-8").read()
check("muxlisa pass_waits ham [30,60,180]",
      "pass_waits = [30, 60, 180]  # 30s/1min/3min" in src2)  # muxlisa qatoriga xos izoh
check("eski [60,120,300] TAYINLASH qolmagan",
      "pass_waits = [60, 120, 300]" not in src2)  # izohda eslatma qolishi mumkin

# Kesh nusxasi: append paytida iteratsiya xavfsiz
bot.TARIFF_LOG_FILE = os.path.join(d, "iter.jsonl")
bot._tariff_log_cache.update({"mtime": None, "size": None, "map": {}})
bot._append_tariff_log(9001, "basic", source="t")
m = bot._get_tariff_log_map()
bot._append_tariff_log(9002, "basic", source="t")   # kesh ichida yangilanadi
check("olingan nusxa o'zgarmadi", 9002 not in m, sorted(m))
check("yangi so'rov yangisini ko'radi", 9002 in bot._get_tariff_log_map())



print("\n[R4] 4-tur: BaseException signal, admission, shartli pop")
# JobQueueFullError endi BaseException — ichki `except Exception` uni yutmaydi
check("JobQueueFullError BaseException'dan", issubclass(bot.JobQueueFullError, BaseException))
check("...lekin Exception'dan EMAS", not issubclass(bot.JobQueueFullError, Exception))
# Haqiqiy oqim shakli: ichki except Exception BOR — signal baribir guard'ga yetadi
@bot.busy_guard
async def _realistic(update, context):
    try:
        await bot._run_heavy(lambda: 1)
    except Exception:
        return "ichki-yutdi"   # bunga TUSHMASLIGI kerak
    return "ok"
bot._job_stats.update({"running": 0, "queued": bot.MAX_QUEUED_JOBS})
async def _sc():
    u = _Upd(9100)
    r = await _realistic(u, None)
    return r, u.message.texts
r, texts = _aio.run(_sc())
bot._job_stats.update({"running": 0, "queued": 0})
check("ichki except YUTMADI, guard javob berdi",
      r is None and len(texts) == 1 and "band" in texts[0], (r, texts))

# Admission: birinchi hop o'tgan oqimning KEYINGI hoplari cap'dan qaytarilmaydi
async def _two_hop():
    a = await bot._run_heavy(lambda: "hop1")
    bot._job_stats["queued"] = bot.MAX_QUEUED_JOBS   # oradagi spike
    try:
        b = await bot._run_heavy(lambda: "hop2")
    finally:
        bot._job_stats["queued"] = 0
    return a, b
check("2-hop spike'da ham o'tdi", _aio.run(_two_hop()) == ("hop1", "hop2"))
bot._job_stats.update({"running": 0, "queued": 0})

# Shartli pop: boshqa rejim o'chirilmaydi
bot.pending_translations.clear()
bot.pending_translations[9200] = {"source": "ru", "target": "uz"}
check("mos kelmasa pop YO'Q", bot._pop_translation_state_if(9200, "en", "uz") is False)
check("rejim joyida", 9200 in bot.pending_translations)
check("mos kelsa pop", bot._pop_translation_state_if(9200, "ru", "uz") is True)
check("rejim iste'mol qilindi", 9200 not in bot.pending_translations)
bot.pending_translations.clear()

# _mark_processing o'lik kod sifatida o'chirildi
check("_mark_processing yo'q", not hasattr(bot, "_mark_processing"))

print(f"\nNatija: {ok} pass, {fail} fail")
sys.exit(1 if fail else 0)
