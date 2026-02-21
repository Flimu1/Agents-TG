"""Базовый класс для AI-агентов с поддержкой tools (function calling)."""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from datetime import datetime
from abc import ABC, abstractmethod
from functools import partial
from pathlib import Path
from typing import Any, Callable, Optional

from notion_client import APIResponseError, Client
from openai import OpenAI

DB_PATH = Path(__file__).parent.parent / "agent_history.db"
APP_KNOWLEDGE_PATH = Path(__file__).resolve().parent.parent / "docs" / "app_knowledge.md"


def _load_app_knowledge() -> str:
    """Читает docs/app_knowledge.md. При отсутствии файла или ошибке возвращает пустую строку."""
    try:
        if APP_KNOWLEDGE_PATH.is_file():
            return APP_KNOWLEDGE_PATH.read_text(encoding="utf-8")
    except (OSError, IOError):
        pass
    return ""


def _init_db():
    con = sqlite3.connect(DB_PATH, timeout=10.0)
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("""CREATE TABLE IF NOT EXISTS history (
        agent_key TEXT PRIMARY KEY,
        messages TEXT NOT NULL,
        updated_at REAL NOT NULL
    )""")
    con.commit()
    con.close()


def _load_history(agent_key: str, history_limit: int) -> list[dict]:
    if history_limit == 0:
        return []
    con = sqlite3.connect(DB_PATH, timeout=10.0)
    row = con.execute(
        "SELECT messages FROM history WHERE agent_key=?", (agent_key,)
    ).fetchone()
    con.close()
    if row:
        msgs = json.loads(row[0])
        return msgs[-history_limit:]
    return []


def _message_to_dict(msg: Any) -> dict:
    """Приводит сообщение (dict или ChatCompletionMessage) к JSON-сериализуемому dict."""
    if isinstance(msg, dict):
        return msg
    # ChatCompletionMessage из openai
    role = getattr(msg, "role", "assistant")
    content = getattr(msg, "content", None) or ""
    out = {"role": role, "content": content}
    if getattr(msg, "tool_calls", None):
        out["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in msg.tool_calls
        ]
    return out


def _save_history(agent_key: str, messages: list[Any], history_limit: int):
    if history_limit == 0:
        return
    import time
    serializable = [_message_to_dict(m) for m in messages[-history_limit:]]
    con = sqlite3.connect(DB_PATH, timeout=10.0)
    con.execute("""INSERT INTO history(agent_key, messages, updated_at)
        VALUES(?,?,?) ON CONFLICT(agent_key) DO UPDATE SET
        messages=excluded.messages, updated_at=excluded.updated_at""",
        (agent_key, json.dumps(serializable, ensure_ascii=False), time.time())
    )
    con.commit()
    con.close()


def _make_client() -> OpenAI:
    """OpenRouter или OpenAI — по наличию OPENROUTER_API_KEY."""
    if os.getenv("OPENROUTER_API_KEY"):
        return OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.getenv("OPENROUTER_API_KEY"),
        )
    return OpenAI()


# Модель по умолчанию при использовании OpenRouter
OPENROUTER_DEFAULT_MODEL = "google/gemini-3-flash-preview"

# Допустимые значения effort для thinking/reasoning (OpenRouter Gemini)
THINKING_EFFORT_VALUES = ("none", "minimal", "low", "medium", "high", "xhigh")

# Сообщения статуса при вызове инструментов (для отображения в Telegram)
TOOL_STATUS_MESSAGES: dict[str, str] = {
    "get_adapty_metrics": "📊 Запрашиваю данные из Adapty...",
    "get_firebase_analytics": "📈 Запрашиваю аналитику GA4...",
    "get_firebase_funnel": "🔄 Строю воронку в GA4...",
    "notion_search": "🔍 Ищу в базе Notion...",
    "notion_get_page": "📄 Открываю страницу в Notion...",
    "notion_get_blocks": "📑 Читаю блоки страницы в Notion...",
    "notion_create_page": "✨ Создаю страницу в Notion...",
    "notion_append_blocks": "📝 Добавляю блоки в Notion...",
    "save_increment_to_notion": "📌 Сохраняю инкремент в Notion...",
}


