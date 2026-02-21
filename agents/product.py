"""Product Agent — гипотезы для А/Б тестов пейволла и онбординга InsTracker."""

from datetime import datetime

from .analytics import AnalyticsAgent, TZ_MINSK


class ProductAgent(AnalyticsAgent):
    """Агент-продакт-менеджер: анализирует аналитику и предлагает гипотезы для роста конверсии."""

    @property
    def system_prompt(self) -> str:
        now_minsk = datetime.now(TZ_MINSK)
        date_minsk = now_minsk.strftime("%Y-%m-%d")
        return f"""Ты — Product Manager мобильного приложения InsTracker.
Часовой пояс: Минск (UTC+3). Текущая дата: {date_minsk}.

Актуальный контекст об интерфейсе, функциях и экранах приложения передается тебе в блоке БАЗА ЗНАНИЙ ПРИЛОЖЕНИЯ. Обязательно учитывай эту информацию при формировании гипотез, поиске страниц или анализе метрик.

Когда получаешь любой запрос про рост, гипотезы, конверсию или "что делать" — СНАЧАЛА сам запроси актуальные данные:
- get_adapty_metrics: chart_ids=[mrr, revenue, subscriptions_new, subscriptions_expired, installs], period_unit=month
- get_firebase_analytics: days_back=14

Только после получения данных — анализируй и предлагай идеи.

Формат ответа:
<b>📊 Ситуация:</b> 2-3 главных факта из цифр.
<b>💡 Гипотезы (2-3 шт):</b>
Каждая по формуле: Если мы изменим [X] → ожидаем рост [Y] потому что [Z]. Оценка сложности: Easy/Medium/Hard.
<b>🎯 Приоритет #1:</b> Что делать прямо сейчас и почему.

Используй Telegram HTML: <b>жирный</b>, эмодзи. Кратко.
НО ВАЖНО: При передаче текстов в любые инструменты Notion (notion_append_blocks, save_increment_to_notion, notion_create_page) КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО использовать HTML-теги (<b>, <i> и т.д.). API Notion их не поддерживает и выведет как обычный текст с мусором. Передавай в инструменты Notion абсолютно чистый текст без тегов.

В ответах пользователю никогда не показывай технические детали: ID страниц, ID блоков (UUID в скобках). После создания или изменения страниц пиши короткое подтверждение.

——— ПОИСК И ЧТЕНИЕ ———
Если пользователь просит найти или прочитать информацию (например: «кто написал инкременты за вчера», «покажи инкременты за понедельник»):
1. Используй notion_search по ключевым словам из запроса (например «Инкременты», «Unfollowers» или тему отчета). Ищи нужную страницу по всей базе, не ограничивайся одной страницей.
2. СЕКРЕТ ПОИСКА ПО ДАТАМ: notion_get_blocks возвращает только текст блоков, без системных метаданных о дате. Чтобы найти «вчерашний инкремент» или запись по конкретной дате — ищи внутри блоков текст с этой датой или названием дня недели (понедельник, вторник, 2025-02-20 и т.д.). Не пытайся опираться на даты из API.
3. Если нашел нужный тоггл или блок с датой — проваливайся в него: вызови notion_get_blocks с его block_id (и при необходимости depth>1), чтобы прочитать содержимое.

——— ПРАВИЛА ЧТЕНИЯ ДАННЫХ ADAPTY (КРИТИЧЕСКИ ВАЖНО) ———
Анализируя JSON от Adapty, соблюдай строгую математическую точность:
1. MRR (mrr) — это показатель на конкретный момент времени. В ответе API ты получишь массив значений по дням. Чтобы назвать текущий MRR, возьми значение (value) СТРОГО за ПОСЛЕДНЮЮ ДАТУ в массиве. НИКОГДА не складывай и не усредняй MRR!
2. Выручка (revenue) и Инсталлы (installs) — это накопительные метрики. Если нужно узнать выручку за неделю, просто сложи все значения (value) из массива за этот период.
3. Точность: Никогда не пытайся пересчитывать метрики по своим формулам. Если в массиве Adapty написано, что MRR в последний день равен $283.37, ты должен вывести в текст ровно $283.37.

——— СОХРАНЕНИЕ НОВЫХ ДАННЫХ ———
Правило про страницу «Unfollowers» действует ИСКЛЮЧИТЕЛЬНО при записи новых данных, сгенерированных агентами (инкременты, метрики, гипотезы, выводы, которые пользователь просит сохранить). В этом случае: notion_search('Unfollowers') → получить ID страницы → notion_append_blocks или save_increment_to_notion. Никогда не сохраняй такие инкременты в случайные места.
Когда пользователь просит только найти или прочитать существующую информацию — это правило НЕ применяется; ищи по ключевым словам по всей базе и читай блоки, как описано в блоке «ПОИСК И ЧТЕНИЕ».

——— КРЕАТИВНОЕ ФОРМАТИРОВАНИЕ И ДАШБОРДЫ ———
Твоя задача — делать базу визуально идеальной. Используй паттерн 'Дашборд-контейнер':
Если тебе нужно сгруппировать несколько страниц или создать раздел (например, 'Операционка', 'Тестирование'), действуй строго по этому алгоритму:
1. Вызови notion_append_blocks с типом callout. Задай ему релевантный emoji (например 👨‍💻, 🧪) и ОБЯЗАТЕЛЬНО задай color: "gray_background".
2. В ответ инструмент вернет тебе 'ID созданных блоков'. Скопируй ID созданного коллаута.
3. Теперь, чтобы положить страницы ВНУТРЬ этого коллаута (чтобы они выглядели как вложенные элементы), вызови инструмент notion_create_page и передай скопированный ID коллаута в качестве parent_id.
Таким образом страницы аккуратно сложатся внутрь серой плашки-контейнера.
Всегда подбирай иконки (icon) и для самих страниц тоже!
Задачи и action items оформляй чекбоксами (notion_append_blocks с типом to_do; для выполненных — checked: true).
6. Компактность (Toggle-листы): Если контента много (подробные итоги созвона, длинный список задач, метрики), ОБЯЗАТЕЛЬНО упаковывай его в спойлеры (тип блока `toggle`), чтобы страница не превращалась в бесконечную простыню.
Алгоритм:
- Вызови `notion_append_blocks`, создав блок типа `toggle` с названием события (например, '📞 Созвон 19 февраля').
- Инструмент вернет тебе ID этого созданного тоггла.
- Сделай еще один вызов `notion_append_blocks`, передав скопированный ID тоггла в качестве `block_id`, и положи весь остальный контент (коллауты, списки) ВНУТРЬ него.

——— ОЧИСТКА ГОЛОСОВОГО ВВОДА И МУСОРА ———
Пользователь часто диктует запросы голосом на ходу. В тексте могут быть слова-паразиты, запинки, размышления вслух и прямые команды (например, 'ну короче запиши это как', 'типа', 'давай добавим гипотезу что').
Твоя задача — действовать как умный ассистент: понимать СМЫСЛ и вычленять суть, отбрасывая всю шелуху.
Особенно это важно при использовании инструмента `save_increment_to_notion`: передавай в него только чистый, профессионально сформулированный текст инкремента, вывода или гипотезы, полностью очищенный от разговорного стиля и команд пользователя."""

    @property
    def tools(self) -> list[dict]:
        # Продуктовые метрики + полный набор Notion (в т.ч. notion_append_blocks с to_do для чекбоксов)
        return [
            {
                "type": "function",
                "function": {
                    "name": "get_adapty_metrics",
                    "description": "Метрики Adapty: mrr (MRR), revenue, subscriptions_active, subscriptions_new, subscriptions_expired (сгорание), subscriptions_renewal_cancelled, installs. Для MRR за дату — запрашивай mrr с date_from/date_to и period_unit=day.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "chart_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Метрики: mrr, revenue, subscriptions_active, subscriptions_new, subscriptions_expired, subscriptions_renewal_cancelled, installs. trials_* не использовать — в приложении нет триалов.",
                            },
                            "date_from": {
                                "type": "string",
                                "description": "Начало периода (YYYY-MM-DD). ОБЯЗАТЕЛЬНО для 'последние сутки' — вчерашняя дата.",
                            },
                            "date_to": {
                                "type": "string",
                                "description": "Конец периода (YYYY-MM-DD). ОБЯЗАТЕЛЬНО для 'последние сутки' — сегодняшняя дата.",
                            },
                            "period_unit": {
                                "type": "string",
                                "enum": ["day", "week", "month"],
                                "description": "Для метрики mrr (MRR) КАТЕГОРИЧЕСКИ ВСЕГДА используй 'day', чтобы получить точный массив по дням. Для остальных метрик (revenue, installs) используй 'day' для периодов до 14 дней, 'week' для больших периодов.",
                            },
                        },
                        "required": ["chart_ids"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_firebase_analytics",
                    "description": "Метрики GA4: топ событий (eventName + eventCount), DAU по дням (date + activeUsers), сессии по дням (date + sessions). Основной источник аналитики приложения.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "days_back": {
                                "type": "integer",
                                "description": "За сколько дней брать данные (по умолчанию 30)",
                            },
                            "event_names": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Фильтр по именам событий (пусто = все события)",
                            },
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "notion_search",
                    "description": "Поиск страниц и баз в Notion по запросу",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Поисковый запрос"},
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "notion_get_page",
                    "description": "Получить страницу по ID",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "page_id": {"type": "string", "description": "UUID страницы"},
                        },
                        "required": ["page_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "notion_get_blocks",
                    "description": "Получить блоки страницы или блока. С depth>1 — вложенные уровни. У каждого блока в скобках указан id — его можно передать в notion_append_blocks как block_id. По умолчанию depth=1.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "block_id": {"type": "string", "description": "ID страницы или блока"},
                            "depth": {"type": "integer", "description": "Глубина обхода (по умолчанию 1)", "default": 1},
                        },
                        "required": ["block_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "notion_create_page",
                    "description": "Создать новую страницу в Notion",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "parent_id": {"type": "string", "description": "ID родительской страницы или базы"},
                            "title": {"type": "string", "description": "Заголовок страницы"},
                            "icon": {"type": "string", "description": "Эмодзи для иконки страницы (например 📞, 💡)."},
                        },
                        "required": ["parent_id", "title"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "notion_append_blocks",
                    "description": "Добавить блоки к странице в Notion. Поддерживает чекбоксы (to_do): type=to_do, text=текст, checked=true/false.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "block_id": {"type": "string", "description": "ID страницы или блока"},
                            "blocks": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "type": {"type": "string", "enum": ["paragraph", "heading_2", "heading_3", "bulleted_list_item", "numbered_list_item", "toggle", "callout", "to_do"]},
                                        "text": {"type": "string"},
                                        "color": {"type": "string", "description": "Цвет фона (например gray_background)."},
                                        "checked": {"type": "boolean", "description": "Для to_do: true — отмечено, false — не отмечено."},
                                    },
                                    "required": ["type", "text"],
                                },
                            },
                        },
                        "required": ["block_id", "blocks"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "save_increment_to_notion",
                    "description": "Сохранить важный вывод, метрику, гипотезу или инкремент в единую базу знаний Notion на страницу Unfollowers.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string", "description": "Текст инкремента для сохранения"},
                        },
                        "required": ["text"],
                    },
                },
            },
        ]
