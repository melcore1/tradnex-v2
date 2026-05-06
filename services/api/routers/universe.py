"""/api/universe — list/add/remove."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from services.api.deps import DB, CurrentUser
from services.api.schemas import UniverseAddRequest, UniverseResponse
from shared.services.universe import (
    InvalidTickerError,
    add_to_universe,
    get_universe,
    remove_from_universe,
)

router = APIRouter()


@router.get("", response_model=UniverseResponse)
async def list_universe(db: DB, user: CurrentUser) -> UniverseResponse:
    return UniverseResponse(tickers=await get_universe(db))


@router.post("", response_model=UniverseResponse)
async def add(
    payload: UniverseAddRequest,
    db: DB,
    user: CurrentUser,
) -> UniverseResponse:
    """Add one or more tickers. Idempotent."""
    final: list[str] = []
    try:
        for t in payload.tickers:
            final = await add_to_universe(db, t)
    except InvalidTickerError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e
    return UniverseResponse(tickers=final)


@router.delete("/{ticker}", response_model=UniverseResponse)
async def remove(
    ticker: str,
    db: DB,
    user: CurrentUser,
) -> UniverseResponse:
    """Remove a ticker. Cascades to watchlists. Idempotent."""
    try:
        final = await remove_from_universe(db, ticker)
    except InvalidTickerError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e
    return UniverseResponse(tickers=final)
