# Deploy va sozlash

## 1. Env o'zgaruvchilar

### Majburiy

| Nomi | Nima uchun |
|---|---|
| `BOT_TOKEN` | BotFather tokeni. Kodda default qiymat **yo'q** — ataylab. Busiz bot DEGRADED rejimga tushadi: HTTP server ko'tariladi va har so'rovga sababni aytadi. |

### AI provayderlari — kamida bittasi kerak

Zanjir **sifat tartibida** tuziladi, narx tartibida emas. Kaliti yo'q
provayder umuman chaqirilmaydi, ya'ni bitta kalit bilan ham bot ishlaydi.
Biri limitga urilsa (`429`) keyingisi darhol o'rnini bosadi.

| Nomi | Nima beradi | Bepulmi |
|---|---|---|
| `GROQ_API_KEY` | audio→matn (whisper-large-v3) **va** matn modeli | ✅ kartasiz, ~2000 so'rov/kun |
| `GEMINI_API_KEY` | tarjima va matn tozalash (eng aniq) | ✅ kartasiz |
| `OPENAI_API_KEY` | audio→matn, matn, premium TTS | ❌ pullik |
| `MUXLISA_KEY` | o'zbek STT — eng yuqori sifat, faqat `pro_*` tariflar uchun | ❌ pullik |

**O'zbek sifati bo'yicha o'lchov** (bir xil "iflos" transkript hamma modelga berildi):

| Model | So'z aniqligi | Vaqt |
|---|---|---|
| `gemini-3.5-flash` | 100.0% | 13.6s |
| `groq/qwen3.8-27b` | 96.6% | 1.0s |
| `gemini-3.1-flash-lite` | 94.7% | 1.3s |

