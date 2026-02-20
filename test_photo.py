#!/usr/bin/env python3
"""
Тесты функционала фото: парсинг IMAGE_B64 и multimodal content.
Запуск: python test_photo.py
"""
from __future__ import annotations

import base64
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

# Загружаем .env
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))


def test_image_b64_parsing():
    """Проверка парсинга префикса [IMAGE_B64:...] в base._process_sync."""
    print("\n" + "=" * 50)
    print("1. Парсинг IMAGE_B64")
    print("=" * 50)

    # Минимальный валидный base64 (1x1 пиксель JPEG)
    minimal_jpeg_b64 = "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAv/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFQEBAQAAAAAAAAAAAAAAAAAAAAX/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBEQACEQAD8ACg/9k="

    user_message = f"[IMAGE_B64:{minimal_jpeg_b64}]\nПроанализируй этот график."
    prefix = "[IMAGE_B64:"
    end_bracket = user_message.find("]", len(prefix))

    assert end_bracket != -1, "Должна находиться закрывающая ]"
    img_b64 = user_message[len(prefix) : end_bracket]
    rest = user_message[end_bracket + 1 :]
    caption = rest[1:].strip() if rest.startswith("\n") else rest.strip()

    assert img_b64 == minimal_jpeg_b64, "Base64 должен совпадать"
    assert caption == "Проанализируй этот график.", "Caption должен совпадать"

    content = [
        {"type": "text", "text": caption or "Проанализируй этот скриншот."},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
    ]

    assert content[0]["type"] == "text"
    assert content[0]["text"] == "Проанализируй этот график."
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")

    print("✓ Парсинг IMAGE_B64 корректен")
    return True


def test_image_b64_with_empty_caption():
    """Caption по умолчанию при пустой подписи."""
    print("\n" + "=" * 50)
    print("2. IMAGE_B64 с пустым caption")
    print("=" * 50)

    b64 = "YWJjMTIz"
    user_message = f"[IMAGE_B64:{b64}]\n"
    prefix = "[IMAGE_B64:"
    end_bracket = user_message.find("]", len(prefix))
    rest = user_message[end_bracket + 1 :]
    caption = rest[1:].strip() if rest.startswith("\n") else rest.strip()

    default = caption or "Проанализируй этот скриншот."
    assert default == "Проанализируй этот скриншот."

    print("✓ Дефолтный caption применяется")
    return True


def test_agent_processes_image_b64():
    """Агент корректно обрабатывает IMAGE_B64 и формирует multimodal content."""
    print("\n" + "=" * 50)
    print("3. Агент + IMAGE_B64 (mock API)")
    print("=" * 50)

    minimal_jpeg_b64 = "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIAAhEBAxED/8QAFQABAQAAAAAAAAAAAAAAAAAAAAv/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFQEBAQAAAAAAAAAAAAAAAAAAAAX/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBEQACEQAD8ACg/9k="
    user_message = f"[IMAGE_B64:{minimal_jpeg_b64}]\nЧто на скриншоте?"

    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(
            message=MagicMock(
                content="Это тестовый ответ.",
                tool_calls=None,
            )
        )
    ]

    with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}, clear=False):
        with patch("agents.base._make_client") as mock_make:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = mock_response
            mock_make.return_value = mock_client

            from agents.product import ProductAgent

            agent = ProductAgent(agent_name="test_photo", thread_id=99999)
            agent.clear_history()

            result = agent._process_sync(user_message)

            assert result == "Это тестовый ответ.", "Должен вернуться mock-ответ"

            # Проверяем, что в API ушёл multimodal content
            call_args = mock_client.chat.completions.create.call_args
            messages = call_args.kwargs.get("messages") or call_args[1].get("messages")
            assert messages is not None

            # Ищем user message с content-списком
            user_msgs = [m for m in messages if m.get("role") == "user"]
            assert len(user_msgs) >= 1
            last_user = user_msgs[-1]
            content = last_user["content"]

            assert isinstance(content, list), "Content должен быть списком для multimodal"
            text_part = next((p for p in content if p.get("type") == "text"), None)
            img_part = next((p for p in content if p.get("type") == "image_url"), None)

            assert text_part is not None, "Должен быть text part"
            assert img_part is not None, "Должен быть image_url part"
            assert text_part["text"] == "Что на скриншоте?"
            assert "data:image/jpeg;base64," in img_part["image_url"]["url"]

    print("✓ Агент формирует multimodal content для IMAGE_B64")
    return True


def test_plain_text_unchanged():
    """Обычный текст обрабатывается как раньше (без multimodal)."""
    print("\n" + "=" * 50)
    print("4. Обычный текст (без изменений)")
    print("=" * 50)

    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(
            message=MagicMock(
                content="Ответ на текст.",
                tool_calls=None,
            )
        )
    ]

    with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}, clear=False):
        with patch("agents.base._make_client") as mock_make:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = mock_response
            mock_make.return_value = mock_client

            from agents.product import ProductAgent

            agent = ProductAgent(agent_name="test_photo", thread_id=99998)
            agent.clear_history()

            result = agent._process_sync("Привет, обычный текст")

            assert result == "Ответ на текст."

            call_args = mock_client.chat.completions.create.call_args
            messages = call_args.kwargs.get("messages") or call_args[1].get("messages")
            user_msgs = [m for m in messages if m.get("role") == "user"]
            last_user = user_msgs[-1]
            content = last_user["content"]

            assert isinstance(content, str), "Для обычного текста content — строка"
            assert content == "Привет, обычный текст"

    print("✓ Обычный текст передаётся как строка")
    return True


def test_photo_to_user_text_format():
    """Симуляция: фото -> base64 -> user_text в формате bot.py."""
    print("\n" + "=" * 50)
    print("5. Формат user_text из bot.py")
    print("=" * 50)

    # Симулируем что bot.py делает с фото
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        f.write(b"\xff\xd8\xff\xe0\x00\x10JFIF")  # минимальный JPEG header
        tmp_path = f.name

    try:
        with open(tmp_path, "rb") as f:
            img_b64 = base64.standard_b64encode(f.read()).decode("ascii")
        caption = "Проанализируй этот скриншот."
        user_text = f"[IMAGE_B64:{img_b64}]\n{caption}"

        assert user_text.startswith("[IMAGE_B64:")
        assert "\n" in user_text
        assert user_text.endswith("Проанализируй этот скриншот.")
    finally:
        os.unlink(tmp_path)

    print("✓ Формат user_text корректен")
    return True


def main():
    print("\n🔍 Тесты функционала фото (IMAGE_B64)\n")

    results = []
    results.append(("Парсинг IMAGE_B64", test_image_b64_parsing()))
    results.append(("Пустой caption", test_image_b64_with_empty_caption()))
    results.append(("Формат user_text", test_photo_to_user_text_format()))
    results.append(("Агент + IMAGE_B64", test_agent_processes_image_b64()))
    results.append(("Обычный текст", test_plain_text_unchanged()))

    print("\n" + "=" * 50)
    print("ИТОГ")
    print("=" * 50)
    for name, ok in results:
        status = "✓ OK" if ok else "❌ FAIL"
        print(f"  {name}: {status}")

    failed = sum(1 for _, ok in results if not ok)
    if failed == 0:
        print("\n✅ Все тесты фото пройдены.")
    else:
        print(f"\n⚠️ Провалено тестов: {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
