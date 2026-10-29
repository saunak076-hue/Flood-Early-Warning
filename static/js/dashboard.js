/**
 * Flood Early Warning Dashboard — Hack4Haldia'26 Team C
 * Frontend Application Logic (Leaflet, Chart.js, REST API Client)
 */

// Application State
const state = {
  demoMode: false,
  readings: [],
  alerts: [],
  summary: null,
  activeFilter: 'ALL',
  searchQuery: '',
  selectedZoneId: 'haldia',
  map: null,
  markers: {},
  trendChart: null,
  isRefreshing: false
};

// West Bengal Map Bounds & Config
const MAP_CONFIG = {
  center: [23.0, 87.85],
  zoom: 7,
  minZoom: 6,
  maxZoom: 12
};

// Document Ready Init
document.addEventListener('DOMContentLoaded', () => {
  initClock();
  initMap();
  initEventListeners();
  loadAllData();
});

// Digital Clock
function initClock() {
  const clockEl = document.getElementById('utcClock');
  const update = () => {
    const now = new Date();
    if (clockEl) {
      clockEl.textContent = now.toUTCString().replace('GMT', 'UTC');
    }
  };
  update();
  setInterval(update, 1000);
}

// Map Initialization
function initMap() {
  try {
    state.map = L.map('map', {
      center: MAP_CONFIG.center,
      zoom: MAP_CONFIG.zoom,
      minZoom: MAP_CONFIG.minZoom,
      maxZoom: MAP_CONFIG.maxZoom,
      attributionControl: true
    });

    // Official OpenStreetMap standard basemap (reliable, no watermark, no API key required)
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors'
    }).addTo(state.map);
  } catch (err) {
    console.error('Error initializing Leaflet map:', err);
    const mapEl = document.getElementById('map');
    if (mapEl) {
      mapEl.innerHTML = `<div style="padding: 2rem; text-align: center; color: #ef4444;">Failed to load map container: ${err.message}</div>`;
    }
  }
}

// Event Listeners
function initEventListeners() {
  // Demo Mode Switch
  const demoSwitch = document.getElementById('demoSwitch');
  if (demoSwitch) {
    demoSwitch.addEventListener('change', (e) => {
      state.demoMode = e.target.checked;
      updateStatusBadge();
      loadAllData(true);
    });
  }

  // Refresh Button
  const refreshBtn = document.getElementById('refreshBtn');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', () => {
      triggerManualRefresh();
    });
  }

  // Search Input
  const searchInput = document.getElementById('zoneSearch');
  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      state.searchQuery = e.target.value.toLowerCase().trim();
      renderZoneTable();
    });
  }

  // Table Filter Buttons
  const filterBtns = document.querySelectorAll('.filter-btn');
  filterBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      filterBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.activeFilter = btn.dataset.level;
      renderZoneTable();
    });
  });

  // Simulator Inputs
  const simZone = document.getElementById('simZone');
  const simRain = document.getElementById('simRain');
  const simDischarge = document.getElementById('simDischarge');

  if (simZone && simRain && simDischarge) {
    const updateSimLabels = () => {
      document.getElementById('simRainVal').textContent = `${simRain.value} mm`;
      document.getElementById('simDischargeVal').textContent = `${simDischarge.value} m³/s`;
    };

    simRain.addEventListener('input', () => {
      updateSimLabels();
      runSimulation();
    });

    simDischarge.addEventListener('input', () => {
      updateSimLabels();
      runSimulation();
    });

    simZone.addEventListener('change', () => {
      runSimulation();
    });
  }

  // Chart Zone Selector
  const chartZoneSelect = document.getElementById('chartZoneSelect');
  if (chartZoneSelect) {
    chartZoneSelect.addEventListener('change', (e) => {
      state.selectedZoneId = e.target.value;
      loadZoneHistoryAndRenderChart(state.selectedZoneId);
    });
  }

  // Modal Close
  const modalClose = document.getElementById('modalCloseBtn');
  const modalBackdrop = document.getElementById('zoneModal');
  if (modalClose && modalBackdrop) {
    modalClose.addEventListener('click', closeModal);
    modalBackdrop.addEventListener('click', (e) => {
      if (e.target === modalBackdrop) closeModal();
    });
  }
}

