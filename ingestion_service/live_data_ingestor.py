# In ingestion_service/live_data_ingestor.py

import logging
import json
import time
from datetime import datetime, timezone

import numpy as np
import pyiqfeed as iq
import redis
from zoneinfo import ZoneInfo

from dtn_iq_client import get_iqfeed_quote_conn
from config import settings

# --- Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(funcName)s - %(message)s')
REDIS_URL = settings.REDIS_URL
redis_client = redis.Redis.from_url(REDIS_URL)

class LiveTickListener(iq.SilentQuoteListener):
    """
    A listener that processes live trades from QuoteConn, aggregates them into
    1-second bars, and publishes completed bars to Redis.
    """
    def __init__(self, name="LiveTickListener"):
        super().__init__(name)
        self.redis_client = redis_client
        self.source_timezone = ZoneInfo("America/New_York")
        self.current_bars = {}

    def process_update(self, update_data: np.ndarray) -> None:
        """
        This method is called by the feed for each new trade/quote update message.
        """
        try:
            for trade in update_data:
                trade_price = float(trade['Most Recent Trade'])
                trade_volume = int(trade['Most Recent Trade Size'])
                
                if trade_price <= 0 or trade_volume <= 0:
                    continue 

                symbol = trade['Symbol'].decode('utf-8')
                
                aware_dt = datetime.now(self.source_timezone)
                utc_dt = aware_dt.astimezone(timezone.utc)
                
                bar_timestamp_dt = utc_dt.replace(microsecond=0)
                bar_timestamp = int(bar_timestamp_dt.timestamp())

                if symbol not in self.current_bars or self.current_bars[symbol]['timestamp'] != bar_timestamp:
                    if symbol in self.current_bars:
                        self.publish_bar(self.current_bars[symbol])

                    self.current_bars[symbol] = {
                        "timestamp": bar_timestamp,
                        "open": trade_price,
                        "high": trade_price,
                        "low": trade_price,
                        "close": trade_price,
                        "volume": trade_volume,
                        "symbol": symbol
                    }
                else:
                    bar = self.current_bars[symbol]
                    bar['high'] = max(bar['high'], trade_price)
                    bar['low'] = min(bar['low'], trade_price)
                    bar['close'] = trade_price
                    bar['volume'] += trade_volume
        
        except Exception as e:
            logging.error(f"Error processing trade data: {e}", exc_info=True)

    def publish_bar(self, bar_data):
        """Publishes a completed bar to the appropriate Redis channel."""
        # --- MODIFICATION START ---
        # Create a copy of the dictionary before modifying it. This prevents
        # the original data from being changed if the publish command fails.
        message_to_publish = bar_data.copy()
        symbol = message_to_publish.pop("symbol")
        # --- MODIFICATION END ---
        
        channel = f"live_bars:{symbol}"
        self.redis_client.publish(channel, json.dumps(message_to_publish))
        logging.info(f"Published 1-sec bar to {channel}: {message_to_publish}")

def start_live_feed(symbols_to_watch: list[str]):
    """
    Sets up the IQFeed QuoteConn connection and attaches the tick listener.
    """
    logging.info("Attempting to get IQFeed Quote connection.")
    feed_conn = get_iqfeed_quote_conn() 
    if not feed_conn:
        logging.error("Could not get IQFeed Quote connection. Aborting.")
        return

    logging.info("Successfully created IQFeed Quote connection object.")
    
    listener = LiveTickListener()
    
    with iq.ConnConnector([feed_conn]):
        feed_conn.add_listener(listener)
        logging.info("LiveTickListener attached to the connection.")

        fields_to_watch = ["Symbol", "Most Recent Trade", "Most Recent Trade Size"]
        feed_conn.select_update_fieldnames(fields_to_watch)
        logging.info(f"Requesting update fields: {fields_to_watch}")

        for symbol in symbols_to_watch:
            feed_conn.trades_watch(symbol)
        
        logging.info(f"Watching trade data for: {symbols_to_watch} to build 1-second bars.")
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logging.info("Shutdown requested. Unwatching symbols.")
            for symbol in symbols_to_watch:
                feed_conn.unwatch(symbol)

if __name__ == '__main__':
    SYMBOLS = ["AAPL", "AMZN", "TSLA", "@ES#"]
    logging.info("--- Starting Live Data Ingestion Service (QuoteConn -> 1-Second Bars) ---")
    start_live_feed(SYMBOLS)
    logging.info("--- Live Data Ingestion Service Shut Down ---")