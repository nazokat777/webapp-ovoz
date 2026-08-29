#!/usr/bin/env bash
# ============================================================================
#  Botni Linux serverga BITTA BUYRUQ bilan o'rnatadi (HTTPS bilan).
#
#  Foydalanish (server terminalida, root sifatida):
#      bash <(curl -sL https://raw.githubusercontent.com/nazokat777/webapp-ovoz/main/tools/server_setup.sh)
#
#  Yoki repo klonlangan bo'lsa:
#      bash tools/server_setup.sh
#
#  NIMA QILADI:
#    1. Docker o'rnatadi (yo'q bo'lsa)
#    2. Reponi /opt/webapp-ovoz ga klonlaydi yoki yangilaydi
#    3. Serverning tashqi IP sini topib HTTPS manzil hosil qiladi
#    4. .env ni so'raydi/yangilaydi (kalitlarni siz kiritasiz)
#    5. Botni va Caddy (HTTPS) ni --restart=always bilan ko'taradi
#
#  NEGA HTTPS MAJBURIY: Telegram Web ilovasi FAQAT https manzilni ochadi.
#  Oddiy http://IP:8000 da tugma bosilganda oq ekran chiqadi va foydalanuvchi
#  butun bot buzuq deb o'ylaydi. Shuning uchun sertifikat ixtiyoriy emas.
#
#  DOMEN SOTIB OLISH SHART EMAS: sslip.io har qanday IP ni domenga aylantiradi
#  (1-2-3-4.sslip.io -> 1.2.3.4). Caddy shu nom uchun Let's Encrypt dan
#  bepul sertifikat oladi va o'zi yangilab turadi.
#
#  NEGA --restart=always: bot yiqilsa yoki server qayta yuklansa Docker uni
#  O'ZI ko'taradi. Bu "o'chib qolmasin" degan talabning texnik javobi.
#
#  MA'LUMOT XAVFSIZLIGI: /data volume qayta deploy'da saqlanadi, ustiga bot
#  har kuni bazani adminning Telegramiga yuboradi. Ya'ni butun server
#  o'chirilsa ham nusxa telefonda qoladi (hosting "Backups" xizmati bunday
#  holatda yordam bermaydi — u server bilan birga o'chadi).
# ============================================================================
set -euo pipefail

REPO="https://github.com/nazokat777/webapp-ovoz.git"
DIR="/opt/webapp-ovoz"
NOM="ovozbot"
TARMOQ="ovoznet"
PORT="${PORT:-8000}"

yashil() { printf "\033[32m%s\033[0m\n" "$*"; }
sariq()  { printf "\033[33m%s\033[0m\n" "$*"; }
qizil()  { printf "\033[31m%s\033[0m\n" "$*"; }

if [ "$(id -u)" -ne 0 ]; then
  qizil "Bu skript root sifatida ishlashi kerak:  sudo bash $0"
  exit 1
fi

# ── 1. Docker ───────────────────────────────────────────────────────────────
if ! command -v docker >/dev/null 2>&1; then
  yashil "[1/7] Docker o'rnatilmoqda..."
  curl -fsSL https://get.docker.com | sh
else
  yashil "[1/7] Docker allaqachon bor: $(docker --version)"
fi
systemctl enable --now docker >/dev/null 2>&1 || true

# ── 2. Kod ──────────────────────────────────────────────────────────────────
if [ -d "$DIR/.git" ]; then
  yashil "[2/7] Kod yangilanmoqda..."
  git -C "$DIR" fetch --quiet origin
  git -C "$DIR" reset --hard origin/main --quiet
else
  yashil "[2/7] Kod klonlanmoqda..."
  command -v git >/dev/null 2>&1 || (apt-get update -qq && apt-get install -y -qq git)
  rm -rf "$DIR"
  git clone --quiet "$REPO" "$DIR"
fi
cd "$DIR"
echo "     joriy commit: $(git log --oneline -1)"

# ── 3. Tashqi IP va HTTPS manzil ────────────────────────────────────────────
yashil "[3/7] Tashqi IP aniqlanmoqda..."
IP="${SERVER_IP:-}"
for manba in \
  "http://169.254.169.254/metadata/v1/interfaces/public/0/ipv4/address" \
  "https://api.ipify.org" \
  "https://ifconfig.me/ip"
do
  if [ -n "$IP" ]; then break; fi
  IP="$(curl -s -m 5 "$manba" 2>/dev/null | tr -d '[:space:]' || true)"
  # Faqat haqiqiy IPv4 ni qabul qilamiz — xato sahifasi HTML qaytarsa
  # u domenga aylanib, sertifikat olinmay qolardi.
  echo "$IP" | grep -Eq '^[0-9]{1,3}(\.[0-9]{1,3}){3}$' || IP=""
