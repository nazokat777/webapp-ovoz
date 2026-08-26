@echo off
REM ============================================================
REM  Botni SHU KOMPYUTERDA ishga tushirish (Railway'siz)
REM
REM  Nega kerak: Railway deploy'i ishlamayotgan bo'lsa ham, bot
REM  shu yerdan to'liq ishlaydi — siz uni sinab ko'rasiz va
REM  mijozlaringiz uzilib qolmaydi.
REM
REM  Talab: .env fayli to'ldirilgan bo'lsin (.env.example dan
REM  nusxa oling). Kamida BOT_TOKEN va OPENAI_API_KEY kerak.
REM ============================================================
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo ============================================================
echo   Audio ^& Konspekt bot - lokal ishga tushirish
echo ============================================================
echo.

if not exist ".env" (
    echo [!] .env fayli topilmadi.
    echo.
    echo     Hoziroq yarataymi? .env.example dan nusxa olinadi,
    echo     keyin uni ochib BOT_TOKEN va OPENAI_API_KEY yozasiz.
    echo.
    choice /C YN /M "Nusxa olinsinmi (Y/N)"
    if errorlevel 2 goto :eof
    copy ".env.example" ".env" >nul
    echo.
    echo [OK] .env yaratildi. Endi u Notepad'da ochiladi —
    echo      BOT_TOKEN va OPENAI_API_KEY ni to'ldiring va SAQLANG.
    echo.
    pause
    notepad ".env"
    echo.
    echo Tayyor bo'lsangiz davom etamiz.
    pause
)

REM Python'ni topish: py launcher, keyin PATH'dagi python
set PYEXE=
where py >nul 2>nul && set PYEXE=py -3
if "%PYEXE%"=="" (
    where python >nul 2>nul && set PYEXE=python
)
if "%PYEXE%"=="" (
    echo [XATO] Python topilmadi. python.org dan o'rnating.
    pause
    goto :eof
)

echo [1/3] Kutubxonalar tekshirilmoqda...
%PYEXE% -c "import telegram, aiohttp, fpdf, pypdf, edge_tts, yt_dlp" 2>nul
if errorlevel 1 (
    echo       Yetishmayotganlari o'rnatilmoqda ^(bir marta^)...
    %PYEXE% -m pip install -q -r requirements.txt
    if errorlevel 1 (
        echo [XATO] Kutubxonalarni o'rnatib bo'lmadi.
        pause
        goto :eof
    )
)
echo       OK

echo [2/3] ffmpeg tekshirilmoqda...
where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo       [!] ffmpeg topilmadi - audio/video ishlamaydi.
    echo           O'rnatish: winget install Gyan.FFmpeg
    echo           ^(PDF va matn xizmatlari busiz ham ishlayveradi^)
) else (
    echo       OK
)

echo [3/3] Bot ishga tushirilmoqda...
echo.
echo ------------------------------------------------------------
echo  To'xtatish uchun: Ctrl+C
echo  Holat sahifasi:   http://localhost:8000/health
echo ------------------------------------------------------------
echo.

%PYEXE% bot.py

echo.
echo Bot to'xtadi. Sabab yuqorida yozilgan.
pause
