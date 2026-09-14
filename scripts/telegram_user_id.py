"""Find your numeric Telegram user ID without exposing the bot token in URLs or logs.
Run before the app, after sending the bot /start. Prints IDs only.
"""

import asyncio

from telegram import Bot

from app.config import Settings


async def main():
    settings = Settings()
    async with Bot(settings.telegram_bot_token.get_secret_value()) as bot:
        updates = await bot.get_updates(timeout=10)
        users = {(u.effective_user.id, u.effective_user.username or "") for u in updates if u.effective_user}
        for identifier, username in users:
            print(f"{identifier} @{username}")
        if not users:
            print("No updates found. Stop Ponke, send /start to your bot, then run this script again.")


if __name__ == "__main__":
    asyncio.run(main())
