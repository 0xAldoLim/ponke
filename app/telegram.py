import asyncio
import io
import time
from collections import defaultdict, deque
from contextlib import suppress
from uuid import uuid4

import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from app.orchestrator import Reply
from app.validation import Clarification
from app.voice import present_reply

log = structlog.get_logger()


class RateLimiter:
    def __init__(self, limit):
        self.limit, self.events = limit, defaultdict(deque)

    def allow(self, user_id, now=None):
        now = time.monotonic() if now is None else now
        events = self.events[user_id]
        while events and events[0] <= now - 60:
            events.popleft()
        if len(events) >= self.limit:
            return False
        events.append(now)
        return True


class Gateway:
    def __init__(self, settings, orchestrator):
        self.settings, self.orchestrator = settings, orchestrator
        self.limiter = RateLimiter(settings.requests_per_minute)
        self.locks = defaultdict(asyncio.Lock)
        self.application = (
            Application.builder()
            .token(settings.telegram_bot_token.get_secret_value())
            .concurrent_updates(4)
            .build()
        )
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("id", self.id_command))
        self.application.add_handler(CallbackQueryHandler(self.callback))
        self.application.add_handler(MessageHandler(filters.ALL, self.message))
        self.application.add_error_handler(self.error)

    def authorized(self, update):
        return bool(
            update.effective_user
            and update.effective_chat
            and update.effective_user.id in self.settings.allowed_ids
            and update.effective_chat.type == "private"
            and update.effective_chat.id == update.effective_user.id
        )

    async def start_command(self, update, context):
        user, chat, message = update.effective_user, update.effective_chat, update.effective_message
        if not user or not chat or not message:
            return
        if chat.type != "private":
            await message.reply_text("Message me privately and send /start to get set up.")
            return
        if not self.authorized(update):
            await message.reply_text(
                f"Hi, I'm Ponke. Your Telegram ID is {user.id}. Send it to the bot owner "
                "to request access. Once they add you, send /start again."
            )
            return
        await message.reply_text(
            "Hey, I'm Ponke. Tell me what you're trying to get done and I'll help you work through it. "
            "I can keep track of expenses, set reminders, check your calendar, read receipts, "
            "and help think through decisions.\n\n"
            "You can say things like “Spent 48k on coffee using BCA” or "
            "“Remind me tomorrow at 8 PM to water the plants.”\n\n"
            "For your calendar, use /connect_calendar. You can also ask for /briefing or /export_finance."
        )

    async def id_command(self, update, context):
        user, chat, message = update.effective_user, update.effective_chat, update.effective_message
        if not user or not chat or not message:
            return
        if chat.type != "private":
            await message.reply_text("Message me privately and send /id to see your Telegram ID.")
            return
        await message.reply_text(
            f"Your Telegram user ID is {user.id}. The bot owner can add this ID to the allowlist."
        )

    async def message(self, update, context):
        if not update.message or not update.effective_user or not update.effective_chat:
            return
        if not self.authorized(update):
            if update.effective_chat.type == "private" and self.limiter.allow(update.effective_user.id):
                await update.message.reply_text(
                    "I can't use your personal workspace yet. Send /id here and share the number "
                    "with the bot owner to request access."
                )
            return
        user_id = update.effective_user.id
        if not self.limiter.allow(user_id):
            await update.message.reply_text("Please wait a minute before sending another request.")
            return
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=uuid4().hex)
        started = time.monotonic()
        async with self.locks[user_id]:
            try:
                message = update.message
                text = message.text or message.caption or ""
                image, document, filename, unique_id = None, None, None, None
                attachment = message.photo[-1] if message.photo else message.document
                if attachment:
                    statement_types = {
                        "text/csv",
                        "text/plain",
                        "application/vnd.ms-excel",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        "application/pdf",
                        "application/octet-stream",
                    }
                    is_statement = bool(
                        message.document
                        and message.document.file_name
                        and message.document.file_name.lower().endswith((".csv", ".xlsx", ".pdf"))
                    )
                    if (
                        message.document
                        and not is_statement
                        and message.document.mime_type not in {"image/jpeg", "image/png"}
                    ):
                        raise Clarification("Send a JPEG/PNG receipt or a CSV/XLSX/PDF bank statement.")
                    if is_statement and message.document.mime_type not in statement_types:
                        raise Clarification("The file type doesn't match a supported statement.")
                    if attachment.file_size is None or attachment.file_size > self.settings.max_upload_bytes:
                        raise Clarification(
                            "This image is too large or its size is unknown. Please send a smaller receipt image."
                        )
                    file = await attachment.get_file()
                    # Telegram Bot API metadata is the only download source; never accept a user URL.
                    content = bytes(await file.download_as_bytearray())
                    if len(content) > self.settings.max_upload_bytes:
                        raise Clarification("This file is too large. Please send a smaller one.")
                    if is_statement:
                        document, filename = content, message.document.file_name
                    else:
                        image = content
                    unique_id = attachment.file_unique_id
                elif not text:
                    raise Clarification("Please send text or a receipt image.")
                progress = asyncio.create_task(self.show_progress(user_id))
                try:
                    reply = await self.orchestrator.handle(
                        user_id,
                        f"{message.chat_id}:{message.message_id}",
                        text,
                        image,
                        unique_id,
                        document,
                        filename,
                    )
                finally:
                    progress.cancel()
                    with suppress(asyncio.CancelledError):
                        await progress
                await self.deliver(user_id, reply)
            except Clarification as exc:
                await self.send(user_id, str(exc))
            except Exception as exc:
                log.error("telegram_request_failed", error_type=type(exc).__name__)
                await self.send(
                    user_id, "I could not deliver a confirmed result. Check your records before trying again."
                )
            finally:
                log.info("request_finished", latency_ms=round((time.monotonic() - started) * 1000))

    async def show_progress(self, user_id):
        elapsed = 0
        while True:
            try:
                await self.application.bot.send_chat_action(chat_id=user_id, action="typing")
                if elapsed == 12:
                    await self.send(user_id, "I'm still working on this. Give me a moment.")
            except Exception:
                return  # A progress update must never prevent the actual answer.
            await asyncio.sleep(4)
            elapsed += 4

    async def callback(self, update, context):
        if not self.authorized(update):
            return
        query = update.callback_query
        await query.answer()
        user_id = update.effective_user.id
        if not self.limiter.allow(user_id):
            await self.send(user_id, "Please wait a minute before trying again.")
            return
        async with self.locks[user_id]:
            data = query.data or ""
            action, separator, identifier = data.partition(":")
            if not separator or len(identifier) != 32:
                return
            if action in {"yes", "no"}:
                reply = await self.orchestrator.confirm(user_id, identifier, action == "yes")
            elif action in {"done", "cancel_reminder"}:
                from app.reminders import change_reminder

                async with self.orchestrator.sessions.begin() as db:
                    text = await change_reminder(
                        db, user_id, identifier, "completed" if action == "done" else "cancelled"
                    )
                reply = Reply(text)
            else:
                return
            await query.edit_message_reply_markup(reply_markup=None)
            await self.deliver(user_id, reply)

    async def send(self, user_id, text, reminder_id=None, markup=None):
        if user_id not in self.settings.allowed_ids:
            raise PermissionError("Unauthorized delivery")
        text = present_reply(text)
        if reminder_id:
            markup = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("Done", callback_data="done:" + reminder_id),
                        InlineKeyboardButton(
                            "Cancel reminder", callback_data="cancel_reminder:" + reminder_id
                        ),
                    ]
                ]
            )
        # Plain text prevents markdown injection. Bound chunks by UTF-16 code units used by Telegram.
        chunks, chunk, units = [], "", 0
        for char in text:
            cost = 2 if ord(char) > 0xFFFF else 1
            if units + cost > 3900:
                chunks.append(chunk)
                chunk, units = "", 0
            chunk += char
            units += cost
        chunks.append(chunk)
        for index, part in enumerate(chunks):
            await self.application.bot.send_message(
                user_id, part or "Done.", reply_markup=markup if index == len(chunks) - 1 else None
            )

    async def deliver(self, user_id, reply):
        markup = None
        if reply.confirmation_id:
            markup = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("Confirm", callback_data="yes:" + reply.confirmation_id),
                        InlineKeyboardButton("Cancel", callback_data="no:" + reply.confirmation_id),
                    ]
                ]
            )
        if reply.document:
            await self.application.bot.send_document(
                user_id, io.BytesIO(reply.document), filename=reply.filename
            )
        await self.send(user_id, reply.text, reminder_id=reply.reminder_id, markup=markup)

    async def error(self, update, context):
        log.error("telegram_handler_failed", error_type=type(context.error).__name__)

    async def start(self):
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling(
            drop_pending_updates=False, allowed_updates=["message", "callback_query"]
        )

    async def stop(self):
        if self.application.updater.running:
            await self.application.updater.stop()
        if self.application.running:
            await self.application.stop()
        await self.application.shutdown()
