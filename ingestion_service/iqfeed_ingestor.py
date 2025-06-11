import os
import logging
import time
from datetime import datetime as dt, timezone
# For timezone-aware datetime objects. ZoneInfo is in the standard library for Python 3.9+.
# If using an older version, you might need 'pip install backports.zoneinfo' or use 'pytz'.
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

import numpy as np
from dotenv import load_dotenv
from influxdb_client import InfluxDBClient, Point, WriteOptions, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

# Local imports from your project structure
import pyiqfeed as iq
from dtn_iq_client import get_iqfeed_history_conn
from config import settings

# --- Configuration ---
load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# InfluxDB Configuration
INFLUX_URL = settings.INFLUX_URL 
INFLUX_TOKEN = settings.INFLUX_TOKEN
INFLUX_ORG = settings.INFLUX_ORG
INFLUX_BUCKET = settings.INFLUX_BUCKET

# --- InfluxDB Connection ---
influx_client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG, timeout=90_000) # Increased timeout for heavy queries
write_api = influx_client.write_api(write_options=WriteOptions(batch_size=5000, flush_interval=10_000, jitter_interval=2_000))
query_api = influx_client.query_api()

def get_latest_timestamp(symbol: str, measurement: str) -> dt | None:
    """
    Queries InfluxDB for the latest timestamp for a given symbol and measurement.
    Returns a timezone-aware datetime object (UTC) or None if no data is found.
    """
    flux_query = f'''
        from(bucket: "{INFLUX_BUCKET}")
          |> range(start: 0)
          |> filter(fn: (r) => r._measurement == "{measurement}" and r.symbol == "{symbol}")
          |> last()
          |> keep(columns: ["_time"])
    '''
    try:
        tables = query_api.query(query=flux_query)
        if not tables or not tables[0].records:
            logging.info(f"No existing data found for '{symbol}' in measurement '{measurement}'.")
            return None
        
        latest_time = tables[0].records[0].get_time()
        
        # Ensure the datetime is timezone-aware (it should be UTC from InfluxDB)
        if latest_time.tzinfo is None:
            latest_time = latest_time.replace(tzinfo=timezone.utc)
            
        logging.info(f"Latest timestamp for '{symbol}' in '{measurement}' is {latest_time}.")
        return latest_time
    except Exception as e:
        logging.error(f"Error querying latest timestamp for {symbol} in {measurement}: {e}", exc_info=True)
        return None

def format_data_for_influx(dtn_data: np.ndarray, symbol: str, exchange: str, measurement: str) -> list[Point]:
    """
    Converts NumPy array from pyiqfeed to a list of InfluxDB Points,
    correctly handling the source timezone.
    """
    points = []
    has_time_field = 'time' in dtn_data.dtype.names
    has_prd_vlm = 'prd_vlm' in dtn_data.dtype.names
    has_tot_vlm = 'tot_vlm' in dtn_data.dtype.names

    # Assume NASDAQ data from IQFeed is in US/Eastern time.
    source_timezone = ZoneInfo("America/New_York")

    for rec in dtn_data:
        # Create a naive datetime object first from the IQFeed data
        if has_time_field:
            naive_timestamp_dt = iq.date_us_to_datetime(rec['date'], rec['time'])
        else:
            daily_date = iq.datetime64_to_date(rec['date'])
            naive_timestamp_dt = dt.combine(daily_date, dt.min.time())

        # Make the naive datetime "aware" of its actual timezone (ET)
        aware_timestamp_dt = naive_timestamp_dt.replace(tzinfo=source_timezone)

        # .timestamp() on an aware datetime correctly converts it to a UTC-based Unix timestamp.
        unix_timestamp_microseconds = int(aware_timestamp_dt.timestamp() * 1_000_000)

        volume = 0
        if has_prd_vlm:
            volume = int(rec['prd_vlm'])
        elif has_tot_vlm:
            volume = int(rec['tot_vlm'])

        point = (
            Point(measurement)
            .tag("symbol", symbol)
            .tag("exchange", exchange)
            .field("open", float(rec['open_p']))
            .field("high", float(rec['high_p']))
            .field("low", float(rec['low_p']))
            .field("close", float(rec['close_p']))
            .field("volume", volume)
            .time(unix_timestamp_microseconds, write_precision=WritePrecision.US)
        )
        points.append(point)
        
    return points

