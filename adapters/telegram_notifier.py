from telegram.ext import Application
from ports.notifier import Notifier

class TelegramNotifier(Notifier):
    def __init__(self, app: Application):
        self._app = app

    async def send(self, chat_id: int, message: str) -> None:
        await self._app.bot.send_message(chat_id=chat_id, text=message)
