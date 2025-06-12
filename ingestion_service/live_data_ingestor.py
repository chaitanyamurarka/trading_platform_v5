# In ingestion_service/live_data_ingestor.py

import logging
import json
import time
from datetime import datetime, timezone
import numpy as np
import pyiqfeed as iq
import redis
from zoneinfo import ZoneInfo

# Local imports
from dtn_iq_client import get_iqfeed_quote_conn, get_iqfeed_history_conn, launch_iqfeed_service_if_needed
from config import settings

# --- Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(funcName)s - %(message)s')
REDIS_URL = settings.REDIS_URL
redis_client = redis.Redis.from_url(REDIS_URL)


class LiveTickListener(iq.SilentQuoteListener):
    """
    A listener that processes live trades from QuoteConn, aggregates them into
    1-second bars, publishes completed bars to Redis pub/sub, and caches them
    in a Redis list for the current trading session.
    """

    def __init__(self, name="LiveTickListener"):
        super().__init__(name)
        self.redis_client = redis_client
        self.source_timezone = ZoneInfo("America/New_York")
        self.current_bars = {}

    def backfill_intraday_data(self, symbol: str, hist_conn: iq.HistoryConn):
        """
        On startup, fetch today's data from IQFeed to populate the cache.
        This assumes hist_conn is already connected and managed externally.
        """
        logging.info(f"Backfilling intraday data for {symbol}...")
        try:
            # The HistoryConn is now managed by the ConnConnector in main()
            today_data = hist_conn.request_bars_for_days(
                ticker=symbol,
                interval_len=1,
                interval_type='s',
                days=1,
                ascend=True
            )

            if today_data is not None and len(today_data) > 0:
                cache_key = f"intraday_bars:{symbol}"
                self.redis_client.delete(cache_key)
                
                for bar in today_data:
                    # The 'time' field from historical data is a numpy.timedelta64
                    # representing the time since midnight. We combine it with the date.
                    bar_datetime = bar['date'] + bar['time']
                    
                    bar_data = {
                        "timestamp": int(bar_datetime.astype(datetime).replace(tzinfo=timezone.utc).timestamp()),
                        "open": float(bar['open_p']),
                        "high": float(bar['high_p']),
                        "low": float(bar['low_p']),
                        "close": float(bar['close_p']),
                        "volume": int(bar['prd_vlm']),
                    }
                    self.redis_client.rpush(cache_key, json.dumps(bar_data))
                
                logging.info(f"Successfully backfilled {len(today_data)} bars for {symbol}.")
            else:
                logging.info(f"No intraday data found to backfill for {symbol}.")
        except iq.NoDataError:
            logging.warning(f"No intraday data available to backfill for {symbol}.")
        except Exception as e:
            logging.error(f"Error during intraday backfill for {symbol}: {e}", exc_info=True)

    def process_update(self, update_data: np.ndarray) -> None:
        """
        This method is called by the feed for each new trade/quote update.
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
                        self.publish_and_cache_bar(self.current_bars[symbol])

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

    def publish_and_cache_bar(self, bar_data):
        """Publishes a completed bar to Redis pub/sub and caches it in a list."""
        message_to_publish = bar_data.copy()
        symbol = message_to_publish.pop("symbol")
        
        channel = f"live_bars:{symbol}"
        self.redis_client.publish(channel, json.dumps(message_to_publish))

        cache_key = f"intraday_bars:{symbol}"
        self.redis_client.rpush(cache_key, json.dumps(message_to_publish))
        self.redis_client.expire(cache_key, 86400)


def main():
    """Main function to start listening to live data."""
    launch_iqfeed_service_if_needed()

    symbols = ["AAPL", "AMZN", "TSLA", "@NQ#"]
    
    # Get instances of both connection types
    quote_conn = get_iqfeed_quote_conn()
    hist_conn = get_iqfeed_history_conn()

    if not quote_conn or not hist_conn:
        logging.error("Could not get IQFeed connections. Exiting.")
        return

    listener = LiveTickListener()
    quote_conn.add_listener(listener)
    
    # Use ConnConnector to manage the lifecycle of BOTH connections
    with iq.ConnConnector([quote_conn, hist_conn]):
        # Both connections are now connected and their reader threads are running.
        for symbol in symbols:
            # Pass the now-connected hist_conn to the backfill function
            listener.backfill_intraday_data(symbol, hist_conn)
            
            # Subscribe to live updates for the symbol
            quote_conn.watch(symbol)
            logging.info(f"Watching {symbol} for live updates.")
        
        try:
            logging.info("Ingestion service is running. Press Ctrl+C to stop.")
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logging.info("Stopping live data ingestion.")
            for symbol in symbols:
                quote_conn.unwatch(symbol)

if __name__ == "__main__":
    main()