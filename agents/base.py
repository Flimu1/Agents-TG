"""Базовый класс для AI-агентов с поддержкой tools (function calling)."""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from openai import OpenAI

DB_PATH = Path(__file__).parent.parent / "agent_history.db"


def _init_db():
    con = sqlite3.connect(DB_PATH)
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
    con = sqlite3.connect(DB_PATH)
    row = con.execute(
        "SELECT messages FROM history WHERE agent_key=?", (agent_key,)
    ).fetchone()
    con.close()
    if row:
        msgs = json.loads(row[0])
        return msgs[-history_limit:]
    return []


def _save_history(agent_key: str, messages: list[dict], history_limit: int):
    if history_limit == 0:
        return
    import time
    con = sqlite3.connect(DB_PATH)
    con.execute("""INSERT INTO history(agent_key, messages, updated_at)
        VALUES(?,?,?) ON CONFLICT(agent_key) DO UPDATE SET
        messages=excluded.messages, updated_at=excluded.updated_at""",
        (agent_key, json.dumps(messages[-history_limit:], ensure_ascii=False), time.time())
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


def _get_thinking_effort() -> str | None:
    """Читает THINKING_EFFORT из env: low, medium, high и др. None = не передавать."""
    raw = (os.getenv("THINKING_EFFORT") or "").strip().lower()
    return raw if raw in THINKING_EFFORT_VALUES else None


class BaseAgent(ABC):
    """Абстрактный агент с системным промптом и тулами."""

    def __init__(self, model: str | None = None, agent_name: str = "", thread_id: int = 0, history_limit: int = 6):
        self._agent_key = f"{agent_name}:{thread_id}"
        self._history_limit = history_limit
        _init_db()
        self.client = _make_client()
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

    def _process_sync(self, user_message: str) -> str:
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

        while True:
            kwargs = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": self.system_prompt},
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
                self.messages.append(msg)
                for tc in msg.tool_calls:
                    name = tc.function.name
                    args = json.loads(tc.function.arguments)
                    result = self._call_tool(name, args)
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    })
                continue

            # Финальный текстовый ответ
            if msg.content:
                self.messages.append({"role": "assistant", "content": msg.content})
                _save_history(self._agent_key, self.messages, self._history_limit)
                return msg.content

            return "Не удалось сформировать ответ."

    async def process(self, user_message: str) -> str:
        """Асинхронная обёртка над _process_sync — не блокирует event loop."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._process_sync, user_message)

    def clear_history(self):
        """Очистить историю диалога."""
        self.messages = []
        _save_history(self._agent_key, [], self._history_limit)
