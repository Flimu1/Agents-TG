"""
Telegram бот: каждый топик в группе = отдельный AI-агент.
Сообщение в топик обрабатывает соответствующий агент.
"""
import logging
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
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


def get_agent(agent_name: str, chat_id: int, thread_id: int):
    """Получить или создать агента для топика."""
    key = (chat_id, thread_id)
    if key not in agent_cache:
        if agent_name not in AGENTS:
            return None
        cls = AGENTS[agent_name]
        agent_cache[key] = cls()
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
    """Обработка сообщений: роутинг по топику -> агент."""
    msg = update.message
    if not msg or not msg.text:
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

    # Голосовые — можно расширить: скачать file, speech-to-text
    user_text = msg.text
    if msg.voice:
        await msg.reply_text("Голосовые пока не поддерживаются — напиши текстом.", message_thread_id=thread_id)
        return

    await msg.chat.send_action("typing", message_thread_id=thread_id)

    try:
        response = agent.process(user_text)
        # Telegram лимит 4096 символов
        if len(response) > 4000:
            response = response[:3997] + "..."
        await msg.reply_text(response, message_thread_id=thread_id)
    except Exception as e:
        logger.exception(e)
        await msg.reply_text(f"Ошибка: {e}", message_thread_id=thread_id)


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN не задан. Создай .env из .env.example")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("topic_id", cmd_topic_id))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot started. Topics: %s", TOPIC_AGENTS)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
