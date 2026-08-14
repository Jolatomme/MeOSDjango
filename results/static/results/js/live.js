/**
 * live.js — Suivi en temps réel des postes radio (page Live).
 *
 * Interroge l'API JSON live (/api/.../live/) toutes les POLL_INTERVAL_MS
 * et re-rend le tableau sans recharger la page. Le tick de l'horloge de
 * course est local (1 s) entre deux polls ; l'horloge serveur fournie par
 * l'API sert de référence pour « il y a X s ».
 *
 * Initialisé depuis live_results.html :
 *   LiveResults.init({ apiUrl, cid, isCourse, initialRaceStart, initialNowClock })
 */
const LiveResults = (() => {
  'use strict';

  const POLL_INTERVAL_MS = 5000;
  const DAY_TENTHS = 24 * 3600 * 10;

  const GROUP_ORDER = ['en_course', 'arrives', 'en_attente', 'termine'];
  const GROUP_LABELS = {
    en_course:  'En course',
    arrives:    'Arrivés',
    en_attente: 'En attente',
    termine:    'Terminé',
  };
  const GROUP_ICONS = {
    en_course:  'bi-person-walking',
    arrives:    'bi-flag-fill',
    en_attente: 'bi-hourglass-split',
    termine:    'bi-x-circle',
  };
  const GROUP_EMPTY = {
    en_course:  'Aucun coureur parti pour le moment.',
    arrives:    'Aucun arrivé pour le moment.',
    en_attente: 'Aucun coureur en attente.',
    termine:    'Aucun.',
  };

  let cfg = null;
  let pollTimer = null;
  let clockTimer = null;
  let lastData = null;
  let lastFetchClientMs = 0;

  // ── Petits utilitaires ───────────────────────────────────────────────────

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, (m) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[m]));
  }

  function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
  }

  /** 1/10 s depuis minuit → 'HH:MM:SS' (passe minuit). */
  function fmtClock(tenths) {
    if (tenths == null || isNaN(tenths)) return '—';
    let t = Math.max(0, Math.floor(tenths / 10)) % 86400;
    const h = String(Math.floor(t / 3600)).padStart(2, '0');
    const m = String(Math.floor((t % 3600) / 60)).padStart(2, '0');
    const s = String(t % 60).padStart(2, '0');
    return `${h}:${m}:${s}`;
  }

  /** Temps de course MeOS (1/10 s) → 'MM:SS' ou 'H:MM:SS' (à la seconde). */
  function fmtRaceTime(tenths) {
    if (tenths == null) return '—';
    const t = Math.floor(tenths / 10);
    const h = Math.floor(t / 3600);
    const m = Math.floor((t % 3600) / 60);
    const s = t % 60;
    return h > 0
      ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
      : `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  }

  function ctrlName(data, ctrlId) {
    for (const c of data.controls) {
      if (c.ctrl_id === ctrlId) return c.ctrl_name;
    }
    return String(ctrlId);
  }

  /** 1/10 s serveur « tic-tac » à la milliseconde client entre deux polls. */
  function tenthsNow(data) {
    const extra = (Date.now() - lastFetchClientMs) * 10 / 1000;
    return (data.server_now_clock + Math.floor(extra)) % DAY_TENTHS;
  }

  /** Écart depuis un poinçon (1/10 s) → 'X h Y min Z s', 'X min Y s' ou 'X s'. */
  function fmtAgo(tenths) {
    let delta = tenths;
    if (delta < 0) delta += DAY_TENTHS; // course à cheval sur minuit
    const totalSec = Math.floor(delta / 10);
    const h = Math.floor(totalSec / 3600);
    const m = Math.floor((totalSec % 3600) / 60);
    const s = totalSec % 60;
    if (h > 0) return `${h} h ${m} min ${s} s`;
    if (m > 0) return `${m} min ${s} s`;
    return `${s} s`;
  }

  // ── Cellules ───────────────────────────────────────────────────────────────

  function rankCell(runner) {
    if (runner.rank == null) return '<span class="text-muted">—</span>';
    return COUtils.renderMedal(runner.rank);
  }

  function statusBadge(runner) {
    if (runner.group === 'en_course') {
      return '<span class="badge bg-success">En course</span>';
    }
    return `<span class="badge bg-${esc(runner.stat_badge)}">${esc(runner.stat_label)}</span>`;
  }

  function progressCell(runner, data) {
    const total = data.n_controls || 0;
    if (runner.group === 'arrives') return '<span class="text-success fw-bold" title="Tous les postes radio">✓</span>';
    if (runner.group !== 'en_course' || total === 0) return '—';
    const pct = Math.max(2, Math.round((runner.n_punches / total) * 100));
    return `<span class="d-inline-flex align-items-center gap-2 justify-content-end">
      <span class="small fw-bold" style="min-width:2.5rem">${runner.n_punches}/${total}</span>
      <span class="progress" style="width:5.5rem;height:.5rem;margin:0">
        <span class="progress-bar" style="width:${pct}%"></span>
      </span>
    </span>`;
  }

  function lastPunchCell(runner, data) {
    if (runner.group !== 'en_course' || runner.n_punches === 0) return '<span class="text-muted">—</span>';
    return `<span class="badge bg-light text-dark border">${esc(ctrlName(data, runner.last_ctrl))}</span>
            <span class="small text-muted ms-1">${fmtClock(runner.last_punch_clock)}</span>
            <span class="live-ago small text-muted ms-1" data-punch-clock="${runner.last_punch_clock}"></span>`;
  }

  function timeCell(runner) {
    if (runner.group === 'arrives') {
      return `<span class="fw-bold">${fmtRaceTime(runner.rt)}</span>`;
    }
    if (runner.group === 'en_course' && runner.st > 0) {
      return `<span class="live-time fw-bold" data-st="${runner.st}" title="Temps de course depuis le départ">—</span>`;
    }
    if (runner.group === 'en_attente' && runner.st > 0) {
      return `<span class="text-muted small" title="Heure de départ">Départ ${fmtClock(runner.st)}</span>`;
    }
    return '—';
  }

  // ── Rendu ──────────────────────────────────────────────────────────────────

  function colSpan() { return cfg.isCourse ? 8 : 7; }

  function render(data) {
    lastData = data;
    const body = document.getElementById('liveBody');
    if (!body) return;

    const counts = { en_course: 0, arrives: 0, en_attente: 0, termine: 0 };
    for (const r of data.runners) counts[r.group] = (counts[r.group] || 0) + 1;

    const html = [];
    for (const group of GROUP_ORDER) {
      const rows = data.runners.filter((r) => r.group === group);
      html.push(`<tr class="live-group-row">
        <td colspan="${colSpan()}">
          <i class="bi ${GROUP_ICONS[group]} me-2"></i>${GROUP_LABELS[group]}
          <span class="badge bg-light text-dark ms-2">${rows.length}</span>
        </td>
      </tr>`);
      if (!rows.length) {
        html.push(`<tr><td colspan="${colSpan()}" class="text-muted small p-2 ps-4">${GROUP_EMPTY[group]}</td></tr>`);
        continue;
      }
      for (const r of rows) {
        html.push(`<tr class="${r.group === 'en_course' ? 'live-running' : ''}">
          <td>${rankCell(r)}</td>
          <td class="runner-name">
            <a href="/competition/${cfg.cid}/competitor/${r.id}/">${esc(r.name)}</a>
          </td>
          ${cfg.isCourse ? `<td>${r.class_name ? `<span class="badge bg-light text-dark border">${esc(r.class_name)}</span>` : '—'}</td>` : ''}
          <td class="club-name text-muted">${r.org ? esc(r.org) : '—'}</td>
          <td class="text-end">${progressCell(r, data)}</td>
          <td>${lastPunchCell(r, data)}</td>
          <td class="text-end">${statusBadge(r)}</td>
          <td class="text-end">${timeCell(r)}</td>
        </tr>`);
      }
    }

    if (!data.runners.length) {
      html.push(`<tr><td colspan="${colSpan()}" class="text-center text-muted p-4">
        <i class="bi bi-inbox me-2"></i>Aucun coureur — le flux MOP n'a peut-être pas encore été reçu.
      </td></tr>`);
    }

    body.innerHTML = html.join('');
    setText('liveCountEnCourse', counts.en_course);
    setText('liveCountArrives', counts.arrives);
    setText('liveCountWaiting', counts.en_attente);
    setText('liveCountDone', counts.termine);
    setText('liveLastUpdate', `Mis à jour ${fmtClock(data.server_now_clock)}`);
  }

  function raceElapsed(data) {
    if (data.race_start_clock == null) return null;
    let delta = data.server_now_clock - data.race_start_clock;
    if (delta < 0) delta += DAY_TENTHS;
    return delta;
  }

  function updateClock(data) {
    const el = document.getElementById('liveRaceClockValue');
    if (!el) return;
    const base = raceElapsed(data);
    if (base == null) { el.textContent = '--:--:--'; return; }
    const now = Date.now();
    const sinceFetch = lastFetchClientMs ? (now - lastFetchClientMs) / 1000 : 0;
    el.textContent = fmtClock(base + sinceFetch * 10);
  }

  /** Heure murale actuelle (secondes, tick 1 s). */
  function updateWallClock(data) {
    const el = document.getElementById('liveWallClockValue');
    if (el) el.textContent = fmtClock(tenthsNow(data));
  }

  function startClock(data) {
    if (clockTimer) clearInterval(clockTimer);
    const tick = () => {
      updateClock(data);
      updateWallClock(data);
      updateTickers(data);
    };
    tick();
    clockTimer = setInterval(tick, 1000);
  }

  /** Recalcule chaque seconde : « il y a X » et chronos des coureurs en course. */
  function updateTickers(data) {
    if (!data) return;
    const now = tenthsNow(data);
    for (const span of document.querySelectorAll('.live-ago')) {
      const punch = Number(span.dataset.punchClock);
      if (isNaN(punch)) continue;
      span.textContent = `· il y a ${fmtAgo(now - punch)}`;
    }
    for (const span of document.querySelectorAll('.live-time')) {
      const st = Number(span.dataset.st);
      if (isNaN(st) || st <= 0) continue;
      let delta = now - st;
      if (delta < 0) delta += DAY_TENTHS; // course à cheval sur minuit
      span.textContent = fmtRaceTime(delta);
    }
  }

  function setLiveStatus(ok) {
    const badge = document.getElementById('liveStatusBadge');
    if (!badge) return;
    badge.className = ok ? 'badge bg-success fs-6' : 'badge bg-danger fs-6';
    badge.innerHTML = `<span class="live-dot"></span>${ok ? 'En direct' : 'Hors ligne'}`;
  }

  async function poll() {
    try {
      const resp = await fetch(cfg.apiUrl, { headers: { 'Accept': 'application/json' } });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      if (!data.success) throw new Error(data.error || 'erreur API');
      lastFetchClientMs = Date.now();
      render(data);
      startClock(data);
      setLiveStatus(true);
    } catch (err) {
      setLiveStatus(false);
    }
  }

  function init(config) {
    cfg = config;
    lastFetchClientMs = Date.now();
    startClock({
      race_start_clock: cfg.initialRaceStart,
      server_now_clock: cfg.initialNowClock,
    });
    poll();
    pollTimer = setInterval(poll, POLL_INTERVAL_MS);
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) {
        if (pollTimer) clearInterval(pollTimer);
      } else {
        poll();
        pollTimer = setInterval(poll, POLL_INTERVAL_MS);
      }
    });
  }

  return { init };
})();