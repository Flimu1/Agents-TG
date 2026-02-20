#!/usr/bin/env python3
"""
Проверка доступа ко всем сервисам: Firebase, Adapty, Notion, OpenRouter.
Запуск: python test_services.py
"""
import os
import sys
from pathlib import Path

# Загружаем .env
from dotenv import load_dotenv
load_dotenv()

# Добавляем корень проекта в path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from agents.analytics import _get_credentials_path, _get_bigquery_client


def test_firebase_analytics():
    """1. Firebase Analytics (BigQuery) — основные метрики."""
    print("\n" + "=" * 50)
    print("1. FIREBASE ANALYTICS (BigQuery)")
    print("=" * 50)

    if not _get_credentials_path():
        print("❌ FIREBASE_CREDENTIALS_PATH не задан или файл не найден")
        return False

    print("✓ Файл credentials найден")

    dataset = os.getenv("FIREBASE_ANALYTICS_DATASET")
    if not dataset:
        print("⚠️ FIREBASE_ANALYTICS_DATASET не задан. Добавь в .env (формат: analytics_XXXXX)")
        return False

    client = _get_bigquery_client()
    if not client:
        print("❌ BigQuery-клиент недоступен (установи google-cloud-bigquery)")
        return False

    try:
        from datetime import datetime, timedelta
        since = (datetime.utcnow() - timedelta(days=1)).strftime("%Y%m%d")
        query = f"""
        SELECT event_name, COUNT(*) as cnt
        FROM `{client.project}.{dataset}.events_*`
        WHERE _TABLE_SUFFIX >= '{since}'
        GROUP BY event_name
        LIMIT 5
        """
        rows = list(client.query(query).result())
        print(f"✓ Firebase Analytics (BigQuery) доступен. Событий за 1 день: {sum(r.cnt for r in rows)}")
        return True
    except Exception as e:
        err = str(e)
        if "404" in err or "Not found" in err:
            print(f"❌ Dataset '{dataset}' не найден. Включи экспорт Firebase → BigQuery.")
        elif "403" in err or "Permission" in err:
            print("❌ Нет доступа к BigQuery. Выдай сервисному аккаунту роль BigQuery Data Viewer.")
        else:
            print(f"❌ Ошибка BigQuery: {e}")
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
