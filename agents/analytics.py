"""Analytics Agent — анализ воронок, конверсий и подписок InsTracker."""
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests

from .base import BaseAgent


def _get_credentials_path() -> str | None:
    """Путь к Firebase credentials (для Firestore и BigQuery)."""
    cred_path = os.getenv("FIREBASE_CREDENTIALS_PATH")
    if not cred_path:
        return None
    if not os.path.isabs(cred_path):
        cred_path = str(Path(__file__).parent.parent / cred_path)
    return cred_path if os.path.exists(cred_path) else None


def _get_bigquery_client():
    """BigQuery-клиент для Firebase Analytics (экспорт в BigQuery)."""
    cred_path = _get_credentials_path()
    if not cred_path:
        return None
    try:
        from google.cloud import bigquery
        from google.oauth2 import service_account
        cred = service_account.Credentials.from_service_account_file(cred_path)
        return bigquery.Client(credentials=cred, project=cred.project_id)
    except ImportError:
        return None
    except Exception:
        return None


def _get_firestore():
    """Получить Firestore-клиент (инициализация при первом обращении)."""
    cred_path = _get_credentials_path()
    if not cred_path:
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
        return """Ты — строгий и точный дата-аналитик приложения InsTracker. Твоя задача — анализировать воронки, конверсии и подписки, отвечать только опираясь на свежие данные из базы.

Источники данных:
- get_firebase_analytics — основные метрики Firebase (события, DAU, сессии). Используй первым для аналитики из Firebase.
- get_adapty_metrics — монетизация (revenue, подписки, триалы).
- get_firebase_funnel — только если события пишутся в Firestore вручную.

Делай выводы кратко и по делу."""

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
                    "name": "get_firebase_analytics",
                    "description": "Получить все метрики и события из Firebase Analytics (BigQuery). События, воронка, DAU, конверсии. Основной источник аналитики Firebase.",
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
                    "description": "Получить воронку из Firestore (если события пишутся в коллекцию вручную). Для Firebase Analytics используй get_firebase_analytics.",
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
            if name == "get_firebase_analytics":
                return self._get_firebase_analytics(
                    days_back=arguments.get("days_back", 30),
                    event_names=arguments.get("event_names") or [],
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

    def _get_firebase_analytics(
        self,
        days_back: int = 30,
        event_names: list[str] | None = None,
    ) -> str:
        """Получить метрики и события из Firebase Analytics (BigQuery export)."""
        client = _get_bigquery_client()
        if not client:
            return "BigQuery недоступен. Установи google-cloud-bigquery и задай FIREBASE_CREDENTIALS_PATH."

        dataset_id = os.getenv("FIREBASE_ANALYTICS_DATASET")
        if not dataset_id:
            return (
                "FIREBASE_ANALYTICS_DATASET не задан в .env. "
                "Укажи dataset из BigQuery (формат: analytics_XXXXX). "
                "Включи экспорт Firebase Analytics → BigQuery в консоли Firebase."
            )

        event_filter = ""
        if event_names:
            escaped = [f"'{e.replace(chr(39), chr(39)+chr(39))}'" for e in event_names[:20]]
            event_filter = f" AND event_name IN ({','.join(escaped)})"

        since = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y%m%d")

        queries = []

        # 1. События и их количество (воронка)
        q_events = f"""
        SELECT event_name, COUNT(*) as cnt
        FROM `{client.project}.{dataset_id}.events_*`
        WHERE _TABLE_SUFFIX >= '{since}'
        {event_filter}
        GROUP BY event_name
        ORDER BY cnt DESC
        LIMIT 50
        """
        queries.append(("События (воронка)", q_events))

        # 2. DAU / активные пользователи
        q_dau = f"""
        SELECT event_date, COUNT(DISTINCT user_pseudo_id) as dau
        FROM `{client.project}.{dataset_id}.events_*`
        WHERE _TABLE_SUFFIX >= '{since}'
        GROUP BY event_date
        ORDER BY event_date DESC
        LIMIT 31
        """
        queries.append(("DAU по дням", q_dau))

        # 3. Сессии
        q_sessions = f"""
        SELECT event_date, COUNT(*) as sessions
        FROM `{client.project}.{dataset_id}.events_*`
        WHERE _TABLE_SUFFIX >= '{since}' AND event_name = 'session_start'
        GROUP BY event_date
        ORDER BY event_date DESC
        LIMIT 31
        """
        queries.append(("Сессии (session_start)", q_sessions))

        results: list[dict[str, Any]] = []
        for label, query in queries:
            try:
                rows = list(client.query(query).result())
                if rows:
                    data = [dict(r) for r in rows]
                    results.append({"metric": label, "data": data})
                else:
                    results.append({"metric": label, "data": [], "note": "Нет данных"})
            except Exception as e:
                results.append({"metric": label, "error": str(e)})

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
