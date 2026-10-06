#!/usr/bin/env bash
# Установка Tasker от root, но ВСЁ работает от пользователя tasker.
# Запуск на сервере под root:  bash deploy/setup_from_root.sh
# Что делает: ставит системные пакеты, код и venv живут в /home/tasker,
# Postgres — в системном Docker, backend — системный systemd-юнит с User=tasker.
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "Запусти как root (sudo -i)"; exit 1; }
id tasker >/dev/null 2>&1 || { echo "Нет пользователя tasker: adduser tasker"; exit 1; }

APP_DIR="/home/tasker/tasker"
VENV_DIR="/home/tasker/tasker/.venv"
REPO_URL="https://github.com/peterheathmp224-sketch/tasker"

# git под root отказывается трогать чужие файлы (dubious ownership) — разрешаем явно
git config --global --add safe.directory "$APP_DIR" 2>/dev/null || true
su - tasker -c "git config --global --add safe.directory $APP_DIR" 2>/dev/null || true

echo "==> 1. Системные пакеты (единственное место, где нужен root)"
apt-get update
apt-get install -y python3 python3-venv python3-pip git docker.io curl
systemctl enable --now docker
# docker compose: plugin (Ubuntu 22.04+) либо v1-пакет, либо бинарник с GitHub
# (проверяем реальную работу команды, а не только код выхода apt)
COMPOSE=""
if apt-get install -y docker-compose-plugin 2>/dev/null && docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
elif apt-get install -y docker-compose 2>/dev/null && docker-compose version >/dev/null 2>&1; then
  COMPOSE="docker-compose"
else
  curl -fSL https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-x86_64 -o /usr/local/bin/docker-compose
  chmod +x /usr/local/bin/docker-compose
  COMPOSE="/usr/local/bin/docker-compose"
fi
$COMPOSE version
usermod -aG docker tasker

echo "==> 2. Код в домашней папке tasker"
if [ ! -d "$APP_DIR/backend" ]; then
  sudo -u tasker git clone "$REPO_URL" "$APP_DIR"
else
  su - tasker -c "cd $APP_DIR && git pull"
fi
chown -R tasker:tasker /home/tasker/tasker

echo "==> 3. venv + зависимости (от имени tasker)"
su - tasker -c "python3 -m venv $VENV_DIR"
su - tasker -c "$VENV_DIR/bin/pip install --upgrade pip"
su - tasker -c "$VENV_DIR/bin/pip install -r $APP_DIR/backend/requirements.txt"

echo "==> 4. .env (владелец tasker, chmod 600)"
if [ ! -f "$APP_DIR/backend/.env" ]; then
  sudo -u tasker cp "$APP_DIR/backend/.env.example" "$APP_DIR/backend/.env"
  echo "!!! Впиши секреты: nano $APP_DIR/backend/.env (BOT_TOKEN, DEV_MOCK_USER=false)"
fi
chown tasker:tasker "$APP_DIR/backend/.env"
chmod 600 "$APP_DIR/backend/.env"

echo "==> 5. Postgres 16 (системный Docker, данные в docker-volume)"
cd "$APP_DIR"
$COMPOSE up -d db
for i in $(seq 1 30); do
  # через $COMPOSE exec: работает и в v1 (tasker_db_1), и в v2 (tasker-db-1)
  $COMPOSE exec -T db pg_isready -U tasker 2>/dev/null && break || sleep 2
done

echo "==> 6. systemd-сервис (системный юнит, процесс от tasker)"
cp "$APP_DIR/deploy/tasker-system.service" /etc/systemd/system/tasker.service
systemctl daemon-reload
systemctl enable --now tasker
sleep 3
systemctl status tasker --no-pager || true
curl -s http://127.0.0.1:8000/api/health && echo " <- backend OK"

echo ""
echo "Готово. Проверка владения (всё должно быть tasker):"
ls -ld "$APP_DIR" "$VENV_DIR"
ps -o user=,cmd= -C uvicorn 2>/dev/null || ps aux | grep '[u]vicorn' | head -3
echo "Логи: journalctl -u tasker -f | Перезапуск после деплоя: systemctl restart tasker"
