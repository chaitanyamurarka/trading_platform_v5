# In app/live_data_service.py

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator, Dict, Optional

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
    Aggregates 1-second ticks into OHLCV bars of a specified interval.
    """

    def __init__(self, interval_str: str):
        self.interval_str = interval_str
        self.interval_td = self._parse_interval(interval_str)
        self.current_bar: Optional[schemas.Candle] = None
        self.last_tick_time: Optional[datetime] = None

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

    def _get_bar_start_time(self, dt: datetime) -> datetime:
        """Calculates the start time of the bar for a given timestamp."""
        return dt - (dt - datetime.min.replace(tzinfo=timezone.utc)) % self.interval_td

    def add_tick(self, tick: Dict) -> Optional[schemas.Candle]:
        """
        Adds a new tick to the current bar or creates a new one.

        Returns the completed bar if a new bar has just been finished.
        """
        completed_bar = None
        price = float(tick['price'])
        volume = int(tick['volume'])
        timestamp = datetime.fromtimestamp(tick['timestamp'], tz=timezone.utc)

        if not self.current_bar:
            # First tick received, start a new bar
            bar_start_time = self._get_bar_start_time(timestamp)
            self.current_bar = schemas.Candle(
                timestamp=bar_start_time,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=volume,
                # This unix timestamp is what the frontend chart will use
                unix_timestamp=int(bar_start_time.timestamp())
            )
        else:
            bar_start_time = self._get_bar_start_time(timestamp)
            if bar_start_time > self.current_bar.timestamp:
                # The tick belongs to a new bar, so the previous one is complete.
                completed_bar = self.current_bar
                # Start the new bar
                self.current_bar = schemas.Candle(
                    timestamp=bar_start_time,
                    open=price,
                    high=price,
                    low=price,
                    close=price,
                    volume=volume,
                    unix_timestamp=int(bar_start_time.timestamp())
                )
            else:
                # Update the current bar
                self.current_bar.high = max(self.current_bar.high, price)
                self.current_bar.low = min(self.current_bar.low, price)
                self.current_bar.close = price
                self.current_bar.volume += volume

        self.last_tick_time = timestamp
        return completed_bar


async def redis_pubsub_generator(symbol: str) -> AsyncGenerator[Dict, None]:
    """
    Subscribes to a Redis channel and yields incoming tick messages.
    """
    channel_name = f"live_ticks:{symbol}"
    async with redis_client.pubsub() as pubsub:
        await pubsub.subscribe(channel_name)
        logger.info(f"Subscribed to Redis channel: {channel_name}")
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=10)
            if message:
                try:
                    yield json.loads(message['data'])
                except (json.JSONDecodeError, TypeError) as e:
                    logger.error(f"Error decoding tick data from Redis: {e}")
            await asyncio.sleep(0.01) # Prevent tight loop

async def websocket_handler(websocket: WebSocket, symbol: str, interval: str):
    """
    Manages the WebSocket lifecycle for a live data subscription.
    """
    await websocket.accept()
    resampler = BarResampler(interval)
    redis_generator = redis_pubsub_generator(symbol)

    try:
        async for tick in redis_generator:
            # Process the tick and check if a bar is completed
            completed_bar = resampler.add_tick(tick)
            
            # This is the bar currently being formed
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