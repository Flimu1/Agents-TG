#!/usr/bin/env python3
"""
Показать все BigQuery datasets в проекте.
Запуск: python scripts/list_bigquery_datasets.py

Используй имя dataset (например analytics_123456789) для FIREBASE_ANALYTICS_DATASET в .env
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()


def _get_client():
    try:
        from google.cloud import bigquery
        from google.oauth2 import service_account
    except ImportError:
        return None

    # Сначала проверяем переменную с полным JSON (удобно для Railway и др.)
    raw = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    if raw and raw.strip():
        try:
            info = json.loads(raw)
            cred = service_account.Credentials.from_service_account_info(info)
            return bigquery.Client(credentials=cred, project=cred.project_id)
        except Exception:
            pass

    cred_path = os.getenv("FIREBASE_CREDENTIALS_PATH")
    if not cred_path:
        return None
    if not os.path.isabs(cred_path):
        cred_path = str(Path(__file__).parent.parent / cred_path)
    if not os.path.exists(cred_path):
        return None
    try:
        cred = service_account.Credentials.from_service_account_file(cred_path)
        return bigquery.Client(credentials=cred, project=cred.project_id)
    except Exception:
        return None


def main():
    client = _get_client()
    if not client:
        print("❌ BigQuery недоступен. Установи: pip install google-cloud-bigquery")
        return 1

    print(f"\n📂 BigQuery datasets в проекте {client.project}:\n")

    try:
        datasets = list(client.list_datasets())
        if not datasets:
            print("  Datasets не найдены.")
            print("\n  Возможные причины:")
            print("  - Экспорт Firebase → BigQuery ещё не настроен")
            print("  - Dataset создаётся при первом экспорте (подожди до 24 часов)")
            print("  - Сервисному аккаунту нужна роль BigQuery Data Viewer")
            return 0

        for ds in datasets:
            full_id = f"{client.project}.{ds.dataset_id}"
            print(f"  • {ds.dataset_id}")
            print(f"    → Добавь в .env: FIREBASE_ANALYTICS_DATASET={ds.dataset_id}")
            print()

        print("  Для Firebase Analytics ищи dataset вида analytics_XXXXX")
        return 0

    except Exception as e:
        print(f"❌ Ошибка: {e}")
        if "403" in str(e) or "Permission" in str(e):
            print("\n  Выдай сервисному аккаунту роль BigQuery Data Viewer:")
            print("  https://console.cloud.google.com/iam-admin/iam?project=insttracker-85c34")
        return 1


if __name__ == "__main__":
    sys.exit(main())
