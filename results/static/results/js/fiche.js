/**
 * fiche.js — fiche coureur v2 (page /competition/<cid>/competitor/<rid>/).
 *
 * - ★ « Suivre ce coureur » : partage le même stockage que l'onglet Favoris
 *   de la page LIVE (COUtils.favs, clé localStorage « co-live-favs »).
 * - Partager : Web Share API si disponible, sinon copie du lien dans le
 *   presse-papiers (retour visuel « Lien copié »).
 * - Graphique d'évolution du rang (Chart.js, chargé par le template) :
 *   courbes interactives avec infobulle au survol (poste, rangs, cumulé,
 *   tronçon), construit à partir des lignes du tableau de splits
 *   (#ficheSplits) qui portent les data-attributes rank/leg-rank/abs/leg/ctrl.
 *   Deux courbes : **rang au cumulé** (vert, data-rank) et **rang sur le
 *   tronçon** (bleu, data-leg-rank) — cette dernière n'apparaît que si elle
 *   porte au moins 2 points, la légende n'est montrée qu'à deux courbes.
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
   *  portant data-ctrl (une par poste + arrivée). Deux courbes : rang au
   *  cumulé (data-rank) et rang sur le tronçon (data-leg-rank). Les postes
   *  sans rang (poste manquant) sont des trous dans la courbe (spanGaps:
   *  false) — on ne relie pas à travers un trou. Une courbe dont il reste
   *  moins de 2 points classés est écartée ; si aucune courbe ne survit —
   *  ou si Chart.js n'est pas chargé — la boîte est masquée. */
  function buildRankChart() {
    const box = document.getElementById('ficheRankChart');
    if (!box) return;

    const labels = [];
    const ranks     = [];    // rang au cumulé (courbe verte, historique)
    const legRanks = [];    // rang sur le tronçon (courbe bleue)
    const rows = document.querySelectorAll('#ficheSplits tbody .split-row[data-ctrl]');
    rows.forEach(function (row) {
      const rank    = Number(row.dataset.rank);
      const legRank = Number(row.dataset.legRank);
      labels.push(row.dataset.ctrl || '');
      ranks.push(Number.isFinite(rank) && rank > 0 ? rank : null);
      legRanks.push(Number.isFinite(legRank) && legRank > 0 ? legRank : null);
    });

    const knownAbs  = ranks.filter(function (r) { return r !== null; });
    const knownLegs = legRanks.filter(function (r) { return r !== null; });
    if ((knownAbs.length < 2 && knownLegs.length < 2) || typeof Chart === 'undefined') {
      box.classList.add('d-none');
      return;
    }

    const canvas = document.createElement('canvas');
    box.innerHTML = '';
    box.appendChild(canvas);

    const gridColor  = chartCssVar('--co-border-soft', '#e8e8e8');
    const labelColor = chartCssVar('--co-text-muted', '#6c757d');
    const green      = chartCssVar('--co-green', '#1a6b3c');
    const blue       = '#4363d8';   // rang tronçon (même bleu que le duel « A »)
    const tickFont   = { family: "'Barlow Condensed', sans-serif", size: 11 };
    const titleFont  = { family: "'Barlow', sans-serif", size: 12 };
    const lblRank    = box.dataset.lblRank || 'Rang';
    const lblAbsRank = box.dataset.lblAbsRank || 'Rang cumulé';
    const lblLegRank = box.dataset.lblLegRank || 'Rang tronçon';
    const lblAbs     = box.dataset.lblAbs || 'Cumulé';
    const lblLeg     = box.dataset.lblLeg || 'Tronçon';

    function dataset(label, data, color) {
      return {
        label: label,
        data: data,
        borderColor: color,
        backgroundColor: color,
        borderWidth: 2,
        tension: 0,
        spanGaps: false,        // rupture de courbe sur un poste sans rang
        pointRadius: 4,
        pointHoverRadius: 7,
        pointHoverBorderWidth: 2,
        pointHoverBorderColor: '#fff',
      };
    }
    const datasets = [];
    if (knownAbs.length >= 2)  datasets.push(dataset(lblAbsRank, ranks, green));
    if (knownLegs.length >= 2) datasets.push(dataset(lblLegRank, legRanks, blue));

    new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: {
        labels: labels,
        datasets: datasets,
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: {
            display: datasets.length > 1,   // une seule courbe → pas de légende
            labels: { font: tickFont, color: labelColor, usePointStyle: true },
          },
          tooltip: {
            callbacks: {
              title: function (items) {
                return items.length ? labels[items[0].dataIndex] : '';
              },
              label: function (ctx) {
                return `${ctx.dataset.label} : ${ctx.parsed.y}`;
              },
              afterBody: function (items) {
                const row = items.length ? rows[items[0].dataIndex] : null;
                if (!row) return [];
                return [
                  `${lblAbs} : ${row.dataset.abs || '—'}`,
                  `${lblLeg} : ${row.dataset.leg || '—'}`,
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
