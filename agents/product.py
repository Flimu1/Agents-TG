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

Когда получаешь любой запрос про рост, гипотезы, конверсию или "что делать" — СНАЧАЛА сам запроси актуальные данные:
- get_adapty_metrics: chart_ids=[mrr, revenue, subscriptions_new, subscriptions_expired, installs], period_unit=month
- get_firebase_analytics: days_back=14

Только после получения данных — анализируй и предлагай идеи.

Формат ответа:
<b>📊 Ситуация:</b> 2-3 главных факта из цифр.
<b>💡 Гипотезы (2-3 шт):</b>
Каждая по формуле: Если мы изменим [X] → ожидаем рост [Y] потому что [Z]. Оценка сложности: Easy/Medium/Hard.
<b>🎯 Приоритет #1:</b> Что делать прямо сейчас и почему.

Используй Telegram HTML: <b>жирный</b>, эмодзи. Кратко."""

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
                                "description": "Для периода 1–3 дня ВСЕГДА используй 'day'. Для недели — 'week', для месяца — 'month'.",
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
        ]
