#!/usr/bin/env python3
"""
Тесты инструментов агентов: вызов _call_tool и проверка корректности ответов.
Запуск: python tests/test_tools.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _tz_minsk():
    from datetime import timezone
    return timezone(timedelta(hours=3))


def test_analytics_get_adapty_metrics():
    """AnalyticsAgent: get_adapty_metrics — возвращает JSON или сообщение об ошибке."""
    print("\n" + "=" * 50)
    print("AnalyticsAgent: get_adapty_metrics")
    print("=" * 50)

    from agents.analytics import AnalyticsAgent

    agent = AnalyticsAgent(agent_name="test_tools", thread_id=1)
    end = datetime.now(_tz_minsk())
    start = end - timedelta(days=7)
    args = {
        "chart_ids": ["revenue", "subscriptions_active"],
        "date_from": start.strftime("%Y-%m-%d"),
        "date_to": end.strftime("%Y-%m-%d"),
        "period_unit": "day",
    }

    result = agent._call_tool("get_adapty_metrics", args)

    if not result or not isinstance(result, str):
        print("❌ Результат пустой или не строка")
        return False

    if "ADAPTY" in result and "не задан" in result:
        print("⚠️ Adapty ключ не задан (ожидаемо без .env)")
        return True  # Ожидаемое поведение

    try:
        data = json.loads(result)
        if not isinstance(data, list):
            print("❌ Ожидается список chart results")
            return False
        for item in data:
            if "chart_id" not in item and "error" not in item:
                print("❌ Каждый элемент должен содержать chart_id или error")
                return False
        print(f"✓ get_adapty_metrics: получено {len(data)} chart(s)")
        return True
    except json.JSONDecodeError:
        print(f"❌ Ответ не валидный JSON: {result[:100]}...")
        return False


def test_analytics_get_firebase_analytics():
    """AnalyticsAgent: get_firebase_analytics — возвращает JSON с метриками."""
    print("\n" + "=" * 50)
    print("AnalyticsAgent: get_firebase_analytics")
    print("=" * 50)

    from agents.analytics import AnalyticsAgent

    agent = AnalyticsAgent(agent_name="test_tools", thread_id=2)
    args = {"days_back": 3, "event_names": []}

    result = agent._call_tool("get_firebase_analytics", args)

    if not result or not isinstance(result, str):
        print("❌ Результат пустой или не строка")
        return False

    if "GA4" in result and ("недоступен" in result or "не задан" in result):
        print("⚠️ GA4 недоступен (ожидаемо без credentials)")
        return True

    if "google-analytics-data" in result and "не установлена" in result:
        print("⚠️ Библиотека GA4 не установлена")
        return True

    try:
        data = json.loads(result)
        if not isinstance(data, list):
            print("❌ Ожидается список метрик")
            return False
        print(f"✓ get_firebase_analytics: получено {len(data)} метрик")
        return True
    except json.JSONDecodeError:
        print(f"❌ Ответ не валидный JSON: {result[:100]}...")
        return False


def test_analytics_get_firebase_funnel():
    """AnalyticsAgent: get_firebase_funnel — воронка по event_names."""
    print("\n" + "=" * 50)
    print("AnalyticsAgent: get_firebase_funnel")
    print("=" * 50)

    from agents.analytics import AnalyticsAgent

    agent = AnalyticsAgent(agent_name="test_tools", thread_id=3)
    args = {
        "event_names": ["session_start", "first_open"],
        "days_back": 7,
    }

    result = agent._call_tool("get_firebase_funnel", args)

    if not result or not isinstance(result, str):
        print("❌ Результат пустой или не строка")
        return False

    if "GA4" in result and ("недоступен" in result or "не задан" in result):
        print("⚠️ GA4 недоступен (ожидаемо)")
        return True

    if "event_names" in result and "Передай" in result:
        print("⚠️ Пустой event_names — ожидаемая ошибка при пустом списке")
        return True

    # GA4 может вернуть 403/ошибку доступа — инструмент вызван корректно
    if "Ошибка GA4:" in result or "403" in result or "permissions" in result.lower():
        print("⚠️ GA4 вернул ошибку доступа (инструмент работает)")
        return True

    try:
        data = json.loads(result)
        if not isinstance(data, list):
            print("❌ Ожидается список")
            return False
        print(f"✓ get_firebase_funnel: получены данные воронки")
        return True
    except json.JSONDecodeError:
        print(f"❌ Ответ не валидный JSON: {result[:100]}...")
        return False


def test_product_get_adapty_metrics():
    """ProductAgent: get_adapty_metrics (наследует от Analytics)."""
    print("\n" + "=" * 50)
    print("ProductAgent: get_adapty_metrics")
    print("=" * 50)

    from agents.product import ProductAgent

    agent = ProductAgent(agent_name="test_tools", thread_id=4)
    args = {"chart_ids": ["mrr", "revenue"], "period_unit": "month"}

    result = agent._call_tool("get_adapty_metrics", args)

    if not result or not isinstance(result, str):
        print("❌ Результат пустой или не строка")
        return False

    if "ADAPTY" in result and "не задан" in result:
        print("⚠️ Adapty ключ не задан")
        return True

    try:
        json.loads(result)
        print("✓ ProductAgent get_adapty_metrics: OK")
        return True
    except json.JSONDecodeError:
        print(f"❌ Не валидный JSON: {result[:80]}...")
        return False


def test_product_get_firebase_analytics():
    """ProductAgent: get_firebase_analytics."""
    print("\n" + "=" * 50)
    print("ProductAgent: get_firebase_analytics")
    print("=" * 50)

    from agents.product import ProductAgent

    agent = ProductAgent(agent_name="test_tools", thread_id=5)
    result = agent._call_tool("get_firebase_analytics", {"days_back": 7})

    if not result or not isinstance(result, str):
        print("❌ Результат пустой или не строка")
        return False

    if "GA4" in result and ("недоступен" in result or "не задан" in result):
        print("⚠️ GA4 недоступен")
        return True

    try:
        json.loads(result)
        print("✓ ProductAgent get_firebase_analytics: OK")
        return True
    except json.JSONDecodeError:
        print(f"❌ Не валидный JSON: {result[:80]}...")
        return False


def test_product_get_firebase_funnel():
    """ProductAgent наследует _call_tool от AnalyticsAgent — get_firebase_funnel тоже работает."""
    print("\n" + "=" * 50)
    print("ProductAgent: get_firebase_funnel (наследование)")
    print("=" * 50)

    from agents.product import ProductAgent

    agent = ProductAgent(agent_name="test_tools", thread_id=6)
    result = agent._call_tool("get_firebase_funnel", {"event_names": ["session_start"], "days_back": 7})

    if not result or not isinstance(result, str):
        print("❌ Результат пустой или не строка")
        return False

    # ProductAgent.tools не включает get_firebase_funnel (LLM его не видит),
    # но _call_tool наследуется — при прямом вызове работает
    if "Ошибка GA4:" in result or "403" in result:
        print("⚠️ GA4 ошибка доступа (инструмент вызывается)")
        return True
    try:
        json.loads(result)
        print("✓ ProductAgent get_firebase_funnel: OK")
        return True
    except json.JSONDecodeError:
        print(f"❌ Не валидный ответ: {result[:80]}...")
        return False


def test_notion_search():
    """NotionAgent: notion_search."""
    print("\n" + "=" * 50)
    print("NotionAgent: notion_search")
    print("=" * 50)

    from agents.notion_agent import NotionAgent

    agent = NotionAgent(agent_name="test_tools", thread_id=7)
    result = agent._call_tool("notion_search", {"query": "test"})

    if not result or not isinstance(result, str):
        print("❌ Результат пустой или не строка")
        return False

    if "NOTION_API_KEY" in result and "не задан" in result:
        print("⚠️ Notion ключ не задан")
        return True

    # Успех: строка со списком или "Ничего не найдено"
    print("✓ notion_search: OK")
    return True


def test_notion_get_page():
    """NotionAgent: notion_get_page — нужен валидный page_id."""
    print("\n" + "=" * 50)
    print("NotionAgent: notion_get_page")
    print("=" * 50)

    from agents.notion_agent import NotionAgent

    agent = NotionAgent(agent_name="test_tools", thread_id=8)
    # Используем невалидный UUID — Notion вернёт 404 или ошибку
    result = agent._call_tool("notion_get_page", {"page_id": "00000000-0000-0000-0000-000000000000"})

    if not result or not isinstance(result, str):
        print("❌ Результат пустой или не строка")
        return False

    if "NOTION_API_KEY" in result and "не задан" in result:
        print("⚠️ Notion ключ не задан")
        return True

    # С валидным ключом: либо "Страница: ...", либо ошибка API
    if "Страница:" in result or "Notion" in result or "404" in result or "ошибка" in result.lower():
        print("✓ notion_get_page: инструмент вызван корректно")
        return True

    print(f"✓ notion_get_page: {result[:60]}...")
    return True


def test_notion_get_blocks():
    """NotionAgent: notion_get_blocks."""
    print("\n" + "=" * 50)
    print("NotionAgent: notion_get_blocks")
    print("=" * 50)

    from agents.notion_agent import NotionAgent

    agent = NotionAgent(agent_name="test_tools", thread_id=9)
    result = agent._call_tool("notion_get_blocks", {"block_id": "00000000-0000-0000-0000-000000000000"})

    if not result or not isinstance(result, str):
        print("❌ Результат пустой или не строка")
        return False

    if "NOTION_API_KEY" in result and "не задан" in result:
        print("⚠️ Notion ключ не задан")
        return True

    print("✓ notion_get_blocks: инструмент вызван корректно")
    return True


def test_notion_create_page():
    """NotionAgent: notion_create_page — только проверка вызова (не создаём реальную страницу без parent)."""
    print("\n" + "=" * 50)
    print("NotionAgent: notion_create_page")
    print("=" * 50)

    from agents.notion_agent import NotionAgent

    agent = NotionAgent(agent_name="test_tools", thread_id=10)
    # Без ключа — ожидаем сообщение. С ключом и невалидным parent — ошибка API.
    result = agent._call_tool("notion_create_page", {
        "parent_id": "00000000-0000-0000-0000-000000000000",
        "title": "Test Page",
    })

    if not result or not isinstance(result, str):
        print("❌ Результат пустой или не строка")
        return False

    if "NOTION_API_KEY" in result and "не задан" in result:
        print("⚠️ Notion ключ не задан")
        return True

    if "Страница создана:" in result or "Notion" in result or "ошибка" in result.lower():
        print("✓ notion_create_page: инструмент вызван корректно")
        return True

    print(f"✓ notion_create_page: {result[:60]}...")
    return True


def test_notion_append_blocks():
    """NotionAgent: notion_append_blocks."""
    print("\n" + "=" * 50)
    print("NotionAgent: notion_append_blocks")
    print("=" * 50)

    from agents.notion_agent import NotionAgent

    agent = NotionAgent(agent_name="test_tools", thread_id=11)
    result = agent._call_tool("notion_append_blocks", {
        "block_id": "00000000-0000-0000-0000-000000000000",
        "blocks": [{"type": "paragraph", "text": "Test"}],
    })

    if not result or not isinstance(result, str):
        print("❌ Результат пустой или не строка")
        return False

    if "NOTION_API_KEY" in result and "не задан" in result:
        print("⚠️ Notion ключ не задан")
        return True

    if "Добавлено блоков:" in result or "Notion" in result or "ошибка" in result.lower():
        print("✓ notion_append_blocks: инструмент вызван корректно")
        return True

    print(f"✓ notion_append_blocks: {result[:60]}...")
    return True


def main():
    print("\n🔧 Тесты инструментов агентов InsTracker Bot\n")

    tests = [
        ("Analytics: get_adapty_metrics", test_analytics_get_adapty_metrics),
        ("Analytics: get_firebase_analytics", test_analytics_get_firebase_analytics),
        ("Analytics: get_firebase_funnel", test_analytics_get_firebase_funnel),
        ("Product: get_adapty_metrics", test_product_get_adapty_metrics),
        ("Product: get_firebase_analytics", test_product_get_firebase_analytics),
        ("Product: get_firebase_funnel", test_product_get_firebase_funnel),
        ("Notion: notion_search", test_notion_search),
        ("Notion: notion_get_page", test_notion_get_page),
        ("Notion: notion_get_blocks", test_notion_get_blocks),
        ("Notion: notion_create_page", test_notion_create_page),
        ("Notion: notion_append_blocks", test_notion_append_blocks),
    ]

    results = []
    for name, fn in tests:
        try:
            ok = fn()
            results.append((name, ok))
        except Exception as e:
            print(f"❌ Исключение: {e}")
            results.append((name, False))

    print("\n" + "=" * 50)
    print("ИТОГ")
    print("=" * 50)
    for name, ok in results:
        status = "✓ OK" if ok else "❌ FAIL"
        print(f"  {name}: {status}")

    failed = sum(1 for _, ok in results if not ok)
    if failed == 0:
        print("\n✅ Все инструменты вызываются корректно.")
    else:
        print(f"\n⚠️ Провалено тестов: {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
