#!/usr/bin/env bash
# Nginx + HTTPS для tasks.immortalhokage.space. Запуск под root:
#   bash deploy/setup_nginx.sh
# Опционально email для Let's Encrypt:  EMAIL=you@example.com bash deploy/setup_nginx.sh
# Требование: DNS A-запись tasks.immortalhokage.space уже указывает на этот сервер (проверено).
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "Запусти как root (sudo -i)"; exit 1; }
DOMAIN="tasks.immortalhokage.space"
EMAIL="${EMAIL:-}"
APP_DIR="/home/tasker/tasker"

echo "==> 1. nginx + certbot"
apt-get update
apt-get install -y nginx certbot python3-certbot-nginx

echo "==> 2. Сайт $DOMAIN -> 127.0.0.1:8000"
cp "$APP_DIR/deploy/nginx-tasks.conf" /etc/nginx/sites-available/tasker
ln -sf /etc/nginx/sites-available/tasker /etc/nginx/sites-enabled/tasker
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable --now nginx
systemctl reload nginx

echo "==> 3. Проверка HTTP до certbot (должен отдать health)"
curl -s -o /dev/null -w "HTTP %{http_code} (plain http)\n" "http://$DOMAIN/api/health"

echo "==> 4. Let's Encrypt (порт 80 должен быть доступен извне)"
if [ -n "$EMAIL" ]; then
  certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$EMAIL" --redirect
else
  certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --register-unsafely-without-email --redirect
fi
systemctl reload nginx

echo "==> 5. Проверка HTTPS"
curl -s "https://$DOMAIN/api/health" && echo " <- HTTPS OK"
echo "Автообновление сертификатов: systemctl status certbot.timer"
