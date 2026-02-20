"""Analytics Agent — анализ воронок, конверсий и подписок InsTracker."""
import json
import os
from datetime import datetime, timedelta
from typing import Any

import requests

from .base import BaseAgent

def _get_firestore():
    """Получить Firestore-клиент (инициализация при первом обращении)."""
    global _firebase_app
    cred_path = os.getenv("FIREBASE_CREDENTIALS_PATH")
    if not cred_path or not os.path.exists(cred_path):
        return None
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore
    except ImportError:
        return None

    if not firebase_admin._apps:
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
    return firestore.client()


class AnalyticsAgent(BaseAgent):
    """Агент для анализа метрик: Adapty (revenue, подписки, триалы) и Firebase (воронка онбординга)."""

    @property
    def system_prompt(self) -> str:
        return """Ты — строгий и точный дата-аналитик приложения InsTracker. Твоя задача — анализировать воронки, конверсии и подписки, отвечать только опираясь на свежие данные из базы. Делай выводы кратко и по делу."""

    @property
    def tools(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "get_adapty_metrics",
                    "description": "Получить метрики Adapty: revenue, активные подписки, триалы. Данные по монетизации приложения.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "chart_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Типы метрик: revenue, subscriptions_active, trials_active, subscriptions_new, trials_new, mrr, arr",
                            },
                            "date_from": {
                                "type": "string",
                                "description": "Начало периода (YYYY-MM-DD)",
                            },
                            "date_to": {
                                "type": "string",
                                "description": "Конец периода (YYYY-MM-DD)",
                            },
                            "period_unit": {
                                "type": "string",
                                "enum": ["day", "week", "month"],
                                "description": "Группировка: day, week, month",
                            },
                        },
                        "required": ["chart_ids"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_firebase_funnel",
                    "description": "Получить конверсии по шагам онбординга из Firebase (воронка).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "collection": {
                                "type": "string",
                                "description": "Имя коллекции с событиями (по умолчанию analytics_events)",
                            },
                            "event_field": {
                                "type": "string",
                                "description": "Поле с названием шага/события (по умолчанию event_name)",
                            },
                            "days_back": {
                                "type": "integer",
                                "description": "За сколько дней считать (по умолчанию 30)",
                            },
                        },
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
            if name == "get_firebase_funnel":
                return self._get_firebase_funnel(
                    collection=arguments.get("collection", "analytics_events"),
                    event_field=arguments.get("event_field", "event_name"),
                    days_back=arguments.get("days_back", 30),
                )
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
            end = datetime.utcnow()
            start = end - timedelta(days=30)
            date_from = start.strftime("%Y-%m-%d")
            date_to = end.strftime("%Y-%m-%d")

        url = "https://api-admin.adapty.io/api/v1/client-api/metrics/analytics/"
        headers = {
            "Authorization": f"Api-Key {api_key}",
            "Content-Type": "application/json",
        }

        results: list[dict[str, Any]] = []
        for chart_id in chart_ids[:5]:  # ограничение: не более 5 чартов за раз
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

    def _get_firebase_funnel(
        self,
        collection: str = "analytics_events",
        event_field: str = "event_name",
        days_back: int = 30,
    ) -> str:
        """Получить воронку онбординга из Firestore по событиям."""
        db = _get_firestore()
        if db is None:
            return "FIREBASE_CREDENTIALS_PATH не задан или файл не найден."

        since = datetime.utcnow() - timedelta(days=days_back)
        try:
            ref = db.collection(collection)
            # Firestore: фильтр по timestamp, если есть поле created_at или timestamp
            docs = ref.stream()

            step_counts: dict[str, int] = {}
            for doc in docs:
                d = doc.to_dict()
                event = d.get(event_field) or d.get("event") or d.get("step") or "unknown"
                ts = d.get("timestamp") or d.get("created_at") or d.get("date")
                if ts:
                    if hasattr(ts, "timestamp"):
                        ts_val = ts.timestamp()
                    else:
                        try:
                            ts_val = float(ts)
                        except (TypeError, ValueError):
                            ts_val = 0
                    if ts_val < since.timestamp():
                        continue
                step_counts[event] = step_counts.get(event, 0) + 1

            if not step_counts:
                return f"События не найдены в коллекции '{collection}' за последние {days_back} дней."

            # Сортируем по количеству (воронка: от большего к меньшему)
            sorted_steps = sorted(
                step_counts.items(),
                key=lambda x: (-x[1], x[0]),
            )
            lines = [f"Воронка онбординга ({collection}, {days_back} дней):"]
            total = max(step_counts.values()) if step_counts else 0
            for step, count in sorted_steps:
                pct = (count / total * 100) if total else 0
                lines.append(f"  {step}: {count} ({pct:.1f}%)")
            return "\n".join(lines)

        except Exception as e:
            return f"Ошибка Firestore: {e}"
