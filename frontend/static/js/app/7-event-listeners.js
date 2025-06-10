// frontend/static/js/app/7-event-listeners.js
import * as elements from './1-dom-elements.js';
import { state } from './2-state.js';
// --- MODIFIED: Import the theme functions ---
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
    [elements.exchangeSelect, elements.symbolSelect, elements.intervalSelect, elements.startTimeInput, elements.endTimeInput, elements.timezoneSelect, elements.scalingSelect].forEach(control => {
        control.addEventListener('change', reloadChartCallback);
    });

    // --- MODIFIED: Rewritten theme toggle listener ---
    elements.themeToggle.addEventListener('click', (event) => {
        // Prevent the default browser action for the label, which can cause double events
        event.preventDefault();
        
        // Determine the new theme
        const newTheme = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
        
        // Apply the new theme to the page and the chart
        applyTheme(newTheme);
        
        // Manually update the toggle icon to reflect the new state
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