# In app/routers/live_data_router.py

from fastapi import APIRouter, WebSocket, Path
import logging

from .. import live_data_service

router = APIRouter(
    prefix="/ws",
    tags=["Live Data"]
)

logger = logging.getLogger(__name__)

@router.websocket("/live/{symbol}/{interval}/{timezone:path}")
async def get_live_data(
    websocket: WebSocket,
    symbol: str = Path(..., description="Asset symbol (e.g., 'AAPL')"),
    interval: str = Path(..., description="Data interval (e.g., '1m', '5m', '1h')"),
    timezone: str = Path(..., description="Client's IANA timezone (e.g., 'America/New_York')")
):
    """
    Provides historical and live OHLC data for a given symbol and interval.

    - **On Connect**: Immediately sends a batch of all available intra-day
      data for the current trading session from the cache.
    - **Live Updates**: Subsequently streams live updates as they occur.
      Each message contains:
        - `completed_bar`: The full OHLCV of the last bar that just finished.
        - `current_bar`: The latest state of the currently forming bar.
    """
    await live_data_service.live_data_stream(websocket, symbol, interval, timezone)