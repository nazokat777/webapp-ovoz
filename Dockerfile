# Yagona build manbai. Ilgari nixpacks.toml va Procfile ham bor edi —
# ular olib tashlandi, chunki:
#   • Dockerfile mavjud bo'lsa Railway nixpacks.toml'ni umuman e'tiborga olmaydi;
#   • nixpacks.toml'da FONTLAR yo'q edi, ya'ni o'sha yo'l bilan qurilganda
#     PDF'lar Helvetica'ga tushib, o'/g' va kirill harflari buzilardi.
FROM python:3.12-slim

# ffmpeg — audio konvertatsiya/bo'laklash uchun MAJBURIY.
# fonts-dejavu / fonts-noto — PDF'da o'zbek o'/g', kirill va arab yozuvi uchun.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    ca-certificates \
    fonts-dejavu-core \
    fonts-dejavu-extra \
    fonts-noto \
    fonts-noto-core \
    && rm -rf /var/lib/apt/lists/*

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