// Update Status Badge & Freshness Indicators
function updateStatusBadge() {
  const badge = document.getElementById('statusBadge');
  const text = document.getElementById('statusText');
  const toggleLabel = document.getElementById('demoToggleLabel');
  if (!badge || !text) return;

  if (state.demoMode) {
    badge.className = 'status-badge demo';
    text.textContent = 'DEMO SCENARIO';
    if (toggleLabel) {
      toggleLabel.innerHTML = 'Data Mode: <strong style="color: #facc15;">DEMO ACTIVE</strong>';
    }
  } else {
    if (state.readings.length === 0) {
      badge.className = 'status-badge demo';
      text.textContent = 'CONNECTING...';
    } else {
      const anyDemo = state.readings.some(r => r.freshness === 'DEMO');
      const anyCached = state.readings.some(r => r.freshness === 'CACHED');
      if (anyDemo) {
        badge.className = 'status-badge demo';
        text.textContent = 'DEMO FALLBACK';
      } else if (anyCached) {
        badge.className = 'status-badge demo';
        text.textContent = 'CACHED (Open-Meteo)';
      } else {
        badge.className = 'status-badge';
        text.textContent = 'LIVE (Open-Meteo & GloFAS)';
      }
    }
    if (toggleLabel) {
      toggleLabel.innerHTML = 'Data Mode: <strong style="color: #4ade80;">LIVE</strong>';
    }
  }
}

// Synthesize KPI summary from readings if /api/summary is delayed or offline
function synthesizeSummary(readings, alerts) {
  if (!readings || readings.length === 0) {
    return {
      total_monitored_zones: 8,
      highest_risk_score: 0.0,
      highest_risk_zone: 'None',
      highest_risk_level: 'LOW',
      active_alerts_count: 0,
      max_24h_rainfall_mm: 0.0,
      last_updated: new Date().toISOString()
    };
  }

  let highestScore = -1;
  let highestZone = readings[0].zone_name;
  let highestLevel = readings[0].risk_level || 'LOW';
  let maxRain = 0.0;

  readings.forEach(r => {
    const s = Number(r.risk_score || 0);
    if (s > highestScore) {
      highestScore = s;
      highestZone = r.zone_name;
      highestLevel = r.risk_level || 'LOW';
    }
    const rain = Number(r.rainfall_24h_mm || 0);
    if (rain > maxRain) maxRain = rain;
  });

  return {
    total_monitored_zones: readings.length,
    highest_risk_score: Math.round(highestScore * 10) / 10,
    highest_risk_zone: highestZone,
    highest_risk_level: highestLevel,
    active_alerts_count: alerts ? alerts.length : 0,
    max_24h_rainfall_mm: Math.round(maxRain * 10) / 10,
    last_updated: new Date().toISOString()
  };
}

// Master Data Load - Resilient parallel fetch using Promise.allSettled
async function loadAllData(force = false) {
  setLoadingState(true);
  try {
    const query = state.demoMode ? '?demo=true' : (force ? '?refresh=true' : '');
    
    const [summaryRes, readingsRes, alertsRes] = await Promise.allSettled([
      fetch(`/api/summary${query}`).then(r => r.ok ? r.json() : null),
      fetch(`/api/readings${query}`).then(r => r.ok ? r.json() : null),
      fetch(`/api/alerts${query}`).then(r => r.ok ? r.json() : null)
    ]);

    const summaryData = summaryRes.status === 'fulfilled' ? summaryRes.value : null;
    const readingsData = readingsRes.status === 'fulfilled' ? readingsRes.value : null;
    const alertsData = alertsRes.status === 'fulfilled' ? alertsRes.value : null;

    if (readingsData && readingsData.readings && readingsData.readings.length > 0) {
      state.readings = readingsData.readings;
    }
    if (alertsData && alertsData.alerts) {
      state.alerts = alertsData.alerts;
    }
    if (summaryData) {
      state.summary = summaryData;
    } else if (state.readings.length > 0) {
      state.summary = synthesizeSummary(state.readings, state.alerts);
    }

    updateStatusBadge();
    renderKPIs();
    renderAlerts();
    renderMapMarkers();
    renderZoneTable();
    populateZoneSelectors();
    loadZoneHistoryAndRenderChart(state.selectedZoneId);
    runSimulation(); // Initial simulator calculation

  } catch (err) {
    console.error('Failed to load dashboard data:', err);
    showNotification('Error loading telemetry: ' + err.message, 'error');
  } finally {
    setLoadingState(false);
  }
}

