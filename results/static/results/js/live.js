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
  const POLL_MAX_INTERVAL_MS = 30000;
  const DAY_TENTHS = 24 * 3600 * 10;

  const GROUP_ORDER = ['en_course', 'valid_gec', 'arrives', 'en_attente', 'termine'];
  const GROUP_LABELS = {
    en_course:  'En course',
    valid_gec:  'En attente validation GEC',
    arrives:    'Arrivés',
    en_attente: 'En attente',
    termine:    'Terminé',
  };
  const GROUP_ICONS = {
    en_course:  'bi-person-walking',
    valid_gec:  'bi-clipboard-check',
    arrives:    'bi-flag-fill',
    en_attente: 'bi-hourglass-split',
    termine:    'bi-x-circle',
  };
  const GROUP_EMPTY = {
    en_course:  'Aucun coureur parti pour le moment.',
    valid_gec:  'Aucun coureur en attente de validation GEC.',
    arrives:    'Aucun arrivé pour le moment.',
    en_attente: 'Aucun coureur en attente.',
    termine:    'Aucun.',
  };

  /** Groupes encore sur le parcours : barre de progression, dernier poste,
   *  chrono de course et surlignage « en course ». */
  const RUNNING_GROUPS = ['en_course', 'valid_gec'];

  let cfg = null;
  let pollTimer = null;
  let clockTimer = null;
  let lastData = null;
  let lastFetchClientMs = 0;
  // Polling conditionnel : ETag de la dernière réponse + intervalle courant
  // (backoff ×2 jusqu'à POLL_MAX_INTERVAL_MS tant que rien ne change, reset
  // à POLL_INTERVAL_MS dès une mise à jour).
  let lastEtag = null;
  let pollIntervalMs = POLL_INTERVAL_MS;
  let currentRaceState = 'live';

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
    const neg = tenths < 0;
    const t = Math.floor(Math.abs(tenths) / 10);
    const h = Math.floor(t / 3600);
    const m = Math.floor((t % 3600) / 60);
    const s = t % 60;
    const fmt = h > 0
      ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
      : `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
    return neg ? `-${fmt}` : fmt;
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
    if (runner.group === 'arrives' || runner.group === 'termine') {
      return COUtils.renderMedal(runner.rank);
    }
    return `<span class="rank-n">${runner.rank}</span>`;
  }

  function statusBadge(runner) {
    if (RUNNING_GROUPS.includes(runner.group)) {
      return '<span class="badge bg-success">En course</span>';
    }
    return `<span class="badge bg-${esc(runner.stat_badge)}">${esc(runner.stat_label)}</span>`;
  }

  /** Badge « Temps négatif » ; le tooltip détaille les postes en cause
   *  quand l'API les fournit (neg_ctrls). */
  function negBadge(r, extraClass) {
    const ctrls = (r.neg_ctrls || []).filter(Boolean);
    const title = ctrls.length
      ? `Temps négatif au poste ${ctrls.length > 1 ? 's' : ''} ${ctrls.join(', ')}`
      : 'Temps négatif : boîtier mal synchronisé ou carte SI non effacée';
    return `<span class="badge neg-badge${extraClass ? ' ' + extraClass : ''}" title="${esc(title)}">Temps négatif</span>`;
  }

  /** Progression compacte pour la colonne de droite (compteur + mini-barre).
   *  Retourne '' quand rien n'est connu : la ligne de progression est absente
   *  plutôt que d'afficher un « — » inutile. */
  function progressCell(runner, data) {
    const total = data.n_controls || 0;
    if (runner.group === 'arrives') return '<span class="live-progress-done text-success" title="Tous les postes du parcours">✓</span>';
    // Un coureur « Terminé » (Abandon, PM…) peut avoir pointé des postes : on
    // conserve sa progression (sans quoi la barre disparaît alors qu'elle est connue).
    if (!RUNNING_GROUPS.includes(runner.group) && runner.group !== 'termine') return '';
    // Un coureur « Terminé » (Abandon, PM…) peut avoir sauté des postes puis
    // atteint le dernier : on compte les postes réellement pointés plutôt que
    // la position du poste le plus avancé (progress_pos).
    const pos = runner.group === 'termine' ? (runner.progress_count || 0) : runner.progress_pos;
    if (total === 0 || !pos) return '';
    // Dénominateur : postes du parcours uniquement (le poste d'arrivée ne compte pas)
    const pct = Math.min(100, Math.max(2, Math.round((pos / total) * 100)));
    return `<span class="live-progress">
      <span class="live-progress-count">${pos}/${total}</span>
      <span class="live-progress-track"><span class="live-progress-bar" style="width:${pct}%"></span></span>
    </span>`;
  }

  /** Couples poste/temps des postes radio pointés (En course + Valid. GEC +
   *  Arrivés), rendus en grille à piste fixe (.live-punches) : toutes les
   *  étiquettes partagent la même largeur, tous les temps aussi, pour un
   *  alignement vertical des poinçons d'une ligne sur l'autre. Le « il y a X »
   *  (qui tique) est posé hors géométrie en fin de liste — il ne concerne que
   *  le dernier poste atteint des coureurs encore en course.
   *  Retourne '' si aucun poste à afficher. */
  function radioPunchCell(runner, data) {
    const showsPosts = RUNNING_GROUPS.includes(runner.group) || runner.group === 'arrives';
    if (!showsPosts || !runner.radio_punches || !runner.radio_punches.length) return '';
    const items = runner.radio_punches.map((p) => {
      const name = esc(ctrlName(data, p.ctrl));
      const beforeStart = p.time <= 0;
      const timeTitle = beforeStart
        ? `${name} — poinçon avant le départ`
        : name;
      return `<span class="live-punch">` +
        `<span class="badge bg-light text-dark border" title="${name}">${name}</span>` +
        `<span class="live-punch-time${beforeStart ? ' live-punch-prestart' : ''}" title="${esc(timeTitle)}">${fmtRaceTime(p.time)}</span>` +
        `</span>`;
    });
    if (runner.group === 'en_course' && runner.last_punch_clock) {
      items.push(`<span class="live-ago" data-punch-clock="${runner.last_punch_clock}"></span>`);
    }
    return items.join('');
  }

  function timeCell(runner) {
    if (runner.group === 'arrives') {
      const t = `<span class="live-time-value fw-bold">${fmtRaceTime(runner.rt)}</span>`;
      if (runner.neg_time) {
        return `${t} ${negBadge(runner, 'ms-1')}`;
      }
      return t;
    }
    if (runner.group === 'valid_gec' && runner.st > 0 && (runner.provisional_rt != null || runner.last_time)) {
      // Poinçon d'arrivée radio (ou résultat préliminaire) : temps final
      // provisoire affiché, en attendant la validation GEC.
      const t = runner.provisional_rt != null ? runner.provisional_rt : runner.last_time;
      return `<span class="live-time-value fw-bold" title="Temps final provisoire — validation GEC en attente">${fmtRaceTime(t)}</span>`;
    }
    if (RUNNING_GROUPS.includes(runner.group) && runner.st > 0) {
      return `<span class="live-time live-time-value fw-bold" data-st="${runner.st}" title="Temps de course depuis le départ">—</span>`;
    }
    if (runner.group === 'en_attente' && runner.st > 0) {
      return `<span class="text-muted small" title="Heure de départ">Départ ${fmtClock(runner.st)}</span>
              <span class="live-countdown small text-muted ms-1" data-st="${runner.st}"></span>`;
    }
    if (runner.group === 'termine') {
      return statusBadge(runner);
    }
    return '—';
  }

  // ── Mesure des largeurs étiquette/temps ────────────────────────────────────

  /** Étalon caché hébergé par #liveTable (et non #liveBody, écrasé à chaque
   *  rendu) pour hériter exactement des polices/tailles du tableau. */
  let measureSpan = null;
  const measureCache = new Map();

  /** Largeur intrinsèque du texte rendu avec les classes de l'élément source
   *  (le padding Bootstrap des badges est ainsi inclus). Cache par libellé :
   *  seuls les textes jamais vus déclenchent une mesure. */
  function textWidth(text, className) {
    const key = className + '\u0000' + text;
    let w = measureCache.get(key);
    if (w != null) return w;
    if (!measureSpan) {
      const tbl = document.getElementById('liveTable');
      if (!tbl) return 0;
      measureSpan = document.createElement('span');
      measureSpan.style.cssText =
        'position:absolute;visibility:hidden;white-space:nowrap;top:-9999px;left:-9999px;';
      tbl.appendChild(measureSpan);
    }
    measureSpan.className = className;
    measureSpan.textContent = text;
    w = measureSpan.getBoundingClientRect().width;
    measureCache.set(key, w);
    return w;
  }

  /** Mesure les libellés réels et pose --lp-badge-w / --lp-time-w sur la
   *  table : toutes les étiquettes de poste prennent la même largeur, tous
   *  les temps aussi → grille alignée d'une ligne sur l'autre. Planchers
   *  ~2.25rem / ~3rem pour rester lisible avec un poste court. */
  function syncPunchWidths() {
    const tbl = document.getElementById('liveTable');
    if (!tbl) return;
    let badgeW = 0;
    let timeW = 0;
    for (const punch of document.querySelectorAll('#liveBody .live-punch')) {
      const badge = punch.querySelector('.badge');
      const time = punch.querySelector('.live-punch-time');
      if (badge) badgeW = Math.max(badgeW, textWidth(badge.textContent, badge.className));
      if (time) timeW = Math.max(timeW, textWidth(time.textContent, time.className));
    }
    if (!badgeW && !timeW) return;
    tbl.style.setProperty('--lp-badge-w', `${Math.ceil(Math.max(badgeW, 36))}px`);
    tbl.style.setProperty('--lp-time-w', `${Math.ceil(Math.max(timeW, 48))}px`);
  }

  /** Les mesures dépendent de la police active et du palier responsive
   *  (.results-table change de taille à 768px) : purge du cache + resync. */
  function watchMeasureContext() {
    const onChange = () => { measureCache.clear(); syncPunchWidths(); };
    if (window.matchMedia) {
      const mq = window.matchMedia('(max-width: 768px)');
      if (mq.addEventListener) mq.addEventListener('change', onChange);
      else if (mq.addListener) mq.addListener(onChange); // vieux navigateurs
    }
    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(onChange);
    }
  }

  // ── Rendu ──────────────────────────────────────────────────────────────────

  /** Une ligne coureur = grille 3 colonnes :
   *  classement | nom (club) + couples poste/temps | temps + progression. */
  function runnerRow(r, data) {
    const punches = radioPunchCell(r, data);
    const progress = progressCell(r, data);
    return `<tr class="live-runner${RUNNING_GROUPS.includes(r.group) ? ' live-running' : ''}">
      <td class="live-cell-rank">${rankCell(r)}</td>
      <td class="live-cell-main">
        <div class="live-runner-line runner-name">
          <a href="/competition/${cfg.cid}/competitor/${r.id}/">${esc(r.name)}</a>
          ${r.org ? `<span class="club-name">(${esc(r.org)})</span>` : ''}
          ${r.neg_time ? negBadge(r) : ''}
        </div>
        ${punches ? `<div class="live-punches">${punches}</div>` : ''}
      </td>
      <td class="live-cell-side">
        <div class="live-time-line">${timeCell(r)}</div>
        ${progress ? `<div class="live-progress-line">${progress}</div>` : ''}
      </td>
    </tr>`;
  }

  function render(data) {
    lastData = data;
    const body = document.getElementById('liveBody');
    if (!body) return;

    const counts = { en_course: 0, valid_gec: 0, arrives: 0, en_attente: 0, termine: 0 };
    for (const r of data.runners) counts[r.group] = (counts[r.group] || 0) + 1;

    const html = [];
    for (const group of GROUP_ORDER) {
      const rows = data.runners.filter((r) => r.group === group);
      html.push(`<tr class="live-group-row"><td>
          <i class="bi ${GROUP_ICONS[group]} me-2"></i>${GROUP_LABELS[group]}
          <span class="badge bg-light text-dark ms-2">${rows.length}</span>
        </td></tr>`);
      if (!rows.length) {
        html.push(`<tr><td class="text-muted small p-2 ps-4">${GROUP_EMPTY[group]}</td></tr>`);
        continue;
      }
      for (const r of rows) html.push(runnerRow(r, data));
    }

    if (!data.runners.length) {
      html.push(`<tr><td class="text-center text-muted p-4">
        <i class="bi bi-inbox me-2"></i>Aucun coureur — le flux MOP n'a peut-être pas encore été reçu.
      </td></tr>`);
    }

    body.innerHTML = html.join('');
    syncPunchWidths();
    setText('liveCountEnCourse', counts.en_course);
    setText('liveCountValidGec', counts.valid_gec);
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
    if (data.race_state === 'upcoming' || data.race_start_clock == null) {
      el.textContent = '--:--:--';
      return;
    }
    if (data.race_state === 'finished') {
      const end = data.race_end_clock != null ? data.race_end_clock : data.server_now_clock;
      let delta = end - data.race_start_clock;
      if (delta < 0) delta += DAY_TENTHS;
      el.textContent = fmtClock(delta);
      return;
    }
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

  /** Recalcule chaque seconde : « il y a X », chronos des coureurs en course
   *  et compte à rebours des coureurs en attente. */
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
    // « En attente » : compte à rebours avant le départ.
    for (const span of document.querySelectorAll('.live-countdown')) {
      const st = Number(span.dataset.st);
      if (isNaN(st) || st <= 0) continue;
      let delta = st - now;
      if (delta < 0) delta += DAY_TENTHS;
      span.textContent = delta > 0 ? `· dans ${fmtAgo(delta)}` : '';
    }
  }

  function setRaceState(state) {
    currentRaceState = state;
    const badge = document.getElementById('liveStatusBadge');
    if (!badge) return;
    if (state === 'finished') {
      badge.className = 'badge bg-secondary fs-6';
      badge.innerHTML = 'Course terminée';
    } else if (state === 'upcoming') {
      badge.className = 'badge bg-info fs-6';
      badge.innerHTML = 'Course à venir';
    } else {
      badge.className = 'badge bg-success fs-6';
      badge.innerHTML = `<span class="live-dot"></span>En direct`;
    }
  }

  function setLiveStatus(ok) {
    if (currentRaceState === 'finished' || currentRaceState === 'upcoming') return;
    const badge = document.getElementById('liveStatusBadge');
    if (!badge) return;
    badge.className = ok ? 'badge bg-success fs-6' : 'badge bg-danger fs-6';
    badge.innerHTML = `<span class="live-dot"></span>${ok ? 'En direct' : 'Hors ligne'}`;
  }

  function schedulePoll(ms) {
    clearTimeout(pollTimer);
    pollTimer = setTimeout(poll, ms);
  }

  async function poll() {
    try {
      const headers = { 'Accept': 'application/json' };
      if (lastEtag) headers['If-None-Match'] = lastEtag;
      const resp = await fetch(cfg.apiUrl, { headers });
      if (resp.status === 304) {
        // Rien de nouveau depuis le dernier poll : on ralentit progressivement
        setLiveStatus(true);
        pollIntervalMs = Math.min(pollIntervalMs * 2, POLL_MAX_INTERVAL_MS);
        schedulePoll(pollIntervalMs);
        return;
      }
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      if (!data.success) throw new Error(data.error || 'erreur API');
      lastEtag = resp.headers.get('ETag');
      lastFetchClientMs = Date.now();
      render(data);
      startClock(data);
      setRaceState(data.race_state);
      setLiveStatus(true);
      pollIntervalMs = POLL_INTERVAL_MS;
    } catch (err) {
      setLiveStatus(false);
      // Erreur : on garde l'intervalle courant (pas de charge supplémentaire
      // si le serveur souffre déjà).
    }
    schedulePoll(pollIntervalMs);
  }

  function init(config) {
    cfg = config;
    lastFetchClientMs = Date.now();
    currentRaceState = cfg.initialRaceState || 'live';
    watchMeasureContext();
    startClock({
      race_start_clock: cfg.initialRaceStart,
      server_now_clock: cfg.initialNowClock,
      race_state: cfg.initialRaceState || 'live',
      race_end_clock: cfg.initialRaceEndClock,
    });
    poll();
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) {
        clearTimeout(pollTimer);
      } else {
        // Retour sur l'onglet : poll immédiat + intervalle de base
        pollIntervalMs = POLL_INTERVAL_MS;
        poll();
      }
    });
  }

  return { init };
})();
