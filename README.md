# Tasker — Telegram Mini App (Vanilla JS + FastAPI + Postgres, без Node)

## Запуск (локально, Node не нужен)
1. Подними Postgres: `docker compose up -d db`
2. Бэкенд + фронт (фронт — статика `web/`, отдаёт сам FastAPI):
```
cd backend
copy .env.example .env   # впиши BOT_TOKEN; DATABASE_URL уже на Postgres
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```
3. Открой `http://localhost:8000/` — это и есть приложение (в браузере работает с мок-юзером, DEV_MOCK_USER=true).
4. Для Telegram: `ngrok http 8000` → https-URL в `WEBAPP_URL` → `python bot/setup_menu.py` → открыть через кнопку Menu бота.

## Правила v1
- Дедлайн — только дата. Календарь группирует по дате, табы Мои/Группа/Все.
- Статусы: new / in_progress / done.
- Редактировать/удалять может любой.
- Удаление группы отвязывает задачи (group_id=NULL), задачи не удаляются.
