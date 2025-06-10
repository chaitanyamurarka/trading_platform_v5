# In app/historical_data_service.py

import logging
from datetime import datetime, timezone as dt_timezone
from typing import List
from fastapi import HTTPException
# Use zoneinfo for timezone conversions (available in Python 3.9+, backports for older versions)
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports import ZoneInfo

from . import schemas
from .cache import get_cached_ohlc_data, set_cached_ohlc_data
from .config import settings
from influxdb_client import InfluxDBClient

# --- InfluxDB Client Setup ---
influx_client = InfluxDBClient(
    url=settings.INFLUX_URL,
    token=settings.INFLUX_TOKEN,
    org=settings.INFLUX_ORG,
    timeout=20_000 # 20 seconds
)
query_api = influx_client.query_api()

INITIAL_FETCH_LIMIT = 5000

def get_initial_historical_data(
    session_token: str,
    exchange: str,
    token: str,
    interval_val: str,
    start_time: datetime,
    end_time: datetime,
    timezone: str,
) -> schemas.HistoricalDataResponse:
    """
    Main entry point for fetching historical data. It now performs timezone conversion.
    """
    # Include the timezone in the request_id to ensure the cache is unique per timezone.
    request_id = f"chart_data:{session_token}:{exchange}:{token}:{interval_val}:{start_time.isoformat()}:{end_time.isoformat()}:{timezone}"
    
    full_data = get_cached_ohlc_data(request_id)
    
    if not full_data:
        logging.info(f"Cache MISS for {request_id}. Querying InfluxDB...")
        try:
            # The Flux query is simplified to just fetch the raw data.
            # Timestamp conversion is now handled in Python.
            flux_query = f"""
                from(bucket: "{settings.INFLUX_BUCKET}")
                  |> range(start: {start_time.isoformat()}Z, stop: {end_time.isoformat()}Z)
                  |> filter(fn: (r) => r._measurement == "ohlc_{interval_val}")
                  |> filter(fn: (r) => r.symbol == "{token}")
                  |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
                  |> sort(columns: ["_time"])
            """
            
            tables = query_api.query(query=flux_query)
            
            full_data = []
            
            try:
                target_tz = ZoneInfo(timezone)
            except Exception:
                logging.warning(f"Invalid timezone '{timezone}' provided. Defaulting to UTC.")
                target_tz = ZoneInfo("UTC")

            for table in tables:
                for record in table.records:
                    utc_dt = record.get_time()

                    # Convert original UTC time to the target timezone to get local time components
                    local_dt = utc_dt.astimezone(target_tz)
                    
                    # Create a "fake" UTC datetime using local components.
                    # This is the trick to make lightweight-charts display local time as if it's UTC.
                    fake_utc_dt = datetime(
                        local_dt.year, local_dt.month, local_dt.day,
                        local_dt.hour, local_dt.minute, local_dt.second,
                        tzinfo=dt_timezone.utc
                    )
                    
                    # Get the UNIX timestamp from the "fake" UTC datetime.
                    unix_timestamp_for_chart = fake_utc_dt.timestamp()

                    full_data.append(schemas.Candle(
                        timestamp=utc_dt,
                        open=record['open'],
                        high=record['high'],
                        low=record['low'],
                        close=record['close'],
                        volume=record['volume'],
                        unix_timestamp=unix_timestamp_for_chart
                    ))

            if not full_data:
                return schemas.HistoricalDataResponse(candles=[], total_available=0, is_partial=False, message="No data available in InfluxDB for this range.", request_id=None, offset=None)

            set_cached_ohlc_data(request_id, full_data, expiration=3600)
            logging.info(f"Cache SET for {request_id} with {len(full_data)} records.")

        except Exception as e:
            logging.error(f"Error querying InfluxDB or processing data: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to retrieve data from database.")

    total_available = len(full_data)
    initial_offset = max(0, total_available - INITIAL_FETCH_LIMIT)
    candles_to_send = full_data[initial_offset:]
    
    return schemas.HistoricalDataResponse(
        request_id=request_id,
        candles=candles_to_send,
        offset=initial_offset,
        total_available=total_available,
        is_partial=(total_available > len(candles_to_send)),
        message=f"Initial data loaded. Displaying last {len(candles_to_send)} of {total_available} candles."
    )

def get_historical_data_chunk(
    request_id: str,
    offset: int,
    limit: int = 5000
) -> schemas.HistoricalDataChunkResponse:
    """
    Retrieves a subsequent chunk of historical data from the cache using the request_id.
    """
    full_data = get_cached_ohlc_data(request_id)
    if full_data is None:
        raise HTTPException(status_code=404, detail="Data for this request not found or has expired.")

    total_available = len(full_data)
    if offset < 0 or offset >= total_available:
        return schemas.HistoricalDataChunkResponse(candles=[], offset=offset, limit=limit, total_available=total_available)
        
    chunk = full_data[offset: offset + limit]
    
    return schemas.HistoricalDataChunkResponse(
        candles=chunk,
        offset=offset,
        limit=limit,
        total_available=total_available
    )