#!/usr/bin/env python3
"""
Проверка доступа ко всем сервисам: Firebase, Adapty, Notion, OpenRouter.
Запуск: python tests/test_services.py
"""
import os
import sys
from pathlib import Path

# Загружаем .env
from dotenv import load_dotenv
load_dotenv()

# Добавляем корень проекта в path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agents.analytics import _get_credentials_path, _get_ga4_client


def test_firebase_analytics():
    """1. GA4 (Google Analytics 4) — основные метрики."""
    print("\n" + "=" * 50)
    print("1. GA4 (Google Analytics 4)")
    print("=" * 50)

    if not _get_credentials_path():
        print("❌ GOOGLE_CREDENTIALS_PATH не задан или файл не найден")
        return False

    print("✓ Файл credentials найден")

    property_id = os.getenv("GA4_PROPERTY_ID")
    if not property_id:
        print("⚠️ GA4_PROPERTY_ID не задан. Добавь в .env (только цифры, например 123456789)")
        return False

    client = _get_ga4_client()
    if not client:
        print("❌ GA4-клиент недоступен (установи google-analytics-data)")
        return False

    try:
        from google.analytics.data_v1beta.types import (
            DateRange,
            Dimension,
            Metric,
            RunReportRequest,
        )

        req = RunReportRequest(
            property=f"properties/{property_id}",
            dimensions=[Dimension(name="eventName")],
            metrics=[Metric(name="eventCount")],
            date_ranges=[DateRange(start_date="1daysAgo", end_date="today")],
            limit=5,
        )
        response = client.run_report(req)
        total = sum(int(r.metric_values[0].value) for r in response.rows) if response.rows else 0
        print(f"✓ GA4 доступен. Событий за 1 день: {total}")
        return True
    except Exception as e:
        err = str(e)
        if "403" in err or "Permission" in err:
            print("❌ Нет доступа к GA4. Добавь сервисный аккаунт в GA4 с ролью Viewer.")
        else:
            print(f"❌ Ошибка GA4: {e}")
        return False


def test_adapty():
    """2. Adapty — метрики монетизации."""
    print("\n" + "=" * 50)
    print("2. ADAPTY")
    print("=" * 50)

    api_key = os.getenv("ADAPTY_API_KEY") or os.getenv("ADAPTY_SECRET_KEY")
    if not api_key:
        print("❌ ADAPTY_API_KEY или ADAPTY_SECRET_KEY не задан в .env")
        return False

    print("✓ API ключ задан")

    import requests
    from datetime import datetime, timedelta

    end = datetime.utcnow()
    start = end - timedelta(days=7)
    date_from = start.strftime("%Y-%m-%d")
    date_to = end.strftime("%Y-%m-%d")

    url = "https://api-admin.adapty.io/api/v1/client-api/metrics/analytics/"
    headers = {
        "Authorization": f"Api-Key {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "chart_id": "revenue",
        "filters": {"date": [date_from, date_to]},
        "period_unit": "day",
        "format": "json",
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            print(f"✓ Adapty API отвечает. Revenue за 7 дней: получены данные")
            return True
        print(f"❌ Adapty API: HTTP {resp.status_code} — {resp.text[:200]}")
        return False
    except requests.RequestException as e:
        print(f"❌ Ошибка запроса Adapty: {e}")
        return False


def test_notion():
    """3. Notion — доступ к пространству."""
    print("\n" + "=" * 50)
    print("3. NOTION")
    print("=" * 50)

    token = os.getenv("NOTION_API_KEY")
    if not token:
        print("❌ NOTION_API_KEY не задан в .env")
        return False

    print("✓ API ключ задан")

    try:
        from notion_client import Client
        client = Client(auth=token)
        resp = client.search(query="", page_size=5)
        results = resp.get("results", [])
        print(f"✓ Notion API отвечает. Найдено объектов: {len(results)}")
        return True
    except Exception as e:
        err = str(e)
        if "401" in err or "Unauthorized" in err:
            print("❌ Notion: неверный токен или интеграция не активирована в workspace")
        elif "404" in err:
            print("❌ Notion: страница/база не найдена или нет доступа")
        else:
            print(f"❌ Ошибка Notion: {e}")
        return False


def test_openrouter():
    """4. OpenRouter — доступ к модели."""
    print("\n" + "=" * 50)
    print("4. OPENROUTER (Gemini 3 Flash)")
    print("=" * 50)

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        print("❌ OPENROUTER_API_KEY не задан в .env")
        return False

    print("✓ API ключ задан")

    try:
        from openai import OpenAI
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
        )
        model = os.getenv("LLM_MODEL", "google/gemini-3-flash-preview")
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Ответь одним словом: OK"}],
            max_tokens=10,
        )
        choice = resp.choices[0] if resp.choices else None
        if not choice:
            print(f"❌ OpenRouter: пустой ответ (choices пуст)")
            return False
        text = (choice.message.content or "").strip()
        print(f"✓ OpenRouter отвечает. Модель: {model}. Ответ: {text[:50] or '(пусто)'}")
        return True
    except Exception as e:
        print(f"❌ Ошибка OpenRouter: {e}")
        return False


def main():
    print("\n🔍 Проверка доступа ко всем сервисам InsTracker Bot\n")

    results = []
    results.append(("Firebase Analytics", test_firebase_analytics()))
    results.append(("Adapty", test_adapty()))
    results.append(("Notion", test_notion()))
    results.append(("OpenRouter", test_openrouter()))

    print("\n" + "=" * 50)
    print("ИТОГ")
    print("=" * 50)
    for name, ok in results:
        status = "✓ OK" if ok else "❌ FAIL"
        print(f"  {name}: {status}")

    failed = sum(1 for _, ok in results if not ok)
    if failed == 0:
        print("\n✅ Все сервисы доступны.")
    else:
        print(f"\n⚠️ Проблемы с {failed} сервисом(ами).")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
