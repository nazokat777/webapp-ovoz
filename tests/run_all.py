"""Barcha sinovlarni bitta buyruq bilan ishga tushirish.

Foydalanish:
    python tests/run_all.py

Tarmoq talab qilmaydi, OpenAI/Telegram API chaqirilmaydi — faqat sof mantiq.
"""
import os
import subprocess
import sys

# Windows konsoli cp1251 bo'lsa emoji chop etishda yiqiladi
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
SUITES = ["test_auth.py", "test_core.py", "test_env_check.py",
          "test_providers.py", "test_tunnel.py",
          "test_tariffs.py", "test_davom.py", "test_lang_route.py", "test_billing_queue.py",
          "test_text_pipeline.py", "test_media_pipeline.py", "test_stt_integration.py",
          "test_http_e2e.py"]  # oxirgisi haqiqiy HTTP server ko'taradi

total_fail = 0
for name in SUITES:
    print(f"\n{'=' * 60}\n{name}\n{'=' * 60}")
    r = subprocess.run([sys.executable, os.path.join(HERE, name)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    for line in (r.stdout or "").splitlines():
        # logging chiqishini o'tkazib yuboramiz
        if line.startswith("20") and " - " in line:
            continue
        print(line)
    if r.returncode != 0:
        total_fail += 1
        if r.stderr:
            print(r.stderr[-2000:])

print(f"\n{'=' * 60}")
if total_fail:
    print(f"❌ {total_fail} ta sinov to'plami yiqildi")
else:
    print("✅ Barcha sinov to'plamlari o'tdi")
sys.exit(1 if total_fail else 0)
