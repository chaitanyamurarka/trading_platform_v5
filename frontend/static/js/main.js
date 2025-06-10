document.addEventListener('DOMContentLoaded', () => {
    // --- HTML Element References ---
    const chartContainer = document.getElementById('chartContainer');
    const exchangeSelect = document.getElementById('exchange');
    const symbolSelect = document.getElementById('symbol');
    const intervalSelect = document.getElementById('interval');
    const startTimeInput = document.getElementById('start_time');
    const endTimeInput = document.getElementById('end_time');
    const themeToggle = document.getElementById('theme-toggle');
    const dataSummaryElement = document.getElementById('dataSummary');
    const loadingIndicator = document.getElementById('loadingIndicator');
    const timezoneSelect = document.getElementById('timezone');
    const scalingSelect = document.getElementById('scaling');
    const chartTypeSelect = document.getElementById('chart-type');
    const screenshotBtn = document.getElementById('screenshot-btn');

    // Drawing Tools Toolbar
    const toolTrendLineBtn = document.getElementById('tool-trend-line');
    const toolHorizontalLineBtn = document.getElementById('tool-horizontal-line');
    const toolFibRetracementBtn = document.getElementById('tool-fib-retracement');
    const toolRectangleBtn = document.getElementById('tool-rectangle');
    const toolBrushBtn = document.getElementById('tool-brush');
    const toolRemoveSelectedBtn = document.getElementById('tool-remove-selected');
    const toolRemoveAllBtn = document.getElementById('tool-remove-all');

    // Settings Modal
    const settingsModal = document.getElementById('settings_modal');
    const bgColorInput = document.getElementById('setting-bg-color');
    const gridColorInput = document.getElementById('setting-grid-color');
    const watermarkInput = document.getElementById('setting-watermark-text');
    const upColorInput = document.getElementById('setting-up-color');
    const downColorInput = document.getElementById('setting-down-color');
    const wickUpColorInput = document.getElementById('setting-wick-up-color');
    const wickDownColorInput = document.getElementById('setting-wick-down-color');
    const volUpColorInput = document.getElementById('setting-vol-up-color');
    const volDownColorInput = document.getElementById('setting-vol-down-color');

    // --- State Variables ---
    let allChartData = [];
    let allVolumeData = [];
    let currentlyFetching = false;
    let allDataLoaded = false;
    let chartRequestId = null;
    let chartCurrentOffset = 0;
    const DATA_CHUNK_SIZE = 5000;
    let mainChart = null;
    let mainSeries = null;
    let volumeSeries = null;
    let sessionToken = null;
    let heartbeatIntervalId = null;

    // --- Core Functions ---

    async function startSession() {
        try {
            const sessionData = await initiateSession();
            sessionToken = sessionData.session_token;
            console.log(`Session started with token: ${sessionToken}`);
            showToast('Session started.', 'info');
            loadInitialChart();
            if (heartbeatIntervalId) clearInterval(heartbeatIntervalId);
            heartbeatIntervalId = setInterval(() => {
                if (sessionToken) sendHeartbeat(sessionToken).catch(e => console.error('Heartbeat failed', e));
            }, 60000);
        } catch (error) {
            console.error('Failed to initiate session:', error);
            showToast('Could not start a session. Please reload.', 'error');
        }
    }

    function initializeCharts() {
        if (mainChart) mainChart.remove();
        mainChart = LightweightCharts.createChart(chartContainer, getChartTheme(localStorage.getItem('chartTheme') || 'light'));
        
        setupEventListeners();
        syncSettingsInputs();

        recreateMainSeries(chartTypeSelect.value);
        volumeSeries = mainChart.addHistogramSeries({ priceFormat: { type: 'volume' }, priceScaleId: '' });
        mainChart.priceScale('').applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });

        mainChart.timeScale().subscribeVisibleLogicalRangeChange(async (newVisibleRange) => {
            if (!newVisibleRange || currentlyFetching || allDataLoaded || !chartRequestId) return;
            if (newVisibleRange.from < 15) {
                await fetchAndPrependDataChunk();
            }
        });
    }

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

    async function fetchAndPrependDataChunk() {
        const nextOffset = chartCurrentOffset - DATA_CHUNK_SIZE;
        if (nextOffset < 0) { allDataLoaded = true; return; }
        currentlyFetching = true;
        loadingIndicator.style.display = 'flex';
        try {
            const chunkData = await fetchHistoricalChunk(chartRequestId, nextOffset, DATA_CHUNK_SIZE);
            if (chunkData && chunkData.candles.length > 0) {
                const chartFormattedData = chunkData.candles.map(c => ({ time: c.unix_timestamp, open: c.open, high: c.high, low: c.low, close: c.close }));
                const volumeFormattedData = chunkData.candles.map(c => ({ time: c.unix_timestamp, value: c.volume, color: c.close >= c.open ? volUpColorInput.value + '80' : volDownColorInput.value + '80' }));
                allChartData = [...chartFormattedData, ...allChartData];
                allVolumeData = [...volumeFormattedData, ...allVolumeData];
                mainSeries.setData(allChartData);
                volumeSeries.setData(allVolumeData);
                chartCurrentOffset = chunkData.offset;
                if (chartCurrentOffset === 0) allDataLoaded = true;
            } else {
                allDataLoaded = true;
            }
        } catch(error) {
            console.error("Failed to prepend data chunk:", error);
            showToast("Could not load older data.", "error");
        } finally {
            loadingIndicator.style.display = 'none';
            currentlyFetching = false;
        }
    }

    async function loadInitialChart() {
        if (!sessionToken) return;
        currentlyFetching = true;
        loadingIndicator.style.display = 'flex';
        allDataLoaded = false;

        try {
            const responseData = await fetchInitialHistoricalData(sessionToken, exchangeSelect.value, symbolSelect.value, intervalSelect.value, startTimeInput.value, endTimeInput.value, timezoneSelect.value);
            if (!responseData || !responseData.request_id || responseData.candles.length === 0) {
                showToast(responseData.message || 'No historical data found.', 'warning');
                if (mainSeries) mainSeries.setData([]);
                if (volumeSeries) volumeSeries.setData([]);
                return;
            }
            chartRequestId = responseData.request_id;
            chartCurrentOffset = responseData.offset;
            if (chartCurrentOffset === 0 && !responseData.is_partial) allDataLoaded = true;

            allChartData = responseData.candles.map(c => ({ time: c.unix_timestamp, open: c.open, high: c.high, low: c.low, close: c.close }));
            allVolumeData = responseData.candles.map(c => ({ time: c.unix_timestamp, value: c.volume, color: c.close >= c.open ? volUpColorInput.value + '80' : volDownColorInput.value + '80' }));
            
            mainSeries.setData(allChartData);
            volumeSeries.setData(allVolumeData);

            if (allChartData.length > 0) {
                const dataSize = allChartData.length;
                mainChart.timeScale().setVisibleLogicalRange({
                    from: Math.max(0, dataSize - 100),
                    to: dataSize - 1,
                });
            } else {
                mainChart.timeScale().fitContent();
            }

            updateDataSummary(allChartData.at(-1));
        } catch (error) {
            console.error('Failed to fetch initial chart data:', error);
            showToast(`Error: ${error.message}`, 'error');
        } finally {
            loadingIndicator.style.display = 'none';
            currentlyFetching = false;
        }
    }
    
    // --- UI and Event Handlers ---

    function setupEventListeners() {
        [exchangeSelect, symbolSelect, intervalSelect, startTimeInput, endTimeInput, timezoneSelect, scalingSelect].forEach(control => control.addEventListener('change', loadInitialChart));
        themeToggle.addEventListener('click', () => applyTheme(document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark'));
        screenshotBtn.addEventListener('click', takeScreenshot);
        chartTypeSelect.addEventListener('change', (e) => recreateMainSeries(e.target.value));
        window.addEventListener('resize', () => mainChart && mainChart.resize(chartContainer.clientWidth, chartContainer.clientHeight));

        toolTrendLineBtn.addEventListener('click', () => mainChart && mainChart.addLineTool('TrendLine'));
        toolHorizontalLineBtn.addEventListener('click', () => mainChart && mainChart.addLineTool('HorizontalLine'));
        toolFibRetracementBtn.addEventListener('click', () => mainChart && mainChart.addLineTool('FibRetracement'));
        toolRectangleBtn.addEventListener('click', () => mainChart && mainChart.addLineTool('Rectangle'));
        toolBrushBtn.addEventListener('click', () => mainChart && mainChart.addLineTool('Brush'));
        toolRemoveSelectedBtn.addEventListener('click', () => mainChart && mainChart.removeSelectedLineTools());
        toolRemoveAllBtn.addEventListener('click', () => mainChart && mainChart.removeAllLineTools());
        
        bgColorInput.addEventListener('input', e => mainChart.applyOptions({ layout: { background: { color: e.target.value } } }));
        gridColorInput.addEventListener('input', e => mainChart.applyOptions({ grid: { vertLines: { color: e.target.value }, horzLines: { color: e.target.value } } }));
        watermarkInput.addEventListener('input', e => mainChart.applyOptions({ watermark: { color: 'rgba(150, 150, 150, 0.2)', visible: true, text: e.target.value, fontSize: 48, horzAlign: 'center', vertAlign: 'center' }}));
        [upColorInput, downColorInput, wickUpColorInput, wickDownColorInput].forEach(input => input.addEventListener('input', applySeriesColors));
        [volUpColorInput, volDownColorInput].forEach(input => input.addEventListener('input', applyVolumeColors));
        
        settingsModal.querySelectorAll('.tab').forEach(tab => tab.addEventListener('click', (e) => {
            settingsModal.querySelectorAll('.tab').forEach(t => t.classList.remove('tab-active'));
            e.currentTarget.classList.add('tab-active');
            settingsModal.querySelectorAll('.tab-content').forEach(c => c.classList.add('hidden'));
            document.getElementById(e.currentTarget.dataset.tab).classList.remove('hidden');
        }));
    }

    function recreateMainSeries(type) {
        if (mainSeries) mainChart.removeSeries(mainSeries);
        const seriesOptions = getSeriesOptions();
        switch (type) {
            case 'bar': mainSeries = mainChart.addBarSeries(seriesOptions); break;
            case 'line': mainSeries = mainChart.addLineSeries({ color: seriesOptions.upColor }); break;
            case 'area': mainSeries = mainChart.addAreaSeries({ lineColor: seriesOptions.upColor, topColor: `${seriesOptions.upColor}66`, bottomColor: `${seriesOptions.upColor}00` }); break;
            default: mainSeries = mainChart.addCandlestickSeries(seriesOptions); break;
        }
        if (allChartData.length > 0) mainSeries.setData(allChartData);
    }
    
    function applySeriesColors() {
        if (!mainSeries) return;
        mainSeries.applyOptions(getSeriesOptions());
    }

    function applyVolumeColors() {
        if (!volumeSeries || !allChartData.length || !allVolumeData.length) return;
        const priceActionMap = new Map();
        allChartData.forEach(priceData => {
            priceActionMap.set(priceData.time, priceData.close >= priceData.open);
        });
        const newVolumeData = allVolumeData.map(volumeData => ({
            ...volumeData,
            color: priceActionMap.get(volumeData.time) ? volUpColorInput.value + '80' : volDownColorInput.value + '80',
        }));
        allVolumeData = newVolumeData;
        volumeSeries.setData(allVolumeData);
    }

    function takeScreenshot() {
        if (!mainChart) return;
        mainChart.takeScreenshot().then(canvas => {
            const link = document.createElement('a');
            link.href = canvas.toDataURL();
            link.download = `chart-screenshot-${new Date().toISOString()}.png`;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
        });
    }
    
    // --- Helpers and Initializers ---

    function getChartTheme(theme) {
        const isDarkMode = theme === 'dark';
        return {
            layout: { background: { type: 'solid', color: isDarkMode ? '#1d232a' : '#ffffff' }, textColor: isDarkMode ? '#a6adba' : '#1f2937' },
            grid: { vertLines: { color: isDarkMode ? '#2a323c' : '#e5e7eb' }, horzLines: { color: isDarkMode ? '#2a323c' : '#e5e7eb' } },
        };
    }
    
    function getSeriesOptions() {
        return {
            upColor: upColorInput.value || '#10b981',
            downColor: downColorInput.value || '#ef4444',
            wickUpColor: wickUpColorInput.value || '#10b981',
            wickDownColor: wickDownColorInput.value || '#ef4444',
            borderVisible: false,
        };
    }

    function applyTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        localStorage.setItem('chartTheme', theme);
        if (mainChart) mainChart.applyOptions(getChartTheme(theme));
        syncSettingsInputs();
    }

    function syncSettingsInputs() {
        const currentTheme = getChartTheme(localStorage.getItem('chartTheme') || 'light');
        bgColorInput.value = currentTheme.layout.background.color;
        gridColorInput.value = currentTheme.grid.vertLines.color;
        upColorInput.value = '#10b981';
        downColorInput.value = '#ef4444';
        wickUpColorInput.value = '#10b981';
        wickDownColorInput.value = '#ef4444';
        volUpColorInput.value = '#10b981';
        volDownColorInput.value = '#ef4444';
    }

    function updateDataSummary(latestData) {
        if (!dataSummaryElement || !latestData) return;
        const change = latestData.close - latestData.open;
        const changePercent = (change / latestData.open) * 100;
        dataSummaryElement.innerHTML = `
            <strong>${symbolSelect.value} (${exchangeSelect.value})</strong> | C: ${latestData.close.toFixed(2)} | H: ${latestData.high.toFixed(2)} | L: ${latestData.low.toFixed(2)} | O: ${latestData.open.toFixed(2)}
            <span class="${change >= 0 ? 'text-success' : 'text-error'}">(${change.toFixed(2)} / ${changePercent.toFixed(2)}%)</span>`;
    }
    
    function showToast(message, type = 'info') {
        const toastContainer = document.getElementById('toast-container');
        if (!toastContainer) return;
        const toast = document.createElement('div');
        toast.className = `alert alert-${type} shadow-lg`;
        toast.innerHTML = `<div><span>${message}</span></div>`;
        toastContainer.appendChild(toast);
        setTimeout(() => toast.remove(), 4000);
    }
    
    // --- Page Load ---
    const now = new Date();
    endTimeInput.value = now.toISOString().slice(0, 16);
    now.setDate(now.getDate() - 30);
    startTimeInput.value = now.toISOString().slice(0, 16);
    
    initializeCharts();
    startSession();
});
