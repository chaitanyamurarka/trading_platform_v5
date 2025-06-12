# In ingestion_service/live_data_ingestor.py

import logging
import json
import time
from datetime import datetime, timezone

import numpy as np
import pyiqfeed as iq
import redis
from zoneinfo import ZoneInfo
from pyiqfeed.field_readers import date_us_to_datetime

from config import settings
from dtn_iq_client import get_iqfeed_bar_conn

# --- Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
REDIS_URL = settings.REDIS_URL
redis_client = redis.Redis.from_url(REDIS_URL)


class LiveBarListener(iq.SilentBarListener):
    """
    A listener that processes live 1-second bars and publishes them to Redis.
    """
    def __init__(self, name="LiveBarListener"):
        super().__init__(name)
        self.redis_client = redis_client
        self.source_timezone = ZoneInfo("America/New_York")

    def process_bar(self, bar_data: np.ndarray) -> None:
        """
        This method is called by the feed for each new bar message.
        """
        try:
            for bar in bar_data:
                symbol = bar['symbol'].decode('utf-8')
                naive_dt = date_us_to_datetime(bar['date'], bar['time'])
                aware_dt = self.source_timezone.localize(naive_dt)
                utc_dt = aware_dt.astimezone(timezone.utc)

                bar_message = {
                    "timestamp": utc_dt.timestamp(),
                    "open": float(bar['open_p']),
                    "high": float(bar['high_p']),
                    "low": float(bar['low_p']),
                    "close": float(bar['close_p']),
                    "volume": int(bar['prd_vlm']),
                }
                
                channel = f"live_bars:{symbol}"
                self.redis_client.publish(channel, json.dumps(bar_message))

        except Exception as e:
            logging.error(f"Error processing bar data: {e}", exc_info=True)


def start_live_feed(symbols_to_watch: list[str]):
    """
    Sets up the IQFeed BarConn connection and attaches the listener.
    """
    feed_conn = get_iqfeed_bar_conn()
    if not feed_conn:
        logging.error("Could not get IQFeed Bar connection. Aborting.")
        return

    listener = LiveBarListener()
    with iq.ConnConnector([feed_conn]):
        feed_conn.add_listener(listener)

        # CORRECTED: Loop through each symbol and call the correct watch() method.
        # The 'watch_bars' method does not exist on the BarConn object.
        for symbol in symbols_to_watch:
            feed_conn.watch(symbol=symbol, interval_len=1, interval_type='s', update=1)
        
        logging.info(f"Watching 1-second bars for: {symbols_to_watch}")

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logging.info("Shutdown requested. Unwatching symbols.")
            # CORRECTED: Loop through each symbol to unwatch it individually.
            for symbol in symbols_to_watch:
                feed_conn.unwatch(symbol)


if __name__ == '__main__':
    SYMBOLS = ["AAPL", "AMZN", "TSLA", "@ES#"]
    logging.info("--- Starting Live Data Ingestion Service (1-Second Bars) ---")
    start_live_feed(SYMBOLS)
    logging.info("--- Live Data Ingestion Service Shut Down ---")