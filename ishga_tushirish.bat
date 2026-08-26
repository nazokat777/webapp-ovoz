@echo off
REM ============================================================
REM  Botni SHU KOMPYUTERDA ishga tushirish (Railway'siz)
REM
REM  Railway deploy'i ishlamayotgan bo'lsa ham bot shu yerdan
REM  to'liq ishlaydi - mijozlaringiz uzilib qolmaydi.
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

if not exist ".env" goto :env_yoq
goto :env_bor

:env_yoq
echo [!] .env fayli topilmadi.
echo(
echo     .env.example dan nusxa olinadi, keyin uni to'ldirasiz.
echo(
set "JAVOB="
set /p "JAVOB=Nusxa olinsinmi? (h/y): "
if /I not "%JAVOB%"=="h" goto :tugadi
copy ".env.example" ".env" >nul
echo(
echo [OK] .env yaratildi. Hozir Notepad'da ochiladi -
echo      BOT_TOKEN va OPENAI_API_KEY ni to'ldiring va SAQLANG.
echo(
pause
notepad ".env"
echo(
echo Tayyor bo'lsangiz davom etamiz.
pause

:env_bor
REM Python'ni topish: py launcher, keyin PATH'dagi python
set "PYEXE="
where py >nul 2>nul && set "PYEXE=py -3"
if not defined PYEXE where python >nul 2>nul && set "PYEXE=python"
if not defined PYEXE goto :python_yoq

echo [1/3] Kutubxonalar tekshirilmoqda...
%PYEXE% -c "import telegram, aiohttp, fpdf, pypdf, edge_tts, yt_dlp" 2>nul
if not errorlevel 1 goto :kutubxona_ok
echo       Yetishmayotganlari o'rnatilmoqda (bir marta)...
%PYEXE% -m pip install -q -r requirements.txt
if errorlevel 1 goto :pip_xato
:kutubxona_ok
echo       OK

echo [2/3] ffmpeg tekshirilmoqda...
where ffmpeg >nul 2>nul
if errorlevel 1 goto :ffmpeg_yoq
echo       OK
goto :ffmpeg_tekshirildi
:ffmpeg_yoq
echo       [!] ffmpeg topilmadi - audio/video ishlamaydi.
echo           O'rnatish: winget install Gyan.FFmpeg
echo           (PDF va matn xizmatlari busiz ham ishlayveradi)
:ffmpeg_tekshirildi

echo [3/3] Bot ishga tushirilmoqda...
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

:python_yoq
echo [XATO] Python topilmadi. python.org dan o'rnating.
goto :tugadi

:pip_xato
echo [XATO] Kutubxonalarni o'rnatib bo'lmadi.
goto :tugadi

:tugadi
pause
