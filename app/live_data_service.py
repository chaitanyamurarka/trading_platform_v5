# In app/live_data_service.py

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator, Dict, Optional, List
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from starlette.websockets import WebSocket, WebSocketDisconnect
from websockets.exceptions import ConnectionClosed

import pandas as pd
import redis.asyncio as aioredis
from fastapi import WebSocket

from . import schemas
from .config import settings

logger = logging.getLogger(__name__)

# Connect to Redis
redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)

class BarResampler:
    """
    Aggregates 1-second BARS from Redis into OHLCV bars of a specified interval.
    """

    def __init__(self, interval_str: str, timezone_str: str):
        self.interval_str = interval_str
        self.interval_td = self._parse_interval(interval_str)
        self.current_bar: Optional[schemas.Candle] = None
        self.last_bar_time: Optional[datetime] = None
        try:
            self.tz = ZoneInfo(timezone_str)
            logger.info(f"BarResampler initialized for timezone: {timezone_str}")
        except ZoneInfoNotFoundError:
            logger.warning(f"Invalid timezone '{timezone_str}', falling back to UTC.")
            self.tz = timezone.utc

    def _parse_interval(self, interval_str: str) -> timedelta:
        """Converts an interval string like '1m', '5s', '1h' to a timedelta."""
        unit = interval_str[-1]
        value = int(interval_str[:-1])
        if unit == 's':
            return timedelta(seconds=value)
        if unit == 'm':
            return timedelta(minutes=value)
        if unit == 'h':
            return timedelta(hours=value)
        raise ValueError(f"Invalid interval format: {interval_str}")

    def _get_bar_start_time_naive(self, dt: datetime) -> datetime:
        """
        Calculates the start time for a bar in the local timezone and returns it
        as a naive datetime object (timezone info is stripped).
        """
        if dt.tzinfo is None:
            # This is a fallback, but dt should always be aware.
            dt = dt.replace(tzinfo=timezone.utc)

        # Convert the UTC time to the user's selected timezone
        local_dt = dt.astimezone(self.tz)
        
        interval_seconds = self.interval_td.total_seconds()
        
        seconds_past_midnight = local_dt.hour * 3600 + local_dt.minute * 60 + local_dt.second
        seconds_into_current_interval = seconds_past_midnight % interval_seconds
        
        bar_start_local_dt = local_dt - timedelta(
            seconds=seconds_into_current_interval,
            microseconds=local_dt.microsecond
        )
        
        # Return the naive datetime, representing the local time of the bar start.
        return bar_start_local_dt.replace(tzinfo=None)

    # --- MODIFIED METHOD ---
    def add_bar(self, bar: Dict) -> Optional[schemas.Candle]:
        """
        Adds a new 1-second bar. Assumes the bar dictionary contains a
        standard UTC Unix timestamp from Redis.
        """
        completed_bar = None
        
        open_p = float(bar['open'])
        high_p = float(bar['high'])
        low_p = float(bar['low'])
        close_p = float(bar['close'])
        volume = int(bar['volume'])
        
        # --- FIX: Correctly interpret the UTC timestamp from Redis ---
        # Create a timezone-aware datetime object directly in UTC.
        timestamp_utc = datetime.fromtimestamp(bar['timestamp'], tz=timezone.utc)

        # This logic correctly creates a "fake" UTC timestamp for the charting library
        # based on the user's selected display timezone.
        bar_start_naive = self._get_bar_start_time_naive(timestamp_utc)
        fake_utc_timestamp = bar_start_naive.replace(tzinfo=timezone.utc).timestamp()
        
        if not self.current_bar:
            self.current_bar = schemas.Candle(
                open=open_p, high=high_p, low=low_p, close=close_p, volume=volume,
                unix_timestamp=fake_utc_timestamp
            )
        else:
            if fake_utc_timestamp > self.current_bar.unix_timestamp:
                completed_bar = self.current_bar
                self.current_bar = schemas.Candle(
                    open=open_p, high=high_p, low=low_p, close=close_p, volume=volume,
                    unix_timestamp=fake_utc_timestamp
                )
            else:
                self.current_bar.high = max(self.current_bar.high, high_p)
                self.current_bar.low = min(self.current_bar.low, low_p)
                self.current_bar.close = close_p
                self.current_bar.volume += volume

        self.last_bar_time = timestamp_utc
        return completed_bar


