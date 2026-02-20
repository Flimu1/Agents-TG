"""
Telegram бот: каждый топик в группе = отдельный AI-агент.
Сообщение в топик обрабатывает соответствующий агент.
Поддержка голосовых сообщений через OpenRouter (Gemini с аудио).
"""
import asyncio
import base64
import logging
import os
import tempfile
from pathlib import Path
from typing import Awaitable, Callable, Optional

import yaml
from dotenv import load_dotenv
from openai import OpenAI
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

from agents import AGENTS

load_dotenv()
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Загрузка конфига
CONFIG_PATH = Path(__file__).parent / "config.yaml"
if not CONFIG_PATH.exists():
    raise SystemExit(
        "Создай config.yaml из config.example.yaml и заполни group_id, topics"
    )
with open(CONFIG_PATH, encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)

GROUP_ID = CONFIG["telegram"]["group_id"]
TOPIC_AGENTS: dict[int, str] = {int(k): v for k, v in CONFIG.get("topics", {}).items()}
ALLOWED_USERS: list[int] = CONFIG.get("telegram", {}).get("allowed_users") or []

# Кэш агентов: (chat_id, thread_id) -> agent instance
agent_cache: dict[tuple[int, int], object] = {}


# Сообщения об ошибках для пользователя (понятным языком)
ERROR_MESSAGES = {
    "rate_limit": "Слишком много запросов. Подожди немного и попробуй снова.",
    "authentication": "Ошибка доступа к API. Проверь OPENROUTER_API_KEY в настройках.",
    "timeout": "Запрос занял слишком много времени. Попробуй ещё раз.",
    "connection": "Не удалось подключиться к серверу. Проверь интернет.",
    "model": "Модель недоступна. Проверь LLM_MODEL в настройках.",
    "quota": "Исчерпан лимит запросов. Попробуй позже или проверь баланс.",
}


def _human_error_message(exc: Exception) -> str:
    """Преобразует исключение в понятное сообщение для пользователя."""
    err_str = str(exc).lower()
    if "rate" in err_str or "limit" in err_str or "429" in err_str:
        return ERROR_MESSAGES["rate_limit"]
    if "auth" in err_str or "401" in err_str or "403" in err_str or "api_key" in err_str:
        return ERROR_MESSAGES["authentication"]
    if "timeout" in err_str or "timed out" in err_str:
        return ERROR_MESSAGES["timeout"]
    if "connection" in err_str or "connect" in err_str or "network" in err_str:
        return ERROR_MESSAGES["connection"]
    if "model" in err_str or "404" in err_str or "not found" in err_str:
        return ERROR_MESSAGES["model"]
    if "unexpected keyword" in err_str or "reasoning" in err_str:
        return "Версия API изменилась. Обнови бота или напиши разработчику."
    if "quota" in err_str or "insufficient" in err_str:
        return ERROR_MESSAGES["quota"]
    # Общий fallback — коротко и без технических деталей
    return "Произошла ошибка при обработке запроса. Попробуй ещё раз или напиши разработчику."


def split_message(text: str, limit: int = 4000) -> list[str]:
    """Разбить текст на части по абзацам, не превышая limit символов."""
    if len(text) <= limit:
        return [text]
    parts = []
    current = ""
    for paragraph in text.split("\n\n"):
        chunk = paragraph + "\n\n"
        if len(current) + len(chunk) > limit:
            if current:
                parts.append(current.rstrip())
            current = chunk
        else:
            current += chunk
    if current.strip():
        parts.append(current.rstrip())
    return parts if parts else [text[:limit]]


def _get_openrouter_client() -> Optional[OpenAI]:
    """OpenRouter-клиент для транскрипции (тот же ключ, что и для агентов)."""
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return None
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )


