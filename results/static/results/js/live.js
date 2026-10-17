/**
 * live.js — Suivi en temps réel des postes radio (page Live).
 *
 * Interroge l'API JSON live (/api/.../live/) toutes les POLL_INTERVAL_MS
 * et re-rend le tableau sans recharger la page. Le tick de l'horloge de
 * course est local (1 s) entre deux polls ; l'horloge serveur fournie par
 * l'API sert de référence pour « il y a X s ».
 *
 * Les ids suivis (★, toutes catégories) sont transmis à chaque poll
 * (?fav=…) : l'API renvoie dans « fav_others » les favoris des autres
 * catégories, que l'onglet Favoris affiche avec leur propre parcours —
 * les suivis survivent donc au changement de catégorie.
 *
 * Initialisé depuis live_results.html :
 *   LiveResults.init({ apiUrl, cid, isCourse, initialRaceStart, initialNowClock })
 */
const LiveResults = (() => {
  'use strict';

  const POLL_INTERVAL_MS = 5000;
  const POLL_MAX_INTERVAL_MS = 30000;
  const DAY_TENTHS = 24 * 3600 * 10;

  // ── Réglages persistés (localStorage) ─────────────────────────────────────
  const LS_FAVS      = 'co-live-favs';      // {"<cid>": [id, …]}
  const LS_TAB       = 'co-live-tab';       // 'live' | 'favos' | 'resultats'
  const LS_REFRESH   = 'co-live-refresh';   // 'auto' | 'eco' | 'slow' | 'manual'
  const LS_ARRIVALS  = 'co-live-arrivals';  // '1' | '0'

  const REFRESH_BASE = { auto: 5000, eco: 10000, slow: 30000, manual: null };

  const GROUP_ORDER = ['en_course', 'valid_gec', 'arrives', 'en_attente', 'termine'];
  const GROUP_ICONS = {
    en_course:  'bi-person-walking',
    valid_gec:  'bi-clipboard-check',
    arrives:    'bi-flag-fill',
    en_attente: 'bi-hourglass-split',
    termine:    'bi-x-circle',
  };

  // ── Chaînes affichables (source FR) ──────────────────────────────────────
  // live_results.html injecte les traductions via
  // LiveResults.init({ strings: { … } }) — mêmes clés ; sans injection les
  // valeurs FR par défaut s'appliquent. Les marqueurs %s sont remplis par
  // fill() (les traductions ne doivent contenir ni " ni \ à cause du
  // groupement JS côté template).
  const DEFAULT_STRINGS = {
    groupLabels: {
      en_course:  'En course',
      valid_gec:  'En attente validation GEC',
      arrives:    'Arrivés',
      en_attente: 'En attente',
      termine:    'Terminé',
    },
    groupEmpty: {
      en_course:  'Aucun coureur parti pour le moment.',
      valid_gec:  'Aucun coureur en attente de validation GEC.',
      arrives:    'Aucun arrivé pour le moment.',
      en_attente: 'Aucun coureur en attente.',
      termine:    'Aucun.',
    },
    inRace: 'En course',
    negPosteSingular: 'Temps négatif au poste %s',
    negPostePlural: 'Temps négatif aux postes %s',
    negTitleFallback: 'Temps négatif : boîtier mal synchronisé ou carte SI non effacée',
    negBadge: 'Temps négatif',
    allCtrls: 'Tous les postes du parcours',
    preStartPunch: '%s — poinçon avant le départ',
    provisionalTime: 'Temps final provisoire — validation GEC en attente',
    raceTimeTitle: 'Temps de course depuis le départ',
    startHourTitle: 'Heure de départ',
    departPrefix: 'Départ %s',
    emptyRunners: "Aucun coureur — le flux MOP n'a peut-être pas encore été reçu.",
    updatedPrefix: 'Mis à jour %s',
    agoPrefix: 'il y a %s',
    inPrefix: 'dans %s',
    raceFinished: 'Course terminée',
    raceUpcoming: 'Course à venir',
    liveNow: 'En direct',
    offline: 'Hors ligne',
    favEmpty: 'Aucun favori pour cette course — touchez ★ sur un coureur pour le suivre.',
    favAriaAdd: 'Suivre ce coureur',
    favAriaRemove: 'Ne plus suivre ce coureur',
    behindTitle: 'Écart sur le leader',
    arrivalTitle: 'Arrivée de %s',
    arrivalProvisional: 'Arrivée (provisoire) de %s',
    searchLoading: 'Recherche…',
    searchHint: 'Tapez un nom de coureur ou de club.',
    searchNoResult: 'Aucun coureur ni club trouvé.',
    searchClassPrefix: 'Voir %s en live',
    searchPickHint: 'Cliquez sur un coureur pour le suivre (★) — plusieurs sélections possibles.',
    toastClose: 'Fermer',
    fmtDayHourMinSec: '%s j %s h %s min %s s',
    fmtHourMinSec: '%s h %s min %s s',
    fmtMinSec: '%s min %s s',
    fmtSec: '%s s',
  };

  /** Groupes encore sur le parcours : barre de progression, dernier poste,
   *  chrono de course et surlignage « en course ». */
  const RUNNING_GROUPS = ['en_course', 'valid_gec'];

  let cfg = null;
  let T = DEFAULT_STRINGS;
  let pollTimer = null;
  let clockTimer = null;
  let lastData = null;
  let lastFetchClientMs = 0;
  // Polling conditionnel : ETag de la dernière réponse + intervalle courant
  // (backoff ×2 jusqu'au plafond tant que rien ne change, reset à l'intervalle
  // de base dès une mise à jour).
  let lastEtag = null;
  let pollIntervalMs = POLL_INTERVAL_MS;
  let currentRaceState = 'live';

  // ── État UI (favoris, onglet, réglages) ────────────────────────────────────
  let activeTab = 'live';          // 'live' | 'favos' | 'resultats'
  let favIds = new Set();          // ids suivis pour la course courante
  let seenArrivals = null;         // Set des ids déjà notifiés (baseline 1er poll)
  let highlightRid = null;         // id à surligner (?hl= ou recherche)
  let searchIndex = null;          // index de la course (fetch paresseux)

  function lsGet(key) {
    try { return localStorage.getItem(key); } catch (e) { return null; }
  }
  function lsSet(key, value) {
    try { localStorage.setItem(key, value); } catch (e) { /* stockage indisponible */ }
  }

  function loadFavs() {
    try {
      const all = JSON.parse(lsGet(LS_FAVS) || '{}');
      favIds = new Set((all[String(cfg.cid)] || []).map(Number));
    } catch (e) {
      favIds = new Set();
    }
  }

  function saveFavs() {
    let all = {};
    try { all = JSON.parse(lsGet(LS_FAVS) || '{}'); } catch (e) { all = {}; }
    all[String(cfg.cid)] = [...favIds];
    lsSet(LS_FAVS, JSON.stringify(all));
  }

  /** ids suivis transmis au serveur (?fav=…) : l'API en déduit les favoris
   *  des AUTRES catégories (payload « fav_others ») — les suivis restent
   *  visibles dans l'onglet Favoris quel que soit l'écran catégorie affiché. */
  function favQuery() {
    if (!favIds.size) return '';
    return '?fav=' + [...favIds].slice(0, 120).join(',');
  }

  function refreshMode() {
    const v = lsGet(LS_REFRESH);
    return (v in REFRESH_BASE) ? v : 'auto';
  }

  function baseInterval() {
    const b = REFRESH_BASE[refreshMode()];
    return b == null ? POLL_INTERVAL_MS : b;
  }

  function arrivalsEnabled() {
    return lsGet(LS_ARRIVALS) !== '0';
  }

  // ── Petits utilitaires ───────────────────────────────────────────────────

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, (m) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[m]));
  }

  /** Remplit les marqueurs %s de gauche à droite (chaînes i18n). */
  function fill(tpl, ...args) {
    let i = 0;
    return String(tpl).replace(/%s/g, () => String(args[i++]));
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

  /** 1/10 s serveur « tic-tac » à la milliseconde client entre deux polls (modulo jour, legacy). */
  function tenthsNow(data) {
    const extra = (Date.now() - lastFetchClientMs) * 10 / 1000;
    return (data.server_now_clock + Math.floor(extra)) % DAY_TENTHS;
  }

  /** 1/10 s absolues depuis 00:00 du jour de la compétition (gère futur + passage minuit). */
  function absNow(data) {
    if (data.server_now_abs != null) {
      const extra = (Date.now() - lastFetchClientMs) * 10 / 1000;
      return data.server_now_abs + Math.floor(extra);
    }
    // Fallback legacy sans date : modulo jour
    return tenthsNow(data);
  }

  /** Écart (1/10 s) → 'X j Y h ...', 'X h Y min Z s', 'X min Y s' ou 'X s'. Gère jours. */
  function fmtAgo(tenths) {
    let delta = tenths;
    // Legacy modulo : si delta négatif et pas d'absolu, on wrappe à 24h
    if (delta < 0) {
      if (lastData && lastData.server_now_abs != null) {
        delta = 0;
      } else {
        delta += DAY_TENTHS;
      }
    }
    if (delta < 0) delta = 0;
    const totalSec = Math.floor(delta / 10);
    const d = Math.floor(totalSec / 86400);
    const rem = totalSec % 86400;
    const h = Math.floor(rem / 3600);
    const m = Math.floor((rem % 3600) / 60);
    const s = rem % 60;
    if (d > 0) return fill(T.fmtDayHourMinSec, d, h, m, s);
    if (h > 0) return fill(T.fmtHourMinSec, h, m, s);
    if (m > 0) return fill(T.fmtMinSec, m, s);
    return fill(T.fmtSec, s);
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
      return `<span class="badge bg-success">${esc(T.inRace)}</span>`;
    }
    return `<span class="badge bg-${esc(runner.stat_badge)}">${esc(runner.stat_label)}</span>`;
  }

  /** Badge « Temps négatif » ; le tooltip détaille les postes en cause
   *  quand l'API les fournit (neg_ctrls). */
  function negBadge(r, extraClass) {
    const ctrls = (r.neg_ctrls || []).filter(Boolean);
    const title = ctrls.length
      ? fill(ctrls.length > 1 ? T.negPostePlural : T.negPosteSingular, ctrls.join(', '))
      : T.negTitleFallback;
    return `<span class="badge neg-badge${extraClass ? ' ' + extraClass : ''}" title="${esc(title)}">${esc(T.negBadge)}</span>`;
  }

  /** Progression compacte pour la colonne de droite (compteur + mini-barre).
   *  Retourne '' quand rien n'est connu : la ligne de progression est absente
   *  plutôt que d'afficher un « — » inutile. */
  function progressCell(runner, data) {
    const total = data.n_controls || 0;
    if (runner.group === 'arrives') return `<span class="live-progress-done text-success" title="${esc(T.allCtrls)}">✓</span>`;
    // Un coureur « Terminé » (Abandon, PM…) peut avoir pointé des postes : on
    // conserve sa progression (sans quoi la barre disparaît alors qu'elle est connue).
    if (!RUNNING_GROUPS.includes(runner.group) && runner.group !== 'termine') return '';
    // Un coureur « Terminé » (Abandon, PM…) peut avoir sauté des postes puis
    // atteint le dernier : on compte les postes réellement pointés plutôt que
    // la position du poste le plus avancé (progress_pos).
    const pos = runner.group === 'termine' ? (runner.progress_count || 0) : runner.progress_pos;
    if (total === 0 || !pos) return '';
    // Barre : progression estimée fournie par le serveur (interpolation à
    // l'allure moyenne des arrivés entre deux poinçons, cf. views.py) quand
    // elle existe — sinon position par poinçon. La transition CSS fait le
    // lien glissant d'un poll à l'autre.
    const est = runner.progress_est;
    const hasEst = typeof est === 'number' && isFinite(est);
    const pct = Math.min(100, Math.max(2, Math.round(
      (hasEst ? est : pos / total) * 100)));
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
   *  Infobulle du temps cumulé : l'écart au premier de la catégorie à ce
   *  poste (payload « behind » par poinçon) — le nom du poste reste sur la
   *  vignette juste à côté ; repli sur le nom si l'écart est inconnu.
   *  Retourne '' si aucun poste à afficher. */
  function radioPunchCell(runner, data) {
    const showsPosts = RUNNING_GROUPS.includes(runner.group) || runner.group === 'arrives';
    if (!showsPosts || !runner.radio_punches || !runner.radio_punches.length) return '';
    const items = runner.radio_punches.map((p) => {
      const name = esc(ctrlName(data, p.ctrl));
      const beforeStart = p.time <= 0;
      const hasBehind = typeof p.behind === 'number' && isFinite(p.behind);
      const timeTitle = beforeStart
        ? fill(T.preStartPunch, name)
        : hasBehind
          ? `${T.behindTitle} : ${(p.behind > 0 ? '+' : '') + fmtRaceTime(p.behind)}`
          : name;
      return `<span class="live-punch">` +
        `<span class="badge bg-light text-dark border" title="${name}">${name}</span>` +
        `<span class="live-punch-time${beforeStart ? ' live-punch-prestart' : ''}" title="${esc(timeTitle)}">${fmtRaceTime(p.time)}</span>` +
        `</span>`;
    });
    if (runner.group === 'en_course' && runner.last_punch_clock) {
      const punchAbs = runner.last_punch_clock_abs != null ? runner.last_punch_clock_abs : runner.last_punch_clock;
      items.push(`<span class="live-ago" data-punch-clock="${punchAbs}"></span>`);
    }
    return items.join('');
  }

  /** Écart sur le leader (payload « behind », 1/10 s) : « +1:23 » à côté du
   *  temps. Absent pour le leader (0) et pour les groupes sans temps. */
  function behindSpan(runner) {
    const b = runner.behind;
    if (b == null || b === 0) return '';
    const label = (b > 0 ? '+' : '') + fmtRaceTime(b);
    return `<span class="live-behind" title="${esc(T.behindTitle)}">${label}</span>`;
  }

  function timeCell(runner) {
    if (runner.group === 'arrives') {
      const t = `<span class="live-time-value fw-bold">${fmtRaceTime(runner.rt)}</span>${behindSpan(runner)}`;
      if (runner.neg_time) {
        return `${t} ${negBadge(runner, 'ms-1')}`;
      }
      return t;
    }
    if (runner.group === 'valid_gec' && runner.st > 0 && (runner.provisional_rt != null || runner.last_time)) {
      // Poinçon d'arrivée radio (ou résultat préliminaire) : temps final
      // provisoire affiché, en attendant la validation GEC.
      const t = runner.provisional_rt != null ? runner.provisional_rt : runner.last_time;
      const prov = runner.provisional_rt != null ? behindSpan(runner) : '';
      return `<span class="live-time-value fw-bold" title="${esc(T.provisionalTime)}">${fmtRaceTime(t)}</span>${prov}`;
    }
    if (RUNNING_GROUPS.includes(runner.group) && runner.st > 0) {
      const stAbs = runner.st_abs != null ? runner.st_abs : runner.st;
      return `<span class="live-time live-time-value fw-bold" data-st="${stAbs}" title="${esc(T.raceTimeTitle)}">—</span>`;
    }
    if (runner.group === 'en_attente' && runner.st > 0) {
      const stAbs = runner.st_abs != null ? runner.st_abs : runner.st;
      return `<span class="text-muted small" title="${esc(T.startHourTitle)}">${esc(fill(T.departPrefix, fmtClock(runner.st)))}</span>
              <span class="live-countdown small text-muted ms-1" data-st="${stAbs}"></span>`;
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
   *  classement | ★ + nom (club) + couples poste/temps | temps + progression. */
  function runnerRow(r, data) {
    // Favori d'une autre catégorie (_ctx) : postes/progression de SON parcours
    const ctx = r._ctx || data;
    const punches = radioPunchCell(r, ctx);
    const progress = progressCell(r, ctx);
    const fav = favIds.has(r.id);
    return `<tr class="live-runner${RUNNING_GROUPS.includes(r.group) ? ' live-running' : ''}${fav ? ' live-fav-row' : ''}"
                data-rid="${r.id}">
      <td class="live-cell-rank">${rankCell(r)}</td>
      <td class="live-cell-main">
        <div class="live-runner-line runner-name">
          <button type="button" class="live-fav${fav ? ' is-fav' : ''}"
                  data-fav-id="${r.id}" aria-pressed="${fav}"
                  title="${esc(fav ? T.favAriaRemove : T.favAriaAdd)}"
                  aria-label="${esc(fav ? T.favAriaRemove : T.favAriaAdd)}">★</button>
          <a href="/competition/${cfg.cid}/competitor/${r.id}/">${r.flag ? `<img class="nat-flag" src="${esc(r.flag)}" alt="" loading="lazy" width="20" height="14">` : ''}${esc(r.name)}</a>
          ${r.org ? `<span class="club-name">(${esc(r.org)})</span>` : ''}
          ${r.class_name && (cfg.isCourse || r._ctx) ? `<span class="badge bg-light text-dark border club-class">${esc(r.class_name)}</span>` : ''}
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

  /** Les runners visibles dépendent de l'onglet actif :
   *  - live      : tout (groupes dans l'ordre usuel)
   *  - favos     : uniquement les ★ suivis
   *  - resultats : arrivés classés, puis « Terminé » sans classement.
   *  Dans chaque cas, les favoris remontent en tête (comme « Mes coureurs »
   *  d'OrientLive) — stable partition, l'ordre d'origine est préservé au sein
   *  de chaque bloc (render() re-groupe ensuite par groupe live). */
  function favToTop(list) {
    const favs = list.filter((r) => favIds.has(r.id));
    if (!favs.length) return list;
    return favs.concat(list.filter((r) => !favIds.has(r.id)));
  }

  /** Favoris appartenant à d'autres catégories que l'affichée : extraits
   *  « fav_others » du payload (déjà filtrés serveur — refiltrés ici, car
   *  lastData peut dater d'un retrait de ★). Chaque coureur reçoit
   *  ``_ctx`` (les postes + effectif de SA catégorie) pour les cellules. */
  function favOthers(data) {
    const out = [];
    for (const entry of (data && data.fav_others) || []) {
      for (const r of entry.runners) {
        if (favIds.has(r.id)) {
          r._ctx = entry;
          out.push(r);
        }
      }
    }
    return out;
  }

  function visibleRunners(data) {
    if (activeTab === 'favos') {
      return data.runners.filter((r) => favIds.has(r.id)).concat(favOthers(data));
    }
    if (activeTab === 'resultats') {
      return favToTop(data.runners.filter((r) => r.group === 'arrives' || r.group === 'termine'));
    }
    return favToTop(data.runners);
  }

  function render(data) {
    lastData = data;
    const body = document.getElementById('liveBody');
    if (!body) return;

    const counts = { en_course: 0, valid_gec: 0, arrives: 0, en_attente: 0, termine: 0 };
    for (const r of data.runners) counts[r.group] = (counts[r.group] || 0) + 1;

    const shown = visibleRunners(data);
    const html = [];
    if (!shown.length) {
      // État vide selon l'onglet (les coureurs peuvent exister mais être masqués)
      let emptyMsg = T.emptyRunners;
      if (activeTab === 'favos') emptyMsg = T.favEmpty;
      else if (data.runners.length) emptyMsg = T.groupEmpty[activeTab === 'resultats' ? 'arrives' : 'en_course'];
      html.push(`<tr><td class="text-center text-muted p-4">
        <i class="bi bi-inbox me-2"></i>${esc(emptyMsg)}
      </td></tr>`);
    } else {
      const groups = activeTab === 'resultats' ? ['arrives', 'termine'] : GROUP_ORDER;
      for (const group of groups) {
        const rows = shown.filter((r) => r.group === group);
        if (activeTab === 'favos' && !rows.length) continue;   // pas d'en-tête vide
        html.push(`<tr class="live-group-row"><td>
            <i class="bi ${GROUP_ICONS[group]} me-2"></i>${T.groupLabels[group]}
            <span class="badge bg-light text-dark ms-2">${rows.length}</span>
          </td></tr>`);
        if (!rows.length) {
          html.push(`<tr><td class="text-muted small p-2 ps-4">${T.groupEmpty[group]}</td></tr>`);
          continue;
        }
        for (const r of rows) html.push(runnerRow(r, data));
      }
    }

    body.innerHTML = html.join('');
    syncPunchWidths();
    applyHighlight();
    setText('liveCountEnCourse', counts.en_course);
    setText('liveCountValidGec', counts.valid_gec);
    setText('liveCountArrives', counts.arrives);
    setText('liveCountWaiting', counts.en_attente);
    setText('liveCountDone', counts.termine);
    setText('tabCountLive', data.runners.length);
    setText('tabCountFav', data.runners.filter((r) => favIds.has(r.id)).length
      + favOthers(data).length);
    setText('tabCountRes', counts.arrives + counts.termine);
    // Badge compact : seule l'heure (le préfixe « Mis à jour » vit dans le
    // title — le bandeau vert doit tenir sur une ligne au format desktop).
    const updClock = fmtClock(data.server_now_clock);
    setText('liveLastUpdate', updClock);
    const updEl = document.getElementById('liveLastUpdate');
    if (updEl) updEl.title = fill(T.updatedPrefix, updClock);
  }

  /** Surligne la ligne highlightRid (recherche ?hl= ou sélection) et la fait
   *  défiler dans le champ de vision. Un favori d'une autre catégorie n'existe
   *  que dans l'onglet Favoris : on y bascule d'abord (garanti de boucle : si
   *  l'onglet est déjà Favoris et que la ligne manque, on abandonne). */
  function applyHighlight() {
    if (highlightRid == null) return;
    const row = document.querySelector(`#liveBody tr[data-rid="${highlightRid}"]`);
    if (!row) {
      if (activeTab !== 'favos' && lastData
          && favOthers(lastData).some((r) => r.id === highlightRid)) {
        switchToRowIfHidden(highlightRid);
      }
      return;
    }
    row.classList.add('live-hl');
    row.scrollIntoView({ block: 'center', behavior: 'smooth' });
    setTimeout(() => row.classList.remove('live-hl'), 4000);
    highlightRid = null;
  }

  function raceElapsed(data) {
    // Préfère les horloges absolues si disponibles (gère futur + minuit)
    if (data.server_now_abs != null && data.race_start_abs != null) {
      return data.server_now_abs - data.race_start_abs;
    }
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
      let delta;
      if (data.race_end_abs != null && data.race_start_abs != null) {
        delta = data.race_end_abs - data.race_start_abs;
      } else {
        const end = data.race_end_clock != null ? data.race_end_clock : data.server_now_clock;
        delta = end - data.race_start_clock;
        if (delta < 0) delta += DAY_TENTHS;
      }
      el.textContent = fmtClock(delta);
      return;
    }
    const base = raceElapsed(data);
    if (base == null) { el.textContent = '--:--:--'; return; }
    if (base < 0) { el.textContent = '--:--:--'; return; }
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
   *  et compte à rebours des coureurs en attente. Gère les horloges absolues. */
  function updateTickers(data) {
    updateFreshness();
    if (!data) return;
    const useAbs = data.server_now_abs != null;
    const now = useAbs ? absNow(data) : tenthsNow(data);
    for (const span of document.querySelectorAll('.live-ago')) {
      const punch = Number(span.dataset.punchClock);
      if (isNaN(punch)) continue;
      let delta;
      if (useAbs) {
        delta = now - punch;
      } else {
        delta = now - punch;
        if (delta < 0) delta += DAY_TENTHS;
      }
      if (delta < 0) delta = 0;
      span.textContent = `· ${fill(T.agoPrefix, fmtAgo(delta))}`;
    }
    for (const span of document.querySelectorAll('.live-time')) {
      const st = Number(span.dataset.st);
      if (isNaN(st) || st <= 0) continue;
      let delta;
      if (useAbs) {
        delta = now - st;
      } else {
        delta = now - st;
        if (delta < 0) delta += DAY_TENTHS;
      }
      if (delta < 0) delta = 0;
      span.textContent = fmtRaceTime(delta);
    }
    // « En attente » : compte à rebours avant le départ (affiche jours si >24h).
    for (const span of document.querySelectorAll('.live-countdown')) {
      const st = Number(span.dataset.st);
      if (isNaN(st) || st <= 0) continue;
      let delta;
      if (useAbs) {
        delta = st - now;
      } else {
        delta = st - now;
        if (delta < 0) delta += DAY_TENTHS;
      }
      span.textContent = delta > 0 ? `· ${fill(T.inPrefix, fmtAgo(delta))}` : '';
    }
  }

  function setRaceState(state) {
    currentRaceState = state;
    const badge = document.getElementById('liveStatusBadge');
    if (!badge) return;
    if (state === 'finished') {
      badge.className = 'badge bg-secondary fs-6';
      badge.innerHTML = T.raceFinished;
    } else if (state === 'upcoming') {
      badge.className = 'badge bg-info fs-6';
      badge.innerHTML = T.raceUpcoming;
    } else {
      badge.className = 'badge bg-success fs-6';
      badge.innerHTML = `<span class="live-dot"></span>${T.liveNow}`;
    }
  }

  function setLiveStatus(ok) {
    if (currentRaceState === 'finished' || currentRaceState === 'upcoming') return;
    const badge = document.getElementById('liveStatusBadge');
    if (!badge) return;
    badge.className = ok ? 'badge bg-success fs-6' : 'badge bg-danger fs-6';
    badge.innerHTML = `<span class="live-dot"></span>${ok ? T.liveNow : T.offline}`;
  }

  function schedulePoll(ms) {
    clearTimeout(pollTimer);
    pollTimer = setTimeout(poll, ms);
  }

  // ── Fraîcheur des données + attente du prochain poll ────────────────────────

  /** Pastille de fraîcheur à côté de l'horloge du bandeau : verte < 20 s
   *  depuis le dernier fetch réussi, orange < 60 s, rouge au-delà (onglet
   *  mis en arrière-plan ou serveur injoignable — le badge « Hors ligne »
   *  signale l'échec du poll lui-même). */
  function updateFreshness() {
    const dot = document.getElementById('liveFreshDot');
    if (!dot || !lastFetchClientMs) return;
    const ageMs = Date.now() - lastFetchClientMs;
    const state = ageMs > 60000 ? 'fresh-old' : (ageMs > 20000 ? 'fresh-stale' : 'fresh-ok');
    if (dot.dataset.fresh !== state) {
      dot.dataset.fresh = state;
      dot.title = fill(T.agoPrefix, fmtAgo(Math.round(ageMs / 100)));
    }
  }

  /** Fine ligne sous le bandeau : compte à rebours visuel du prochain poll
   *  (redémarrée à chaque planification ; mascée en mode manuel). */
  function startCountdown(ms) {
    const line = document.getElementById('liveRefreshLine');
    const bar = document.getElementById('liveRefreshBar');
    if (!line || !bar) return;
    if (ms > POLL_MAX_INTERVAL_MS) { line.classList.add('d-none'); return; }
    line.classList.remove('d-none');
    bar.style.transition = 'none';
    bar.style.width = '100%';
    void bar.offsetWidth;                       // reflow : redémarre l'animation
    bar.style.transition = `width ${ms}ms linear`;
    bar.style.width = '0%';
  }

  function hideCountdown() {
    const line = document.getElementById('liveRefreshLine');
    if (line) line.classList.add('d-none');
  }

  // ── Popups d'arrivée ───────────────────────────────────────────────────────

  /** Détecte les nouvelles arrivées entre deux payloads et affiche un
   *  bandeau. Le premier poll pose la baseline (pas de popup au chargement :
   *  seules les arrivées survenues pendant la session sont notifiées). */
  function notifyArrivals(data) {
    const arrived = data.runners.filter(
      (r) => r.group === 'arrives' || (r.group === 'valid_gec' && r.provisional_rt != null));
    if (seenArrivals === null) {
      seenArrivals = new Set(arrived.map((r) => r.id));
      return;
    }
    for (const r of arrived) {
      if (seenArrivals.has(r.id)) continue;
      seenArrivals.add(r.id);
      if (arrivalsEnabled()) showArrivalToast(r);
    }
  }

  function showArrivalToast(r) {
    const box = document.getElementById('liveToasts');
    if (!box) return;
    const provisional = r.group !== 'arrives';
    const title = fill(
      provisional ? T.arrivalProvisional : T.arrivalTitle, r.name);
    const time = fmtRaceTime(provisional ? r.provisional_rt : r.rt);
    const rank = r.rank != null ? ` <span class="badge bg-success-subtle text-success">#${r.rank}</span>` : '';
    const el = document.createElement('div');
    el.className = 'live-toast';
    el.setAttribute('role', 'status');
    el.innerHTML = `<i class="bi bi-flag-fill"></i>
      <span class="live-toast-body">
        <strong>${esc(title)}</strong>
        <span class="live-toast-meta">${esc(time)}${rank}${cfg.isCourse && r.class_name ? ` · ${esc(r.class_name)}` : ''}</span>
      </span>
      <button type="button" class="live-toast-close" aria-label="${esc(T.toastClose)}">&times;</button>`;
    el.addEventListener('click', (e) => {
      if (e.target.closest('.live-toast-close')) { el.remove(); return; }
      switchToRowIfHidden(r.id);
      highlightRid = r.id;
      applyHighlight();
      el.remove();
    });
    box.appendChild(el);
    // Max 4 bandeaux empilés : le plus ancien tombe.
    while (box.children.length > 4) box.firstChild.remove();
    setTimeout(() => el.remove(), 8000);
  }

  // ── Polling ─────────────────────────────────────────────────────────────────

  async function poll() {
    try {
      const headers = { 'Accept': 'application/json' };
      if (lastEtag) headers['If-None-Match'] = lastEtag;
      const resp = await fetch(cfg.apiUrl + favQuery(), { headers });
      if (resp.status === 304) {
        // Rien de nouveau depuis le dernier poll : on ralentit progressivement
        setLiveStatus(true);
        pollIntervalMs = Math.min(pollIntervalMs * 2, POLL_MAX_INTERVAL_MS);
        scheduleNext();
        return;
      }
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      if (!data.success) throw new Error(data.error || 'erreur API');
      lastEtag = resp.headers.get('ETag');
      lastFetchClientMs = Date.now();
      render(data);
      notifyArrivals(data);
      startClock(data);
      setRaceState(data.race_state);
      setLiveStatus(true);
      pollIntervalMs = baseInterval();
    } catch (err) {
      setLiveStatus(false);
      // Erreur : on garde l'intervalle courant (pas de charge supplémentaire
      // si le serveur souffre déjà).
    }
    scheduleNext();
  }

  /** Planifie le poll suivant selon le mode d'actualisation (manuel = ↻ seul). */
  function scheduleNext() {
    if (refreshMode() === 'manual') { hideCountdown(); return; }
    schedulePoll(pollIntervalMs);
    startCountdown(pollIntervalMs);
  }

  /** Change de mode d'actualisation (déclenché depuis la modale Réglages). */
  function setRefreshMode(mode) {
    lsSet(LS_REFRESH, mode);
    clearTimeout(pollTimer);
    pollIntervalMs = baseInterval();
    updateRefreshHint();
    if (mode !== 'manual') poll(); else hideCountdown();
  }

  // ── UI : onglets, favoris, réglages, recherche ──────────────────────────────

  /** Onglets LIVE / FAVORIS / RÉSULTATS (état persisté par course). */
  function initTabs() {
    const stored = lsGet(LS_TAB);
    if (['live', 'favos', 'resultats'].includes(stored)) activeTab = stored;
    for (const btn of document.querySelectorAll('#liveTabs [data-live-tab]')) {
      btn.classList.toggle('active', btn.dataset.liveTab === activeTab);
      btn.addEventListener('click', () => {
        activeTab = btn.dataset.liveTab;
        lsSet(LS_TAB, activeTab);
        for (const b of document.querySelectorAll('#liveTabs [data-live-tab]')) {
          b.classList.toggle('active', b === btn);
        }
        if (lastData) render(lastData);
      });
    }
  }

  /** Bascule le ★ d'un coureur (lignes du tableau + résultats de la
   *  recherche) : sauvegarde, re-rendu immédiat, puis poll pour que le suivi
   *  rejoigne/quitte « fav_others » sans attendre l'intervalle courant. */
  function toggleFav(id) {
    if (favIds.has(id)) favIds.delete(id); else favIds.add(id);
    saveFavs();
    if (lastData) render(lastData);
    clearTimeout(pollTimer);
    poll();
  }

  /** ★ favoris : délégation sur le tbody (recréé à chaque render). */
  function initFavs() {
    const body = document.getElementById('liveBody');
    if (!body) return;
    body.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-fav-id]');
      if (!btn) return;
      e.preventDefault();
      toggleFav(Number(btn.dataset.favId));
    });
  }

  /** Modale Réglages : radios d'actualisation + popup d'arrivée. */
  function initSettings() {
    const mode = refreshMode();
    const radio = document.getElementById(`liveRefresh${mode.charAt(0).toUpperCase()}${mode.slice(1)}`);
    if (radio) radio.checked = true;
    for (const r of document.querySelectorAll('input[name="liveRefresh"]')) {
      r.addEventListener('change', () => { if (r.checked) setRefreshMode(r.value); });
    }
    const arrivals = document.getElementById('liveArrivalsToggle');
    if (arrivals) {
      arrivals.checked = arrivalsEnabled();
      arrivals.addEventListener('change', () => {
        lsSet(LS_ARRIVALS, arrivals.checked ? '1' : '0');
      });
    }
    const refreshBtn = document.getElementById('liveRefreshBtn');
    if (refreshBtn) refreshBtn.addEventListener('click', () => {
      refreshBtn.classList.add('is-spinning');
      setTimeout(() => refreshBtn.classList.remove('is-spinning'), 650);
      poll();
    });
    updateRefreshHint();
  }

  /** En mode manuel, rappel visible à côté de la dernière mise à jour. */
  function updateRefreshHint() {
    const hint = document.getElementById('liveRefreshHint');
    if (hint) hint.classList.toggle('d-none', refreshMode() !== 'manual');
  }

  /** Modale Recherche : index de la course (fetch paresseux) + filtre local. */
  function initSearch() {
    const input = document.getElementById('liveSearchInput');
    const results = document.getElementById('liveSearchResults');
    if (!input || !results) return;

    function normalize(s) {
      return String(s).toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
    }

    function renderResults() {
      const q = normalize(input.value.trim());
      if (!searchIndex) { results.innerHTML = `<div class="list-group-item text-muted small text-center border-0">${esc(T.searchLoading)}</div>`; return; }
      if (!q) {
        results.innerHTML = `<div class="list-group-item text-muted small text-center border-0">${esc(T.searchHint)}</div>`;
        return;
      }
      const hits = searchIndex.filter((r) => normalize(r.name).includes(q) || normalize(r.org).includes(q)).slice(0, 30);
      if (!hits.length) {
        results.innerHTML = `<div class="list-group-item text-muted small text-center border-0">${esc(T.searchNoResult)}</div>`;
        return;
      }
      // Chaque ligne se clique pour suivre (★) — la modale reste ouverte :
      // on peut alors sélectionner plusieurs coureurs, p. ex. tout un club.
      // Le badge de catégorie est le lien de saut (« Voir … en live »).
      results.innerHTML = hits.map((r) => {
        const fav = favIds.has(r.id);
        return `
        <div class="list-group-item list-group-item-action search-hit${fav ? ' is-fav' : ''}"
             data-rid="${r.id}" data-cls="${esc(r.cls)}">
          <button type="button" class="search-fav${fav ? ' is-fav' : ''}"
                  aria-pressed="${fav}"
                  title="${esc(fav ? T.favAriaRemove : T.favAriaAdd)}"
                  aria-label="${esc(fav ? T.favAriaRemove : T.favAriaAdd)}">★</button>
          <span class="search-hit-name">
            ${r.flag ? `<img class="nat-flag" src="${esc(r.flag)}" alt="" loading="lazy" width="20" height="14">` : ''}<span class="fw-semibold">${esc(r.name)}</span>
            ${r.org ? `<span class="text-muted small ms-1">${esc(r.org)}</span>` : ''}
          </span>
          <a class="search-jump" href="${esc(cfg.classLiveTpl.replace('__CLS__', encodeURIComponent(r.cls)) + `?hl=${r.id}`)}"
             title="${esc(fill(T.searchClassPrefix, r.cls))}">
            <span class="badge bg-light text-dark border">${esc(r.cls)}</span>
          </a>
        </div>`;
      }).join('') +
        `<div class="list-group-item search-pick-hint text-muted small text-center border-0">${esc(T.searchPickHint)}</div>`;
    }

    input.addEventListener('input', renderResults);

    // Chargement paresseux de l'index à la première ouverture de la modale
    const modal = document.getElementById('liveSearchModal');
    if (modal) {
      modal.addEventListener('show.bs.modal', () => {
        renderResults();               // état ★ à jour (bascules hors modale)
        if (searchIndex) return;
        fetch(cfg.searchApiUrl, { headers: { 'Accept': 'application/json' } })
          .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
          .then((d) => { searchIndex = d.runners || []; renderResults(); })
          .catch(() => { searchIndex = []; renderResults(); });
      });
    }

    // Clic sur un résultat :
    //  - badge de catégorie (.search-jump) → ancien comportement de saut
    //    (course actuelle : onglet + surlignage ; autre : page live de la
    //    catégorie avec ?hl=) ;
    //  - ailleurs dans la ligne → ★ favori (la modale reste ouverte pour
    //    sélectionner plusieurs coureurs, p. ex. tout un club).
    results.addEventListener('click', (e) => {
      const jump = e.target.closest('.search-jump');
      const hit = e.target.closest('.search-hit');
      if (!hit) return;
      const rid = Number(hit.dataset.rid);
      if (jump) {
        e.preventDefault();
        const cls = hit.dataset.cls;
        const modalEl = document.getElementById('liveSearchModal');
        if (modalEl) bootstrap.Modal.getOrCreateInstance(modalEl).hide();
        const inPage = lastData && (
          lastData.runners.some((r) => r.id === rid)
          || favOthers(lastData).some((r) => r.id === rid));
        if (inPage) {
          switchToRowIfHidden(rid);
          highlightRid = rid;
          applyHighlight();
        } else if (cls) {
          window.location.href = cfg.classLiveTpl.replace('__CLS__', encodeURIComponent(cls)) + `?hl=${rid}`;
        }
        return;
      }
      toggleFav(rid);
      renderResults();                 // repeindre ★ et ligne sélectionnée
    });
  }

  /** La ligne peut être masquée par l'onglet actif : bascule sur l'onglet où
   *  elle existe — Live pour un coureur de la catégorie affichée, Favoris
   *  pour un favori d'une autre catégorie (absent du payload courant) —
   *  puis re-rend si elle n'était pas dans le DOM. */
  function switchToRowIfHidden(rid) {
    if (document.querySelector(`#liveBody tr[data-rid="${rid}"]`)) return;
    const extra = lastData ? favOthers(lastData).some((r) => r.id === rid) : false;
    const tab = extra ? 'favos' : 'live';
    activeTab = tab;
    lsSet(LS_TAB, tab);
    for (const b of document.querySelectorAll('#liveTabs [data-live-tab]')) {
      b.classList.toggle('active', b.dataset.liveTab === tab);
    }
    if (lastData) render(lastData);
  }

  function init(config) {
    cfg = config;
    T = {
      ...DEFAULT_STRINGS,
      ...(config.strings || {}),
      groupLabels: { ...DEFAULT_STRINGS.groupLabels, ...((config.strings || {}).groupLabels || {}) },
      groupEmpty: { ...DEFAULT_STRINGS.groupEmpty, ...((config.strings || {}).groupEmpty || {}) },
    };
    lastFetchClientMs = Date.now();
    currentRaceState = cfg.initialRaceState || 'live';
    loadFavs();
    // Surlignage demandé par la recherche (?hl=<id>) : mémorisé avant le
    // premier render, appliqué dès qu'il apparaît dans le tableau. L'onglet
    // est forcé sur Live (l'onglet Favoris/Résultats pourrait masquer la ligne).
    const hl = new URLSearchParams(window.location.search).get('hl');
    if (hl) {
      highlightRid = Number(hl);
      activeTab = 'live';
      lsSet(LS_TAB, 'live');
    }
    watchMeasureContext();
    initTabs();
    initFavs();
    initSettings();
    initSearch();
    startClock({
      race_start_clock: cfg.initialRaceStart,
      race_start_abs: cfg.initialRaceStartAbs,
      server_now_clock: cfg.initialNowClock,
      server_now_abs: cfg.initialNowAbs,
      race_state: cfg.initialRaceState || 'live',
      race_end_clock: cfg.initialRaceEndClock,
      race_end_abs: cfg.initialRaceEndAbs,
      competition_date: cfg.competitionDate,
    });
    poll();
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) {
        clearTimeout(pollTimer);
        hideCountdown();
      } else if (refreshMode() !== 'manual') {
        // Retour sur l'onglet : poll immédiat + intervalle de base
        pollIntervalMs = baseInterval();
        poll();
      }
    });
  }

  return { init };
})();
