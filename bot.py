import asyncio
from aiogram import Bot, Dispatcher
from config import BOT_TOKEN
from handlers import router
from middlewares import Logger

async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    
    # Подключаем логгирование и обработчики
    dp.message.middleware(Logger())
    dp.include_router(router)
    
    print("Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())