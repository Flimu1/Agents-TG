# Telegram AI Agents по топикам

Каждый топик в Telegram-группе = отдельный AI-агент со своим промптом и тулами. Пишешь в топик — отвечает нужный агент.

## Архитектура

```
Telegram Group (с топиками)
├── Топик "Notion AI Agent" (thread_id=2) → NotionAgent
│   └── Тулы: notion_search, notion_get_page, notion_append_blocks, ...
├── Топик "Analytics" (thread_id=3) → AnalyticsAgent
│   └── Тулы: get_adapty_metrics, get_firebase_funnel
└── ...
```

## Быстрый старт

### 1. Создай группу с топиками

1. Создай **супергруппу** в Telegram
2. Включи **Topics** (Темы): Настройки группы → Topics → Включить
3. Добавь бота в группу как админа (чтобы читал все сообщения)
4. Создай топики: "Notion", "Analytics" (или любые названия)

### 2. Узнай ID группы и топиков

**ID группы:**
- Добавь бота [@userinfobot](https://t.me/userinfobot) в группу — он покажет `Chat ID` (отрицательное число, например `-1001234567890`)
- Или: перешли любое сообщение из группы боту [@getidsbot](https://t.me/getidsbot)

**ID топиков (message_thread_id):**
- Напиши в нужный топик любое сообщение
- Запусти бота (см. ниже) и в логах увидишь `thread_id`
- Либо используй команду `/topic_id` прямо в топике — бот ответит ID

### 3. Настрой проект

```bash
cd "Agents TG"
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

```bash
cp .env.example .env
cp config.example.yaml config.yaml
```

Заполни `.env`:
- `TELEGRAM_BOT_TOKEN` — от [@BotFather](https://t.me/BotFather)
- `OPENROUTER_API_KEY` — от [openrouter.ai](https://openrouter.ai) (или `OPENAI_API_KEY` для прямого OpenAI)
- `LLM_MODEL` — модель для ответов (по умолчанию `google/gemini-3-flash-preview`), можно `z-ai/glm-5` и др. Голос всегда распознаётся через `openai/gpt-audio-mini` (тот же OpenRouter).
- `NOTION_API_KEY` — от [notion.so/my-integrations](https://www.notion.so/my-integrations) (для Notion агента)

Заполни `config.yaml`:
- `telegram.group_id` — ID твоей группы
- `topics` — маппинг `thread_id: agent_name`:
  ```yaml
  topics:
    2: notion   # топик Notion
    3: analytics   # топик Analytics
  ```

### 4. Запуск

```bash
python bot.py
```

## Агенты

### Notion Agent
- Поиск страниц и баз
- Чтение страниц и блоков
- Создание страниц, добавление блоков

Не забудь подключить интеграцию к нужным страницам в Notion (Share → Invite → твоя интеграция).

### Analytics Agent
- Метрики Adapty: revenue, подписки, триалы
- Воронка онбординга из Firebase

Переменные: `ADAPTY_API_KEY` (или `ADAPTY_SECRET_KEY`), `FIREBASE_CREDENTIALS_PATH`.

## Команды

- `/topic_id` — показать ID текущего топика (для настройки config)
- `/clear` — очистить историю диалога в этом топике

## Деплой на Railway

1. Создай проект на [railway.app](https://railway.app), подключи репозиторий
2. Добавь переменные окружения в Settings → Variables:
   - `TELEGRAM_BOT_TOKEN`
   - `OPENROUTER_API_KEY` (или `OPENAI_API_KEY`)
   - `NOTION_API_KEY` (для Notion агента)
   - опционально: `ADAPTY_SECRET_KEY`, `FIREBASE_CREDENTIALS_PATH`
3. Railway подхватит `Procfile` и запустит `worker: python bot.py`
4. `config.yaml` уже в репо — group_id и topics настроены

## Добавление новых агентов

1. Создай класс в `agents/` (наследник `BaseAgent`)
2. Добавь в `agents/__init__.py` в словарь `AGENTS`
3. Создай топик в группе, узнай его `thread_id`, добавь в `config.yaml`
