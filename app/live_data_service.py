# In app/live_data_service.py

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator, Dict, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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

    def add_bar(self, bar: Dict) -> Optional[schemas.Candle]:
        """
        Adds a new 1-second bar and generates a "fake UTC timestamp".
        """
        completed_bar = None
        
        open_p = float(bar['open'])
        high_p = float(bar['high'])
        low_p = float(bar['low'])
        close_p = float(bar['close'])
        volume = int(bar['volume'])
        timestamp_utc = datetime.fromtimestamp(bar['timestamp'], tz=timezone.utc)
        
        # --- MODIFICATION START ---
        # 1. Get the naive local start time of the bar (e.g., datetime object for 09:30:00).
        bar_start_naive = self._get_bar_start_time_naive(timestamp_utc)
        
        # 2. Create the "fake" UTC timestamp by interpreting the naive local time as if it were UTC.
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
        # --- MODIFICATION END ---
        return completed_bar


async def redis_pubsub_generator(symbol: str) -> AsyncGenerator[Dict, None]:
    """
    Subscribes to a Redis channel and yields incoming bar messages.
    """
    channel_name = f"live_bars:{symbol}"
    
    async with redis_client.pubsub() as pubsub:
        await pubsub.subscribe(channel_name)
        logger.info(f"Subscribed to Redis channel: {channel_name}")
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=10)
            if message:
                try:
                    yield json.loads(message['data'])
                except (json.JSONDecodeError, TypeError) as e:
                    logger.error(f"Error decoding bar data from Redis: {e}")
            await asyncio.sleep(0.01)

async def websocket_handler(websocket: WebSocket, symbol: str, interval: str, timezone: str):
    """
    Manages the WebSocket lifecycle for a live data subscription.
    """
    await websocket.accept()
    resampler = BarResampler(interval, timezone)
    redis_generator = redis_pubsub_generator(symbol)

    try:
        async for bar in redis_generator:
            completed_bar = resampler.add_bar(bar)
            current_incomplete_bar = resampler.current_bar

            response_data = {
                "completed_bar": completed_bar.model_dump(mode='json') if completed_bar else None,
                "current_bar": current_incomplete_bar.model_dump(mode='json') if current_incomplete_bar else None
            }

            await websocket.send_json(response_data)

    except asyncio.CancelledError:
        logger.info(f"WebSocket for {symbol}/{interval} was cancelled.")
    except Exception as e:
        logger.error(f"Error in WebSocket handler for {symbol}/{interval}: {e}", exc_info=True)
    finally:
        logger.info(f"Closing WebSocket connection for {symbol}/{interval}.")
        if not websocket.client_state == 'DISCONNECTED':
             await websocket.close()