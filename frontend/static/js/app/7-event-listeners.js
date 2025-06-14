// frontend/static/js/app/7-event-listeners.js
import * as elements from './1-dom-elements.js';
import { state } from './2-state.js';
import { applyTheme, updateThemeToggleIcon,showToast } from './4-ui-helpers.js';
import { takeScreenshot, recreateMainSeries, applySeriesColors, applyVolumeColors } from './5-chart-drawing.js';
import { loadInitialChart, fetchAndPrependDataChunk, connectToLiveDataFeed, disconnectFromLiveDataFeed, setAutomaticDateTime } from './6-api-service.js';
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

// In frontend/static/js/app/7-event-listeners.js

export function setupControlListeners(reloadChartCallback) {
    // Handle changes for controls that define the chart's main context
    [elements.exchangeSelect, elements.symbolSelect, elements.intervalSelect].forEach(control => {
        control.addEventListener('change', () => {
            if (elements.liveToggle.checked) {
                loadInitialChart().then(() => {
                    if (state.sessionToken) {
                        const symbol = elements.symbolSelect.value;
                        const interval = elements.intervalSelect.value;
                        connectToLiveDataFeed(symbol, interval);
                    }
                });
            } else {
                reloadChartCallback();
            }
        });
    });

    // --- FIX: Handle Start/End time changes separately ---
    // These controls should still disable live mode.
    [elements.startTimeInput, elements.endTimeInput].forEach(control => {
        control.addEventListener('change', () => {
            if (elements.liveToggle.checked) {
                elements.liveToggle.checked = false; // This will trigger the liveToggle's own 'change' listener to disconnect.
            }
            reloadChartCallback();
        });
    });

    let previousTimezoneValue = elements.timezoneSelect.value;

    elements.timezoneSelect.addEventListener('focus', () => {
        previousTimezoneValue = elements.timezoneSelect.value;
    });

    // --- FIX: Create a dedicated listener for the timezone selector ---
    elements.timezoneSelect.addEventListener('change', () => {
        if (elements.liveToggle.checked) {
        showToast('Cannot change timezone while Live mode is ON.', 'warning');
        elements.timezoneSelect.value = previousTimezoneValue; // revert to previous
        return;
        }

        setAutomaticDateTime();
        if (elements.liveToggle.checked) {
            // If in live mode, reload the chart and reconnect the feed with the new timezone.
            loadInitialChart().then(() => {
                if (state.sessionToken) {
                    const symbol = elements.symbolSelect.value;
                    const interval = elements.intervalSelect.value;
                    // connectToLiveDataFeed reads the new timezone value from the DOM element.
                    connectToLiveDataFeed(symbol, interval);
                }
            });
        } else {
            // If not in live mode, just reload the historical chart data.
            reloadChartCallback();
        }
    });


    elements.liveToggle.addEventListener('change', (e) => {
        if (e.target.checked) {
            elements.endTimeInput.disabled = true;
            loadInitialChart().then(() => {
                if (state.sessionToken) {
                    const symbol = elements.symbolSelect.value;
                    const interval = elements.intervalSelect.value;
                    connectToLiveDataFeed(symbol, interval);
                }
            });
        } else {
            elements.endTimeInput.disabled = false;
            disconnectFromLiveDataFeed();
        }
    });

    const autoScaleBtn = document.getElementById('scaling-auto-btn');
    const linearScaleBtn = document.getElementById('scaling-linear-btn');

    if (autoScaleBtn) {
        autoScaleBtn.addEventListener('click', () => {
            if (!state.mainChart) return;

            // 1. Apply autoscale to the price axis
            state.mainChart.applyOptions({
                rightPriceScale: { autoScale: true },
                leftPriceScale: { autoScale: true }
            });

            // 2. --- MODIFIED: Enable auto-scrolling to the latest bar ---
            // This will keep a small margin from the right edge, making new bars visible
            state.mainChart.timeScale().applyOptions({ rightOffset: 12 });

            if (state.allChartData.length > 0) {
            const dataSize = state.allChartData.length;
            state.mainChart.timeScale().setVisibleLogicalRange({
                from: Math.max(0, dataSize - 100),
                to: dataSize - 1,
            });
            } else {
                state.mainChart.timeScale().fitContent();
            }

            // 3. Update button styles
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

            // --- NEW: Disable auto-scrolling when switching to linear scale ---
            state.mainChart.timeScale().applyOptions({ rightOffset: 0 });

            linearScaleBtn.classList.add('btn-active');
            autoScaleBtn.classList.remove('btn-active');
        });
    }

    elements.themeToggle.addEventListener('click', (event) => {
        event.preventDefault();
        const newTheme = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
        applyTheme(newTheme);
        updateThemeToggleIcon();
    });

    elements.screenshotBtn.addEventListener('click', takeScreenshot);
    elements.chartTypeSelect.addEventListener('change', (e) => recreateMainSeries(e.target.value));

    elements.toolTrendLineBtn.addEventListener('click', () => state.mainChart && state.mainChart.addLineTool('TrendLine'));
    elements.toolHorizontalLineBtn.addEventListener('click', () => state.mainChart && state.mainChart.addLineTool('HorizontalLine'));
    elements.toolFibRetracementBtn.addEventListener('click', () => state.mainChart && state.mainChart.addLineTool('FibRetracement'));
    elements.toolRectangleBtn.addEventListener('click', () => state.mainChart && state.mainChart.addLineTool('Rectangle'));
    elements.toolBrushBtn.addEventListener('click', () => state.mainChart && state.mainChart.addLineTool('Brush'));
    elements.toolRemoveSelectedBtn.addEventListener('click', () => state.mainChart && state.mainChart.removeSelectedLineTools());
    elements.toolRemoveAllBtn.addEventListener('click', () => state.mainChart && state.mainChart.removeAllLineTools());

    elements.bgColorInput.addEventListener('input', e => state.mainChart.applyOptions({ layout: { background: { color: e.target.value } } }));
    elements.gridColorInput.addEventListener('input', e => state.mainChart.applyOptions({ grid: { vertLines: { color: e.target.value }, horzLines: { color: e.target.value } } }));
    elements.watermarkInput.addEventListener('input', e => state.mainChart.applyOptions({ watermark: { color: 'rgba(150, 150, 150, 0.2)', visible: true, text: e.target.value, fontSize: 48, horzAlign: 'center', vertAlign: 'center' }}));
    [elements.upColorInput, elements.downColorInput, elements.wickUpColorInput, elements.wickDownColorInput].forEach(input => input.addEventListener('input', applySeriesColors));
    elements.disableWicksInput.addEventListener('change', applySeriesColors);
    [elements.volUpColorInput, elements.volDownColorInput].forEach(input => input.addEventListener('input', applyVolumeColors));

    elements.settingsModal.querySelectorAll('.tab').forEach(tab => tab.addEventListener('click', (e) => {
        elements.settingsModal.querySelectorAll('.tab').forEach(t => t.classList.remove('tab-active'));
        e.currentTarget.classList.add('tab-active');
        elements.settingsModal.querySelectorAll('.tab-content').forEach(c => c.classList.add('hidden'));
        document.getElementById(e.currentTarget.dataset.tab).classList.remove('hidden');
    }));
}