// app/6-api-service.js
import { getHistoricalDataUrl, getHistoricalDataChunkUrl, initiateSession, sendHeartbeat } from '../api.js';
import { state, constants } from './2-state.js';
import * as elements from './1-dom-elements.js';
import { showToast, updateDataSummary } from './4-ui-helpers.js';

// ADD THIS LINE AT THE TOP OF THE FILE
let liveDataSocket = null;

// This function now returns the fetched data
async function fetchInitialHistoricalData(sessionToken, exchange, token, interval, startTime, endTime, timezone) {
    const url = getHistoricalDataUrl(sessionToken, exchange, token, interval, startTime, endTime, timezone);
    const response = await fetch(url);
    if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: 'Network error' }));
        throw new Error(error.detail);
    }
    return response.json();
}

// This function now returns the fetched data
async function fetchHistoricalChunk(requestId, offset, limit) {
    const url = getHistoricalDataChunkUrl(requestId, offset, limit);
    const response = await fetch(url);
    if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: 'Network error' }));
        throw new Error(error.detail);
    }
    return response.json();
}

// =================================================================
// --- NEW FUNCTION TO AUTOMATICALLY SET START AND END TIMES ---
// =================================================================
function setAutomaticDateTime() {
    // Get current time and convert to ET ('America/New_York')
    const now = new Date();
    // Using Intl.DateTimeFormat to reliably get the current time in a specific timezone
    const etFormatter = new Intl.DateTimeFormat('en-US', {
        timeZone: 'America/New_York',
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
    });

    const parts = etFormatter.formatToParts(now).reduce((acc, part) => {
        acc[part.type] = part.value;
        return acc;
    }, {});
    
    // Construct a date object representing the current time in ET
    const etDate = new Date(`${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second}`);

    let targetEndDate = new Date(etDate);

    // If current ET is before 8 PM (20:00), we set the target to the previous day.
    if (etDate.getHours() < 20) {
        targetEndDate.setDate(targetEndDate.getDate() - 1);
    }

    // Set the end time to exactly 8 PM (20:00:00) on the target date
    targetEndDate.setHours(20, 0, 0, 0);

    // Set the start time to be 90 days before the end time for a decent initial view
    let startDate = new Date(targetEndDate);
    startDate.setDate(startDate.getDate() - 90);
    
    // Function to format Date objects into 'YYYY-MM-DDTHH:mm' string for datetime-local input
    const formatForInput = (date) => {
        const year = date.getFullYear();
        const month = (date.getMonth() + 1).toString().padStart(2, '0');
        const day = date.getDate().toString().padStart(2, '0');
        const hours = date.getHours().toString().padStart(2, '0');
        const minutes = date.getMinutes().toString().padStart(2, '0');
        return `${year}-${month}-${day}T${hours}:${minutes}`;
    };

    // Update the DOM elements with the calculated values
    elements.startTimeInput.value = formatForInput(startDate);
    elements.endTimeInput.value = formatForInput(targetEndDate);
    elements.timezoneSelect.value = 'America/New_York'; // Explicitly set timezone
    console.log(`Auto-set time range: ${elements.startTimeInput.value} to ${elements.endTimeInput.value} [America/New_York]`);
}


export async function fetchAndPrependDataChunk() {
    const nextOffset = state.chartCurrentOffset - constants.DATA_CHUNK_SIZE;
    if (nextOffset < 0) { state.allDataLoaded = true; return; }
    state.currentlyFetching = true;
    elements.loadingIndicator.style.display = 'flex';
    try {
        const chunkData = await fetchHistoricalChunk(state.chartRequestId, nextOffset, constants.DATA_CHUNK_SIZE);
        if (chunkData && chunkData.candles.length > 0) {
            const chartFormattedData = chunkData.candles.map(c => ({ time: c.unix_timestamp, open: c.open, high: c.high, low: c.low, close: c.close }));
            const volumeFormattedData = chunkData.candles.map(c => ({ time: c.unix_timestamp, value: c.volume, color: c.close >= c.open ? elements.volUpColorInput.value + '80' : elements.volDownColorInput.value + '80' }));
            state.allChartData = [...chartFormattedData, ...state.allChartData];
            state.allVolumeData = [...volumeFormattedData, ...state.allVolumeData];
            state.mainSeries.setData(state.allChartData);
            state.volumeSeries.setData(state.allVolumeData);
            state.chartCurrentOffset = chunkData.offset;
            if (state.chartCurrentOffset === 0) state.allDataLoaded = true;
        } else {
            state.allDataLoaded = true;
        }
    } catch(error) {
        console.error("Failed to prepend data chunk:", error);
        showToast("Could not load older data.", "error");
    } finally {
        elements.loadingIndicator.style.display = 'none';
        state.currentlyFetching = false;
    }
}

