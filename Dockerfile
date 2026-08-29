# Yagona build manbai. Ilgari nixpacks.toml va Procfile ham bor edi —
# ular olib tashlandi, chunki:
#   • Dockerfile mavjud bo'lsa Railway nixpacks.toml'ni umuman e'tiborga olmaydi;
#   • nixpacks.toml'da FONTLAR yo'q edi, ya'ni o'sha yo'l bilan qurilganda
#     PDF'lar Helvetica'ga tushib, o'/g' va kirill harflari buzilardi.
FROM python:3.12-slim

# ffmpeg — audio konvertatsiya/bo'laklash uchun MAJBURIY.
# fonts-dejavu / fonts-noto — PDF'da o'zbek o'/g', kirill va arab yozuvi uchun.
# curl/unzip — quyidagi Deno o'rnatishi uchun.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    unzip \
    ca-certificates \
    fonts-dejavu-core \
    fonts-dejavu-extra \
    fonts-noto \
    fonts-noto-core \
    && rm -rf /var/lib/apt/lists/*

# ── Deno: YouTube "n challenge" ni yechadigan JS runtime ────────────────────
# NODEJS EMAS. Ilgari bu yerda nodejs bor edi, lekin Debian'dagi Node 20 ni
# yt-dlp RAD ETADI. Serverda o'lchangan (2026-08-29):
#     JS runtimes: node-20.19.2 (unsupported)
#     JS Challenge Providers: node (unavailable), deno (unavailable) ...
#     -> "n challenge solving failed" -> YouTube'dan HECH QANDAY format kelmadi
# Deno o'rnatilgach o'sha video darrov ochildi (deno-2.9.6).
#
# Bu `yt-dlp-ejs` (requirements.txt) va cookies bilan BIRGA ishlaydi —
# uchtasidan biri yetishmasa YouTube baribir bermaydi.
RUN curl -fsSL -o /tmp/deno.zip \
      https://github.com/denoland/deno/releases/latest/download/deno-x86_64-unknown-linux-gnu.zip \
    && unzip -q /tmp/deno.zip -d /usr/local/bin \
    && chmod +x /usr/local/bin/deno \
    && rm /tmp/deno.zip \
    && deno --version

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Ma'lumotlar katalogi. Railway'da SHU YO'LGA volume mount qiling —
# aks holda user_data.json va tariff_log.jsonl har deploy'da yo'qoladi.
RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8000
CMD ["python", "bot.py"]
