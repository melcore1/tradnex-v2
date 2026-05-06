"""/api/watchlist — get/set today's watchlist + history."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from services.api.deps import DB, CurrentUser
from services.api.schemas import WatchlistResponse, WatchlistSetRequest
from shared.services.universe import TickerNotInUniverseError
from shared.services.watchlist import (
    add_ticker_to_watchlist,
    get_active_watchlist,
    get_watchlist_history,
    remove_ticker_from_watchlist,
    set_watchlist,
)

router = APIRouter()


def _entry_to_response(entry: Any) -> WatchlistResponse:
    return WatchlistResponse(
        date=entry.date,
        tickers=list(entry.tickers),
        per_ticker_overrides=dict(entry.per_ticker_overrides),
        notes=entry.notes,
    )


@router.get("/today", response_model=WatchlistResponse)
async def get_today(db: DB, user: CurrentUser) -> WatchlistResponse:
    entry = await get_active_watchlist(db)
    return _entry_to_response(entry)


@router.put("", response_model=WatchlistResponse)
async def set_today_or_date(
    payload: WatchlistSetRequest,
    db: DB,
    user: CurrentUser,
) -> WatchlistResponse:
    try:
        entry = await set_watchlist(
            db,
            tickers=payload.tickers,
            per_ticker_overrides=payload.per_ticker_overrides,
            notes=payload.notes,
            date=payload.date,
        )
    except TickerNotInUniverseError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e
    return _entry_to_response(entry)


@router.post("/tickers/{ticker}", response_model=WatchlistResponse)
async def add_ticker(
    ticker: str,
    db: DB,
    user: CurrentUser,
) -> WatchlistResponse:
    try:
        entry = await add_ticker_to_watchlist(db, ticker)
    except TickerNotInUniverseError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e
    return _entry_to_response(entry)


@router.delete("/tickers/{ticker}", response_model=WatchlistResponse)
async def remove_ticker(
    ticker: str,
    db: DB,
    user: CurrentUser,
) -> WatchlistResponse:
    entry = await remove_ticker_from_watchlist(db, ticker)
    return _entry_to_response(entry)


@router.get("/history", response_model=list[WatchlistResponse])
async def history(
    db: DB,
    user: CurrentUser,
    days: int = Query(30, ge=1, le=365),
) -> list[WatchlistResponse]:
    entries = await get_watchlist_history(db, days=days)
    return [_entry_to_response(e) for e in entries]