def fetch_and_store_history(symbol: str, exchange: str, hist_conn: iq.HistoryConn):
    """
    Fetches history for all supported timeframes. If data already exists,
    it fetches incrementally from the last known timestamp. Otherwise, it performs
    a full backfill.
    """
    logging.info(f"Starting historical data ingestion for {symbol}...")

    timeframes_to_fetch = {
        # Seconds
        "1s":   {"interval": 1,    "type": "s", "days": 7},
        "5s":   {"interval": 5,    "type": "s", "days": 7},
        "10s":  {"interval": 10,   "type": "s", "days": 7},
        "15s":  {"interval": 15,   "type": "s", "days": 7},
        "30s":  {"interval": 30,   "type": "s", "days": 7},
        "45s":  {"interval": 45,   "type": "s", "days": 7},
        # Minutes
        "1m":   {"interval": 60,   "type": "s", "days": 180},
        "5m":   {"interval": 300,  "type": "s", "days": 180},
        "10m":  {"interval": 600,  "type": "s", "days": 180},
        "15m":  {"interval": 900,  "type": "s", "days": 180},
        "30m":  {"interval": 1800, "type": "s", "days": 180},
        "45m":  {"interval": 2700, "type": "s", "days": 180},
        # Hours
        "1h":   {"interval": 3600, "type": "s", "days": 180},
        # Days
        "1d":   {"interval": 1,    "type": "d", "days": 10000}
    }

    for tf_name, params in timeframes_to_fetch.items():
        try:
            measurement = f"ohlc_{tf_name}"
            latest_timestamp = get_latest_timestamp(symbol, measurement)

            days_to_fetch = params['days']
            if latest_timestamp:
                # Calculate days from last data point to now. Add 1 for a buffer.
                incremental_days = (dt.now(timezone.utc) - latest_timestamp).days + 1
                # Fetch the smaller of the two: the incremental days or the full backfill period.
                days_to_fetch = min(incremental_days, params['days'])
                logging.info(f"Incremental fetch for {tf_name} data for {symbol}. Fetching last {days_to_fetch} days.")
            else:
                logging.info(f"Full backfill for {tf_name} data for {symbol}. Fetching last {days_to_fetch} days.")

            if days_to_fetch <= 0:
                logging.info(f"Data for {symbol} on {tf_name} is already up to date. Skipping fetch.")
                continue

            dtn_data = None
            if params['type'] == "d":
                 dtn_data = hist_conn.request_daily_data(ticker=symbol, num_days=days_to_fetch, ascend=True)
            else:
                 dtn_data = hist_conn.request_bars_for_days(
                    ticker=symbol, interval_len=params['interval'], interval_type=params['type'],
                    days=days_to_fetch, ascend=True
                 )

            if dtn_data is not None and len(dtn_data) > 0:
                logging.info(f"Fetched {len(dtn_data)} records for {tf_name} timeframe.")
                influx_points = format_data_for_influx(dtn_data, symbol, exchange, measurement)
                write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=influx_points)
                logging.info(f"Wrote {len(influx_points)} points to InfluxDB measurement '{measurement}'.")
                write_api.flush()
                
            else:
                logging.warning(f"No new {tf_name} data returned for {symbol}.")

        except iq.NoDataError:
            logging.warning(f"IQFeed reported NoDataError for {symbol} on {tf_name} timeframe.")
        except Exception as e:
            logging.error(f"An error occurred while fetching {tf_name} data for {symbol}: {e}", exc_info=True)
        time.sleep(2) # Pause between queries to avoid overwhelming the source

def daily_update(symbols_to_update: list, exchange: str):
    """
    Performs the daily update for a list of symbols.
    """
    logging.info("--- Starting Daily Update Process ---")
    hist_conn = get_iqfeed_history_conn()
    if hist_conn is None:
        logging.error("Could not get IQFeed connection. Aborting daily update.")
        return

    with iq.ConnConnector([hist_conn]):
        for symbol in symbols_to_update:
            logging.info(f"Daily update for {symbol}...")
            fetch_and_store_history(symbol, exchange, hist_conn)

    logging.info("--- Daily Update Process Finished ---")

if __name__ == '__main__':
    symbols_to_backfill = ["AAPL", "AMZN", "TSLA", "@NQ#"]
    exchange = "NASDAQ"

    iq_connection = get_iqfeed_history_conn()
    if iq_connection:
        with iq.ConnConnector([iq_connection]):
            for new_symbol in symbols_to_backfill:
                fetch_and_store_history(new_symbol, exchange, iq_connection)
    else:
        logging.error("Failed to connect to IQFeed. Cannot perform backfill.")