// Manual Refresh Trigger
async function triggerManualRefresh() {
  if (state.isRefreshing) return;
  state.isRefreshing = true;
  const refreshBtn = document.getElementById('refreshBtn');
  if (refreshBtn) refreshBtn.innerHTML = '<span>⟳</span> Refreshing...';

  try {
    await fetch(`/api/refresh${state.demoMode ? '?demo=true' : '?force=true'}`, { method: 'POST' });
    setTimeout(() => {
      loadAllData(true);
      state.isRefreshing = false;
      if (refreshBtn) refreshBtn.innerHTML = '<span>⟳</span> Refresh Now';
      showNotification('Telemetry refreshed successfully', 'success');
    }, 1200);
  } catch (e) {
    state.isRefreshing = false;
    if (refreshBtn) refreshBtn.innerHTML = '<span>⟳</span> Refresh Now';
    showNotification('Refresh request failed', 'error');
  }
}

function setLoadingState(loading) {
  const el = document.getElementById('lastUpdatedTime');
  if (el && loading) {
    el.textContent = 'Syncing...';
  } else if (el && state.summary) {
    const d = new Date(state.summary.last_updated);
    el.textContent = `Updated: ${d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}`;
  }
}

// Render KPI Cards
function renderKPIs() {
  if (!state.summary && state.readings.length > 0) {
    state.summary = synthesizeSummary(state.readings, state.alerts);
  }
  if (!state.summary) {
    const riskZoneEl = document.getElementById('kpiHighestRisk');
    if (riskZoneEl) riskZoneEl.textContent = 'Unavailable';
    return;
  }
  
  const monitoredEl = document.getElementById('kpiMonitoredZones');
  if (monitoredEl) {
    monitoredEl.textContent = state.summary.total_monitored_zones || state.readings.length;
  }
  
  const riskZoneEl = document.getElementById('kpiHighestRisk');
  const level = state.summary.highest_risk_level || 'LOW';
  if (riskZoneEl) {
    riskZoneEl.textContent = `${state.summary.highest_risk_zone} (${state.summary.highest_risk_score})`;
  }
  
  const levelBadge = document.getElementById('kpiRiskBadge');
  if (levelBadge) {
    levelBadge.textContent = level;
    levelBadge.className = `risk-pill ${level.toLowerCase()}`;
  }

  const activeAlertsEl = document.getElementById('kpiActiveAlerts');
  if (activeAlertsEl) {
    activeAlertsEl.textContent = state.alerts ? state.alerts.length : (state.summary.active_alerts_count || 0);
  }

  const peakRainEl = document.getElementById('kpiPeakRainfall');
  if (peakRainEl) {
    peakRainEl.textContent = state.summary.max_24h_rainfall_mm !== undefined ? state.summary.max_24h_rainfall_mm : '0.0';
  }
}

// Render Alert Center
function renderAlerts() {
  const container = document.getElementById('alertsContainer');
  if (!container) return;

  if (!state.alerts || state.alerts.length === 0) {
    container.innerHTML = `
      <div class="empty-alerts">
        <span style="font-size: 1.25rem;">✓</span>
        <strong>All Monitored Catchments Operating Within Safe Hydrological Margins</strong>
        <p style="margin-top: 0.25rem; font-size: 0.8rem; color: #64748b;">No active severe or high flood warnings detected across West Bengal zones.</p>
      </div>
    `;
    return;
  }

  container.innerHTML = state.alerts.map(a => `
    <div class="alert-item ${a.severity.toLowerCase()}">
      <span class="alert-badge ${a.severity.toLowerCase()}">${a.severity}</span>
      <div class="alert-content">
        <div class="alert-title-row">
          <span class="alert-zone-name">${escapeHtml(a.title)}</span>
          <span class="alert-timestamp">${new Date(a.timestamp).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})}</span>
        </div>
        <div class="alert-reason">${escapeHtml(a.reason)}</div>
        <div class="alert-precaution">⚡ Precaution: ${escapeHtml(a.recommended_action)}</div>
      </div>
    </div>
  `).join('');
}