done
if [ -z "$IP" ]; then
  qizil "Tashqi IP topilmadi. Qo'lda bering:  SERVER_IP=1.2.3.4 bash $0"
  exit 1
fi
SAYT="$(echo "$IP" | tr '.' '-').sslip.io"
SAYT_URL="https://${SAYT}"
echo "     IP: $IP"
echo "     Manzil: $SAYT_URL"

# ── 3b. Swap ────────────────────────────────────────────────────────────────
# 1 GB RAM li serverda Ubuntu o'zi ~300 MB oladi. 3 soatlik ma'ruzani qayta
# ishlashda yuklab olish + ffmpeg 300-500 MB talab qiladi — chegara juda yaqin.
# Swap bo'lmasa Linux OOM killer botni JIMGINA o'ldiradi: xato xabari yo'q,
# logda sabab ko'rinmaydi, foydalanuvchi esa "bot yana o'chdi" deydi.
# 2 GB swap 25 GB diskdan joy oladi va sekinroq ishlaydi — lekin o'lishdan
# ko'ra sekin ishlagan yaxshi.
if [ -f /swapfile ]; then
  yashil "[3b/7] Swap allaqachon bor"
elif [ "$(free -m 2>/dev/null | awk '/^Mem:/{print $2}')" -ge 2048 ] 2>/dev/null; then
  yashil "[3b/7] Xotira yetarli, swap kerak emas"
else
  yashil "[3b/7] Swap yaratilmoqda (2 GB)..."
  fallocate -l 2G /swapfile 2>/dev/null \
    || dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  # Server qayta yuklansa swap o'zi qaytishi uchun
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  echo "     swap: $(free -m | awk '/^Swap:/{print $2}') MB"
fi

# ── 4. Sozlamalar ───────────────────────────────────────────────────────────
mkdir -p /data

env_yoz() {   # kalit qiymat — bor bo'lsa almashtiradi, yo'q bo'lsa qo'shadi
  local k="$1" v="$2"
  if grep -q "^${k}=" /data/.env 2>/dev/null; then
    sed -i "s|^${k}=.*|${k}=${v}|" /data/.env
  else
    echo "${k}=${v}" >> /data/.env
  fi
}

if [ -f /data/.env ]; then
  yashil "[4/7] Mavjud /data/.env ishlatiladi"
else
  sariq "[4/7] Sozlamalar kerak. Kalitlarni kiriting (bo'sh qoldirsa ham bo'ladi)."
  echo "     Kalitlar EKRANDA KO'RINMAYDI — joylashtirib Enter bosavering."
  echo

  # Kalit yozilayotganda ekranda ko'rinmasligi kerak: server konsolining
  # ekran rasmi tez-tez olinadi va bitta rasm butun botni begonaga beradi.
  # read -rs joylashtirishga ham ishlaydi, faqat hech narsa chizilmaydi —
  # shuning uchun uzunligini qaytarib, kiritilganini tasdiqlaymiz.
  sir_sora() {
    local nom="$1" savol="$2" qiymat=""
    read -rsp "  $savol" qiymat
    echo
    if [ -n "$qiymat" ]; then
      echo "     ✓ qabul qilindi (${#qiymat} belgi)"
    else
      echo "     — bo'sh qoldirildi"
    fi
    printf -v "$nom" '%s' "$qiymat"
  }

  sir_sora V_BOT  "BOT_TOKEN (majburiy)      : "
  sir_sora V_GROQ "GROQ_API_KEY (bepul)      : "
  sir_sora V_GEM  "GEMINI_API_KEY (bepul)    : "
  sir_sora V_MUX  "MUXLISA_KEY (premium)     : "
  # Bu sir emas — oddiy raqam, ko'rinib tursa xavf yo'q va xatoni sezish oson.
  read -rp "  ADMIN_USER_ID             : " V_ADM
  cat > /data/.env <<EOF
BOT_TOKEN=$V_BOT
GROQ_API_KEY=$V_GROQ
GEMINI_API_KEY=$V_GEM
MUXLISA_KEY=$V_MUX
ADMIN_USER_ID=$V_ADM
DATA_FILE=/data/user_data.json
EOF
  echo "     /data/.env yaratildi"
fi
chmod 600 /data/.env

