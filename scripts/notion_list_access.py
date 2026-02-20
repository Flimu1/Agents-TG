#!/usr/bin/env python3
"""
Показать страницы и базы, к которым есть доступ у Notion-интеграции.
Запуск: python scripts/notion_list_access.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

from notion_client import Client, APIResponseError


def get_title(props):
    """Извлечь заголовок из properties."""
    for key in ("title", "Name"):
        if key in props:
            val = props[key]
            if isinstance(val.get("title"), list) and val["title"]:
                return val["title"][0].get("plain_text", "?")
    return "—"


def main():
    token = os.getenv("NOTION_API_KEY")
    if not token:
        print("❌ NOTION_API_KEY не задан в .env")
        return 1

    client = Client(auth=token)

    print("\n📋 Доступ Notion-интеграции\n")
    print("=" * 60)

    try:
        # Search возвращает всё, к чему у интеграции есть доступ
        resp = client.search(query="", page_size=100, sort={"direction": "descending", "timestamp": "last_edited_time"})
        results = resp.get("results", [])

        if not results:
            print("\n  Нет доступа ни к одной странице или базе.")
            print("\n  Как дать доступ:")
            print("  1. Открой страницу/базу в Notion")
            print("  2. Share → Add connections → выбери свою интеграцию")
            return 0

        pages = []
        databases = []

        for r in results:
            obj = r.get("object", "")
            title = get_title(r.get("properties", {}))
            url = r.get("url", "")
            pid = r.get("id", "")
            if obj == "page":
                pages.append((title, pid, url))
            elif obj == "database":
                databases.append((title, pid, url))

        if databases:
            print("\n📂 БАЗЫ ДАННЫХ (databases)")
            print("-" * 60)
            for title, pid, url in databases:
                print(f"  • {title}")
                print(f"    ID: {pid}  |  {url}")

        if pages:
            print("\n📄 СТРАНИЦЫ (pages)")
            print("-" * 60)
            for title, pid, url in pages:
                print(f"  • {title}")
                print(f"    ID: {pid}  |  {url}")

        print("\n" + "=" * 60)
        print(f"\n  Всего: {len(databases)} баз, {len(pages)} страниц")
        print("\n  Агент может:")
        print("  • ЧИТАТЬ: search, get_page, get_blocks")
        print("  • СОЗДАВАТЬ: create_page, append_blocks")
        print("  • Редактировать существующие блоки — НЕТ")
        return 0

    except APIResponseError as e:
        print(f"❌ Notion API: {e.body}")
        return 1
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
