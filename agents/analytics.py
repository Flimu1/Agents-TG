"""Analytics Agent — анализ воронок, конверсий и подписок InsTracker."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from notion_client import APIResponseError

from .base import BaseAgent

TZ_MINSK = timezone(timedelta(hours=3))

# Lazy GA4 client (инициализация при первом вызове)
_ga4_client: Any = None


def _get_credentials_path() -> str | None:
    """Путь к Google credentials (service account JSON для GA4)."""
    cred_path = os.getenv("GOOGLE_CREDENTIALS_PATH")
    if not cred_path:
        return None
    if not os.path.isabs(cred_path):
        cred_path = str(Path(__file__).parent.parent / cred_path)
    return cred_path if os.path.exists(cred_path) else None


def _get_ga4_client():
    """GA4 Data API клиент (lazy, при первом обращении)."""
    global _ga4_client
    if _ga4_client is not None:
        return _ga4_client
    cred_path = _get_credentials_path()
    if not cred_path:
        return None
    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient

        _ga4_client = BetaAnalyticsDataClient.from_service_account_file(cred_path)
        return _ga4_client
    except ImportError:
        return None
    except Exception:
        return None


class AnalyticsAgent(BaseAgent):
    """Агент для анализа метрик: Adapty (revenue, подписки, триалы) и GA4 (воронка онбординга)."""

    def __init__(self, **kwargs):
        kwargs.pop("history_limit", None)  # всегда 0 для аналитики
        super().__init__(history_limit=0, **kwargs)

    @property
    def system_prompt(self) -> str:
        now_minsk = datetime.now(TZ_MINSK)
        date_minsk = now_minsk.strftime("%Y-%m-%d")
        yesterday_minsk = (now_minsk - timedelta(days=1)).strftime("%Y-%m-%d")
        return f"""Ты — ведущий продуктовый аналитик мобильного приложения InsTracker. Твоя главная задача — собирать, структурировать и интерпретировать данные из баз, чтобы находить точки роста выручки и конверсий.

Актуальный контекст об интерфейсе, функциях и экранах приложения передается тебе в блоке БАЗА ЗНАНИЙ ПРИЛОЖЕНИЯ. Обязательно учитывай эту информацию при формировании гипотез, поиске страниц или анализе метрик.

Часовой пояс: Минск (UTC+3). Текущая дата в Минске: {date_minsk}. Вчера: {yesterday_minsk}. Используй эти даты для запросов "за сегодня", "за вчера", "за сутки".

Контекст InsTracker:
- В приложении НЕТ пробных периодов (trials). Метрики trials_* будут нулевыми — не фокусируйся на них.
- Приоритетные метрики: MRR (mrr), revenue, subscriptions_active, subscriptions_new, subscriptions_expired (сгорание), subscriptions_renewal_cancelled (отмена продления), installs.

Твои инструменты и правила работы с ними:
1. get_firebase_analytics — DAU, сессии, популярные события из GA4 (Google Analytics 4).
2. get_adapty_metrics — монетизация и продукт. Если просят "за сегодня/вчера/сутки", ОБЯЗАТЕЛЬНО передавай date_from, date_to (YYYY-MM-DD) и period_unit = "day".
   Ключевые chart_ids: mrr (MRR — приоритет при запросе "какой MRR за дату"), revenue, subscriptions_active, subscriptions_new, subscriptions_expired (сгорание подписок), subscriptions_renewal_cancelled, installs (инсталлы за период).
3. get_firebase_funnel — воронка по шагам (event_names). Возвращает eventCount по каждому событию и % относительно первого шага.

Продуктовые инсайты: когда просят сводку или "что важно" — сам определяй, какие метрики сейчас релевантны. Запрашивай: mrr, revenue, subscriptions_active, subscriptions_new, subscriptions_expired, subscriptions_renewal_cancelled, installs. Выделяй закономерности, тренды, аномалии. Держи пользователя в курсе всего важного и интересного.

Интерпретация данных: бери фактические числа из data в JSON. Не выдумывай цифры.

