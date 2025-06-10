// frontend/static/js/app/3-chart-options.js
import * as elements from './1-dom-elements.js';

export function getChartTheme(theme) {
    const isDarkMode = theme === 'dark';
    return {
        layout: { background: { type: 'solid', color: isDarkMode ? '#1d232a' : '#ffffff' }, textColor: isDarkMode ? '#a6adba' : '#1f2937' },
        grid: { vertLines: { color: isDarkMode ? '#2a323c' : '#e5e7eb' }, horzLines: { color: isDarkMode ? '#2a323c' : '#e5e7eb' } },
        // --- ADD THIS
        timeScale: {
            timeVisible: true,
            secondsVisible: true, // You can set this to true if you need seconds precision
        }
        // ---
    };
}

export function getSeriesOptions() {
    return {
        upColor: elements.upColorInput.value || '#10b981',
        downColor: elements.downColorInput.value || '#ef4444',
        wickUpColor: elements.wickUpColorInput.value || '#10b981',
        wickDownColor: elements.wickDownColorInput.value || '#ef4444',
        borderVisible: false,
    };
}