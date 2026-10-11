/**
 * fiche.js — fiche coureur v2 (page /competition/<cid>/competitor/<rid>/).
 *
 * - ★ « Suivre ce coureur » : partage le même stockage que l'onglet Favoris
 *   de la page LIVE (COUtils.favs, clé localStorage « co-live-favs »).
 * - Partager : Web Share API si disponible, sinon copie du lien dans le
 *   presse-papiers (retour visuel « Lien copié »).
 * - Graphique d'évolution du rang (Chart.js, chargé par le template) :
 *   courbe interactive avec infobulle au survol (poste, rang, cumulé,
 *   tronçon), construit à partir des lignes du tableau de splits
 *   (#ficheSplits) qui portent les data-attributes rank/abs/leg/ctrl.
 *
 * Chargé par competitor_detail.html via {% block extra_js %}, après site.js.
 */
(function () {
  'use strict';

  // ── ★ Suivre / ne plus suivre ─────────────────────────────────────────────

  function initFavButton() {
    const btn = document.getElementById('ficheFavBtn');
    if (!btn || typeof COUtils === 'undefined' || !COUtils.favs) return;
    const cid = Number(btn.dataset.cid);
    const rid = Number(btn.dataset.rid);
    if (!Number.isFinite(cid) || !Number.isFinite(rid)) return;

    function paint() {
      const on = COUtils.favs.has(cid, rid);
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
      btn.classList.toggle('is-fav', on);
      const lbl = btn.querySelector('.fiche-fav-label');
      if (lbl) {
        lbl.textContent = on ? btn.dataset.labelUnfollow : btn.dataset.labelFollow;
      }
    }
    btn.addEventListener('click', function () {
      COUtils.favs.toggle(cid, rid);
      paint();
    });
    paint();
  }

  // ── Partager ──────────────────────────────────────────────────────────────

  /** Substitue brièvement le libellé du bouton (retour « Lien copié »). */
  function flashLabel(btn, msg) {
    const lbl = btn.querySelector('.fiche-share-label');
    if (!lbl || !msg || btn.dataset.flash) return;
    const prev = lbl.textContent;
    btn.dataset.flash = '1';
    lbl.textContent = msg;
    setTimeout(function () {
      lbl.textContent = prev;
      delete btn.dataset.flash;
    }, 2500);
  }

  function initShare() {
    const btn = document.getElementById('ficheShareBtn');
    if (!btn) return;
    btn.addEventListener('click', async function () {
      const url = window.location.href;
      const title = document.title;
      if (navigator.share) {
        try {
          await navigator.share({ title: title, url: url });
          return;
        } catch (e) {
          return;                    // partage annulé : on n'insiste pas
        }
      }
      try {
        await navigator.clipboard.writeText(url);
        flashLabel(btn, btn.dataset.msgCopied);
      } catch (e) {
        // Clipboard indisponible (contexte non sécurisé) : saisie manuelle.
        window.prompt('URL', url);
      }
    });
  }

  // ── Graphique d'évolution du rang (Chart.js) ──────────────────────────────

  /** Lit une variable CSS du thème courant (couleurs dynamiques sombre/clair). */
  function chartCssVar(name, fallback) {
    const v = getComputedStyle(document.body).getPropertyValue(name);
    return (v && v.trim()) || fallback;
  }

  /** Construit le graphique dans #ficheRankChart à partir des lignes de splits
   *  portant data-ctrl (une par poste + arrivée). Les postes sans rang
   *  (poste manquant) sont des trous dans la courbe (spanGaps: false) — on ne
   *  relie pas à travers un trou. Boîte masquée s'il reste moins de 2 points
   *  classés ou si Chart.js n'est pas chargé. */
  function buildRankChart() {
    const box = document.getElementById('ficheRankChart');
    if (!box) return;

    const labels = [];
    const ranks = [];
    const rows = document.querySelectorAll('#ficheSplits tbody .split-row[data-ctrl]');
    rows.forEach(function (row) {
      const rank = Number(row.dataset.rank);
      labels.push(row.dataset.ctrl || '');
      ranks.push(Number.isFinite(rank) && rank > 0 ? rank : null);
    });

    const known = ranks.filter(function (r) { return r !== null; });
    if (known.length < 2 || typeof Chart === 'undefined') {
      box.classList.add('d-none');
      return;
    }

    const canvas = document.createElement('canvas');
    box.innerHTML = '';
    box.appendChild(canvas);

    const gridColor  = chartCssVar('--co-border-soft', '#e8e8e8');
    const labelColor = chartCssVar('--co-text-muted', '#6c757d');
    const green      = chartCssVar('--co-green', '#1a6b3c');
    const tickFont   = { family: "'Barlow Condensed', sans-serif", size: 11 };
    const titleFont  = { family: "'Barlow', sans-serif", size: 12 };
    const lblRank    = box.dataset.lblRank || 'Rang';
    const lblAbs     = box.dataset.lblAbs || 'Cumulé';
    const lblLeg     = box.dataset.lblLeg || 'Tronçon';

    new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: {
        labels: labels,
        datasets: [{
          label: box.dataset.title || '',
          data: ranks,
          borderColor: green,
          backgroundColor: green,
          borderWidth: 2,
          tension: 0,
          spanGaps: false,          // rupture de courbe sur un poste sans rang
          pointRadius: 4,
          pointHoverRadius: 7,
          pointHoverBorderWidth: 2,
          pointHoverBorderColor: '#fff',
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: function (items) {
                return items.length ? labels[items[0].dataIndex] : '';
              },
              label: function (ctx) {
                const row = rows[ctx.dataIndex];
                return [
                  `${lblRank} : ${ctx.parsed.y}`,
                  `${lblAbs} : ${row ? row.dataset.abs || '—' : '—'}`,
                  `${lblLeg} : ${row ? row.dataset.leg || '—' : '—'}`,
                ];
              },
            },
          },
        },
        scales: {
          x: {
            ticks: { font: tickFont, color: labelColor, maxRotation: 55, minRotation: 0 },
            grid:  { display: false },
          },
          y: {
            reverse: true,          // 1er degré en haut
            ticks: { font: tickFont, color: labelColor, precision: 0 },
            grid:  { color: gridColor },
            title: { display: true, text: lblRank, font: titleFont, color: labelColor },
          },
        },
      },
    });
  }

  // ── Init ──────────────────────────────────────────────────────────────────

  initFavButton();
  initShare();
  buildRankChart();
})();