# WEBAPP_URL ni O'ZIMIZ to'ldiramiz — foydalanuvchi qo'lda yozsa xato qiladi.
# Eski ngrok manzili qolib ketsa Web ilova o'lik havolaga olib borardi.
JORIY_WEB="$(grep '^WEBAPP_URL=' /data/.env 2>/dev/null | cut -d= -f2- || true)"
case "$JORIY_WEB" in
  ""|*ngrok*|*sslip.io*|*railway*)
    env_yoz "WEBAPP_URL" "$SAYT_URL"
    echo "     WEBAPP_URL = $SAYT_URL"
    ;;
  *)
    echo "     WEBAPP_URL o'zgartirilmadi (o'z domeningiz): $JORIY_WEB"
    ;;
esac
env_yoz "DATA_FILE" "/data/user_data.json"

# ── 5. Qurish ───────────────────────────────────────────────────────────────
yashil "[5/7] Docker image qurilmoqda (birinchi marta 3-5 daqiqa)..."
docker build -q -t "$NOM:latest" . >/dev/null

# ── 6. Ishga tushirish ──────────────────────────────────────────────────────
yashil "[6/7] Konteynerlar ko'tarilmoqda..."
docker network create "$TARMOQ" >/dev/null 2>&1 || true

docker rm -f "$NOM" >/dev/null 2>&1 || true
# Port FAQAT localhost'ga ochiladi: tashqariga Caddy HTTPS orqali chiqaradi.
# 0.0.0.0:8000 ochiq qolsa bot shifrsiz http'da ham javob berardi.
docker run -d \
  --name "$NOM" \
  --restart=always \
  --network "$TARMOQ" \
  --env-file /data/.env \
  -v /data:/data \
  -p "127.0.0.1:${PORT}:8000" \
  "$NOM:latest" >/dev/null

cat > /data/Caddyfile <<EOF
${SAYT} {
    reverse_proxy ${NOM}:8000
}
EOF

docker rm -f caddy >/dev/null 2>&1 || true
docker run -d \
  --name caddy \
  --restart=always \
  --network "$TARMOQ" \
  -p 80:80 -p 443:443 \
  -v /data/Caddyfile:/etc/caddy/Caddyfile:ro \
  -v caddy_data:/data \
  -v caddy_config:/config \
  caddy:2 >/dev/null

# Let's Encrypt 80/443 orqali tekshiradi — yopiq bo'lsa sertifikat kelmaydi.
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
  ufw allow 80/tcp  >/dev/null 2>&1 || true
  ufw allow 443/tcp >/dev/null 2>&1 || true
  echo "     ufw: 80 va 443 ochildi"
fi

# ── 7. Tekshirish ───────────────────────────────────────────────────────────
yashil "[7/7] Tekshirilmoqda..."
sleep 8
if ! docker ps --filter "name=$NOM" --filter "status=running" | grep -q "$NOM"; then
  qizil "❌ Bot konteyneri ko'tarilmadi. Log:"
  docker logs --tail 40 "$NOM" || true
  exit 1
fi
echo "     bot: ishlayapti"

if curl -s -m 10 "http://127.0.0.1:${PORT}/health" | grep -q '"status"'; then
  echo "     health: javob bermoqda"
else
  sariq "     health hali javob bermadi (bot yuklanayotgan bo'lishi mumkin)"
fi

printf "     HTTPS sertifikati olinmoqda"
HTTPS_OK=0
for _ in $(seq 1 24); do
  if curl -s -m 8 "${SAYT_URL}/health" 2>/dev/null | grep -q '"status"'; then
    HTTPS_OK=1
    break
  fi
  printf "."
  sleep 5
done
echo
if [ "$HTTPS_OK" -eq 1 ]; then
  yashil "✅ Hammasi ishlayapti: $SAYT_URL"
else
  sariq "⚠️  HTTPS hali tayyor emas. Odatda 1-2 daqiqada keladi."
  echo "    Tekshirish : curl -v ${SAYT_URL}/health"
  echo "    Caddy log  : docker logs --tail 30 caddy"
  echo "    Sabablari  : 80/443 portlari yopiq, yoki IP hali tarqalmagan."
fi

echo
echo "  Web ilova manzili : $SAYT_URL"
echo "  Holat tekshirish  : curl -s ${SAYT_URL}/health"
echo "  Log ko'rish       : docker logs -f $NOM"
echo "  Qayta ishga tush  : docker restart $NOM"
echo "  Yangilash         : bash $DIR/tools/server_setup.sh"
echo
echo "  Ma'lumotlar /data da — qayta deploy'da YO'QOLMAYDI."
echo "  --restart=always: server qayta yuklansa bot O'ZI ko'tariladi."
echo "  Bot har kuni bazani Telegramingizga zaxira qilib yuboradi."
echo
sariq "  ESLATMA: botda eski tugmalar qolgan bo'lsa /keshyangila yuboring."
echo
