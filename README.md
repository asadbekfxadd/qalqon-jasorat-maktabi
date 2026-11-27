# Qalqon Jasorat Maktabi — цифровая платформа школы

Flask + SQLAlchemy (PostgreSQL на Railway, SQLite локально). Сайт, электронная запись (Qabul), админ-панель с дашбордом,
кабинеты учителя / родителя / ученика, электронный дневник, уведомления, журнал действий.
Язык по умолчанию — узбекский (Latin), переключатель RU; тёмная/светлая тема.

## Структура
- `qalqon/models.py` — БД (таблицы с префиксом `q_`), `core.py` — права, уведомления, отчёты, файлы,
  `public.py` / `auth.py` / `admin.py` / `teacher.py` / `cabinet.py` — модули (blueprints), `seed.py` — демо-данные.
- Бизнес-логика отделена от шаблонов — на этой базе можно добавить JSON API / мобильное приложение.

## Запуск локально
    pip install -r requirements.txt
    python -c "from app import app; app.run(port=5000)"   # admin / admin12345 (только вне PRODUCTION)
    flask --app app seed-demo      # демо-данные (все помечены DEMO), пароль demo-аккаунтов Demo2026pass
    flask --app app purge-demo     # удалить демо

## Railway (переменные)
`PRODUCTION=1`, `SECRET_KEY`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `DATABASE_URL=${{Postgres.DATABASE_URL}}`.
Необязательно: `TG_BOT_TOKEN`, `TG_CHAT_ID` (Telegram), `SMTP_HOST/PORT/USER/PASS/FROM` (Email), `SITE_PHONE`, `SITE_EMAIL`,
`SITE_INSTAGRAM`, `SITE_TELEGRAM`. Файлы (документы, фото) хранятся в БД и доступны только через проверку прав.

## Роли
admin — вся система · teacher — только назначенные классы/предметы · parent — только свои дети · student — только свои данные.

## Тесты и безопасность

    pip install -r requirements-dev.txt
    python -m pytest -q tests

Тесты проверяют правила, на которых держится портал: вход и блокировка после неверных паролей, CSRF, родитель видит файлы только своего ребёнка, чужие кабинеты закрыты, смена пароля завершает остальные сессии, ссылка сброса пароля строится из `PUBLIC_URL`, а не из заголовка Host.

Переменная `PUBLIC_URL` (например `https://qalqon.up.railway.app`) нужна для ссылки восстановления пароля в письме. Без неё берётся адрес запроса. После выкладки все пользователи один раз выйдут из аккаунтов и войдут заново (сессии теперь привязаны к паролю).
