@echo off
REM ============================================================
REM  Botni SHU KOMPYUTERDA ishga tushirish (serversiz)
REM
REM  Server ishlamayotgan bo'lsa ham bot shu yerdan to'liq
REM  ishlaydi - mijozlaringiz uzilib qolmaydi.
REM
REM  ESLATMA: bu fayl CRLF qator oxirlari bilan saqlanishi SHART.
REM  LF bilan Windows uni buzib o'qiydi (echo. -> 'cho.' xatosi).
REM  .gitattributes buni kafolatlaydi.
REM ============================================================
chcp 65001 >nul
cd /d "%~dp0"

echo(
echo ============================================================
echo   Audio ^& Konspekt bot - lokal ishga tushirish
echo ============================================================
echo(

REM --- Python avval kerak: .env tekshiruvini ham u bajaradi -----
set "PYEXE="
where py >nul 2>nul && set "PYEXE=py -3"
if not defined PYEXE where python >nul 2>nul && set "PYEXE=python"
if not defined PYEXE goto :python_yoq

echo [1/6] Bot allaqachon ishlayaptimi...
REM Telegram bitta tokenga BITTA poller ruxsat beradi. Ikkinchi nusxa
REM ko'tarilsa IKKALASI ham 409 Conflict oladi va bot hech kimga javob
REM bermay qoladi - ya'ni 'yana bir marta ishga tushiray' degan zararsiz
REM harakat butun xizmatni to'xtatadi.
%PYEXE% "tools\already_running.py"
if errorlevel 1 goto :allaqachon
echo       OK

REM --- .env BOR-YO'QLIGI emas, ICHI ham tekshiriladi -------------
REM Ilgari faqat fayl bor-yo'qligi ko'rilardi. Bo'sh .env bilan bot
REM JIMGINA 'DEGRADED' rejimga tushib, hech kimga javob bermay turardi -
REM sabab esa faqat loglarda qolardi.
REM Tekshiruvni Python bajaradi: batch'ning findstr regexi ishonchsiz
REM (/R va /C: birga berilganda naqsh LITERAL deb olinadi).
:env_tekshir
echo [2/6] Sozlamalar tekshirilmoqda...
%PYEXE% "tools\env_check.py"
if errorlevel 4 goto :env_yarat
if errorlevel 3 goto :kalit_yoq
if errorlevel 2 goto :token_yoq

:env_bor
echo [3/6] Kutubxonalar tekshirilmoqda...
%PYEXE% -c "import telegram, aiohttp, fpdf, pypdf, edge_tts, yt_dlp" 2>nul
if not errorlevel 1 goto :kutubxona_ok
echo       Yetishmayotganlari o'rnatilmoqda (bir marta, biroz vaqt oladi)...
%PYEXE% -m pip install -q -r requirements.txt
if errorlevel 1 goto :pip_xato
:kutubxona_ok
echo       OK

echo [4/6] ffmpeg tekshirilmoqda...
where ffmpeg >nul 2>nul
if errorlevel 1 goto :ffmpeg_yoq
echo       OK
goto :ffmpeg_tekshirildi
:ffmpeg_yoq
echo       [!] ffmpeg topilmadi - audio/video ishlamaydi.
echo           O'rnatish: winget install Gyan.FFmpeg
echo           (PDF va matn xizmatlari busiz ham ishlayveradi)
:ffmpeg_tekshirildi

echo [5/6] Web ilova tunneli tekshirilmoqda...
REM Bot lokal ishlaganda Web ilova FAQAT tunnel orqali ochiladi.
REM Tunnel tushib qolsa bot ishlayveradi, lekin "Web ilovani ochish"
REM tugmasi o'lik sahifaga olib boradi va foydalanuvchi butun bot
REM buzuq deb o'ylaydi (amalda shunday bo'ldi). Shu sababli birga.
%PYEXE% "tools\tunnel_start.py"
if errorlevel 1 echo       (Web ilova ochilmaydi - bot Telegram ichida to'liq ishlayveradi)

echo [6/6] Bot ishga tushirilmoqda...
echo(
echo ------------------------------------------------------------
echo  To'xtatish uchun: Ctrl+C
echo  Holat sahifasi:   http://localhost:8000/health
echo ------------------------------------------------------------
echo(

REM Bot to'g'ridan-to'g'ri emas, NAZORATCHI orqali ishga tushiriladi.
REM Sabab: Telegram bilan aloqa vaqtinchalik uzilganda bot butunlay
REM o'lib qolardi (telegram.error.TimedOut -> exited with code 1) va
REM xizmat nazoratsiz to'xtardi. Nazoratchi uni qayta ko'taradi,
REM lekin sozlama xato bo'lsa cheksiz aylanmaydi.
%PYEXE% "tools\nazoratchi.py"

echo(
echo Bot to'xtadi. Sabab yuqorida yozilgan.
:allaqachon
echo(
echo Ishga tushirish TO'XTATILDI - ikkinchi nusxa zarar keltirardi.
goto :tugadi

goto :tugadi

:env_yarat
echo(
echo     .env.example dan nusxa olinadi.
copy ".env.example" ".env" >nul
echo     [OK] .env yaratildi. Notepad ochiladi - to'ldiring va SAQLANG.
echo(
pause
notepad ".env"
goto :env_tekshir

:token_yoq
echo(
echo     Telegram'da @BotFather ga kiring:
echo       /mybots  ^>  botingizni tanlang  ^>  API Token
echo     Tokenni nusxalab, .env faylga shunday yozing:
echo       BOT_TOKEN=123456:ABC...
echo(
echo     Notepad ochiladi. To'ldiring, SAQLANG (Ctrl+S), yoping.
echo(
pause
notepad ".env"
goto :env_tekshir

:kalit_yoq
echo(
echo     Busiz audio matnga aylanmaydi (asosiy xizmat).
echo     Kamida bittasi kerak - ikkalasi ham BEPUL, kartasiz:
echo       GROQ_API_KEY   - console.groq.com
echo       GEMINI_API_KEY - aistudio.google.com/apikey
echo(
set "JAVOB="
set /p "JAVOB=Kalit kiritasizmi? (h/y): "
if /I not "%JAVOB%"=="h" goto :env_bor
notepad ".env"
goto :env_tekshir

:python_yoq
echo [XATO] Python topilmadi. python.org dan o'rnating.
goto :tugadi

:pip_xato
echo [XATO] Kutubxonalarni o'rnatib bo'lmadi.
goto :tugadi

:tugadi
pause
