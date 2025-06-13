// frontend/static/js/main.js
import { state } from './app/2-state.js';
import * as elements from './app/1-dom-elements.js';
import { getChartTheme } from './app/3-chart-options.js';
import { syncSettingsInputs, updateThemeToggleIcon } from './app/4-ui-helpers.js';
import { recreateMainSeries } from './app/5-chart-drawing.js';
// --- MODIFIED: Import the new setAutomaticDateTime function ---
import { startSession, loadInitialChart, setAutomaticDateTime } from './app/6-api-service.js';
import { setupChartObjectListeners, setupControlListeners } from './app/7-event-listeners.js';

function initializeNewChartObject() {
    if (state.mainChart) {
        state.mainChart.remove();
    }
    state.mainChart = null;
    state.mainSeries = null;
    state.volumeSeries = null;
    state.mainChart = LightweightCharts.createChart(elements.chartContainer, getChartTheme(localStorage.getItem('chartTheme') || 'light'));
    setupChartObjectListeners();
    syncSettingsInputs();
    recreateMainSeries(elements.chartTypeSelect.value);
    state.volumeSeries = state.mainChart.addHistogramSeries({ priceFormat: { type: 'volume' }, priceScaleId: '' });
    state.mainChart.priceScale('').applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });
}

export function reinitializeAndLoadChart() {
    console.log("Re-initializing chart from fresh...");
    initializeNewChartObject();
    loadInitialChart();
}

document.addEventListener('DOMContentLoaded', () => {
    const savedTheme = localStorage.getItem('chartTheme') || 'light';
    document.documentElement.setAttribute('data-theme', savedTheme);
    
    updateThemeToggleIcon();

    // --- MODIFIED: Call setAutomaticDateTime() on page load ---
    // This sets the default time range ONCE.
    setAutomaticDateTime();

    // --- REMOVED old manual date setting ---
    // const now = new Date();
    // elements.endTimeInput.value = now.toISOString().slice(0, 16);
    // now.setDate(now.getDate() - 30);
    // elements.startTimeInput.value = now.toISOString().slice(0, 16);
    
    setupControlListeners(reinitializeAndLoadChart);
    initializeNewChartObject();
    startSession(); // This will call loadInitialChart, which now uses the pre-filled values
});