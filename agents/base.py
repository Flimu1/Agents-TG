"""Базовый класс для AI-агентов с поддержкой tools (function calling)."""
import json
import os
from abc import ABC, abstractmethod
from typing import Any

from openai import OpenAI


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


class BaseAgent(ABC):
    """Абстрактный агент с системным промптом и тулами."""

    def __init__(self, model: str | None = None):
        self.client = _make_client()
        if os.getenv("OPENROUTER_API_KEY"):
            self.model = model or os.getenv("LLM_MODEL", OPENROUTER_DEFAULT_MODEL)
        else:
            self.model = model or os.getenv("LLM_MODEL", "openai/gpt-4o-mini")
        self.messages: list[dict[str, Any]] = []

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

    def process(self, user_message: str) -> str:
        """Обработка сообщения пользователя с поддержкой tool calls."""
        self.messages.append({"role": "user", "content": user_message})

        while True:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    *self.messages,
                ],
                tools=self.tools if self.tools else None,
                tool_choice="auto" if self.tools else None,
            )

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
                return msg.content

            return "Не удалось сформировать ответ."

    def clear_history(self):
        """Очистить историю диалога."""
        self.messages = []