export async function loadInitialChart() {
    if (!state.sessionToken) return;

    // --- ADD THIS LINE TO AUTOMATICALLY SET THE TIME ---
    setAutomaticDateTime();

    state.currentlyFetching = true;
    elements.loadingIndicator.style.display = 'flex';
    state.allDataLoaded = false;

    try {
        const responseData = await fetchInitialHistoricalData(state.sessionToken, elements.exchangeSelect.value, elements.symbolSelect.value, elements.intervalSelect.value, elements.startTimeInput.value, elements.endTimeInput.value, elements.timezoneSelect.value);
        if (!responseData || !responseData.request_id || responseData.candles.length === 0) {
            showToast(responseData.message || 'No historical data found.', 'warning');
            if (state.mainSeries) state.mainSeries.setData([]);
            if (state.volumeSeries) state.volumeSeries.setData([]);
            return;
        }
        state.chartRequestId = responseData.request_id;
        state.chartCurrentOffset = responseData.offset;
        if (state.chartCurrentOffset === 0 && !responseData.is_partial) state.allDataLoaded = true;

        state.allChartData = responseData.candles.map(c => ({ time: c.unix_timestamp, open: c.open, high: c.high, low: c.low, close: c.close }));
        state.allVolumeData = responseData.candles.map(c => ({ time: c.unix_timestamp, value: c.volume, color: c.close >= c.open ? elements.volUpColorInput.value + '80' : elements.volDownColorInput.value + '80' }));
        
        state.mainSeries.setData(state.allChartData);
        state.volumeSeries.setData(state.allVolumeData);

        if (state.allChartData.length > 0) {
            const dataSize = state.allChartData.length;
            state.mainChart.timeScale().setVisibleLogicalRange({
                from: Math.max(0, dataSize - 100),
                to: dataSize - 1,
            });
        } else {
            state.mainChart.timeScale().fitContent();
        }

        // --- ADD THIS LINE ---
        state.mainChart.priceScale().applyOptions({ autoscale: true });
        // ---------------------

        updateDataSummary(state.allChartData.at(-1));
    } catch (error) {
        console.error('Failed to fetch initial chart data:', error);
        showToast(`Error: ${error.message}`, 'error');
    } finally {
        elements.loadingIndicator.style.display = 'none';
        state.currentlyFetching = false;
    }
}

export async function startSession() {
    try {
        const sessionData = await initiateSession();
        state.sessionToken = sessionData.session_token;
        console.log(`Session started with token: ${state.sessionToken}`);
        showToast('Session started.', 'info');
        loadInitialChart();
        if (state.heartbeatIntervalId) clearInterval(state.heartbeatIntervalId);
        state.heartbeatIntervalId = setInterval(() => {
            if (state.sessionToken) sendHeartbeat(state.sessionToken).catch(e => console.error('Heartbeat failed', e));
        }, 60000);
    } catch (error) {
        console.error('Failed to initiate session:', error);
        showToast('Could not start a session. Please reload.', 'error');
    }
}

// =================================================================
// --- NEW: FUNCTIONS TO MANAGE LIVE DATA WEBSOCKET ---
// =================================================================

/**
 * Disconnects any existing live data WebSocket connection.
 */
export function disconnectFromLiveDataFeed() {
    if (liveDataSocket) {
        console.log('Closing existing WebSocket connection.');
        liveDataSocket.close();
        liveDataSocket = null;
    }
}

/**
 * Connects to the live data WebSocket and sets up message handling.
 * @param {string} symbol - The symbol to watch.
 * @param {string} interval - The chart interval.
 */
export function connectToLiveDataFeed(symbol, interval) {
    // Ensure any old connection is closed before starting a new one.
    disconnectFromLiveDataFeed();

    // Construct the WebSocket URL based on the current window location.
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsURL = `${wsProtocol}//${window.location.host}/ws/live/${symbol}/${interval}`;
    
    console.log(`Connecting to WebSocket: ${wsURL}`);
    showToast(`Connecting to live feed for ${symbol}...`, 'info');

    liveDataSocket = new WebSocket(wsURL);

    liveDataSocket.onopen = () => {
        console.log('WebSocket connection established.');
        showToast(`Live feed connected for ${symbol}!`, 'success');
    };

    liveDataSocket.onmessage = (event) => {
        const data = JSON.parse(event.data);
        const { completed_bar, current_bar } = data;

        // The main candlestick series on your chart is in the global state
        if (state.mainSeries && current_bar) {
            // The update method intelligently creates a new bar if the timestamp is new,
            // or updates the last bar if the timestamp is the same.
            state.mainSeries.update(current_bar);
            
            // Update the volume series as well
            if (state.volumeSeries) {
                const volumeData = {
                    time: current_bar.unix_timestamp, // Ensure you use the same timestamp key as the chart
                    value: current_bar.volume,
                    color: current_bar.close >= current_bar.open ? elements.volUpColorInput.value + '80' : elements.volDownColorInput.value + '80'
                };
                state.volumeSeries.update(volumeData);
            }
            // Also update the summary display with the latest data
            updateDataSummary(current_bar);
        }
    };

    liveDataSocket.onclose = () => {
        console.log('WebSocket connection closed.');
        showToast('Live feed disconnected.', 'warning');
    };

    liveDataSocket.onerror = (error) => {
        console.error('WebSocket error:', error);
        showToast('Live feed connection error.', 'error');
    };
}