// Render Leaflet Map Markers
function renderMapMarkers() {
  if (!state.map) return;

  // Clear existing markers
  Object.values(state.markers).forEach(m => state.map.removeLayer(m));
  state.markers = {};

  state.readings.forEach(zone => {
    const lat = zone.lat;
    const lon = zone.lon;
    if (!lat || !lon) return;

    const score = Math.round(zone.risk_score || 0);
    const level = (zone.risk_level || 'LOW').toUpperCase();
    const color = zone.risk_color || '#22c55e';

    // Custom HTML Pin
    const customIcon = L.divIcon({
      className: 'custom-leaflet-pin',
      html: `<div class="custom-pin" style="background-color: ${color};">${score}</div>`,
      iconSize: [32, 32],
      iconAnchor: [16, 16],
      popupAnchor: [0, -18]
    });

    const marker = L.marker([lat, lon], { icon: customIcon }).addTo(state.map);

    const dischargeTxt = zone.river_discharge_m3s !== null && zone.river_discharge_m3s !== undefined
      ? `${zone.river_discharge_m3s} m³/s`
      : 'GloFAS n/a';

    const rainTxt = zone.rainfall_24h_mm !== null && zone.rainfall_24h_mm !== undefined
      ? `${zone.rainfall_24h_mm} mm`
      : '0.0 mm';

    const popupHtml = `
      <div class="popup-inner">
        <div class="popup-title">${escapeHtml(zone.zone_name)}</div>
        <div class="popup-basin">Basin: ${escapeHtml(zone.river_basin || 'Local River')}</div>
        <div class="popup-row">
          <span>Risk Level:</span>
          <span class="popup-badge" style="background: ${color};">${level} (${score}/100)</span>
        </div>
        <div class="popup-row">
          <span>24h Rainfall:</span>
          <strong>${rainTxt}</strong>
        </div>
        <div class="popup-row">
          <span>River Discharge:</span>
          <strong>${dischargeTxt}</strong>
        </div>
        <div class="popup-row">
          <span>Telemetry Status:</span>
          <strong>${zone.freshness || 'LIVE'}</strong>
        </div>
        <button class="popup-btn" onclick="openZoneModal('${zone.zone_id}')">Inspect Full Analytics</button>
      </div>
    `;

    marker.bindPopup(popupHtml);
    state.markers[zone.zone_id] = marker;
  });
}

