// frontend/static/js/app/7-event-listeners.js
import * as elements from './1-dom-elements.js';
import { state } from './2-state.js';
import { applyTheme, updateThemeToggleIcon } from './4-ui-helpers.js';
import { takeScreenshot, recreateMainSeries, applySeriesColors, applyVolumeColors } from './5-chart-drawing.js';
import { fetchAndPrependDataChunk } from './6-api-service.js';
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
    // --- MODIFICATION START ---
    // The 'scalingSelect' element has been removed from this list to prevent full reloads.
    [elements.exchangeSelect, elements.symbolSelect, elements.intervalSelect, elements.startTimeInput, elements.endTimeInput, elements.timezoneSelect].forEach(control => {
        control.addEventListener('change', reloadChartCallback);
    });

    // A new, dedicated listener for the scaling select dropdown.
    elements.scalingSelect.addEventListener('change', (e) => {
        if (!state.mainChart) return;

        const isAutomatic = e.target.value === 'automatic';

        // Apply the new autoScale value dynamically without reloading the chart.
        state.mainChart.applyOptions({
            rightPriceScale: {
                autoScale: isAutomatic,
            },
            leftPriceScale: {
                autoScale: isAutomatic,
            }
        });
    });
    // --- MODIFICATION END ---


    elements.themeToggle.addEventListener('click', (event) => {
        event.preventDefault();
        const newTheme = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
        applyTheme(newTheme);
        updateThemeToggleIcon();
    });

    // Other UI controls
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
    [elements.volUpColorInput, elements.volDownColorInput].forEach(input => input.addEventListener('input', applyVolumeColors));
    
    elements.settingsModal.querySelectorAll('.tab').forEach(tab => tab.addEventListener('click', (e) => {
        elements.settingsModal.querySelectorAll('.tab').forEach(t => t.classList.remove('tab-active'));
        e.currentTarget.classList.add('tab-active');
        elements.settingsModal.querySelectorAll('.tab-content').forEach(c => c.classList.add('hidden'));
        document.getElementById(e.currentTarget.dataset.tab).classList.remove('hidden');
    }));
}