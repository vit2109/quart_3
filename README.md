# СЦ-отчеты

Локальная информационно-аналитическая система для загрузки и подготовки табличных данных, статистического и AI-анализа, формирования отчётов и поиска по базе знаний.

## Интерфейс

SPA содержит четыре вкладки:

- **Данные** — загрузка CSV, XLSX, XLS, JSON и Parquet, паспорт набора, редактирование, Join и встроенный раздел подготовки данных ETL.
- **Анализ** — таблицы и сводки, статистика, KPI, временные ряды, сравнение периодов, прогноз, Pareto, корреляции, аномалии, локальный AI, NLQ и безопасный SQL SELECT.
- **Отчёты** — шаблоны, фильтры, группировки, графики, история, cron-расписания и экспорт отчётов или строк.
- **База знаний** — индексация документов и датасетов, семантический, BM25 и гибридный RRF-поиск, локальные RAG-ответы и управление ChromaDB.

Активный набор данных выбирается в шапке и используется во всех применимых сценариях.

## Архитектура

```text
api/                         HTTP-контракты FastAPI и ролевые зависимости
application/use_cases/       прикладные сценарии и оркестрация
domain/                      сущности и интерфейсы репозиториев
infrastructure/storage/      файловые реестры, загрузчики и кэши
infrastructure/persistence/  SQLAlchemy-модели и репозиторий пользователей
infrastructure/ai/           локальные LLM, модели, эмбеддинги и RAG
infrastructure/knowledge/    документы, чанки, парсинг и worker индексации
core/                        конфигурация, БД, JWT, лимиты, scheduler, logging
static/                      HTML, CSS и модульный JavaScript-клиент
```

Основные API-модули: `auth`, `datasets`, `etl`, `analysis`, `reports`, `export_data`, `knowledge`, `jobs` и `metadata`.

Длительные операции выполняются встроенным `JobService`. Индексация базы знаний может запускаться в отдельном процессе; расписания обслуживает APScheduler. Внешний брокер сообщений не требуется.

## Технологии

- Python 3.14 и FastAPI;
- Polars и fastexcel;
- SQLAlchemy и PostgreSQL;
- Transformers, PyTorch и локальные GGUF-модели;
- sentence-transformers и ChromaDB;
- Vanilla JavaScript ES modules и локальный Chart.js;
- ReportLab для PDF.

## Запуск

Создайте локальную конфигурацию:

```powershell
Copy-Item .env.example .env
```

Установите зависимости и запустите приложение:

```powershell
uv sync --extra dev
uv run python main.py
```

Интерфейс: `http://localhost:8000`  
OpenAPI в режиме разработки: `http://localhost:8000/docs`

Запуск через Docker:

```powershell
docker compose up --build
```

## Проверка

```powershell
uv run pytest -q
```

Тесты покрывают API, аутентификацию, ETL, анализ, NLQ и SQL, отчёты, хранилища, парсинг документов, поиск базы знаний, ограничения памяти и экспорт PDF.

## Локальные данные

Каталоги `uploads/`, `reports/`, `knowledge/`, `chroma_db/`, `data/`, `logs/` и `models/`, а также файл `.env`, не должны попадать в систему контроля версий. Для переноса настроек используется `.env.example`.

## Безопасность

Реализованы bcrypt-хеширование паролей, JWT access/refresh-токены и роли `viewer`, `analyst`, `admin`. NLQ-планы и пользовательский SQL валидируются до выполнения. В текущем SPA токены хранятся в `localStorage`; для публичного промышленного развёртывания рекомендуется перенести refresh-токен в httpOnly-cookie и настроить CSP на внешнем шлюзе.
# quart_3
