#!/usr/bin/env bash
# ============================================================================
#  Botni Linux serverga BITTA BUYRUQ bilan o'rnatadi.
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
#    3. .env faylini so'raydi (kalitlarni siz kiritasiz)
#    4. Image quradi va konteynerni --restart=always bilan ishga tushiradi
#    5. Doimiy disk (/data) ulaydi — tariflar va foydalanuvchi ma'lumotlari
#       qayta deploy'da YO'QOLMAYDI
#
#  NEGA --restart=always: bot yiqilsa yoki server qayta yuklansa Docker uni
#  O'ZI ko'taradi. Bu "o'chib qolmasin" degan talabning texnik javobi.
# ============================================================================
set -euo pipefail

REPO="https://github.com/nazokat777/webapp-ovoz.git"
DIR="/opt/webapp-ovoz"
NOM="ovozbot"
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
  yashil "[1/5] Docker o'rnatilmoqda..."
  curl -fsSL https://get.docker.com | sh
else
  yashil "[1/5] Docker allaqachon bor: $(docker --version)"
fi
systemctl enable --now docker >/dev/null 2>&1 || true

# ── 2. Kod ──────────────────────────────────────────────────────────────────
if [ -d "$DIR/.git" ]; then
  yashil "[2/5] Kod yangilanmoqda..."
  git -C "$DIR" fetch --quiet origin
  git -C "$DIR" reset --hard origin/main --quiet
else
  yashil "[2/5] Kod klonlanmoqda..."
  command -v git >/dev/null 2>&1 || (apt-get update -qq && apt-get install -y -qq git)
  rm -rf "$DIR"
  git clone --quiet "$REPO" "$DIR"
fi
cd "$DIR"
echo "     joriy commit: $(git log --oneline -1)"

# ── 3. Sozlamalar ───────────────────────────────────────────────────────────
mkdir -p /data
if [ -f /data/.env ]; then
  yashil "[3/5] Mavjud /data/.env ishlatiladi"
else
  sariq "[3/5] Sozlamalar kerak. Kalitlarni kiriting (bo'sh qoldirsa ham bo'ladi)."
  echo
  read -rp "  BOT_TOKEN (majburiy)      : " V_BOT
  read -rp "  GROQ_API_KEY (bepul)      : " V_GROQ
  read -rp "  GEMINI_API_KEY (bepul)    : " V_GEM
  read -rp "  MUXLISA_KEY (premium)     : " V_MUX
  read -rp "  ADMIN_USER_ID             : " V_ADM
  read -rp "  WEBAPP_URL (https://...)  : " V_WEB
  cat > /data/.env <<EOF
BOT_TOKEN=$V_BOT
GROQ_API_KEY=$V_GROQ
GEMINI_API_KEY=$V_GEM
MUXLISA_KEY=$V_MUX
ADMIN_USER_ID=$V_ADM
WEBAPP_URL=$V_WEB
DATA_FILE=/data/user_data.json
EOF
  chmod 600 /data/.env
  echo "     /data/.env yaratildi (faqat root o'qiy oladi)"
fi

# ── 4. Qurish ───────────────────────────────────────────────────────────────
yashil "[4/5] Docker image qurilmoqda (birinchi marta 3-5 daqiqa)..."
docker build -q -t "$NOM:latest" . >/dev/null

# ── 5. Ishga tushirish ──────────────────────────────────────────────────────
yashil "[5/5] Konteyner ishga tushirilmoqda..."
docker rm -f "$NOM" >/dev/null 2>&1 || true
docker run -d \
  --name "$NOM" \
  --restart=always \
  --env-file /data/.env \
  -v /data:/data \
  -p "${PORT}:8000" \
  "$NOM:latest" >/dev/null

echo
sleep 8
if docker ps --filter "name=$NOM" --filter "status=running" | grep -q "$NOM"; then
  yashil "✅ Bot ishga tushdi."
else
  qizil "❌ Konteyner ko'tarilmadi. Log:"
  docker logs --tail 40 "$NOM" || true
  exit 1
fi

echo
echo "  Holat tekshirish : curl -s localhost:${PORT}/health"
echo "  Log ko'rish      : docker logs -f $NOM"
echo "  Qayta ishga tush : docker restart $NOM"
echo "  Yangilash        : bash $DIR/tools/server_setup.sh"
echo
echo "  Ma'lumotlar /data da — qayta deploy'da YO'QOLMAYDI."
echo "  --restart=always: server qayta yuklansa bot O'ZI ko'tariladi."
echo
curl -s -m 10 "http://localhost:${PORT}/health" || echo "  (health hali javob bermadi, 10-20 soniyadan keyin urinib ko'ring)"
echo
