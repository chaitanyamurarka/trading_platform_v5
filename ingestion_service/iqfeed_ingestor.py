import os
import logging
import time
from datetime import datetime as dt

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
influx_client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG, timeout=30_000)
write_api = influx_client.write_api(write_options=WriteOptions(batch_size=5000, flush_interval=10_000, jitter_interval=2_000))

def format_data_for_influx(dtn_data: np.ndarray, symbol: str, exchange: str, measurement: str) -> list[Point]:
    """
    Converts NumPy array from pyiqfeed to a list of InfluxDB Points
    using a UNIX timestamp in MICROSECOND precision.
    """
    points = []
    
    has_time_field = 'time' in dtn_data.dtype.names
    has_prd_vlm = 'prd_vlm' in dtn_data.dtype.names
    has_tot_vlm = 'tot_vlm' in dtn_data.dtype.names

    for rec in dtn_data:
        # 1. Create the full datetime object first
        if has_time_field:
            timestamp_dt = iq.date_us_to_datetime(rec['date'], rec['time'])
        else:
            daily_date = iq.datetime64_to_date(rec['date'])
            timestamp_dt = dt.combine(daily_date, dt.min.time())

        # 2. Convert the datetime object to a UNIX timestamp in MICROSECONDS
        # A float timestamp is in seconds, so multiply to get microseconds.
        unix_timestamp_microseconds = int(timestamp_dt.timestamp() * 1_000_000)

        # 3. Determine the correct volume field
        volume = 0
        if has_prd_vlm:
            volume = int(rec['prd_vlm'])
        elif has_tot_vlm:
            volume = int(rec['tot_vlm'])

        # 4. Create the InfluxDB Point, providing the UNIX timestamp and its precision
        point = (
            Point(measurement)
            .tag("symbol", symbol)
            .tag("exchange", exchange)
            .field("open", float(rec['open_p']))
            .field("high", float(rec['high_p']))
            .field("low", float(rec['low_p']))
            .field("close", float(rec['close_p']))
            .field("volume", volume)
            # Use the integer timestamp and specify its precision is MICROSECONDS
            .time(unix_timestamp_microseconds, write_precision=WritePrecision.US)
        )
        points.append(point)
        
    return points

def fetch_and_store_history(symbol: str, exchange: str, hist_conn: iq.HistoryConn):
    """
    Fetches maximum available history for 1s, 1m, and 1d timeframes and stores it.
    """
    logging.info(f"Starting historical data ingestion for {symbol}...")

    # Define the timeframes to fetch
    timeframes_to_fetch = {
        "1d": {"interval": 1, "type": "d", "days": 10000}, # Fetch max daily data
        "1m": {"interval": 60, "type": "s", "days": 180},  # Fetch max minute data (e.g., 180 days)
        "1s": {"interval": 1, "type": "s", "days": 7},     # Fetch max second data (e.g., 7 days)
    }

    for tf_name, params in timeframes_to_fetch.items():
        try:
            logging.info(f"Fetching {tf_name} data for {symbol} for the last {params['days']} days.")
            if tf_name == "1d":
                 # Use daily-specific request function
                 dtn_data = hist_conn.request_daily_data(ticker=symbol, num_days=params['days'], ascend=True)
            else:
                 # Use interval-based request function
                 dtn_data = hist_conn.request_bars_for_days(
                    ticker=symbol,
                    interval_len=params['interval'],
                    interval_type=params['type'],
                    days=params['days'],
                    ascend=True
                 )

            if dtn_data is not None and len(dtn_data) > 0:
                logging.info(f"Fetched {len(dtn_data)} records for {tf_name} timeframe.")
                measurement = f"ohlc_{tf_name}" # e.g., ohlc_1d, ohlc_1m
                influx_points = format_data_for_influx(dtn_data, symbol, exchange, measurement)
                write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=influx_points)
                logging.info(f"Wrote {len(influx_points)} points to InfluxDB measurement '{measurement}'.")
                # Wait for the batch to be written
                write_api.flush()
            else:
                logging.warning(f"No {tf_name} data returned for {symbol}.")

        except iq.NoDataError:
            logging.warning(f"IQFeed reported NoDataError for {symbol} on {tf_name} timeframe.")
        except Exception as e:
            logging.error(f"An error occurred while fetching {tf_name} data for {symbol}: {e}", exc_info=True)
        time.sleep(2) # Be courteous to the API

def daily_update(symbols_to_update: list, exchange: str):
    """
    Performs the daily update for a list of symbols.
    Fetches the last day of data and appends it.
    """
    logging.info("--- Starting Daily Update Process ---")
    hist_conn = get_iqfeed_history_conn()
    if hist_conn is None:
        logging.error("Could not get IQFeed connection. Aborting daily update.")
        return

    with iq.ConnConnector([hist_conn]):
        for symbol in symbols_to_update:
            logging.info(f"Daily update for {symbol}...")
            # For daily updates, we can just re-fetch the last few days
            # of data. InfluxDB will handle duplicates based on timestamp.
            fetch_and_store_history(symbol, exchange, hist_conn)

    logging.info("--- Daily Update Process Finished ---")

if __name__ == '__main__':
    # This part of the script would be triggered to add new symbols or run the daily update.
    # For example, you could pass command-line arguments.

    # Example: To add a new symbol and backfill its history
    symbols_to_backfill = ["AAPL", "TSLA", "MSFT"]
    exchange = "NASDAQ"

    iq_connection = get_iqfeed_history_conn()
    if iq_connection:
        with iq.ConnConnector([iq_connection]):
            for new_symbol in symbols_to_backfill:
                fetch_and_store_history(new_symbol, exchange, iq_connection)
    else:
        logging.error("Failed to connect to IQFeed. Cannot perform backfill.")

    # Example: To run the daily update for existing symbols
    # You would get this list from your database or a config file
    # existing_symbols = ["AAPL", "TSLA", "MSFT"]
    # daily_update(existing_symbols, "NASDAQ")