async def transcribe_voice(
    bot,
    voice_file_id: str,
    *,
    on_status: Optional[Callable[[str], Awaitable[None]]] = None,
) -> Optional[str]:
    """Транскрипция голосового сообщения через OpenRouter (Gemini с аудио)."""
    client = _get_openrouter_client()
    if not client:
        return None

    try:
        if on_status:
            await on_status("Скачиваю голосовое...")
        voice_file = await bot.get_file(voice_file_id)
        tmp_path = tempfile.mktemp(suffix=".ogg")
        await voice_file.download_to_drive(tmp_path)
        try:
            with open(tmp_path, "rb") as f:
                audio_bytes = f.read()
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

        if on_status:
            await on_status("Транскрибирую голосовое...")
        audio_b64 = base64.standard_b64encode(audio_bytes).decode("ascii")
        model = os.getenv("LLM_MODEL", "google/gemini-3-flash-preview")

        resp = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Транскрибируй это голосовое сообщение в текст. Верни только текст, без пояснений.",
                        },
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": audio_b64,
                                "format": "ogg",
                            },
                        },
                    ],
                },
            ],
            max_tokens=1000,
        )
        text = resp.choices[0].message.content
        return text.strip() if text else None
    except Exception as e:
        logger.exception("Voice transcription failed: %s", e)
        return None


def get_agent(agent_name: str, chat_id: int, thread_id: int):
    """Получить или создать агента для топика."""
    key = (chat_id, thread_id)
    if key not in agent_cache:
        if agent_name not in AGENTS:
            return None
        cls = AGENTS[agent_name]
        agent_cache[key] = cls(agent_name=agent_name, thread_id=thread_id)
    return agent_cache[key]


