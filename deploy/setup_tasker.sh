#!/usr/bin/env bash
# Установка Tasker (Postgres + FastAPI) строго под пользователем tasker, без sudo/root.
# Запуск на сервере под пользователем tasker:  bash deploy/setup_tasker.sh
set -euo pipefail

APP_DIR="$HOME/tasker"
VENV_DIR="$HOME/tasker/.venv"
SERVICE_SRC="$(cd "$(dirname "$0")" && pwd)/tasker.service"
SERVICE_DST="$HOME/.config/systemd/user/tasker.service"

export PATH="$HOME/bin:$HOME/.local/bin:$PATH"

echo "==> 0. Кто мы (должен быть tasker, без sudo)"
whoami
if [ "$(whoami)" != "tasker" ]; then echo "Зайди как tasker: su - tasker"; exit 1; fi

echo "==> 1. Python venv в домашней папке (без sudo/apt)"
python3 --version
[ -d "$APP_DIR/backend" ] || { echo "Скопируй проект в $APP_DIR (git clone ... $APP_DIR)"; exit 1; }
ensure_venv() {
  # 1) системный venv, если есть
  python3 -m venv "$VENV_DIR" 2>/dev/null && return 0
  # 2) virtualenv в юзерспейс (без sudo)
  python3 -m ensurepip --user 2>/dev/null || true
  python3 -m pip install --user virtualenv 2>/dev/null || return 1
  python3 -m virtualenv "$VENV_DIR" && return 0
  return 1
}
if [ ! -x "$VENV_DIR/bin/python" ]; then
  ensure_venv || {
    echo "Нет модуля venv и не встал virtualenv. Запасной вариант — uv:";
    echo "  curl -LsSf https://astral.sh/uv/install.sh | sh && ~/.local/bin/uv venv $VENV_DIR";
    exit 1;
  }
fi
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$APP_DIR/backend/requirements.txt"

echo "==> 2. .env (только владелец, chmod 600)"
[ -f "$APP_DIR/backend/.env" ] || cp "$APP_DIR/backend/.env.example" "$APP_DIR/backend/.env"
chmod 600 "$APP_DIR/backend/.env"
grep -q "^DATABASE_URL=" "$APP_DIR/backend/.env" || echo "DATABASE_URL=postgresql+psycopg2://tasker:tasker@127.0.0.1:5432/tasker" >> "$APP_DIR/backend/.env"
ls -l "$APP_DIR/backend/.env"

echo "==> 3. Docker (rootless, ставится в ~/bin без sudo)"
if ! docker info >/dev/null 2>&1; then
  echo "Ставлю Rootless Docker в домашнюю папку..."
  curl -fsSL https://get.docker.com/rootless | sh
  export PATH="$HOME/bin:$PATH"
  export DOCKER_HOST="unix://$XDG_RUNTIME_DIR/docker.sock"
  systemctl --user daemon-reload 2>/dev/null || true
  dockerd-rootless-setuptool.sh install || true
  echo 'export PATH=$HOME/bin:$PATH' >> "$HOME/.bashrc"
  echo 'export DOCKER_HOST=unix://$XDG_RUNTIME_DIR/docker.sock' >> "$HOME/.bashrc"
fi
docker info >/dev/null
docker compose version

echo "==> 4. Postgres 16 в Docker (данные в ~/.local/share/docker, порты 127.0.0.1:5432)"
cd "$APP_DIR"
export DOCKER_HOST="unix://$XDG_RUNTIME_DIR/docker.sock"
docker compose up -d db
for i in $(seq 1 30); do
  docker exec tasker-db-1 pg_isready -U tasker 2>/dev/null && break || sleep 2
done

echo "==> 5. Проверка подключения из venv"
"$VENV_DIR/bin/python" -c "
from sqlalchemy import create_engine
import os
url = [l for l in open(os.path.expanduser('$APP_DIR/backend/.env')) if l.startswith('DATABASE_URL=')][0].strip().split('=',1)[1]
e = create_engine(url)
with e.connect() as c: c.exec_driver_sql('SELECT 1')
print('Postgres OK:', url.split('@')[1])
"

echo "==> 6. systemd --user сервис tasker (без sudo)"
mkdir -p "$HOME/.config/systemd/user"
cp "$SERVICE_SRC" "$SERVICE_DST"
systemctl --user daemon-reload
systemctl --user enable --now tasker
sleep 3
curl -s http://127.0.0.1:8000/api/health && echo " <- backend OK"

echo ""
echo "Готово (все живет под tasker):"
echo "  systemctl --user status tasker   # backend"
echo "  journalctl --user -u tasker -f    # логи"
echo "  docker ps                         # postgres"
echo "Автозапуск после ребута: попроси админа один раз: sudo loginctl enable-linger tasker"
