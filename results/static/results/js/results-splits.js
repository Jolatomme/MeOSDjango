const COResultsSplits = (() => {
  let _legErrorData = [];
  let _errorChart = null;
  let _errorChartOpen = false;

  function _thSec() {
    return parseFloat(document.getElementById('thresholdSec')?.value) || 0;
  }
  function _thPct() {
    return parseFloat(document.getElementById('thresholdPct')?.value) || 0;
  }

  function applyErrorThresholds() {
    const thSec = _thSec();
    const thPct = _thPct();
    const thRaw = thSec * 10;
    document.querySelectorAll('.split-cell[data-error-time]').forEach(cell => {
      const et = parseFloat(cell.dataset.errorTime);
      const ep = parseFloat(cell.dataset.errorPct);
      const isError = !isNaN(et) && !isNaN(ep) && (et >= thRaw || ep >= thPct);
      const errSpan = cell.querySelector('.split-error');
      if (isError) {
        cell.classList.add('split-error-flag');
        if (errSpan) {
          errSpan.textContent = `+${(et / 10).toFixed(0)}s / +${Math.round(ep)}%`;
          errSpan.classList.remove('d-none');
        }
      } else {
        cell.classList.remove('split-error-flag');
        if (errSpan) {
          errSpan.textContent = '';
          errSpan.classList.add('d-none');
        }
      }
    });
  }

  function _buildChartData() {
    const thSec = _thSec();
    const thPct = _thPct();
    const thRaw = thSec * 10;
    return _legErrorData.map(leg => {
      const inError = leg.errors.filter(e => e.et > thRaw || e.ep > thPct);
      return {
        label: leg.ctrl_name,
        rate: leg.errors.length > 0 ? (inError.length / leg.errors.length * 100).toFixed(1) : 0,
        avg: inError.length > 0 ? (inError.reduce((s, e) => s + e.et / 10, 0) / inError.length).toFixed(1) : 0,
      };
    });
  }

  function _renderChart() {
    if (!_legErrorData.length) return;
    const data = _buildChartData();
    if (_errorChart) {
      _errorChart.data.labels = data.map(d => d.label);
      _errorChart.data.datasets[0].data = data.map(d => d.rate);
      _errorChart.data.datasets[1].data = data.map(d => d.avg);
      _errorChart.update();
      return;
    }
    const ctx = document.getElementById('errorChart');
    if (!ctx) return;
    _errorChart = new Chart(ctx.getContext('2d'), {
      type: 'bar',
      data: {
        labels: data.map(d => d.label),
        datasets: [
          {
            type: 'bar', label: 'Coureurs en erreur (%)', data: data.map(d => d.rate),
            backgroundColor: 'rgba(67,99,216,0.65)', borderColor: 'rgba(67,99,216,0.9)',
            borderWidth: 1, yAxisID: 'yRate', order: 2,
          },
          {
            type: 'line', label: 'Erreur moyenne (s)', data: data.map(d => d.avg),
            borderColor: '#f58231', backgroundColor: 'rgba(245,130,49,0.15)',
            borderWidth: 2.5, pointRadius: 4, pointBackgroundColor: '#f58231',
            tension: 0.3, yAxisID: 'yAvg', order: 1,
          },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: { legend: { position: 'top' } },
        scales: {
          yRate: {
            type: 'linear', position: 'left', min: 0, max: 100,
            title: { display: true, text: 'Coureurs en erreur (%)' },
          },
          yAvg: {
            type: 'linear', position: 'right', min: 0,
            title: { display: true, text: 'Erreur moy. (s)' },
            grid: { drawOnChartArea: false },
          },
        },
      },
    });
  }

  function toggleErrorChart() {
    _errorChartOpen = !_errorChartOpen;
    const body = document.getElementById('errorChartBody');
    const chevron = document.getElementById('errorChartChevron');
    if (body) body.style.display = _errorChartOpen ? '' : 'none';
    if (chevron) chevron.style.transform = _errorChartOpen ? 'rotate(180deg)' : '';
    if (_errorChartOpen) {
      requestAnimationFrame(() => requestAnimationFrame(_renderChart));
    }
  }

  function init(legErrorData) {
    _legErrorData = legErrorData || [];
    applyErrorThresholds();
    document.getElementById('thresholdSec')?.addEventListener('input', applyErrorThresholds);
    document.getElementById('thresholdPct')?.addEventListener('input', applyErrorThresholds);
    document.addEventListener('DOMContentLoaded', applyErrorThresholds);
    ['thresholdSec', 'thresholdPct'].forEach(id => {
      document.getElementById(id)?.addEventListener('input', () => {
        if (_errorChartOpen) _renderChart();
      });
    });
  }

  return { init, applyErrorThresholds, toggleErrorChart };
})();
