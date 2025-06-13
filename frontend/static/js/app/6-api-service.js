// app/6-api-service.js
import { getHistoricalDataUrl, getHistoricalDataChunkUrl, initiateSession, sendHeartbeat } from '../api.js';
import { state, constants } from './2-state.js';
import * as elements from './1-dom-elements.js';
import { showToast, updateDataSummary } from './4-ui-helpers.js';

let liveDataSocket = null;

async function fetchInitialHistoricalData(sessionToken, exchange, token, interval, startTime, endTime, timezone) {
    const url = getHistoricalDataUrl(sessionToken, exchange, token, interval, startTime, endTime, timezone);
    const response = await fetch(url);
    if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: 'Network error' }));
        throw new Error(error.detail);
    }
    return response.json();
}

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
// --- MODIFIED: EXPORT THIS FUNCTION ---
// =================================================================
export function setAutomaticDateTime() {
    const now = new Date();
    const etFormatter = new Intl.DateTimeFormat('en-US', {
        timeZone: 'America/New_York',
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
    });

    const parts = etFormatter.formatToParts(now).reduce((acc, part) => {
        acc[part.type] = part.value;
        return acc;
    }, {});
    
    const etDate = new Date(`${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second}`);

    let targetEndDate = new Date(etDate);

    if (etDate.getHours() < 20) {
        targetEndDate.setDate(targetEndDate.getDate() - 1);
    }

    targetEndDate.setHours(20, 0, 0, 0);

    let startDate = new Date(targetEndDate);
    startDate.setDate(startDate.getDate() - 30);
    
    const formatForInput = (date) => {
        const year = date.getFullYear();
        const month = (date.getMonth() + 1).toString().padStart(2, '0');
        const day = date.getDate().toString().padStart(2, '0');
        const hours = date.getHours().toString().padStart(2, '0');
        const minutes = date.getMinutes().toString().padStart(2, '0');
        return `${year}-${month}-${day}T${hours}:${minutes}`;
    };

    elements.startTimeInput.value = formatForInput(startDate);
    elements.endTimeInput.value = formatForInput(targetEndDate);
    elements.timezoneSelect.value = 'America/New_York';
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

    // --- REMOVED THIS LINE TO PREVENT RESETTING THE TIME ON EVERY LOAD ---
    // setAutomaticDateTime();

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

        state.mainChart.priceScale().applyOptions({ autoscale: true });

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

// --- Live data functions remain unchanged ---
export function disconnectFromLiveDataFeed() {
    if (liveDataSocket) {
        console.log('Closing existing WebSocket connection.');
        liveDataSocket.onclose = null;
        liveDataSocket.close();
        liveDataSocket = null;
    }
}

export function connectToLiveDataFeed(symbol, interval) {
    disconnectFromLiveDataFeed();
    const timezone = elements.timezoneSelect.value;
    if (!timezone) {
        showToast('Please select a timezone before connecting to live feed.', 'error');
        return;
    }
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsURL = `${wsProtocol}//${window.location.host}/ws/live/${encodeURIComponent(symbol)}/${interval}/${encodeURIComponent(timezone)}`;    console.log(`Connecting to WebSocket: ${wsURL}`);
    showToast(`Connecting to live feed for ${symbol}...`, 'info');
    const socket = new WebSocket(wsURL);
    socket.onopen = () => {
        console.log('WebSocket connection established.');
        showToast(`Live feed connected for ${symbol}!`, 'success');
    };
    socket.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (Array.isArray(data)) {
            if (data.length === 0) return;
            console.log(`Received backfill data with ${data.length} bars.`);
            const formattedBackfillBars = data.map(c => ({ time: c.unix_timestamp, open: c.open, high: c.high, low: c.low, close: c.close }));
            const formattedVolumeBars = data.map(c => ({ time: c.unix_timestamp, value: c.volume, color: c.close >= c.open ? elements.volUpColorInput.value + '80' : elements.volDownColorInput.value + '80' }));
            const lastHistoricalTime = state.allChartData.length > 0 ? state.allChartData[state.allChartData.length - 1].time : 0;
            const newOhlcBars = formattedBackfillBars.filter(d => d.time > lastHistoricalTime);
            const newVolumeBars = formattedVolumeBars.filter(d => d.time > lastHistoricalTime);
            if (newOhlcBars.length > 0) {
                state.allChartData.push(...newOhlcBars);
                state.allVolumeData.push(...newVolumeBars);
                state.mainSeries.setData(state.allChartData);
                state.volumeSeries.setData(state.allVolumeData);
                console.log(`Applied ${newOhlcBars.length} new bars from backfill.`);
            } else {
                console.log('Backfill data did not contain any new bars.');
            }
        }
        else if (data.current_bar && state.mainSeries) {
            const { current_bar } = data;
            const chartFormattedBar = { time: current_bar.unix_timestamp, open: current_bar.open, high: current_bar.high, low: current_bar.low, close: current_bar.close };
            state.mainSeries.update(chartFormattedBar);
            if (state.volumeSeries) {
                const volumeData = { time: current_bar.unix_timestamp, value: current_bar.volume, color: current_bar.close >= current_bar.open ? elements.volUpColorInput.value + '80' : elements.volDownColorInput.value + '80' };
                state.volumeSeries.update(volumeData);
            }
            updateDataSummary(current_bar);
        }
    };
    liveDataSocket = socket;
}