def _get_thinking_effort() -> str | None:
    """Читает THINKING_EFFORT из env: low, medium, high и др. None = не передавать."""
    raw = (os.getenv("THINKING_EFFORT") or "").strip().lower()
    return raw if raw in THINKING_EFFORT_VALUES else None


class BaseAgent(ABC):
    """Абстрактный агент с системным промптом и тулами."""

    def __init__(self, model: str | None = None, agent_name: str = "", thread_id: int = 0, history_limit: int = 6):
        self._agent_key = f"{agent_name}:{thread_id}"
        self._history_limit = history_limit
        self._app_knowledge = _load_app_knowledge()
        _init_db()
        self.client = _make_client()
        self.notion = Client(auth=os.getenv("NOTION_API_KEY")) if os.getenv("NOTION_API_KEY") else None
        if os.getenv("OPENROUTER_API_KEY"):
            self.model = model or os.getenv("LLM_MODEL", OPENROUTER_DEFAULT_MODEL)
        else:
            self.model = model or os.getenv("LLM_MODEL", "openai/gpt-4o-mini")
        self.messages: list[dict[str, Any]] = _load_history(self._agent_key, self._history_limit)
        self._thinking_effort = _get_thinking_effort()

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """Системный промпт агента."""
        pass

    @property
    @abstractmethod
    def tools(self) -> list[dict]:
        """Список tools в формате OpenAI function calling."""
        pass

    def _call_tool(self, name: str, arguments: dict) -> str:
        """Вызов тула по имени. Переопределяется в наследниках."""
        raise NotImplementedError(f"Tool {name} not implemented")

    def _save_increment_to_notion(self, text: str) -> str:
        """Сохранить инкремент (текст) на страницу Unfollowers в Notion."""
        if self.notion is None:
            return "NOTION_API_KEY не задан."
        resp = self.notion.search(query="Unfollowers", page_size=1)
        results = resp.get("results", [])
        if not results:
            return "Страница Unfollowers не найдена."
        page_id = results[0]["id"]
        title = f"📌 Инкремент ({datetime.now().strftime('%d.%m.%Y %H:%M')})"
        self.notion.blocks.children.append(
            block_id=page_id,
            children=[
                {
                    "object": "block",
                    "type": "toggle",
                    "toggle": {
                        "rich_text": [{"type": "text", "text": {"content": title}}],
                        "children": [
                            {
                                "object": "block",
                                "type": "paragraph",
                                "paragraph": {"rich_text": [{"type": "text", "text": {"content": text}}]}
                            }
                        ]
                    }
                }
            ],
        )
        return "✅ Инкремент успешно сохранен в Notion (страница Unfollowers)"

    def _search(self, query: str) -> str:
        if self.notion is None:
            return "NOTION_API_KEY не задан."
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
        if self.notion is None:
            return "NOTION_API_KEY не задан."
        page = self.notion.pages.retrieve(page_id=page_id)
        props = page.get("properties", {})
        title = props.get("title", props.get("Name", {}))
        if isinstance(title.get("title"), list) and title["title"]:
            title = title["title"][0].get("plain_text", "")
        return f"Страница: {title}\nID: {page_id}"

    def _blocks_children_all(self, block_id: str) -> list[dict]:
        """Все дочерние блоки с учётом пагинации."""
        if self.notion is None:
            return []
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

    def _create_page(self, parent_id: str, title: str, icon: str | None = None) -> str:
        if self.notion is None:
            return "NOTION_API_KEY не задан."
        parent: dict[str, Any]
        try:
            self.notion.databases.retrieve(database_id=parent_id)
            parent = {"database_id": parent_id}
            props = {"Name": {"title": [{"text": {"content": title}}]}}
        except Exception:
            parent = {"page_id": parent_id}
            props = {"title": {"title": [{"text": {"content": title}}]}}
        page_kwargs: dict[str, Any] = {"parent": parent, "properties": props}
        if icon:
            page_kwargs["icon"] = {"type": "emoji", "emoji": icon}
        page = self.notion.pages.create(**page_kwargs)
        return f"Страница создана: {page['id']}"

    def _append_blocks(self, block_id: str, blocks: list[dict]) -> str:
        if self.notion is None:
            return "NOTION_API_KEY не задан."
        children = []
        for b in blocks:
            bt = b.get("type", "paragraph")
            if bt == "link_to_page":
                payload: dict[str, Any] = {
                    "object": "block",
                    "type": "link_to_page",
                    "link_to_page": {"type": "page_id", "page_id": b.get("page_id", "")}
                }
            else:
                text = b.get("text", "")
                rich = [{"type": "text", "text": {"content": text}}]
                payload = {
                    "object": "block",
                    "type": bt,
                    bt: {"rich_text": rich},
                }
                if bt == "callout":
                    payload[bt]["icon"] = {"type": "emoji", "emoji": b.get("emoji", "💡")}
                    payload[bt]["color"] = b.get("color", "default")
                elif bt == "to_do":
                    payload[bt]["checked"] = bool(b.get("checked", False))
                elif b.get("color"):
                    payload[bt]["color"] = b["color"]
            children.append(payload)
        resp = self.notion.blocks.children.append(block_id=block_id, children=children)
        created_ids = [res.get("id") for res in resp.get("results", [])]
        return f"Добавлено блоков: {len(blocks)}. ID созданных блоков: {', '.join(map(str, created_ids))}"

    def _process_sync(
        self,
        user_message: str,
        status_callback: Optional[Callable[[str], None]] = None,
    ) -> str:
        """Обработка сообщения пользователя с поддержкой tool calls (синхронная)."""
        if user_message.startswith("[IMAGE_B64:"):
            prefix = "[IMAGE_B64:"
            end_bracket = user_message.find("]", len(prefix))
            if end_bracket != -1:
                img_b64 = user_message[len(prefix):end_bracket]
                rest = user_message[end_bracket + 1:]
                caption = rest[1:].strip() if rest.startswith("\n") else rest.strip()
                content = [
                    {"type": "text", "text": caption or "Проанализируй этот скриншот."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                ]
                self.messages.append({"role": "user", "content": content})
            else:
                self.messages.append({"role": "user", "content": user_message})
        else:
            self.messages.append({"role": "user", "content": user_message})

        system_content = self.system_prompt
        if self._app_knowledge:
            system_content += "\n\n--- БАЗА ЗНАНИЙ ПРИЛОЖЕНИЯ ---\n\n" + self._app_knowledge

        while True:
            kwargs = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_content},
                    *self.messages,
                ],
                "tools": self.tools if self.tools else None,
                "tool_choice": "auto" if self.tools else None,
            }
            if self._thinking_effort and os.getenv("OPENROUTER_API_KEY"):
                kwargs["extra_body"] = {"reasoning": {"effort": self._thinking_effort}}
            response = self.client.chat.completions.create(**kwargs)

            choice = response.choices[0]
            msg = choice.message

            if msg.tool_calls:
                self.messages.append(_message_to_dict(msg))
                for tc in msg.tool_calls:
                    name = tc.function.name
                    args = json.loads(tc.function.arguments)
                    if status_callback:
                        status_text = TOOL_STATUS_MESSAGES.get(
                            name, f"⚙️ Вызываю {name}..."
                        )
                        status_callback(status_text)
                    result = self._call_tool(name, args)
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    })
                continue

            # Финальный текстовый ответ
            content = (msg.content or "").strip()
            if content:
                self.messages.append({"role": "assistant", "content": msg.content})
                _save_history(self._agent_key, self.messages, self._history_limit)
                return msg.content

            # Модель не вернула текст (часто после успешных tool calls). Отправляем короткое подтверждение.
            had_tool_calls = any(m.get("role") == "tool" for m in self.messages)
            if had_tool_calls:
                fallback = "✅ Задача выполнена. Проверь результат (например в Notion)."
                self.messages.append({"role": "assistant", "content": fallback})
                _save_history(self._agent_key, self.messages, self._history_limit)
                return fallback
            return "Не удалось сформировать ответ."

    async def process(
        self,
        user_message: str,
        status_callback: Optional[Callable[[str], None]] = None,
    ) -> str:
        """Асинхронная обёртка над _process_sync — не блокирует event loop."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, partial(self._process_sync, user_message, status_callback)
        )

    def clear_history(self):
        """Очистить историю диалога."""
        self.messages = []
        _save_history(self._agent_key, [], self._history_limit)
