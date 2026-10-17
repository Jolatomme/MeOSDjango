/**
 * test_fiche_js.test.js
 *
 * Tests unitaires pour fiche.js (fiche coureur — graphique d'évolution du rang).
 * Exécuter avec (depuis la racine du projet) : npx jest results/tests/test_fiche_js.test.js
 *   (ou npm run test:js)
 *
 * Chart.js est simulé (jest.fn) : on vérifie la configuration passée à
 * `new Chart(ctx, config)` — deux courbes (rang cumulé + rang tronçon),
 * légende, trou de courbe sur poste sans rang, masquage de la boîte.
 */

'use strict';

const fs   = require('fs');
const path = require('path');

const src = fs.readFileSync(
  path.join(__dirname, '..', 'static', 'results', 'js', 'fiche.js'),
  'utf8'
);

// ── DOM minimal : boîte du graphe + tableau de splits ────────────────────────

const BOX_ATTRS =
  'data-title="Évolution du classement" ' +
  'data-lbl-rank="Rang" ' +
  'data-lbl-abs-rank="Rang cumulé" ' +
  'data-lbl-leg-rank="Rang tronçon" ' +
  'data-lbl-abs="Cumulé" ' +
  'data-lbl-leg="Tronçon"';

function setupDom(rowsHtml) {
  document.body.innerHTML =
    `<div id="ficheRankChart" class="fiche-rank-chart" ${BOX_ATTRS}></div>` +
    '<table id="ficheSplits"><tbody>' + rowsHtml + '</tbody></table>';
}

function row(ctrl, rank, legRank, abs, leg) {
  return `<tr class="split-row" data-ctrl="${ctrl}" ` +
    `data-abs="${abs}" data-leg="${leg}"` +
    (rank    != null ? ` data-rank="${rank}"`         : '') +
    (legRank != null ? ` data-leg-rank="${legRank}"`  : '') +
    '></tr>';
}

// Deux postes + arrivée : rangs au cumulé 3/2/2, tronçons 1/3/2
const FULL_ROWS =
  row('1-101', 3, 1, '0:30', '0:30') +
  row('2-102', 2, 3, '1:02', '0:32') +
  row('Arrivée', 2, 2, '1:25', '0:23');

let charts;   // configs passées à `new Chart(ctx, config)`

beforeEach(() => {
  document.body.innerHTML = '';
  charts = [];
  // jsdom n'a pas de canvas : getContext lève/NOT IMPLEMENTED → neutralisé
  HTMLCanvasElement.prototype.getContext = () => null;
  global.Chart = jest.fn(function (ctx, config) {
    this.ctx = ctx;
    this.config = config;
    charts.push(config);
  });
});

/** Charge fiche.js (IIFE) dans le DOM courant. */
function loadFiche() {
  // eslint-disable-next-line no-eval
  eval(src);
}

// ─────────────────────────────────────────────────────────────────────────────
describe('buildRankChart — courbes', () => {
  test('deux courbes : rang cumulé (vert) et rang tronçon (bleu)', () => {
    setupDom(FULL_ROWS);
    loadFiche();
    expect(charts).toHaveLength(1);
    const ds = charts[0].data.datasets;
    expect(ds).toHaveLength(2);
    expect(ds[0].label).toBe('Rang cumulé');
    expect(ds[0].data).toEqual([3, 2, 2]);
    expect(ds[1].label).toBe('Rang tronçon');
    expect(ds[1].data).toEqual([1, 3, 2]);
    // Cumulé = vert du thème (repli '#1a6b3c'), tronçon = bleu fixe
    expect(ds[0].borderColor).toBe('#1a6b3c');
    expect(ds[1].borderColor).toBe('#4363d8');
    expect(charts[0].data.labels).toEqual(['1-101', '2-102', 'Arrivée']);
  });

  test('poste sans rang = trou dans chaque courbe (spanGaps false)', () => {
    setupDom(row('1-101', 3, 1, '0:30', '0:30') +
             row('2-102', null, null, '—', '—') +
             row('Arrivée', 2, 2, '1:25', '0:23'));
    loadFiche();
    const ds = charts[0].data.datasets;
    expect(ds[0].data).toEqual([3, null, 2]);
    expect(ds[1].data).toEqual([1, null, 2]);
    expect(ds[0].spanGaps).toBe(false);
    expect(ds[1].spanGaps).toBe(false);
  });

  test('sans rang tronçon : courbe unique, légende masquée', () => {
    setupDom(row('1-101', 3, null, '0:30', '0:30') +
             row('Arrivée', 2, null, '1:25', '0:23'));
    loadFiche();
    const cfg = charts[0];
    expect(cfg.data.datasets).toHaveLength(1);
    expect(cfg.data.datasets[0].label).toBe('Rang cumulé');
    expect(cfg.options.plugins.legend.display).toBe(false);
    // La boîte reste visible
    expect(document.getElementById('ficheRankChart').classList.contains('d-none')).toBe(false);
  });

  test('rang tronçon seul (≥ 2 points) suffit à afficher le graphe', () => {
    setupDom(row('1-101', null, 1, '0:30', '0:30') +
             row('Arrivée', null, 2, '1:25', '0:23'));
    loadFiche();
    const cfg = charts[0];
    expect(cfg.data.datasets).toHaveLength(1);
    expect(cfg.data.datasets[0].label).toBe('Rang tronçon');
    expect(cfg.data.datasets[0].data).toEqual([1, 2]);
    expect(cfg.options.plugins.legend.display).toBe(false);
  });

  test('moins de 2 points classés partout : boîte masquée, aucun graphe', () => {
    setupDom(row('1-101', 3, 1, '0:30', '0:30'));
    loadFiche();
    expect(charts).toHaveLength(0);
    expect(document.getElementById('ficheRankChart').classList.contains('d-none')).toBe(true);
  });

  test('boîte absente : sans effet, sans erreur', () => {
    document.body.innerHTML = '';
    expect(() => loadFiche()).not.toThrow();
    expect(charts).toHaveLength(0);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
describe('buildRankChart — options', () => {
  test('axe rang inversé (1er en haut) et légende visible à deux courbes', () => {
    setupDom(FULL_ROWS);
    loadFiche();
    const opt = charts[0].options;
    expect(opt.scales.y.reverse).toBe(true);
    expect(opt.scales.y.title.text).toBe('Rang');
    expect(opt.plugins.legend.display).toBe(true);
    expect(opt.interaction).toEqual({ mode: 'index', intersect: false });
  });

  test('infobulle : une ligne par courbe + cumulé/tronçon de la ligne survolée', () => {
    setupDom(FULL_ROWS);
    loadFiche();
    const cb = charts[0].options.plugins.tooltip.callbacks;
    const items = [{ dataIndex: 1 }, { dataIndex: 1 }];
    expect(cb.title(items)).toBe('2-102');
    // label reçoit le contexte du dataset courant (mock minimal)
    expect(cb.label({ dataset: { label: 'Rang cumulé' }, parsed: { y: 2 } }))
      .toBe('Rang cumulé : 2');
    expect(cb.afterBody(items)).toEqual(['Cumulé : 1:02', 'Tronçon : 0:32']);
  });

  test('afterBody sans ligne correspondante renvoie une liste vide', () => {
    setupDom(FULL_ROWS);
    loadFiche();
    const cb = charts[0].options.plugins.tooltip.callbacks;
    expect(cb.afterBody([])).toEqual([]);
  });
});
