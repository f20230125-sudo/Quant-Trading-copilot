from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .agent.client import build_client
from .api.ratelimit import SlidingWindowLimiter
from .api.routes import router
from .config import Settings, get_settings
from .market import SyntheticMarket

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app(settings: Settings | None = None, market: SyntheticMarket | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.market = market or SyntheticMarket(seed=settings.market_seed, history_size=settings.market_history_size)
        app.state.market.start()
        yield
        await app.state.market.stop()

    app = FastAPI(title="Quant Copilot", lifespan=lifespan)
    app.state.settings = settings
    app.state.anthropic = build_client(settings)
    app.state.chat_limiter = SlidingWindowLimiter(settings.chat_rate_limit_per_minute)
    app.state.key_limiter = SlidingWindowLimiter(5)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type"],
    )
    app.include_router(router)
    return app


app = create_app()
