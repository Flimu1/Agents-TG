"""Notion AI Agent — работа с Notion: страницы, базы, блоки."""
import os
from typing import Any

from notion_client import APIResponseError, Client

from .base import BaseAgent


class NotionAgent(BaseAgent):
    """Агент для работы с Notion: поиск, чтение, создание, обновление."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        token = os.getenv("NOTION_API_KEY")
        self.notion = Client(auth=token) if token else None

    @property
    def system_prompt(self) -> str:
        return """Ты — системный архитектор и хранитель знаний команды приложения InsTracker. Твоя задача — поддерживать порядок в базе Notion, сохранять туда важные отчеты, идеи от продакта и результаты созвонов команды.

Твои инструменты (Notion API):
- notion_search: всегда используй первым, чтобы найти нужную базу или страницу, если у тебя нет ее точного ID.
- notion_get_page / notion_get_blocks: чтобы прочитать, что уже написано.
- notion_create_page / notion_append_blocks: чтобы аккуратно записать новые данные. Помни, что ID в Notion выглядят как длинные строки с дефисами (UUID).

Как отвечать:
- Не пиши длинных текстов. Если тебя просят сохранить гипотезу — просто сохрани ее через инструмент и ответь: "✅ Сохранил на страницу [Название]".
- Если ищешь информацию — выдавай ее структурированным списком.
- Используй Telegram HTML: <b>жирный шрифт</b> для названий страниц, эмодзи (📁, 📝, 🔍) для визуального порядка.
"""

    @property
    def tools(self) -> list[dict]:
        return [
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
                    "description": "Получить блоки (контент) страницы",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "block_id": {"type": "string", "description": "ID страницы или блока"},
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
                                        "type": {"type": "string", "enum": ["paragraph", "heading_2", "heading_3", "bulleted_list_item", "numbered_list_item"]},
                                        "text": {"type": "string"},
                                    },
                                    "required": ["type", "text"],
                                },
                            },
                        },
                        "required": ["block_id", "blocks"],
                    },
                },
            },
        ]

    def _call_tool(self, name: str, arguments: dict) -> str:
        if not self.notion:
            return "NOTION_API_KEY не задан в .env. Создай интеграцию на notion.so/my-integrations."

        try:
            if name == "notion_search":
                return self._search(arguments["query"])
            if name == "notion_get_page":
                return self._get_page(arguments["page_id"])
            if name == "notion_get_blocks":
                return self._get_blocks(arguments["block_id"])
            if name == "notion_create_page":
                return self._create_page(arguments["parent_id"], arguments["title"])
            if name == "notion_append_blocks":
                return self._append_blocks(arguments["block_id"], arguments["blocks"])
        except APIResponseError as e:
            return f"Notion API ошибка: {e.body}"
        except Exception as e:
            return f"Ошибка: {e}"

        return f"Unknown tool: {name}"

    def _search(self, query: str) -> str:
        resp = self.notion.search(query=query, page_size=10)
        items = []
        for r in resp.get("results", []):
            obj = r.get("object", "")
            props = r.get("properties", {})
            title = "?"
            for key in ("title", "Name"):
                if key in props and isinstance(props[key].get("title"), list):
                    arr = props[key]["title"]
                    if arr:
                        title = arr[0].get("plain_text", "?")
                        break
            items.append(f"- {obj} {r['id']}: {title}")
        return "\n".join(items) if items else "Ничего не найдено."

    def _get_page(self, page_id: str) -> str:
        page = self.notion.pages.retrieve(page_id=page_id)
        props = page.get("properties", {})
        title = props.get("title", props.get("Name", {}))
        if isinstance(title.get("title"), list) and title["title"]:
            title = title["title"][0].get("plain_text", "")
        return f"Страница: {title}\nID: {page_id}"

    def _get_blocks(self, block_id: str) -> str:
        resp = self.notion.blocks.children.list(block_id=block_id)
        lines = []
        for b in resp.get("results", []):
            t = b.get("type", "")
            content = b.get(t, {})
            if "rich_text" in content and content["rich_text"]:
                text = content["rich_text"][0].get("plain_text", "")
                lines.append(f"[{t}] {text}")
        return "\n".join(lines) if lines else "Блоков нет."

    def _create_page(self, parent_id: str, title: str) -> str:
        parent: dict[str, Any]
        try:
            self.notion.databases.retrieve(database_id=parent_id)
            parent = {"database_id": parent_id}
            props = {"Name": {"title": [{"text": {"content": title}}]}}
        except Exception:
            parent = {"page_id": parent_id}
            props = {"title": {"title": [{"text": {"content": title}}]}}
        page = self.notion.pages.create(parent=parent, properties=props)
        return f"Страница создана: {page['id']}"

    def _append_blocks(self, block_id: str, blocks: list[dict]) -> str:
        children = []
        for b in blocks:
            bt = b.get("type", "paragraph")
            text = b.get("text", "")
            children.append({
                "object": "block",
                "type": bt,
                bt: {"rich_text": [{"type": "text", "text": {"content": text}}]},
            })
        self.notion.blocks.children.append(block_id=block_id, children=children)
        return f"Добавлено блоков: {len(blocks)}"