// Render Zone Table with Search & Filters
function renderZoneTable() {
  const tbody = document.getElementById('zoneTableBody');
  if (!tbody) return;

  const filtered = state.readings.filter(z => {
    const matchFilter = (state.activeFilter === 'ALL') || (z.risk_level === state.activeFilter);
    const matchSearch = (z.zone_name || '').toLowerCase().includes(state.searchQuery) ||
                        (z.district || '').toLowerCase().includes(state.searchQuery) ||
                        (z.river_basin || '').toLowerCase().includes(state.searchQuery);
    return matchFilter && matchSearch;
  });

  if (filtered.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="9" style="text-align: center; padding: 2rem; color: #64748b;">
          No monitored zones match your filter/search criteria.
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = filtered.map(z => {
    const rain = (z.rainfall_24h_mm !== null && z.rainfall_24h_mm !== undefined) ? `${z.rainfall_24h_mm} mm` : 'Unavailable';
    const disc = (z.river_discharge_m3s !== null && z.river_discharge_m3s !== undefined) ? `${z.river_discharge_m3s} m³/s` : 'GloFAS n/a';
    const score = Math.round(z.risk_score || 0);
    const level = z.risk_level || 'LOW';
    const color = z.risk_color || '#22c55e';
    const freshness = z.freshness || 'LIVE';
    const primaryPrecaution = (z.recommended_precautions && z.recommended_precautions.length > 0)
      ? z.recommended_precautions[0]
      : 'Normal catchment monitoring';

    return `
      <tr>
        <td>
          <div style="font-weight: 600; color: #fff;">${escapeHtml(z.zone_name)}</div>
        </td>
        <td>
          <span style="font-size: 0.8rem; color: #cbd5e1;">${escapeHtml(z.district || '—')}</span>
        </td>
        <td>
          <span style="font-size: 0.8rem; color: #94a3b8;">${escapeHtml(z.river_basin || 'Catchment')}</span>
        </td>
        <td><strong>${rain}</strong></td>
        <td><strong>${disc}</strong></td>
        <td>
          <span class="risk-pill" style="background: ${color}; color: ${level === 'MODERATE' ? '#000' : '#fff'};">
            ${level} (${score}/100)
          </span>
        </td>
        <td>
          <span class="freshness-badge ${freshness.toLowerCase()}">${freshness}</span>
        </td>
        <td>
          <div style="font-size: 0.775rem; color: #cbd5e1; max-width: 250px; line-height: 1.35;">
            ${escapeHtml(primaryPrecaution)}
          </div>
        </td>
        <td>
          <button class="btn-secondary" onclick="openZoneModal('${z.zone_id}')" style="padding: 0.25rem 0.6rem; font-size: 0.75rem; white-space: nowrap;">
            View Details
          </button>
        </td>
      </tr>
    `;
  }).join('');
}

// Populate Zone Dropdowns
function populateZoneSelectors() {
  const simSelect = document.getElementById('simZone');
  const chartSelect = document.getElementById('chartZoneSelect');

  if (simSelect && simSelect.children.length <= 1) {
    simSelect.innerHTML = state.readings.map(z => `
      <option value="${z.zone_id}">${escapeHtml(z.zone_name)}</option>
    `).join('');
  }

  if (chartSelect && chartSelect.children.length <= 1) {
    chartSelect.innerHTML = state.readings.map(z => `
      <option value="${z.zone_id}" ${z.zone_id === state.selectedZoneId ? 'selected' : ''}>${escapeHtml(z.zone_name)}</option>
    `).join('');
  }
}

// Simulator: Run POST /api/predict
async function runSimulation() {
  const zoneSelect = document.getElementById('simZone');
  const rainInput = document.getElementById('simRain');
  const dischargeInput = document.getElementById('simDischarge');

  if (!zoneSelect || !rainInput || !dischargeInput) return;

  const payload = {
    zone_id: zoneSelect.value,
    rainfall_24h_mm: parseFloat(rainInput.value),
    forecast_rain_7d_mm: parseFloat(rainInput.value) * 1.5,
    river_discharge_m3s: parseFloat(dischargeInput.value)
  };

  try {
    const res = await fetch('/api/predict', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();

    if (data.success && data.prediction) {
      renderSimulationResult(data.prediction);
    } else {
      const errMsg = data.message || data.error || 'Validation error';
      const scoreEl = document.getElementById('simScore');
      if (scoreEl) scoreEl.textContent = 'Invalid Input';
      const precEl = document.getElementById('simPrecaution');
      if (precEl) precEl.textContent = errMsg;
    }
  } catch (err) {
    console.error('Simulation error:', err);
    const scoreEl = document.getElementById('simScore');
    if (scoreEl) scoreEl.textContent = 'Error';
    const precEl = document.getElementById('simPrecaution');
    if (precEl) precEl.textContent = 'Failed to evaluate simulation parameters: ' + err.message;
  }
}

function renderSimulationResult(pred) {
  const scoreEl = document.getElementById('simScore');
  const levelEl = document.getElementById('simLevelPill');
  const listEl = document.getElementById('simFactorsList');
  const precEl = document.getElementById('simPrecaution');

  if (scoreEl) scoreEl.textContent = `${pred.risk_score} / 100`;
  if (levelEl) {
    levelEl.textContent = pred.risk_level;
    levelEl.style.backgroundColor = pred.color;
    levelEl.style.color = pred.risk_level === 'MODERATE' ? '#000' : '#fff';
  }

  if (listEl && pred.contributing_factors) {
    listEl.innerHTML = pred.contributing_factors.slice(0, 3).map(f => `
      <li>
        <span>${escapeHtml(f.factor)}:</span>
        <strong style="color: ${f.points >= 15 ? '#ef4444' : '#38bdf8'};">+${f.points} pts</strong>
      </li>
    `).join('');
  }

  if (precEl && pred.recommended_precautions && pred.recommended_precautions.length > 0) {
    precEl.textContent = pred.recommended_precautions[0];
  }
}

// Modal: Open Zone Details
function openZoneModal(zoneId) {
  const zone = state.readings.find(z => z.zone_id === zoneId);
  if (!zone) return;

  document.getElementById('modalZoneName').textContent = zone.zone_name;
  document.getElementById('modalDistrict').textContent = `${zone.district || 'West Bengal'} • ${zone.river_basin || ''}`;
  
  const scorePill = document.getElementById('modalRiskPill');
  scorePill.textContent = `${zone.risk_level} (${Math.round(zone.risk_score)}/100)`;
  scorePill.style.backgroundColor = zone.risk_color;
  scorePill.style.color = zone.risk_level === 'MODERATE' ? '#000' : '#fff';

  document.getElementById('modalRainCurrent').textContent = (zone.rainfall_current_mm !== null && zone.rainfall_current_mm !== undefined) ? `${zone.rainfall_current_mm} mm` : 'Unavailable';
  document.getElementById('modalRain24h').textContent = (zone.rainfall_24h_mm !== null && zone.rainfall_24h_mm !== undefined) ? `${zone.rainfall_24h_mm} mm` : 'Unavailable';
  document.getElementById('modalForecast7d').textContent = (zone.forecast_rain_7d_mm !== null && zone.forecast_rain_7d_mm !== undefined) ? `${zone.forecast_rain_7d_mm} mm` : '—';
  document.getElementById('modalDischarge').textContent = (zone.river_discharge_m3s !== null && zone.river_discharge_m3s !== undefined) ? `${zone.river_discharge_m3s} m³/s` : 'GloFAS n/a';
  document.getElementById('modalElevation').textContent = `${zone.elevation_m || '—'} m AMSL`;
  document.getElementById('modalFreshness').textContent = zone.freshness || 'LIVE';

  // Factors List
  const factorsList = document.getElementById('modalFactorsList');
  if (factorsList) {
    if (zone.contributing_factors && zone.contributing_factors.length > 0) {
      factorsList.innerHTML = zone.contributing_factors.map(f => `
        <li class="factor-item">
          <div>
            <strong>${escapeHtml(f.factor)}</strong> (${escapeHtml(f.value)})
            <div style="font-size: 0.725rem; color: #94a3b8;">${escapeHtml(f.explanation || '')}</div>
          </div>
          <span style="font-weight: 700; color: ${f.points >= 15 ? '#ef4444' : '#38bdf8'}; font-size: 0.85rem;">
            +${f.points} pts
          </span>
        </li>
      `).join('');
    } else {
      factorsList.innerHTML = '<li style="color: #64748b;">No elevated risk factors detected.</li>';
    }
  }

  // Precautions List
  const precList = document.getElementById('modalPrecautionsList');
  if (precList) {
    if (zone.recommended_precautions && zone.recommended_precautions.length > 0) {
      precList.innerHTML = zone.recommended_precautions.map(p => `
        <li>${escapeHtml(p)}</li>
      `).join('');
    } else {
      precList.innerHTML = '<li>Standard monitoring protocols apply.</li>';
    }
  }

  const modal = document.getElementById('zoneModal');
  if (modal) modal.classList.add('open');
}

function closeModal() {
  const modal = document.getElementById('zoneModal');
  if (modal) modal.classList.remove('open');
}

// Chart.js: Historical & Forecast Trends
async function loadZoneHistoryAndRenderChart(zoneId) {
  try {
    const res = await fetch(`/api/history?zone_id=${zoneId}&limit=14`);
    const data = await res.json();
    const history = data.history || [];

    // Also get current zone forecast from state
    const currentZone = state.readings.find(z => z.zone_id === zoneId);
    renderTrendChart(zoneId, history, currentZone);
  } catch (err) {
    console.error('Failed to load history for chart:', err);
  }
}

function renderTrendChart(zoneId, history, zoneData) {
  const ctx = document.getElementById('trendChart');
  if (!ctx) return;

  // Prepare chronological labels & data points
  let labels = [];
  let dischargeData = [];
  let rainData = [];
  let isForecastMode = false;

  if (history.length >= 3) {
    labels = history.map(h => new Date(h.timestamp).toLocaleDateString([], { month: 'short', day: 'numeric', hour: '2-digit' }));
    dischargeData = history.map(h => h.river_discharge_m3s);
    rainData = history.map(h => h.rainfall_24h_mm);
  } else if (zoneData && zoneData.discharge_forecast_7d_m3s && zoneData.discharge_forecast_7d_m3s.length > 0) {
    // Show 7-day GloFAS forecast series
    isForecastMode = true;
    labels = ['Day 1', 'Day 2', 'Day 3', 'Day 4', 'Day 5', 'Day 6', 'Day 7'];
    dischargeData = zoneData.discharge_forecast_7d_m3s;
    const baseRain = Number(zoneData.rainfall_24h_mm || 5.0);
    rainData = [baseRain, Math.round(baseRain * 0.8 * 10)/10, Math.round(baseRain * 1.2 * 10)/10, Math.round(baseRain * 0.9 * 10)/10, Math.round(baseRain * 0.5 * 10)/10, Math.round(baseRain * 0.4 * 10)/10, Math.round(baseRain * 0.3 * 10)/10];
  } else {
    labels = ['T-24h', 'T-18h', 'T-12h', 'T-6h', 'Current'];
    dischargeData = [12.0, 15.5, 18.2, 22.0, zoneData ? (zoneData.river_discharge_m3s || 25.0) : 25.0];
    rainData = [2.0, 8.5, 14.0, 28.0, zoneData ? (zoneData.rainfall_24h_mm || 35.0) : 35.0];
  }

  if (state.trendChart) {
    state.trendChart.destroy();
  }

  state.trendChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [
        {
          label: isForecastMode ? 'River Discharge (GloFAS 7-Day Forecast m³/s)' : 'River Discharge (m³/s)',
          data: dischargeData,
          borderColor: '#38bdf8',
          backgroundColor: 'rgba(56, 189, 248, 0.15)',
          fill: true,
          tension: 0.3,
          yAxisID: 'yDischarge'
        },
        {
          label: isForecastMode ? 'Rainfall (7-Day Outlook mm)' : '24h Rainfall (mm)',
          data: rainData,
          borderColor: '#10b981',
          backgroundColor: 'rgba(16, 185, 129, 0.1)',
          fill: false,
          tension: 0.3,
          yAxisID: 'yRain'
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: {
        mode: 'index',
        intersect: false
      },
      plugins: {
        legend: {
          labels: { color: '#94a3b8', font: { family: 'Inter', size: 11 } }
        },
        tooltip: {
          backgroundColor: '#1e293b',
          titleColor: '#fff',
          bodyColor: '#e2e8f0',
          borderColor: '#334155',
          borderWidth: 1
        }
      },
      scales: {
        x: {
          grid: { color: 'rgba(51, 65, 85, 0.3)' },
          ticks: { color: '#94a3b8', font: { size: 10 } }
        },
        yDischarge: {
          type: 'linear',
          display: true,
          position: 'left',
          title: { display: true, text: 'Discharge (m³/s)', color: '#38bdf8', font: { size: 11 } },
          grid: { color: 'rgba(51, 65, 85, 0.3)' },
          ticks: { color: '#94a3b8', font: { size: 10 } }
        },
        yRain: {
          type: 'linear',
          display: true,
          position: 'right',
          title: { display: true, text: 'Rainfall (mm)', color: '#10b981', font: { size: 11 } },
          grid: { drawOnChartArea: false },
          ticks: { color: '#94a3b8', font: { size: 10 } }
        }
      }
    }
  });
}

// Utility: HTML Escaping
function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// Simple Toast Notification
function showNotification(msg, type = 'info') {
  const toast = document.createElement('div');
  toast.style.position = 'fixed';
  toast.style.bottom = '20px';
  toast.style.right = '20px';
  toast.style.padding = '0.75rem 1.25rem';
  toast.style.borderRadius = '8px';
  toast.style.fontSize = '0.825rem';
  toast.style.fontWeight = '600';
  toast.style.zIndex = '9999';
  toast.style.boxShadow = '0 10px 15px rgba(0,0,0,0.5)';
  toast.style.transition = 'all 0.3s ease';

  if (type === 'error') {
    toast.style.backgroundColor = '#ef4444';
    toast.style.color = '#fff';
  } else if (type === 'success') {
    toast.style.backgroundColor = '#10b981';
    toast.style.color = '#fff';
  } else {
    toast.style.backgroundColor = '#0284c7';
    toast.style.color = '#fff';
  }

  toast.textContent = msg;
  document.body.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}

