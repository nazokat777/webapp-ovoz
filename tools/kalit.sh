#!/usr/bin/env bash
# ============================================================================
#  Serverga SSH kalit o'rnatadi.
#
#  NEGA KERAK: DigitalOcean'ning brauzerdagi Web Console'ida ko'chirib-
#  joylashtirish ISHLAMAYDI — uzun matn yutilib, bitta belgi qoladi.
#  Amalda shu sabab API kalitlari "2 belgi" bo'lib tushdi va bot ishlamadi.
#  Uzun kalitlarni qo'lda terish esa xatoga to'la.
#
#  Bu skript foydalanuvchining O'Z KOMPYUTERIDAGI ochiq kalitni serverga
#  qo'shadi. Shundan keyin sozlash ishlari kompyuterdan turib bajariladi,
#  brauzer konsoli kerak bo'lmaydi.
#
#  MAXFIY kalit foydalanuvchining kompyuterida qoladi va HECH QAYERGA
#  yuborilmaydi. Bu yerdagi ochiq kalit sir emas — u faqat "shu maxfiy
#  kalit egasini kirit" degani.
#
#  BEKOR QILISH (istalgan vaqtda):
#      sed -i '/claude-code-ovozbot/d' ~/.ssh/authorized_keys
#
#  Foydalanish:
#      curl -sL https://raw.githubusercontent.com/nazokat777/webapp-ovoz/main/tools/kalit.sh | bash
# ============================================================================
set -euo pipefail

KALIT="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAICxlSTpQd1m7P8//tTkxsnSCiw85PTzhERgIYp/FRcPF claude-code-ovozbot"

mkdir -p ~/.ssh
chmod 700 ~/.ssh
touch ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys

# Takror qo'shmaslik: skript bir necha marta ishlatilishi mumkin.
if grep -qF "claude-code-ovozbot" ~/.ssh/authorized_keys; then
  echo "Kalit allaqachon o'rnatilgan."
else
  printf '%s\n' "$KALIT" >> ~/.ssh/authorized_keys
  echo "Kalit qo'shildi."
fi

echo
echo "Endi kompyuteringizdan ulanish mumkin."
echo "Bekor qilish uchun:"
echo "  sed -i '/claude-code-ovozbot/d' ~/.ssh/authorized_keys"