async def cmd_topic_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать ID текущего топика (для настройки config.yaml)."""
    msg = update.message
    if not msg:
        return
    if ALLOWED_USERS and msg.from_user and msg.from_user.id not in ALLOWED_USERS:
        return
    thread_id = msg.message_thread_id
    chat_id = msg.chat_id
    text = f"Topic ID (message_thread_id): {thread_id}\nДобавь в config.yaml: {thread_id}: <agent_name>"
    await msg.reply_text(text, message_thread_id=thread_id)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать список агентов и команд."""
    msg = update.message
    if not msg:
        return
    if ALLOWED_USERS and msg.from_user and msg.from_user.id not in ALLOWED_USERS:
        return
    thread_id = msg.message_thread_id or 1
    lines = ["🤖 <b>Агенты InsTracker</b>\n\nПиши в нужный топик:\n"]
    for topic_id, agent_name in sorted(TOPIC_AGENTS.items()):
        lines.append(f"• Топик <code>{topic_id}</code> → {agent_name}")
    lines.append(
        "\n<b>Команды:</b>\n"
        "/clear — очистить историю агента в этом топике\n"
        "/status — проверить подключения\n"
        "/topic_id — узнать ID текущего топика"
    )
    await msg.reply_text("\n".join(lines), message_thread_id=thread_id, parse_mode="HTML")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверить наличие API ключей в env."""
    msg = update.message
    if not msg:
        return
    if ALLOWED_USERS and msg.from_user and msg.from_user.id not in ALLOWED_USERS:
        return
    thread_id = msg.message_thread_id or 1
    checks = [
        ("OPENROUTER_API_KEY", "LLM (OpenRouter)"),
        ("GA4_PROPERTY_ID", "Firebase Analytics (GA4)"),
        ("GOOGLE_CREDENTIALS_PATH", "Google Service Account"),
        ("ADAPTY_SECRET_KEY", "Adapty"),
        ("NOTION_API_KEY", "Notion"),
    ]
    status_lines = ["<b>🔌 Статус подключений:</b>"]
    for env_var, label in checks:
        value = os.getenv(env_var)
        icon = "✅" if value and value.strip() else "❌"
        status_lines.append(f"{icon} {label}")
    await msg.reply_text("\n".join(status_lines), message_thread_id=thread_id, parse_mode="HTML")


async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Очистить историю диалога агента в этом топике."""
    msg = update.message
    if not msg:
        return
    if ALLOWED_USERS and msg.from_user and msg.from_user.id not in ALLOWED_USERS:
        return
    thread_id = msg.message_thread_id or 1
    chat_id = msg.chat_id
    key = (chat_id, thread_id)
    if key in agent_cache:
        agent_cache[key].clear_history()
        del agent_cache[key]
    await msg.reply_text("История очищена.", message_thread_id=thread_id)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка сообщений: роутинг по топику -> агент. Поддержка текста и голоса."""
    msg = update.message
    if not msg:
        return

    if ALLOWED_USERS and msg.from_user and msg.from_user.id not in ALLOWED_USERS:
        return

    chat_id = msg.chat_id
    thread_id = msg.message_thread_id

    # Только наша группа
    if chat_id != GROUP_ID:
        logger.info(f"Ignoring chat {chat_id} (expected {GROUP_ID})")
        return

    # Определяем агента по топику
    agent_name = TOPIC_AGENTS.get(thread_id) if thread_id else TOPIC_AGENTS.get(1)
    if not agent_name:
        logger.info(f"No agent for thread_id={thread_id}")
        return

    agent = get_agent(agent_name, chat_id, thread_id or 1)
    if not agent:
        await msg.reply_text(f"Агент '{agent_name}' не найден.", message_thread_id=thread_id)
        return

    # Текст или голос -> текст (голос через OpenRouter/Gemini)
    status_msg = None

    if msg.voice:
        status_msg = await msg.reply_text(
            "🔹 Принял голосовое. Скачиваю...",
            message_thread_id=thread_id,
        )

        async def update_status(text: str) -> None:
            if status_msg:
                try:
                    await status_msg.edit_text(f"🔹 {text}")
                except Exception:
                    pass

        user_text = await transcribe_voice(
            context.bot,
            msg.voice.file_id,
            on_status=update_status,
        )
        if not user_text:
            await msg.reply_text(
                "Не удалось распознать голос. Проверь OPENROUTER_API_KEY и попробуй ещё раз.",
                message_thread_id=thread_id,
            )
            if status_msg:
                try:
                    await status_msg.delete()
                except Exception:
                    pass
            return
        logger.info("Voice transcribed: %s...", user_text[:50] if len(user_text) > 50 else user_text)
        if status_msg:
            try:
                await status_msg.edit_text("🔹 Генерирую ответ...")
            except Exception:
                pass
    elif msg.text:
        user_text = msg.text
        status_msg = await msg.reply_text(
            "🔹 Генерирую ответ...",
            message_thread_id=thread_id,
        )
    elif msg.photo:
        photo = msg.photo[-1]
        status_msg = await msg.reply_text(
            "🔹 Анализирую изображение...",
            message_thread_id=thread_id,
        )
        photo_file = await context.bot.get_file(photo.file_id)
        tmp_path = tempfile.mktemp(suffix=".jpg")
        await photo_file.download_to_drive(tmp_path)
        with open(tmp_path, "rb") as f:
            img_b64 = base64.standard_b64encode(f.read()).decode("ascii")
        os.unlink(tmp_path)
        caption = msg.caption or "Проанализируй этот скриншот."
        user_text = f"[IMAGE_B64:{img_b64}]\n{caption}"
    else:
        return

    async def _keep_typing():
        while not done_event.is_set():
            await msg.chat.send_action("typing", message_thread_id=thread_id)
            await asyncio.sleep(4)

    done_event = asyncio.Event()
    typing_task = asyncio.create_task(_keep_typing())
    try:
        response = await agent.process(user_text)
        # Удаляем статус перед ответом
        if status_msg:
            try:
                await status_msg.delete()
            except Exception:
                pass
        parts = split_message(response)
        for i, part in enumerate(parts):
            try:
                if i == 0:
                    await msg.reply_text(part, message_thread_id=thread_id, parse_mode="HTML")
                else:
                    await msg.chat.send_message(part, message_thread_id=thread_id, parse_mode="HTML")
            except Exception as parse_err:
                logger.warning("HTML parse failed for part %d, sending as plain text: %s", i + 1, parse_err)
                if i == 0:
                    await msg.reply_text(part, message_thread_id=thread_id)
                else:
                    await msg.chat.send_message(part, message_thread_id=thread_id)
    except Exception as e:
        logger.exception("Ошибка при обработке запроса: %s", e, exc_info=True)
        if status_msg:
            try:
                await status_msg.delete()
            except Exception:
                pass
        user_friendly = _human_error_message(e)
        await msg.reply_text(user_friendly, message_thread_id=thread_id)
    finally:
        done_event.set()
        typing_task.cancel()


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN не задан. Создай .env из .env.example")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("topic_id", cmd_topic_id))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(
        MessageHandler(
            (filters.TEXT & ~filters.COMMAND) | filters.VOICE | filters.PHOTO,
            handle_message,
        )
    )

    logger.info("Bot started. Topics: %s", TOPIC_AGENTS)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