# --- UNIFIED AND CORRECTED FUNCTION ---
async def get_cached_intraday_bars(symbol: str, interval: str, timezone_str: str) -> List[schemas.Candle]:
    """
    Fetches 1-second bars from the Redis cache, resamples them, and returns them.
    """
    cache_key = f"intraday_bars:{symbol}"
    try:
        # Fetch all bars from the list
        cached_bars_str = await redis_client.lrange(cache_key, 0, -1)
        if not cached_bars_str:
            logger.info(f"No cached intraday bars found for {symbol}.")
            return []

        # Deserialize the bars
        one_sec_bars = [json.loads(b) for b in cached_bars_str]
        logger.info(f"Fetched {len(one_sec_bars)} 1-sec bars from cache for {symbol} for resampling.")

        # Resample the bars
        resampler = BarResampler(interval, timezone_str)
        resampled_bars = []
        for bar in one_sec_bars:
            # The 'is_from_dtn_backfill' flag is removed as it's no longer needed.
            completed_bar = resampler.add_bar(bar)
            if completed_bar:
                resampled_bars.append(completed_bar)
        
        # --- FIX RETAINED ---
        # After the loop, append the final, incomplete bar from the resampler.
        # This ensures the last bar of the backfill is not dropped.
        if resampler.current_bar:
            resampled_bars.append(resampler.current_bar)
        
        logger.info(f"Resampled into {len(resampled_bars)} bars for {symbol} with interval {interval}.")
        return resampled_bars

    except Exception as e:
        logger.error(f"Error fetching/resampling cached intraday bars for {symbol}: {e}", exc_info=True)
        return []


async def live_data_stream(websocket: WebSocket, symbol: str, interval: str, timezone_str: str):
    """
    Handles the WebSocket connection for live data streaming.
    """
    await websocket.accept()
    resampler = BarResampler(interval, timezone_str)
    
    try:
        # --- 1. Send Initial Cached Data ---
        cached_bars = await get_cached_intraday_bars(symbol, interval, timezone_str)
        if cached_bars:
            await websocket.send_json([bar.model_dump() for bar in cached_bars])
            logger.info(f"Sent {len(cached_bars)} cached bars to client for {symbol}.")

        # --- 2. Stream Live Data ---
        async for bar_message in redis_pubsub_generator(symbol):
            completed_bar = resampler.add_bar(bar_message)
            
            live_update_payload = {
                "completed_bar": completed_bar.model_dump() if completed_bar else None,
                "current_bar": resampler.current_bar.model_dump() if resampler.current_bar else None
            }
            await websocket.send_json(live_update_payload)

    except (WebSocketDisconnect, ConnectionClosed):
        logger.info(f"Client disconnected from {symbol} stream. Closing connection gracefully.")
    except Exception as e:
        logger.error(f"An unexpected error occurred in the live stream for {symbol}: {e}", exc_info=True)
    finally:
        logger.info(f"Closing stream and cleaning up resources for {symbol}.")
        try:
            await websocket.close()
        except RuntimeError:
            pass


async def redis_pubsub_generator(symbol: str) -> AsyncGenerator[Dict, None]:
    """
    Subscribes to a Redis channel and yields incoming bar messages.
    """
    channel_name = f"live_bars:{symbol}"
    
    async with redis_client.pubsub() as pubsub:
        await pubsub.subscribe(channel_name)
        logger.info(f"Subscribed to Redis channel: {channel_name}")
        while True:
            # Use a timeout to prevent the loop from blocking indefinitely
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=10)
            if message:
                try:
                    yield json.loads(message['data'])
                except (json.JSONDecodeError, TypeError) as e:
                    logger.error(f"Error decoding bar data from Redis: {e}")
            # Add a small sleep to yield control, preventing a tight loop on timeout
            await asyncio.sleep(0.01)