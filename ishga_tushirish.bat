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

REM --- .env BOR-YO'QLIGI emas, ICHI ham tekshiriladi -------------
REM Ilgari faqat fayl bor-yo'qligi ko'rilardi. Bo'sh .env bilan bot
REM JIMGINA 'DEGRADED' rejimga tushib, hech kimga javob bermay turardi -
REM sabab esa faqat loglarda qolardi.
REM Tekshiruvni Python bajaradi: batch'ning findstr regexi ishonchsiz
REM (/R va /C: birga berilganda naqsh LITERAL deb olinadi).
:env_tekshir
echo [1/5] Sozlamalar tekshirilmoqda...
%PYEXE% "tools\env_check.py"
if errorlevel 4 goto :env_yarat
if errorlevel 3 goto :kalit_yoq
if errorlevel 2 goto :token_yoq

:env_bor
echo [2/5] Kutubxonalar tekshirilmoqda...
%PYEXE% -c "import telegram, aiohttp, fpdf, pypdf, edge_tts, yt_dlp" 2>nul
if not errorlevel 1 goto :kutubxona_ok
echo       Yetishmayotganlari o'rnatilmoqda (bir marta, biroz vaqt oladi)...
%PYEXE% -m pip install -q -r requirements.txt
if errorlevel 1 goto :pip_xato
:kutubxona_ok
echo       OK

echo [3/5] ffmpeg tekshirilmoqda...
where ffmpeg >nul 2>nul
if errorlevel 1 goto :ffmpeg_yoq
echo       OK
goto :ffmpeg_tekshirildi
:ffmpeg_yoq
echo       [!] ffmpeg topilmadi - audio/video ishlamaydi.
echo           O'rnatish: winget install Gyan.FFmpeg
echo           (PDF va matn xizmatlari busiz ham ishlayveradi)
:ffmpeg_tekshirildi

echo [4/5] Web ilova tunneli tekshirilmoqda...
REM Bot lokal ishlaganda Web ilova FAQAT tunnel orqali ochiladi.
REM Tunnel tushib qolsa bot ishlayveradi, lekin "Web ilovani ochish"
REM tugmasi o'lik sahifaga olib boradi va foydalanuvchi butun bot
REM buzuq deb o'ylaydi (amalda shunday bo'ldi). Shu sababli birga.
%PYEXE% "tools\tunnel_start.py"
if errorlevel 1 echo       (Web ilova ochilmaydi - bot Telegram ichida to'liq ishlayveradi)

echo [5/5] Bot ishga tushirilmoqda...
echo(
echo ------------------------------------------------------------
echo  To'xtatish uchun: Ctrl+C
echo  Holat sahifasi:   http://localhost:8000/health
echo ------------------------------------------------------------
echo(

%PYEXE% bot.py

echo(
echo Bot to'xtadi. Sabab yuqorida yozilgan.
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
echo     Busiz audio/video matnga aylanmaydi (asosiy xizmat).
echo     Kalit olish: https://platform.openai.com/api-keys
echo(
set "JAVOB="
set /p "JAVOB=Kalitni hozir kiritasizmi? (h/y): "
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
