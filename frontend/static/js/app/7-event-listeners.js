// frontend/static/js/app/7-event-listeners.js
import * as elements from './1-dom-elements.js';
import { state } from './2-state.js';
import { applyTheme, updateThemeToggleIcon } from './4-ui-helpers.js';
import { takeScreenshot, recreateMainSeries, applySeriesColors, applyVolumeColors } from './5-chart-drawing.js';
import { loadInitialChart, fetchAndPrependDataChunk, connectToLiveDataFeed, disconnectFromLiveDataFeed } from './6-api-service.js';
import { reinitializeAndLoadChart } from '../main.js';

export function setupChartObjectListeners() {
    if (!state.mainChart) return;

    state.mainChart.timeScale().subscribeVisibleLogicalRangeChange(async (newVisibleRange) => {
        if (!newVisibleRange || state.currentlyFetching || state.allDataLoaded || !state.chartRequestId) return;
        if (newVisibleRange.from < 15) {
            await fetchAndPrependDataChunk();
        }
    });

    window.addEventListener('resize', () => {
        if (state.mainChart) {
            state.mainChart.resize(elements.chartContainer.clientWidth, elements.chartContainer.clientHeight);
        }
    });
}

export function setupControlListeners(reloadChartCallback) {
    // --- Main controls that trigger a full chart reload ---
    [elements.exchangeSelect, elements.symbolSelect, elements.intervalSelect, elements.startTimeInput, elements.endTimeInput, elements.timezoneSelect].forEach(control => {
        control.addEventListener('change', reloadChartCallback);
    });

    // // --- Go Button Listener ---
    // elements.goButton.addEventListener('click', () => {
    //     // When "Go" is clicked, always disconnect from any live feed.
    //     if (elements.liveToggle.checked) {
    //         elements.liveToggle.checked = false;
    //     }
    //     disconnectFromLiveDataFeed();
    //     elements.endTimeInput.disabled = false; // Ensure end time is re-enabled
    //     loadInitialChart();
    // });

    // --- Live Toggle Listener ---
    elements.liveToggle.addEventListener('change', (e) => {
        if (e.target.checked) {
            // LIVE MODE ACTIVATED
            elements.endTimeInput.disabled = true;
            loadInitialChart().then(() => {
                if (state.sessionToken) {
                    const symbol = elements.symbolSelect.value;
                    const interval = elements.intervalSelect.value;
                    connectToLiveDataFeed(symbol, interval);
                }
            });
        } else {
            // LIVE MODE DEACTIVATED
            elements.endTimeInput.disabled = false;
            disconnectFromLiveDataFeed();
        }
    });
    // --- New scaling buttons ---
    const autoScaleBtn = document.getElementById('scaling-auto-btn');
    const linearScaleBtn = document.getElementById('scaling-linear-btn');

    if (autoScaleBtn) {
        autoScaleBtn.addEventListener('click', () => {
            if (!state.mainChart) return;
            state.mainChart.applyOptions({
                rightPriceScale: { autoScale: true },
                leftPriceScale: { autoScale: true }
            });
            autoScaleBtn.classList.add('btn-active');
            linearScaleBtn.classList.remove('btn-active');
        });
    }

    if (linearScaleBtn) {
        linearScaleBtn.addEventListener('click', () => {
            if (!state.mainChart) return;
            state.mainChart.applyOptions({
                rightPriceScale: { autoScale: false },
                leftPriceScale: { autoScale: false }
            });
            linearScaleBtn.classList.add('btn-active');
            autoScaleBtn.classList.remove('btn-active');
        });
    }

    // --- Other UI controls ---
    elements.themeToggle.addEventListener('click', (event) => {
        event.preventDefault();
        const newTheme = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
        applyTheme(newTheme);
        updateThemeToggleIcon();
    });

    elements.screenshotBtn.addEventListener('click', takeScreenshot);
    elements.chartTypeSelect.addEventListener('change', (e) => recreateMainSeries(e.target.value));

    // --- Drawing tools ---
    elements.toolTrendLineBtn.addEventListener('click', () => state.mainChart && state.mainChart.addLineTool('TrendLine'));
    elements.toolHorizontalLineBtn.addEventListener('click', () => state.mainChart && state.mainChart.addLineTool('HorizontalLine'));
    elements.toolFibRetracementBtn.addEventListener('click', () => state.mainChart && state.mainChart.addLineTool('FibRetracement'));
    elements.toolRectangleBtn.addEventListener('click', () => state.mainChart && state.mainChart.addLineTool('Rectangle'));
    elements.toolBrushBtn.addEventListener('click', () => state.mainChart && state.mainChart.addLineTool('Brush'));
    elements.toolRemoveSelectedBtn.addEventListener('click', () => state.mainChart && state.mainChart.removeSelectedLineTools());
    elements.toolRemoveAllBtn.addEventListener('click', () => state.mainChart && state.mainChart.removeAllLineTools());

    // --- Settings Modal ---
    elements.bgColorInput.addEventListener('input', e => state.mainChart.applyOptions({ layout: { background: { color: e.target.value } } }));
    elements.gridColorInput.addEventListener('input', e => state.mainChart.applyOptions({ grid: { vertLines: { color: e.target.value }, horzLines: { color: e.target.value } } }));
    elements.watermarkInput.addEventListener('input', e => state.mainChart.applyOptions({ watermark: { color: 'rgba(150, 150, 150, 0.2)', visible: true, text: e.target.value, fontSize: 48, horzAlign: 'center', vertAlign: 'center' }}));
    [elements.upColorInput, elements.downColorInput, elements.wickUpColorInput, elements.wickDownColorInput].forEach(input => input.addEventListener('input', applySeriesColors));
    [elements.volUpColorInput, elements.volDownColorInput].forEach(input => input.addEventListener('input', applyVolumeColors));

    elements.settingsModal.querySelectorAll('.tab').forEach(tab => tab.addEventListener('click', (e) => {
        elements.settingsModal.querySelectorAll('.tab').forEach(t => t.classList.remove('tab-active'));
        e.currentTarget.classList.add('tab-active');
        elements.settingsModal.querySelectorAll('.tab-content').forEach(c => c.classList.add('hidden'));
        document.getElementById(e.currentTarget.dataset.tab).classList.remove('hidden');
    }));
}