Ishlatilmaydiganlar: `gemini-2.5-pro` (404 — yangi hisoblarga berilmaydi),
`gemini-3.7-flash` (503 — doimiy band), `llama-3.3-70b` (Groq'dan olib tashlangan).

> **MUHIM:** Groq'ga `language=uz` yuborilishi shart. Yuborilmasa u o'zbek
> nutqini **arab yozuvida** qaytaradi (`اسلام علیکم` = `assalomu alaykum`) —
> tovushlar to'g'ri, matn yaroqsiz. Buni `GROQ_STT_LANGS` hal qiladi.

### Juda tavsiya etiladi

| Nomi | Nima uchun |
|---|---|
| `ADMIN_USER_ID` | Admin tekshiruvi. Sozlanmasa username fallback ishlaydi — bu xavfsiz emas (username bo'shatilsa boshqa odam egallashi mumkin). Bir nechta admin: `123,456` |
| `WEBAPP_URL` | Web ilova manzili. Sozlanmasa tugma **berkitiladi** (o'lik tugmadan yo'q tugma yaxshi). |

To'liq ro'yxat: [.env.example](.env.example)

### Tekshirish

```
python tools/env_check.py       # .env to'liqmi
python tools/provider_check.py  # kalitlar HAQIQIY API'da ishlaydimi
```

Ikkinchisi muhim: noto'g'ri kalit aks holda faqat birinchi audio kelganda
bilinadi — foydalanuvchi kutib turadi va xato oladi.

## 1b. Lokal ishga tushirish (serversiz)

Server ishlamayotgan bo'lsa ham bot shu kompyuterda to'liq ishlaydi:

**`ishga_tushirish.bat`** ni ikki marta bosing. U ketma-ket:

1. Python'ni topadi
2. `.env` ICHINI tekshiradi (bo'sh token bilan jim DEGRADED rejimga tushmaslik uchun)
3. Kutubxonalar va `ffmpeg` ni tekshiradi
4. **Web ilova tunnelini ko'taradi** (`WEBAPP_URL` ngrok bo'lsa)
5. Botni ishga tushiradi

Tunnel ko'tarilmasa bot baribir ishlaydi — faqat Web ilova ochilmaydi,
Telegram ichidagi hamma narsa (audio, video, PDF, tarjima) joyida qoladi.

> Telegram cheklovi: bot chatga yuborilgan fayldan faqat **20 MB** gacha
> yuklab ola oladi. Uzun ma'ruza (2-3 soat) uchun **Web ilova** orqali
> yuboring — u botning o'z serveriga boradi, chegara `MAX_UPLOAD_MB` (300).

## 1c. Tariflar va kunlik limit

**Bepul tarif KUNLIK:** har kuni 60 daqiqa qaytadan beriladi
(`TARIFFS["free"]["daily"] = True`). Hisob `user_daily_usage`
`{user_id: [kun, soniya]}` shaklida yuritiladi — kechagi sarf bugungi
limitni yemaydi.

**Pullik (Premium) tariflar bir martalik:** daqiqalar tugaguncha amal
qiladi, umrbod jamlanadi. Faqat ular Muxlisa AI (o'zbekka maxsus STT)
ga kirish beradi.

**Standart tariflar sotuvdan olindi** (`"hidden": True`). Kalitlar
ATAYLAB qoldirilgan: kod `TARIFFS[...]` ni 32 joyda to'g'ridan-to'g'ri
indekslaydi va kalit o'chirilsa eski xaridorlarda `KeyError` bo'lib bot
yiqilardi.

> **Bonus daqiqalar kunlik tarifga QO'SHILMAYDI.** Bonus (referral +
> carryover) bir martalik. Kunlik tarifda qo'shilsa, bir martalik sovg'a
> cheksiz obunaga aylanardi — Premium'dan qolgan 500 daqiqa har kuni
> qayta berilardi. Bonus pooli saqlanadi va Premium olinganda ishlaydi.

### Uzun audio: qisman ishlash va davom ettirish

3 soatlik ma'ruza 60 daqiqalik kunlik limitga sig'maydi. Ilgari bunday
fayl **butunlay rad etilardi**. Endi:

1. Qolgan limit qancha bo'lsa, audioning shuncha qismi qayta ishlanadi
2. To'xtagan nuqta `davom_holati` da saqlanadi (`user_data.json` ichida)
3. Foydalanuvchi ertaga **`/davom`** yuboradi — aynan o'sha joydan davom etadi

| Sozlama | Qiymat | Izoh |
|---|---|---|
| `DAVOM_MIN_SEK` | 300 | 5 daqiqadan kam qolgan bo'lsa boshlanmaydi |
| `DAVOM_TTL_KUN` | 7 | saqlangan audio shuncha kundan keyin o'chadi |
| `DAVOM_MAX_MB` | 2000 | papka chegarasi, eng eskilari o'chiriladi |

Havoladan kelgan audio uchun faqat **havola** saqlanadi (qayta yuklab
olish ~85 MB diskdan arzon). Fayl uchun siqilgan nusxa `davomi/`
papkasida turadi — u `.gitignore` da.

## 2. Doimiy saqlash (MUHIM)

Kod Railway'ni aniqlasa `DATA_FILE` ni `/data/user_data.json` ga qo'yadi.
**Railway'da `/data` ga volume mount qilinishi shart** — aks holda har deploy'da
tariflar, foydalanish hisobi va tarif jurnali yo'qoladi.

Tekshirish: botda `/debug` → `DATA_FILE` yo'li va fayl hajmi ko'rinadi.
Zaxira: `/backup` (fayl Telegram'ga keladi) → tiklash: shu faylga reply qilib `/restore`.

## 3. Build

Yagona manba — [Dockerfile](Dockerfile). `nixpacks.toml` va `Procfile` olib
tashlandi: Dockerfile mavjud bo'lsa Railway nixpacks'ni e'tiborga olmaydi, va
nixpacks konfiguratsiyasida **fontlar yo'q** edi — u yo'l bilan qurilganda
PDF'lardagi `o'`, `g'` va kirill harflari buzilardi.

Dockerfile o'rnatadi: `ffmpeg` (audio uchun majburiy), `nodejs` (yt-dlp'ning
YouTube imzo yechishi uchun — busiz ko'p YouTube havolalari ishlamaydi),
DejaVu + Noto fontlari (PDF uchun majburiy). Bot YouTube himoyasi
o'zgarganda yt-dlp'ni o'zi yangilashga urinadi (6 soatda ko'pi bilan 1 marta).

## 4. Resurs sozlamalari

| Env | Default | Izoh |
|---|---|---|
| `MAX_UPLOAD_MB` | 300 | Fayl RAM'ga emas, bo'lak-bo'lak diskka yoziladi |
| `MAX_CONCURRENT_JOBS` | 3 | Bir vaqtda nechta og'ir ish — GLOBAL cap (WebApp + Telegram birga). Har ish ichida yana 4 ta parallel so'rov bor |
| `MAX_QUEUED_JOBS` | 12 | Navbat to'lsa foydalanuvchi darrov ochiq rad javobini oladi |
| `MUXLISA_FOR_FREE` | o'chiq | Yoqilsa bepul tarif ham Muxlisa'ga ketadi (~7x qimmat) |
| `INIT_DATA_MAX_AGE_HOURS` | 24 | WebApp imzosi amal qilish muddati; qisqartirish = xavfsizroq, lekin ochiq turgan WebApp'dan kelgan yozuv auth'dan yiqilishi mumkin |

1 vCPU / 1 GB uchun `MAX_CONCURRENT_JOBS=3` mos. RAM qo'shsangiz oshiring.

Joriy holat: `/debug` → navbat, faol thread, sozlamalar.

## 4.5 Holat va DEGRADED rejim

`GET /health` — bir so'rovda deploy holati (navbat, admin/OpenAI sozlanganmi,
DATA_FILE yo'li). Sirlarni oshkor qilmaydi.

- `200 {"status":"ok"}` — bot to'liq ishlayapti
- `503 {"status":"degraded","reason":...}` — bot sozlanmagan (masalan
  `BOT_TOKEN` yo'q). Bunday holatda jarayon **o'lmaydi**: HTTP server tirik
  qoladi, HAMMA endpoint 503 + sabab qaytaradi va log har daqiqada
  ogohlantiradi.

Nega shunday: ilgari `BOT_TOKEN` bo'lmasa jarayon `sys.exit(1)` qilardi —
Railway'da deployment yaratilmasdi va domen "Application not found" degan
sirli javob berardi, sabab esa faqat deploy logida qolardi. Endi nosozlik
KO'RINADI. Bu xatoni yashirish emas: hech qanday ish qabul qilinmaydi
(tokensiz imzoni tekshirib bo'lmaydi, shuning uchun barcha so'rov rad etiladi).

## 4.6 Startup konfiguratsiya auditi

Bot ishga tushganda JIM ishlaydigan noto'g'ri sozlamalarni topib, logda
baland ovozda e'lon qiladi, `/health` ichida qaytaradi, jiddiylarini
adminga Telegram orqali yuboradi va `/debug` da ko'rsatadi:

| Tekshiruv | Daraja | Nima bo'ladi sozlanmasa |
|---|---|---|
| STT provayderi (Groq **yoki** OpenAI) | jiddiy | audio matnga aylanmaydi |
| Matn modeli (Gemini / Groq / OpenAI) | jiddiy | tarjima va imlo tozalash ishlamaydi |
| `OPENAI_API_KEY` | ogohlantirish | faqat premium OpenAI TTS ishlamaydi (Edge TTS zaxira) |
| `ffmpeg` | jiddiy | audio/video umuman qayta ishlanmaydi |
| `/data` MOUNT qilinganmi | jiddiy | **tariflar har deploy'da yo'qoladi** |
| `ADMIN_USER_ID` | ogohlantirish | admin faqat username bo'yicha (xavfli) |
| `MUXLISA_KEY` | ogohlantirish | Premium tarif Whisper'ga tushadi |
| To'lov kartasi | ogohlantirish | `/buy` oqimi chala |

Volume tekshiruvi `os.path.ismount()` orqali: yo'l NOMI hech narsani
isbotlamaydi, chunki kod Railway'da uni majburan `/data` qiladi. Mount
qilinmagan `/data` — konteyner ichidagi vaqtinchalik disk.

## 4.7 Lokal ishga tushirish

To'liq yo'riqnoma yuqorida: **[1b. Lokal ishga tushirish](#1b-lokal-ishga-tushirish-serversiz)**.

Qisqacha: `.env` ni to'ldiring va `ishga_tushirish.bat` ni bosing. Skript
takroriy nusxadan saqlaydi, sozlamani tekshiradi, tunnelni ko'taradi va
botni nazoratchi ostida ishga tushiradi.

> `OPENAI_API_KEY` **majburiy emas** — Groq va Gemini uni almashtiradi.
> `.env` ni bot O'ZI o'qiydi (tashqi kutubxonasiz), haqiqiy env
> o'zgaruvchilari har doim ustun turadi.

WebApp Telegram'dan ochilishi uchun HTTPS domen kerak (ngrok yoki server).
Telegram tomonidagi barcha xizmatlar domensiz ham ishlayveradi.

## 5. Sinovlar

```bash
python tests/run_all.py
```

Tarmoq talab qilmaydi, hech qanday API chaqirilmaydi. Qamrov: WebApp imzo
tekshiruvi, admin autentifikatsiyasi, hisob-kitob (billing), navbat, tarif
jurnali keshi, URL sxema validatsiyasi.

## 6. Deploy'dan keyin tekshirish ro'yxati

1. `/debug` — `DATA_FILE` `/data/...` da va `ADMIN_USER_IDS` bo'sh emas
2. `/balance` — javob beradi
3. WebApp'dan qisqa audio → 2 ta PDF keladi
4. Boshqa akkauntdan `/start` → limitlar to'g'ri ko'rinadi

## 7. Xavfsizlik eslatmalari

- Bot tokeni **hech qachon** kodga yozilmaydi. Sirlar faqat env'da.
- `.env` git'da kuzatilmaydi (`.gitignore`).
- WebApp so'rovlari Telegram `initData` HMAC imzosi bilan tasdiqlanadi —
  imzo kaliti bot tokenidan olinadi. **Token tarqalsa bu himoya ham kuchsiz**,
  shuning uchun token oshkor bo'lsa BotFather'da `/revoke` qiling.
