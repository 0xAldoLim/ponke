from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import text

from app.calendar import GoogleCalendar
from app.config import Settings
from app.database import make_database
from app.llm import OpenAIModel
from app.logging import configure_logging
from app.orchestrator import Orchestrator
from app.reminders import SchedulerWorker
from app.telegram import Gateway
from app.validation import Clarification


def create_app(settings=None):
    config = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        configure_logging()
        config.validate_runtime()
        engine, sessions = make_database(config.database_url.get_secret_value())
        app.state.engine, app.state.ready = engine, False
        singleton = await engine.connect()
        gateway, scheduler, model, calendar = None, None, None, None
        try:
            if engine.dialect.name == "postgresql":
                acquired = await singleton.scalar(text("SELECT pg_try_advisory_lock(70666501)"))
                if not acquired:
                    raise RuntimeError("Another Ponke process is active; use exactly one app replica")
            async with sessions() as db:
                # Production schema must be installed by Alembic, never create_all at startup.
                await db.execute(text("SELECT id FROM inbound LIMIT 1"))
            model = OpenAIModel(config)
            calendar = GoogleCalendar(config, sessions)
            service = Orchestrator(sessions, config, model, calendar)
            gateway = Gateway(config, service)
            app.state.calendar = calendar
            worker = SchedulerWorker(sessions, config, gateway, service.briefing)
            await gateway.start()
            scheduler = AsyncIOScheduler(timezone=config.user_timezone)
            scheduler.add_job(worker.tick, "interval", seconds=15, max_instances=1, coalesce=True)
            scheduler.start()
            app.state.ready = True
            yield
        finally:
            app.state.ready = False
            if scheduler and scheduler.running:
                scheduler.shutdown(wait=False)
            if gateway:
                await gateway.stop()
            if calendar:
                await calendar.close()
            if model:
                await model.close()
            if engine.dialect.name == "postgresql":
                await singleton.execute(text("SELECT pg_advisory_unlock(70666501)"))
            await singleton.close()
            await engine.dispose()

    app = FastAPI(title="Ponke", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health/live")
    async def live():
        return {"status": "alive"}

    @app.get("/health/ready")
    async def ready():
        if not getattr(app.state, "ready", False):
            raise HTTPException(503, "Starting")
        async with app.state.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return {"status": "ready"}

    @app.get("/oauth/google/callback", response_class=HTMLResponse)
    async def oauth_callback(
        state: str = Query(min_length=20, max_length=200),
        code: str | None = Query(default=None, max_length=4000),
        error: str | None = Query(default=None, max_length=200),
    ):
        if error or not code:
            raise HTTPException(400, "Authorization was not completed. Request a new link in Telegram.")
        try:
            await app.state.calendar.callback(state, code)
        except Clarification as exc:
            raise HTTPException(400, str(exc)) from None
        except Exception:
            raise HTTPException(
                502, "Google authorization could not be completed. Request a new link in Telegram."
            ) from None
        return HTMLResponse(
            "<h1>Google Calendar connected</h1><p>You can return to Ponke in Telegram.</p>",
            headers={
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
            },
        )

    return app


app = create_app()
