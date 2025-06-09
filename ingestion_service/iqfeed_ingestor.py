import os
import logging
import time
from datetime import datetime as dt
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

def resample_to_new_timeframe(symbol: str, source_interval: str, target_interval: str, time_range_start: str):
    """
    Executes a Flux query to resample data from a source measurement to a target measurement.
    """
    logging.info(f"Resampling '{symbol}' from 'ohlc_{source_interval}' to 'ohlc_{target_interval}'...")
    
    # This Flux query reads unpivoted data, aggregates each field correctly,
    # renames the measurement, and writes it back to the database.
    flux_query = f'''
        base_data = from(bucket: "{INFLUX_BUCKET}")
            |> range(start: {time_range_start})
            |> filter(fn: (r) => r._measurement == "ohlc_{source_interval}" and r.symbol == "{symbol}")

        opens = base_data |> filter(fn: (r) => r._field == "open") |> aggregateWindow(every: {target_interval}, fn: first, createEmpty: false)
        highs = base_data |> filter(fn: (r) => r._field == "high") |> aggregateWindow(every: {target_interval}, fn: max, createEmpty: false)
        lows = base_data |> filter(fn: (r) => r._field == "low") |> aggregateWindow(every: {target_interval}, fn: min, createEmpty: false)
        closes = base_data |> filter(fn: (r) => r._field == "close") |> aggregateWindow(every: {target_interval}, fn: last, createEmpty: false)
        volumes = base_data |> filter(fn: (r) => r._field == "volume") |> aggregateWindow(every: {target_interval}, fn: sum, createEmpty: false)

        union(tables: [opens, highs, lows, closes, volumes])
            |> set(key: "_measurement", value: "ohlc_{target_interval}")
            |> to(bucket: "{INFLUX_BUCKET}", org: "{INFLUX_ORG}")
    '''
    
    try:
        query_api.query(flux_query)
        logging.info(f"Successfully triggered resampling for {symbol} to ohlc_{target_interval}.")
    except Exception as e:
        logging.error(f"Error resampling data for {symbol} to ohlc_{target_interval}: {e}", exc_info=True)

def resample_seconds_data(symbol: str):
    """
    Triggers resampling from 1s data to other second-based timeframes.
    """
    target_intervals = ["5s", "10s", "15s", "30s", "45s"]
    logging.info(f"--- Starting second-level resampling for {symbol} ---")
    for interval in target_intervals:
        # Resample from the last 7 days of 1s data
        resample_to_new_timeframe(symbol, source_interval="1s", target_interval=interval, time_range_start="-7d")
        time.sleep(2) # Pause between heavy queries

def resample_minutes_data(symbol: str):
    """
    Triggers resampling from 1m data to other minute-based and hourly timeframes.
    """
    target_intervals = ["5m", "10m", "15m", "30m", "45m", "1h"]
    logging.info(f"--- Starting minute-level resampling for {symbol} ---")
    for interval in target_intervals:
        # Resample from the last 180 days of 1m data
        resample_to_new_timeframe(symbol, source_interval="1m", target_interval=interval, time_range_start="-180d")
        time.sleep(2) # Pause between heavy queries

def fetch_and_store_history(symbol: str, exchange: str, hist_conn: iq.HistoryConn):
    """
    Fetches history for 1s, 1m, and 1d timeframes, stores it,
    and triggers the appropriate tiered resampling.
    """
    logging.info(f"Starting historical data ingestion for {symbol}...")

    timeframes_to_fetch = {
        "1d": {"interval": 1, "type": "d", "days": 10000},
        "1m": {"interval": 60, "type": "s", "days": 180},
        "1s": {"interval": 1, "type": "s", "days": 7},
    }

    for tf_name, params in timeframes_to_fetch.items():
        try:
            logging.info(f"Fetching {tf_name} data for {symbol} for the last {params['days']} days.")
            if tf_name == "1d":
                 dtn_data = hist_conn.request_daily_data(ticker=symbol, num_days=params['days'], ascend=True)
            else:
                 dtn_data = hist_conn.request_bars_for_days(
                    ticker=symbol, interval_len=params['interval'], interval_type=params['type'],
                    days=params['days'], ascend=True
                 )

            if dtn_data is not None and len(dtn_data) > 0:
                logging.info(f"Fetched {len(dtn_data)} records for {tf_name} timeframe.")
                measurement = f"ohlc_{tf_name}"
                influx_points = format_data_for_influx(dtn_data, symbol, exchange, measurement)
                write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=influx_points)
                logging.info(f"Wrote {len(influx_points)} points to InfluxDB measurement '{measurement}'.")
                write_api.flush()

                # --- CORRECTED TIERED RESAMPLING LOGIC ---
                if tf_name == "1s" and influx_points:
                    resample_seconds_data(symbol)
                
                if tf_name == "1m" and influx_points:
                    resample_minutes_data(symbol)

            else:
                logging.warning(f"No {tf_name} data returned for {symbol}.")

        except iq.NoDataError:
            logging.warning(f"IQFeed reported NoDataError for {symbol} on {tf_name} timeframe.")
        except Exception as e:
            logging.error(f"An error occurred while fetching {tf_name} data for {symbol}: {e}", exc_info=True)
        time.sleep(2)

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