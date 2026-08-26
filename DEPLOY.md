# Deploy va sozlash

## 1. Majburiy env o'zgaruvchilar

Bot bularsiz **ishga tushmaydi**:

| Nomi | Nima uchun |
|---|---|
| `BOT_TOKEN` | BotFather tokeni. Kodda default qiymat **yo'q** — ataylab. |
| `OPENAI_API_KEY` | STT, matn tozalash, tarjima, TTS |

Juda tavsiya etiladi:

| Nomi | Nima uchun |
|---|---|
| `ADMIN_USER_ID` | Admin tekshiruvi. Sozlanmasa username fallback ishlaydi — bu xavfsiz emas (username bo'shatilsa boshqa odam egallashi mumkin). Bir nechta admin: `123,456` |

To'liq ro'yxat: [.env.example](.env.example)

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
| `INIT_DATA_MAX_AGE_HOURS` | 6 | WebApp imzosi amal qilish muddati (replay himoyasi) |

1 vCPU / 1 GB uchun `MAX_CONCURRENT_JOBS=3` mos. RAM qo'shsangiz oshiring.

Joriy holat: `/debug` → navbat, faol thread, sozlamalar.

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
