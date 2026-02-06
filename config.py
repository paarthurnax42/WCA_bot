# Загружаем токены из .env — ничего сложного
import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
USDA_API_KEY = os.getenv("USDA_API_KEY", "")  # может быть пустым

# Минимальная проверка — чтобы не гадать, почему бот не запускается
if not BOT_TOKEN:
    raise RuntimeError("Не нашёл BOT_TOKEN в .env! Проверь файл.")