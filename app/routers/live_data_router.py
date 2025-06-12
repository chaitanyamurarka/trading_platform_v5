# In app/routers/live_data_router.py

from fastapi import APIRouter, WebSocket, Path, Depends
import logging

from .. import live_data_service

router = APIRouter(
    prefix="/ws",
    tags=["Live Data"]
)

logger = logging.getLogger(__name__)

@router.websocket("/live/{symbol}/{interval}")
async def get_live_data(
    websocket: WebSocket,
    symbol: str = Path(..., description="Asset symbol (e.g., 'AAPL')"),
    interval: str = Path(..., description="Data interval (e.g., '1m', '5m', '1h')")
):
    """
    Provides live OHLC data for a given symbol and interval over a WebSocket.

    - **Backend**: Subscribes to 1-second ticks from Redis.
    - **Resampling**: Aggregates ticks into the requested interval.
    - **Broadcast**: Sends two objects in each message:
        - `completed_bar`: The full OHLCV of the last bar that just finished.
        - `current_bar`: The latest state of the bar currently being formed.
    """
    logger.info(f"WebSocket connection initiated for {symbol} with interval {interval}.")
    await live_data_service.websocket_handler(websocket, symbol, interval)