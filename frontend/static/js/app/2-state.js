// app/2-state.js
export const state = {
    allChartData: [],
    allVolumeData: [],
    currentlyFetching: false,
    allDataLoaded: false,
    chartRequestId: null,
    chartCurrentOffset: 0,
    mainChart: null,
    mainSeries: null,
    volumeSeries: null,
    sessionToken: null,
    heartbeatIntervalId: null
};

export const constants = {
    DATA_CHUNK_SIZE: 5000
};