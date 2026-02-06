from aiogram import BaseMiddleware
from aiogram.types import Message

class Logger(BaseMiddleware):
    async def __call__(self, handler, event: Message, data: dict):
        name = event.from_user.first_name or "Аноним"
        print(f"[{event.from_user.id}] {name}: {event.text}")
        return await handler(event, data)