Как отвечать:
- Кратко, только на основе цифр из инструментов.
- Telegram HTML: <b>жирный</b> для метрик и заголовков, эмодзи (💰 MRR/выручка, 📥 инсталлы, 📉 сгорание, 📈 рост).
- НО ВАЖНО: При передаче текстов в любые инструменты Notion (notion_append_blocks, save_increment_to_notion, notion_create_page) КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО использовать HTML-теги (<b>, <i> и т.д.). API Notion их не поддерживает и выведет как обычный текст с мусором. Передавай в инструменты Notion абсолютно чистый текст без тегов.
- В конце — один емкий вывод: главная проблема или успех.

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
Задачи и action items оформляй чекбоксами (тип to_do в notion_append_blocks); для выполненных пунктов указывай checked: true.
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
                    "name": "get_firebase_funnel",
                    "description": "Воронка по шагам: передай event_names (список событий в порядке воронки). Возвращает eventCount по каждому событию и % относительно первого шага.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "event_names": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Список имён событий — шаги воронки (например: session_start, onboarding_step1, paywall_view, purchase)",
                            },
                            "days_back": {
                                "type": "integer",
                                "description": "За сколько дней считать (по умолчанию 30)",
                            },
                        },
                        "required": ["event_names"],
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
                    "description": "Получить блоки страницы или блока. С depth>1 — рекурсивно все вложенные уровни (год→даты→тогглы с именами). У каждого блока в скобках указан id — его можно передать в notion_append_blocks как block_id, чтобы добавить туда дочерние блоки. ВНИМАНИЕ: По умолчанию depth=1 (только верхний уровень). Используй depth>1 ТОЛЬКО если тебе нужно заглянуть внутрь конкретного небольшого блока. Никогда не вызывай depth=3 или 4 для целых страниц, это приведет к зависанию!",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "block_id": {"type": "string", "description": "ID страницы или блока"},
                            "depth": {"type": "integer", "description": "Глубина обхода: 1 — только прямой уровень, 2–4 — с вложенными блоками (даты, тогглы). По умолчанию 1.", "default": 1},
                        },
                        "required": ["block_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "notion_create_page",
                    "description": "Создать новую страницу",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "parent_id": {"type": "string", "description": "ID родительской страницы или базы"},
                            "title": {"type": "string", "description": "Заголовок страницы"},
                            "icon": {"type": "string", "description": "Один эмодзи-символ для иконки страницы, подходящий по смыслу (например 📞, 💡, 📊)."},
                        },
                        "required": ["parent_id", "title"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "notion_append_blocks",
                    "description": "Добавить блоки к странице",
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
                                        "color": {"type": "string", "description": "Цвет фона блока. Для красивых дашбордов используй 'gray_background'."},
                                        "checked": {"type": "boolean", "description": "Для to_do: true — отмечено выполненным, false или не указывать — не отмечено."},
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

    def _call_tool(self, name: str, arguments: dict) -> str:
        try:
            if name == "get_adapty_metrics":
                return self._get_adapty_metrics(
                    chart_ids=arguments.get("chart_ids", ["revenue", "subscriptions_active"]),
                    date_from=arguments.get("date_from"),
                    date_to=arguments.get("date_to"),
                    period_unit=arguments.get("period_unit", "month"),
                )
            if name == "get_firebase_analytics":
                return self._get_firebase_analytics(
                    days_back=arguments.get("days_back", 30),
                    event_names=arguments.get("event_names") or [],
                )
            if name == "get_firebase_funnel":
                return self._get_firebase_funnel(
                    event_names=arguments.get("event_names") or [],
                    days_back=arguments.get("days_back", 30),
                )
            if name == "notion_search":
                return self._search(arguments["query"])
            if name == "notion_get_page":
                return self._get_page(arguments["page_id"])
            if name == "notion_get_blocks":
                return self._get_blocks(arguments["block_id"], arguments.get("depth", 1))
            if name == "notion_create_page":
                return self._create_page(arguments["parent_id"], arguments["title"], arguments.get("icon"))
            if name == "notion_append_blocks":
                return self._append_blocks(arguments["block_id"], arguments["blocks"])
            if name == "save_increment_to_notion":
                return self._save_increment_to_notion(arguments.get("text", ""))
        except APIResponseError as e:
            return f"Notion API ошибка: {e.body}"
        except Exception as e:
            return f"Ошибка: {e}"
        return f"Unknown tool: {name}"

    def _get_adapty_metrics(
        self,
        chart_ids: list[str],
        date_from: str | None = None,
        date_to: str | None = None,
        period_unit: str = "month",
    ) -> str:
        """Запрос метрик Adapty через REST API."""
        api_key = os.getenv("ADAPTY_API_KEY") or os.getenv("ADAPTY_SECRET_KEY")
        if not api_key:
            return "ADAPTY_API_KEY или ADAPTY_SECRET_KEY не задан в .env."

        if not date_from or not date_to:
            end = datetime.now(TZ_MINSK)
            start = end - timedelta(days=30)
            date_from = start.strftime("%Y-%m-%d")
            date_to = end.strftime("%Y-%m-%d")
        else:
            # Для периода 1–2 дня принудительно day-гранулярность
            try:
                from_dt = datetime.strptime(date_from, "%Y-%m-%d")
                to_dt = datetime.strptime(date_to, "%Y-%m-%d")
                if (to_dt - from_dt).days <= 2:
                    period_unit = "day"
            except ValueError:
                pass

        url = "https://api-admin.adapty.io/api/v1/client-api/metrics/analytics/"
        headers = {
            "Authorization": f"Api-Key {api_key}",
            "Content-Type": "application/json",
            "Adapty-Tz": "Europe/Minsk",
        }

        results: list[dict[str, Any]] = []
        for chart_id in chart_ids[:8]:  # до 8 чартов за раз (mrr, revenue, subs, installs и др.)
            payload = {
                "chart_id": chart_id,
                "filters": {"date": [date_from, date_to]},
                "period_unit": period_unit,
                "format": "json",
            }
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                results.append({"chart_id": chart_id, "data": data})
            except requests.RequestException as e:
                results.append({"chart_id": chart_id, "error": str(e)})

        return json.dumps(results, ensure_ascii=False, indent=2)

    def _get_firebase_analytics(
        self,
        days_back: int = 30,
        event_names: list[str] | None = None,
    ) -> str:
        """Получить метрики и события из GA4 (Google Analytics Data API)."""
        try:
            from google.analytics.data_v1beta import BetaAnalyticsDataClient
            from google.analytics.data_v1beta.types import (
                DateRange,
                Dimension,
                Filter,
                FilterExpression,
                Metric,
                RunReportRequest,
            )
        except ImportError:
            return (
                "Библиотека google-analytics-data не установлена. "
                "Выполни: pip install google-analytics-data>=0.18.0"
            )

        client = _get_ga4_client()
        if not client:
            return (
                "GA4 недоступен. Задай GOOGLE_CREDENTIALS_PATH (путь к service account JSON) в .env."
            )

        property_id = os.getenv("GA4_PROPERTY_ID")
        if not property_id:
            return (
                "GA4_PROPERTY_ID не задан в .env. "
                "Укажи Property ID GA4 (только цифры, например 123456789)."
            )

        end_date = datetime.now(TZ_MINSK)
        start_date = end_date - timedelta(days=days_back)
        date_range = DateRange(
            start_date=start_date.strftime("%Y-%m-%d"),
            end_date=end_date.strftime("%Y-%m-%d"),
        )

        results: list[dict[str, Any]] = []

        # 1. Топ событий (eventName + eventCount)
        dim_filter = None
        if event_names:
            dim_filter = FilterExpression(
                filter=Filter(
                    field_name="eventName",
                    in_list_filter=Filter.InListFilter(values=event_names[:20]),
                )
            )
        try:
            req = RunReportRequest(
                property=f"properties/{property_id}",
                dimensions=[Dimension(name="eventName")],
                metrics=[Metric(name="eventCount")],
                date_ranges=[date_range],
                dimension_filter=dim_filter,
                limit=50,
            )
            response = client.run_report(req)
            data = []
            for row in response.rows:
                event_name = row.dimension_values[0].value if row.dimension_values else ""
                event_count = int(row.metric_values[0].value) if row.metric_values else 0
                data.append({"event_name": event_name, "cnt": event_count})
            results.append({"metric": "События (воронка)", "data": data})
        except Exception as e:
            results.append({"metric": "События (воронка)", "error": str(e)})

        # 2. DAU по дням (date + activeUsers)
        try:
            req = RunReportRequest(
                property=f"properties/{property_id}",
                dimensions=[Dimension(name="date")],
                metrics=[Metric(name="activeUsers")],
                date_ranges=[date_range],
                limit=31,
            )
            response = client.run_report(req)
            data = []
            for row in response.rows:
                d = row.dimension_values[0].value if row.dimension_values else ""
                dau = int(row.metric_values[0].value) if row.metric_values else 0
                data.append({"event_date": d, "dau": dau})
            results.append({"metric": "DAU по дням", "data": data})
        except Exception as e:
            results.append({"metric": "DAU по дням", "error": str(e)})

        # 3. Сессии по дням (date + sessions)
        try:
            req = RunReportRequest(
                property=f"properties/{property_id}",
                dimensions=[Dimension(name="date")],
                metrics=[Metric(name="sessions")],
                date_ranges=[date_range],
                limit=31,
            )
            response = client.run_report(req)
            data = []
            for row in response.rows:
                d = row.dimension_values[0].value if row.dimension_values else ""
                sessions = int(row.metric_values[0].value) if row.metric_values else 0
                data.append({"event_date": d, "sessions": sessions})
            results.append({"metric": "Сессии (session_start)", "data": data})
        except Exception as e:
            results.append({"metric": "Сессии (session_start)", "error": str(e)})

        return json.dumps(results, ensure_ascii=False, indent=2)

    def _get_firebase_funnel(
        self,
        event_names: list[str],
        days_back: int = 30,
    ) -> str:
        """Получить воронку по шагам (event_names) из GA4."""
        try:
            from google.analytics.data_v1beta.types import (
                DateRange,
                Dimension,
                Filter,
                FilterExpression,
                Metric,
                RunReportRequest,
            )
        except ImportError:
            return (
                "Библиотека google-analytics-data не установлена. "
                "Выполни: pip install google-analytics-data>=0.18.0"
            )

        client = _get_ga4_client()
        if not client:
            return (
                "GA4 недоступен. Задай GOOGLE_CREDENTIALS_PATH (путь к service account JSON) в .env."
            )

        property_id = os.getenv("GA4_PROPERTY_ID")
        if not property_id:
            return (
                "GA4_PROPERTY_ID не задан в .env. "
                "Укажи Property ID GA4 (только цифры, например 123456789)."
            )

        if not event_names:
            return "Передай event_names — список шагов воронки (например: session_start, onboarding_step1, paywall_view, purchase)."

        end_date = datetime.now(TZ_MINSK)
        start_date = end_date - timedelta(days=days_back)
        date_range = DateRange(
            start_date=start_date.strftime("%Y-%m-%d"),
            end_date=end_date.strftime("%Y-%m-%d"),
        )

        try:
            req = RunReportRequest(
                property=f"properties/{property_id}",
                dimensions=[Dimension(name="eventName")],
                metrics=[Metric(name="eventCount")],
                date_ranges=[date_range],
                dimension_filter=FilterExpression(
                    filter=Filter(
                        field_name="eventName",
                        in_list_filter=Filter.InListFilter(values=event_names),
                    )
                ),
            )
            response = client.run_report(req)

            # Собираем eventCount по каждому событию (в порядке event_names)
            event_counts: dict[str, int] = {}
            for row in response.rows:
                name = row.dimension_values[0].value if row.dimension_values else ""
                cnt = int(row.metric_values[0].value) if row.metric_values else 0
                event_counts[name] = cnt

            # Сохраняем порядок из event_names, добавляем % относительно первого шага
            first_count = event_counts.get(event_names[0], 0) if event_names else 0
            data = []
            for ev in event_names:
                cnt = event_counts.get(ev, 0)
                pct = (cnt / first_count * 100) if first_count else 0
                data.append({"event_name": ev, "event_count": cnt, "pct": round(pct, 1)})

            results: list[dict[str, Any]] = [
                {"metric": "Воронка", "data": data},
            ]
            return json.dumps(results, ensure_ascii=False, indent=2)

        except Exception as e:
            return f"Ошибка GA4: {e}"
