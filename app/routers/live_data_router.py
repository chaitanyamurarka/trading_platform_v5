# In app/routers/live_data_router.py

from fastapi import APIRouter, WebSocket, Path, Depends
import logging

from .. import live_data_service

router = APIRouter(
    prefix="/ws",
    tags=["Live Data"]
)

logger = logging.getLogger(__name__)

# --- MODIFICATION START ---
# The WebSocket path now includes a {timezone} parameter.
# Using ':path' allows for timezones containing slashes (e.g., 'America/New_York').
@router.websocket("/live/{symbol}/{interval}/{timezone:path}")
async def get_live_data(
    websocket: WebSocket,
    symbol: str = Path(..., description="Asset symbol (e.g., 'AAPL')"),
    interval: str = Path(..., description="Data interval (e.g., '1m', '5m', '1h')"),
    timezone: str = Path(..., description="Client's IANA timezone (e.g., 'America/New_York')")
):
# --- MODIFICATION END ---
    """
    Provides live OHLC data for a given symbol and interval over a WebSocket.

    - **Backend**: Subscribes to 1-second ticks from Redis.
    - **Resampling**: Aggregates ticks into the requested interval, aligned to the client's timezone.
    - **Broadcast**: Sends two objects in each message:
        - `completed_bar`: The full OHLCV of the last bar that just finished.
        - `current_bar`: The latest state of the bar currently being formed.
    """
    logger.info(f"WebSocket connection initiated for {symbol} with interval {interval} for timezone {timezone}.")
    # --- MODIFICATION START ---
    # Pass the received timezone to the websocket handler service.
    await live_data_service.websocket_handler(websocket, symbol, interval, timezone)
    # --- MODIFICATION END ---