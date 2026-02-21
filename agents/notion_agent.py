"""Notion AI Agent — работа с Notion: страницы, базы, блоки."""
import os
from datetime import datetime
from typing import Any

from notion_client import APIResponseError

from .analytics import TZ_MINSK
from .base import BaseAgent


class NotionAgent(BaseAgent):
    """Агент для работы с Notion: поиск, чтение, создание, обновление."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    @property
    def system_prompt(self) -> str:
        now_minsk = datetime.now(TZ_MINSK)
        date_minsk = now_minsk.strftime("%Y-%m-%d")
        return f"""Часовой пояс: Минск (UTC+3). Текущая дата: {date_minsk}.

Ты — системный архитектор и хранитель знаний команды приложения InsTracker. Твоя задача — поддерживать порядок в базе Notion, сохранять туда важные отчеты, идеи от продакта и результаты созвонов команды.

Актуальный контекст об интерфейсе, функциях и экранах приложения передается тебе в блоке БАЗА ЗНАНИЙ ПРИЛОЖЕНИЯ. Обязательно учитывай эту информацию при формировании гипотез, поиске страниц или анализе метрик.

Твои инструменты (Notion API):
- notion_search: поиск страниц и баз по запросу. Используй первым, если нет точного ID.
- notion_get_page / notion_get_blocks: прочитать контент. По умолчанию notion_get_blocks возвращает только верхний уровень (depth=1). Используй depth>1 только для конкретного небольшого блока, когда нужно заглянуть внутрь; id блока в скобках — это block_id для добавления в него нового тоггла.
- notion_create_page / notion_append_blocks: записать новые данные. ID в Notion — длинные строки с дефисами (UUID).

Как отвечать:
- Не пиши длинных текстов. Если тебя просят сохранить гипотезу — просто сохрани ее через инструмент и ответь: "✅ Сохранил на страницу [Название]".
- Если ищешь информацию — выдавай ее структурированным списком.
- Используй Telegram HTML: <b>жирный шрифт</b> для названий страниц, эмодзи (📁, 📝, 🔍) для визуального порядка.
- В ответах пользователю никогда не показывай технические детали: ID страниц, ID блоков (UUID в скобках), названия моделей. Только читаемый текст и названия страниц.

——— ПОИСК И ЧТЕНИЕ ———
Если пользователь просит найти или прочитать информацию (например: «кто написал инкременты за вчера», «покажи инкременты за понедельник»):
1. Используй notion_search по ключевым словам из запроса (например «Инкременты», «Unfollowers» или тему отчета). Ищи нужную страницу по всей базе, не ограничивайся одной страницей.
2. СЕКРЕТ ПОИСКА ПО ДАТАМ: notion_get_blocks возвращает только текст блоков, без системных метаданных о дате. Чтобы найти «вчерашний инкремент» или запись по конкретной дате — ищи внутри блоков текст с этой датой или названием дня недели (понедельник, вторник, 2025-02-20 и т.д.). Не пытайся опираться на даты из API.
3. Если нашел нужный тоггл или блок с датой — проваливайся в него: вызови notion_get_blocks с его block_id (и при необходимости depth>1), чтобы прочитать содержимое.

——— СОХРАНЕНИЕ НОВЫХ ДАННЫХ ———
Правило про страницу «Unfollowers» действует ИСКЛЮЧИТЕЛЬНО при записи новых данных, сгенерированных агентами (инкременты, гипотезы, выводы, которые пользователь просит сохранить). В этом случае: notion_search('Unfollowers') → получить ID страницы → notion_append_blocks или save_increment_to_notion. Никогда не сохраняй такие инкременты в случайные места.
Когда пользователь просит только найти или прочитать существующую информацию — это правило НЕ применяется; ищи по ключевым словам по всей базе и читай блоки, как описано в блоке «ПОИСК И ЧТЕНИЕ».
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
                                        "type": {"type": "string", "enum": ["paragraph", "heading_2", "heading_3", "bulleted_list_item", "numbered_list_item", "toggle"]},
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
        if not self.notion:
            return "NOTION_API_KEY не задан в .env. Создай интеграцию на notion.so/my-integrations."

        try:
            if name == "notion_search":
                return self._search(arguments["query"])
            if name == "notion_get_page":
                return self._get_page(arguments["page_id"])
            if name == "notion_get_blocks":
                return self._get_blocks(arguments["block_id"], arguments.get("depth", 1))
            if name == "notion_create_page":
                return self._create_page(arguments["parent_id"], arguments["title"])
            if name == "notion_append_blocks":
                return self._append_blocks(arguments["block_id"], arguments["blocks"])
            if name == "save_increment_to_notion":
                return self._save_increment_to_notion(arguments.get("text", ""))
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

    def _blocks_children_all(self, block_id: str) -> list[dict]:
        """Все дочерние блоки с учётом пагинации."""
        out: list[dict] = []
        cursor: str | None = None
        while True:
            kwargs: dict[str, Any] = {"block_id": block_id, "page_size": 100}
            if cursor:
                kwargs["start_cursor"] = cursor
            resp = self.notion.blocks.children.list(**kwargs)
            out.extend(resp.get("results", []))
            if not resp.get("has_more"):
                break
            cursor = resp.get("next_cursor")
            if not cursor:
                break
        return out

    def _block_text(self, b: dict) -> str:
        t = b.get("type", "")
        content = b.get(t, {})
        if "rich_text" in content and content["rich_text"]:
            return content["rich_text"][0].get("plain_text", "")
        return ""

    def _get_blocks(self, block_id: str, depth: int = 1) -> str:
        lines: list[str] = []

        def walk(bid: str, level: int) -> None:
            if level <= 0:
                return
            children = self._blocks_children_all(bid)
            indent = "  " * (depth - level)
            for b in children:
                t = b.get("type", "")
                text = self._block_text(b)
                bid_child = b.get("id", "")
                lines.append(f"{indent}[{t}] {text} (id: {bid_child})")
                if level > 1:
                    walk(bid_child, level - 1)

        walk(block_id, depth)
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
            rich = [{"type": "text", "text": {"content": text}}]
            payload: dict[str, Any] = {
                "object": "block",
                "type": bt,
                bt: {"rich_text": rich},
            }
            # Toggle в Notion API — то же rich_text, без children в одном запросе
            children.append(payload)
        self.notion.blocks.children.append(block_id=block_id, children=children)
        return f"Добавлено блоков: {len(blocks)}"
