#!/usr/bin/env python3
"""Запуск Notion Agent с одним сообщением (для теста).
Использование: python scripts/run_notion_agent_test.py
"""
import asyncio
import os
import sys

# корень проекта
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from agents.notion_agent import NotionAgent


async def main():
    user_message = (
        "На странице HappyAI Team найди страницу Инкременты HappyAI, "
        "найди там вчерашний тоггл и создай в нем новый тоггл с подписью Murphy"
    )
    print("Запрос:", user_message)
    print("-" * 60)
    agent = NotionAgent(agent_name="test_run", thread_id=0)
    try:
        result = await agent.process(user_message)
        print("Ответ агента:")
        print(result)
    except Exception as e:
        print("Ошибка:", e)
        raise


if __name__ == "__main__":
    asyncio.run(main())
