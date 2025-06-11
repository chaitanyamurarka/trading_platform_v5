// frontend/static/js/app/3-chart-options.js

import * as elements from './1-dom-elements.js';

/**
 * Generates the main options object for creating the chart.
 * @param {string} theme - The current theme ('light' or 'dark').
 * @returns {object} The chart options for the Lightweight Charts library.
 */
export function getChartOptions(theme) {
    const isDark = theme === 'dark';
    const bgColor = isDark ? '#1a1e25' : '#ffffff';
    const textColor = isDark ? '#d1d5db' : '#1f2937';
    const gridColor = isDark ? '#374151' : '#e5e7eb';

    // --- MODIFICATION START ---
    // Read the scaling mode from the dropdown to control price scale behavior.
    const scalingMode = elements.scalingSelect.value;
    const isAutoScale = scalingMode === 'automatic';
    // --- MODIFICATION END ---

    return {
        layout: {
            background: { color: bgColor },
            textColor: textColor,
        },
        grid: {
            vertLines: { color: gridColor },
            horzLines: { color: gridColor },
        },
        // --- MODIFICATION START ---
        // Apply the selected scaling mode to the chart's price scales.
        rightPriceScale: {
            borderColor: gridColor,
            autoScale: isAutoScale, // Enable or disable auto-scaling.
            scaleMargins: {
                top: 0.1,
                bottom: 0.1,
            },
        },
        leftPriceScale: {
            visible: true,
            borderColor: gridColor,
            autoScale: isAutoScale, // Sync with the right scale.
            scaleMargins: {
                top: 0.1,
                bottom: 0.1,
            },
        },
        // --- MODIFICATION END ---
        timeScale: {
            borderColor: gridColor,
            timeVisible: true,
            secondsVisible: false,
        },
        crosshair: {
            mode: LightweightCharts.CrosshairMode.Normal,
        },
        watermark: {
            color: 'rgba(150, 150, 150, 0.2)',
            visible: false,
            text: 'EigenKor',
            fontSize: 48,
            horzAlign: 'center',
            vertAlign: 'center',
        },
    };
}

/**
 * Generates the options for the main candlestick/bar series.
 * @returns {object} The series options.
 */
export function getSeriesOptions() {
    return {
        upColor: elements.upColorInput.value,
        downColor: elements.downColorInput.value,
        borderDownColor: elements.downColorInput.value,
        borderUpColor: elements.upColorInput.value,
        wickDownColor: elements.wickDownColorInput.value,
        wickUpColor: elements.wickUpColorInput.value,
    };
}

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