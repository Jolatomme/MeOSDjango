/**
 * test_site_js.test.js
 *
 * Tests unitaires pour COUtils (results/static/results/js/site.js).
 * Exécuter avec (depuis la racine du projet) : npx jest results/tests/test_site_js.test.js
 *   (ou npm run test:js)
 *
 * Dépendances : jest, jest-environment-jsdom — devDependencies du package.json
 * à la racine, config « jest » (testEnvironment: "jsdom") dans le même fichier.
 *   npm install   # 1 fois (node_modules/ est gitignoré)
 */

'use strict';

// ── Charger COUtils dans l'environnement jsdom ────────────────────────────────
const fs   = require('fs');
const path = require('path');

const src = fs.readFileSync(
  path.join(__dirname, '..', 'static', 'results', 'js', 'site.js'),
  'utf8'
);

// Injecte le script dans le contexte global jsdom
// (un export explicite est ajouté : un const déclaré dans un eval strict
// n'échappe pas à la portée de l'eval — sans cela, COUtils est inaccessible
// dans les tests)
beforeEach(() => {
  // Réinitialise le DOM entre chaque test
  document.body.innerHTML = '';
  document.body.dataset.medalGold   = '/static/medal-gold.svg';
  document.body.dataset.medalSilver = '/static/medal-silver.svg';
  document.body.dataset.medalBronze = '/static/medal-bronze.svg';
  // eslint-disable-next-line no-eval
  eval(src + '\n;globalThis.COUtils = COUtils;');
});

// ─────────────────────────────────────────────────────────────────────────────
// renderMedal
// ─────────────────────────────────────────────────────────────────────────────
describe('COUtils.renderMedal', () => {
  test('rang 1 → image médaille or', () => {
    const html = COUtils.renderMedal(1);
    expect(html).toContain('medal-gold.svg');
    expect(html).toContain('<img');
    expect(html).toContain('alt="1er"');
  });

  test('rang 2 → image médaille argent', () => {
    const html = COUtils.renderMedal(2);
    expect(html).toContain('medal-silver.svg');
    expect(html).toContain('alt="2e"');
  });

  test('rang 3 → image médaille bronze', () => {
    const html = COUtils.renderMedal(3);
    expect(html).toContain('medal-bronze.svg');
    expect(html).toContain('alt="3e"');
  });

  test('rang 4+ → badge rank-n avec le numéro', () => {
    const html = COUtils.renderMedal(4);
    expect(html).toContain('class="rank-n"');
    expect(html).toContain('4');
  });

  test('rang 99 → badge rank-n avec 99', () => {
    const html = COUtils.renderMedal(99);
    expect(html).toContain('99');
  });

  test('rang null → tiret text-muted', () => {
    const html = COUtils.renderMedal(null);
    expect(html).toContain('text-muted');
    expect(html).toContain('—');
  });

  test('rang 0 → tiret text-muted (falsy)', () => {
    const html = COUtils.renderMedal(0);
    expect(html).toContain('text-muted');
  });

  test('rang undefined → tiret text-muted', () => {
    const html = COUtils.renderMedal(undefined);
    expect(html).toContain('text-muted');
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// escapeHtml / readJSONScript
// ─────────────────────────────────────────────────────────────────────────────
describe('COUtils.escapeHtml', () => {
  test('échappe les caractères HTML dangereux', () => {
    expect(COUtils.escapeHtml(`<img src=x onerror="alert('x')"> &`))
      .toBe('&lt;img src=x onerror=&quot;alert(&#39;x&#39;)&quot;&gt; &amp;');
  });

  test('null et undefined → chaîne vide', () => {
    expect(COUtils.escapeHtml(null)).toBe('');
    expect(COUtils.escapeHtml(undefined)).toBe('');
  });
});

describe('COUtils.readJSONScript', () => {
  test('lit le JSON d\'un bloc json_script', () => {
    const el = document.createElement('script');
    el.type = 'application/json';
    el.id = 'test-data';
    el.textContent = JSON.stringify({ name: '</script><img onerror=alert(1)>', n: 2 });
    document.body.appendChild(el);

    expect(COUtils.readJSONScript('test-data')).toEqual({
      name: '</script><img onerror=alert(1)>',
      n: 2,
    });
  });

  test('renvoie null si le bloc est absent', () => {
    expect(COUtils.readJSONScript('absent')).toBeNull();
  });

  test('renvoie null et journalise si le JSON est invalide', () => {
    const el = document.createElement('script');
    el.type = 'application/json';
    el.id = 'bad-data';
    el.textContent = '{not json';
    document.body.appendChild(el);
    const spy = jest.spyOn(console, 'error').mockImplementation(() => {});

    expect(COUtils.readJSONScript('bad-data')).toBeNull();
    expect(spy).toHaveBeenCalled();
    spy.mockRestore();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// renderRunnerDot
// ─────────────────────────────────────────────────────────────────────────────
describe('COUtils.renderRunnerDot', () => {
  test('contient la couleur passée', () => {
    const html = COUtils.renderRunnerDot('#e6194b', 'Alice');
    expect(html).toContain('#e6194b');
  });

  test('contient le nom du coureur', () => {
    const html = COUtils.renderRunnerDot('#e6194b', 'Alice');
    expect(html).toContain('Alice');
  });

  test('contient le span style avec border-radius:50%', () => {
    const html = COUtils.renderRunnerDot('#fff', 'Bob');
    expect(html).toContain('border-radius:50%');
  });

  test('échappe les caractères spéciaux dans le nom', () => {
    const html = COUtils.renderRunnerDot('#000', 'Ève O\'Brien');
    expect(html).toContain('Ève O&#39;Brien');
  });

  test('n\'interprète pas un nom comme du HTML', () => {
    const html = COUtils.renderRunnerDot('#000', '<img src=x onerror=alert(1)>');
    expect(html).not.toContain('<img');
    expect(html).toContain('&lt;img');
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// makeNonFinisherToggle
// ─────────────────────────────────────────────────────────────────────────────
describe('COUtils.makeNonFinisherToggle', () => {
  function setupDOM() {
    // Les <tr> ne sont conservés par le parseur HTML QUE dans une <table> :
    // placés nus dans <body>, ils sont silencieusement ignorés.
    document.body.innerHTML = `
      <span id="toggleLabel">Masquer abandons</span>
      <table><tbody>
        <tr class="non-finisher"></tr>
        <tr class="non-finisher"></tr>
        <tr class="result-row"></tr>
      </tbody></table>
    `;
  }

  test('premier appel → masque les non-finishers et change le label', () => {
    setupDOM();
    const toggle = COUtils.makeNonFinisherToggle('toggleLabel');
    toggle();
    document.querySelectorAll('.non-finisher').forEach(el => {
      expect(el.style.display).toBe('none');
    });
    expect(document.getElementById('toggleLabel').textContent).toBe('Afficher abandons');
  });

  test('deuxième appel → ré-affiche les non-finishers', () => {
    setupDOM();
    const toggle = COUtils.makeNonFinisherToggle('toggleLabel');
    toggle();
    toggle();
    document.querySelectorAll('.non-finisher').forEach(el => {
      expect(el.style.display).toBe('');
    });
    expect(document.getElementById('toggleLabel').textContent).toBe('Masquer abandons');
  });

  test('ne plante pas si le label est absent du DOM', () => {
    document.body.innerHTML = `<table><tbody><tr class="non-finisher"></tr></tbody></table>`;
    const toggle = COUtils.makeNonFinisherToggle('labelInexistant');
    expect(() => toggle()).not.toThrow();
  });

  test('ne touche pas les lignes sans la classe non-finisher', () => {
    setupDOM();
    const toggle = COUtils.makeNonFinisherToggle('toggleLabel');
    toggle();
    const normal = document.querySelector('.result-row');
    expect(normal.style.display).toBe('');
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// bindRowSearch
// ─────────────────────────────────────────────────────────────────────────────
describe('COUtils.bindRowSearch', () => {
  function setupTable() {
    document.body.innerHTML = `
      <input id="search" type="text">
      <table>
        <tr class="result-row" data-name="alice dupont" data-org="cob">
          <td>Alice</td>
        </tr>
        <tr class="splits-row" data-name="alice dupont" data-org="cob">
          <td>splits alice</td>
        </tr>
        <tr class="result-row" data-name="bob martin" data-org="asv">
          <td>Bob</td>
        </tr>
        <tr class="splits-row" data-name="bob martin" data-org="asv">
          <td>splits bob</td>
        </tr>
      </table>
    `;
  }

  function fireInput(id, value) {
    const el = document.getElementById(id);
    el.value = value;
    el.dispatchEvent(new Event('input'));
  }

  test('filtre par nom (correspondance partielle)', () => {
    setupTable();
    COUtils.bindRowSearch('search', 'tr.result-row', 'splits-row');
    fireInput('search', 'alice');
    const rows = document.querySelectorAll('tr.result-row');
    expect(rows[0].style.display).toBe('');   // alice visible
    expect(rows[1].style.display).toBe('none'); // bob caché
  });

  test('filtre par club (data-org)', () => {
    setupTable();
    COUtils.bindRowSearch('search', 'tr.result-row', 'splits-row');
    fireInput('search', 'asv');
    const rows = document.querySelectorAll('tr.result-row');
    expect(rows[0].style.display).toBe('none'); // alice caché
    expect(rows[1].style.display).toBe('');    // bob visible
  });

  test('masque la ligne de détail adjacente quand la principale est cachée', () => {
    setupTable();
    COUtils.bindRowSearch('search', 'tr.result-row:not(.splits-row)', 'splits-row');
    fireInput('search', 'alice');
    const splitRows = document.querySelectorAll('tr.splits-row');
    // La ligne de splits de bob doit être masquée
    expect(splitRows[1].style.display).toBe('none');
  });

  test('réinitialise tout quand la recherche est vidée', () => {
    setupTable();
    COUtils.bindRowSearch('search', 'tr.result-row', 'splits-row');
    fireInput('search', 'alice');
    fireInput('search', '');
    document.querySelectorAll('tr.result-row').forEach(r => {
      expect(r.style.display).toBe('');
    });
  });

  test('ne plante pas si l\'input est absent', () => {
    document.body.innerHTML = '';
    expect(() => COUtils.bindRowSearch('inexistant', 'tr', null)).not.toThrow();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// toggleDetailRow
// ─────────────────────────────────────────────────────────────────────────────
describe('COUtils.toggleDetailRow', () => {
  function setupRow(hidden = true) {
    document.body.innerHTML = `
      <div id="detail" class="${hidden ? 'd-none' : ''}"></div>
      <button id="btn"></button>
    `;
  }

  test('ouvre une ligne fermée (d-none → visible)', () => {
    setupRow(true);
    const btn = document.getElementById('btn');
    COUtils.toggleDetailRow('detail', btn);
    expect(document.getElementById('detail').classList.contains('d-none')).toBe(false);
    expect(btn.classList.contains('open')).toBe(true);
  });

  test('ferme une ligne ouverte (visible → d-none)', () => {
    setupRow(false);
    const btn = document.getElementById('btn');
    COUtils.toggleDetailRow('detail', btn);
    expect(document.getElementById('detail').classList.contains('d-none')).toBe(true);
    expect(btn.classList.contains('open')).toBe(false);
  });

  test('appelle le callback onOpen à l\'ouverture', () => {
    setupRow(true);
    const cb = jest.fn();
    COUtils.toggleDetailRow('detail', null, cb);
    expect(cb).toHaveBeenCalledTimes(1);
  });

  test('n\'appelle pas le callback onOpen à la fermeture', () => {
    setupRow(false);
    const cb = jest.fn();
    COUtils.toggleDetailRow('detail', null, cb);
    expect(cb).not.toHaveBeenCalled();
  });

  test('fonctionne sans bouton (btn = null)', () => {
    setupRow(true);
    expect(() => COUtils.toggleDetailRow('detail', null)).not.toThrow();
  });

  test('ne plante pas si l\'ID est inexistant', () => {
    document.body.innerHTML = '';
    expect(() => COUtils.toggleDetailRow('inexistant', null)).not.toThrow();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// makeAllToggle
// ─────────────────────────────────────────────────────────────────────────────
describe('COUtils.makeAllToggle', () => {
  function setupDOM() {
    document.body.innerHTML = `
      <span id="lbl">Développer</span>
      <tr class="detail-row d-none"></tr>
      <tr class="detail-row d-none"></tr>
      <button class="toggle-btn"></button>
      <button class="toggle-btn"></button>
    `;
  }

  const OPTS = {
    rowSelector: '.detail-row',
    btnSelector: '.toggle-btn',
    labelId:     'lbl',
    openText:    'Réduire',
    closeText:   'Développer',
  };

  test('premier appel → ouvre toutes les lignes', () => {
    setupDOM();
    const toggleAll = COUtils.makeAllToggle(OPTS);
    toggleAll();
    document.querySelectorAll('.detail-row').forEach(r => {
      expect(r.classList.contains('d-none')).toBe(false);
    });
  });

  test('premier appel → active tous les boutons (.open)', () => {
    setupDOM();
    const toggleAll = COUtils.makeAllToggle(OPTS);
    toggleAll();
    document.querySelectorAll('.toggle-btn').forEach(b => {
      expect(b.classList.contains('open')).toBe(true);
    });
  });

  test('premier appel → met le libellé openText', () => {
    setupDOM();
    const toggleAll = COUtils.makeAllToggle(OPTS);
    toggleAll();
    expect(document.getElementById('lbl').textContent).toBe('Réduire');
  });

  test('deuxième appel → referme tout', () => {
    setupDOM();
    const toggleAll = COUtils.makeAllToggle(OPTS);
    toggleAll();
    toggleAll();
    document.querySelectorAll('.detail-row').forEach(r => {
      expect(r.classList.contains('d-none')).toBe(true);
    });
    expect(document.getElementById('lbl').textContent).toBe('Développer');
  });

  test('appelle onOpen à l\'ouverture', () => {
    setupDOM();
    const onOpen = jest.fn();
    const toggleAll = COUtils.makeAllToggle({ ...OPTS, onOpen });
    toggleAll();
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  test('appelle onClose à la fermeture', () => {
    setupDOM();
    const onClose = jest.fn();
    const toggleAll = COUtils.makeAllToggle({ ...OPTS, onClose });
    toggleAll(); // ouvre
    toggleAll(); // ferme
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  test('n\'appelle pas onClose à l\'ouverture', () => {
    setupDOM();
    const onClose = jest.fn();
    const toggleAll = COUtils.makeAllToggle({ ...OPTS, onClose });
    toggleAll();
    expect(onClose).not.toHaveBeenCalled();
  });

  test('ne plante pas si le label est absent', () => {
    document.body.innerHTML = `
      <tr class="detail-row d-none"></tr>
      <button class="toggle-btn"></button>
    `;
    const toggleAll = COUtils.makeAllToggle({ ...OPTS, labelId: 'inexistant' });
    expect(() => toggleAll()).not.toThrow();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// bindSimpleSearch
// ─────────────────────────────────────────────────────────────────────────────
describe('COUtils.bindSimpleSearch', () => {
  function setupDOM() {
    document.body.innerHTML = `
      <input id="classSearch" type="text">
      <div class="class-item" data-name="hommes élite"></div>
      <div class="class-item" data-name="dames"></div>
      <div class="class-item" data-name="h21e"></div>
    `;
  }

  function fireInput(value) {
    const el = document.getElementById('classSearch');
    el.value = value;
    el.dispatchEvent(new Event('input'));
  }

  test('filtre les éléments selon le data-attribute', () => {
    setupDOM();
    COUtils.bindSimpleSearch('classSearch', '.class-item', 'name');
    fireInput('dame');
    const items = document.querySelectorAll('.class-item');
    expect(items[0].style.display).toBe('none');
    expect(items[1].style.display).toBe('');
    expect(items[2].style.display).toBe('none');
  });

  test('recherche insensible à la casse (via data en minuscules)', () => {
    setupDOM();
    COUtils.bindSimpleSearch('classSearch', '.class-item', 'name');
    fireInput('elite');  // data-name contient "élite", pas "elite" → aucun match
    const items = document.querySelectorAll('.class-item');
    // "hommes élite" ne contient pas "elite" → caché
    expect(items[0].style.display).toBe('none');
  });

  test('réinitialise quand la recherche est vidée', () => {
    setupDOM();
    COUtils.bindSimpleSearch('classSearch', '.class-item', 'name');
    fireInput('dames');
    fireInput('');
    document.querySelectorAll('.class-item').forEach(el => {
      expect(el.style.display).toBe('');
    });
  });

  test('ne plante pas si l\'input est absent', () => {
    document.body.innerHTML = '';
    expect(() => COUtils.bindSimpleSearch('inexistant', '.class-item', 'name')).not.toThrow();
  });

  test('ne plante pas si aucun élément ne correspond au sélecteur', () => {
    document.body.innerHTML = '<input id="classSearch" type="text">';
    COUtils.bindSimpleSearch('classSearch', '.class-item', 'name');
    const el = document.getElementById('classSearch');
    el.value = 'test';
    expect(() => el.dispatchEvent(new Event('input'))).not.toThrow();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// bindTableSort
// ─────────────────────────────────────────────────────────────────────────────
describe('COUtils.bindTableSort', () => {
  function setupTable() {
    document.body.innerHTML = `
      <table id="t">
        <thead>
          <tr>
            <th data-sort-key="cid">CID <i class="bi sort-chevron"></i></th>
            <th data-sort-key="date">Date <i class="bi sort-chevron"></i></th>
            <th>Nom</th>
          </tr>
        </thead>
        <tbody>
          <tr data-cid="10" data-date="2024-03-01"><td>10</td><td>01/03/2024</td><td>A</td></tr>
          <tr data-cid="2"  data-date="2025-07-15"><td>2</td><td>15/07/2025</td><td>B</td></tr>
          <tr data-cid="7"  data-date="2023-11-30"><td>7</td><td>30/11/2023</td><td>C</td></tr>
        </tbody>
      </table>
    `;
  }

  function rowCids() {
    return Array.from(document.querySelectorAll('#t tbody tr')).map(r => r.dataset.cid);
  }

  function chevronClasses(key) {
    const chev = document.querySelector(`th[data-sort-key="${key}"] .sort-chevron`);
    return chev.className;
  }

  test('bindTableSort est exposé dans COUtils', () => {
    expect(typeof COUtils.bindTableSort).toBe('function');
  });

  test('état initial : date desc par défaut et chevron actif', () => {
    setupTable();
    COUtils.bindTableSort('#t', 'th', { defaultKey: 'date', defaultOrder: 'desc' });
    expect(rowCids()).toEqual(['2', '10', '7']);
    expect(chevronClasses('date')).toContain('bi-chevron-down');
    expect(chevronClasses('cid')).toContain('opacity-50');
  });

  test('clic CID → tri ascendant par CID', () => {
    setupTable();
    COUtils.bindTableSort('#t', 'th', { defaultKey: 'date', defaultOrder: 'desc' });
    document.querySelector('th[data-sort-key="cid"] .sort-chevron').click();
    expect(rowCids()).toEqual(['2', '7', '10']);
    expect(chevronClasses('cid')).toContain('bi-chevron-up');
    expect(chevronClasses('date')).toContain('opacity-50');
  });

  test('second clic CID → tri descendant', () => {
    setupTable();
    COUtils.bindTableSort('#t', 'th', { defaultKey: 'date', defaultOrder: 'desc' });
    const chev = document.querySelector('th[data-sort-key="cid"] .sort-chevron');
    chev.click();
    chev.click();
    expect(rowCids()).toEqual(['10', '7', '2']);
    expect(chevronClasses('cid')).toContain('bi-chevron-down');
  });

  test('troisième clic CID → retour ascendant', () => {
    setupTable();
    COUtils.bindTableSort('#t', 'th', { defaultKey: 'date', defaultOrder: 'desc' });
    const chev = document.querySelector('th[data-sort-key="cid"] .sort-chevron');
    chev.click();
    chev.click();
    chev.click();
    expect(rowCids()).toEqual(['2', '7', '10']);
  });

  test('tri par date (valeurs ISO) — ordre chronologique', () => {
    setupTable();
    COUtils.bindTableSort('#t', 'th', { defaultKey: 'cid', defaultOrder: 'asc' });
    document.querySelector('th[data-sort-key="date"] .sort-chevron').click();
    expect(rowCids()).toEqual(['7', '10', '2']); // 2023-11-30, 2024-03-01, 2025-07-15
  });

  test('dates vides placées en fin de liste (desc et asc)', () => {
    setupTable();
    const tbody = document.querySelector('#t tbody');
    const row = document.createElement('tr');
    row.dataset.cid = '99';
    row.dataset.date = '';
    tbody.appendChild(row);

    COUtils.bindTableSort('#t', 'th', { defaultKey: 'date', defaultOrder: 'desc' });
    expect(rowCids()[3]).toBe('99');

    document.querySelector('th[data-sort-key="date"] .sort-chevron').click(); // asc
    expect(rowCids()[3]).toBe('99');
  });

  test('l\'état initial par défaut est asc si defaultKey seule', () => {
    setupTable();
    COUtils.bindTableSort('#t', 'th', { defaultKey: 'cid' });
    expect(rowCids()).toEqual(['2', '7', '10']);
  });

  test('ne plante pas si la table est absente', () => {
    document.body.innerHTML = '';
    expect(() => COUtils.bindTableSort('#inexistant', 'th')).not.toThrow();
  });

  test('ne plante pas sans en-têtes triables ni tbody', () => {
    document.body.innerHTML = '<table id="t"><thead><tr><th>Nom</th></tr></thead></table>';
    expect(() => COUtils.bindTableSort('#t', 'th')).not.toThrow();
    document.body.innerHTML = '<table id="t"><thead><tr><th data-sort-key="cid"></th></tr></thead></table>';
    expect(() => COUtils.bindTableSort('#t', 'th')).not.toThrow();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// initBackToTop
// ─────────────────────────────────────────────────────────────────────────────
describe('COUtils.initBackToTop', () => {
  // Helpers
  function setupBtn(extraClass = '') {
    document.body.innerHTML = `<button id="backToTop" ${extraClass}></button>`;
  }

  function setScrollY(value) {
    // jsdom ne gère pas le scroll natif — on surcharge pageYOffset via Object.defineProperty
    Object.defineProperty(window, 'pageYOffset', { writable: true, configurable: true, value });
    // Déclencher manuellement l'événement scroll
    window.dispatchEvent(new Event('scroll'));
  }

  // ── Existence dans l'API publique ─────────────────────────────────────────

  test('initBackToTop est exposé dans COUtils', () => {
    expect(typeof COUtils.initBackToTop).toBe('function');
  });

  // ── Comportement nominal ──────────────────────────────────────────────────

  test('ne plante pas si le bouton est absent du DOM', () => {
    document.body.innerHTML = '';
    expect(() => COUtils.initBackToTop('backToTop')).not.toThrow();
  });

  test('le bouton n\'a pas la classe visible au chargement (scroll = 0)', () => {
    setupBtn();
    setScrollY(0);
    COUtils.initBackToTop('backToTop');
    expect(document.getElementById('backToTop').classList.contains('visible')).toBe(false);
  });

  test('le bouton reçoit la classe visible quand scroll > seuil par défaut (300)', () => {
    setupBtn();
    COUtils.initBackToTop('backToTop');
    setScrollY(301);
    expect(document.getElementById('backToTop').classList.contains('visible')).toBe(true);
  });

  test('le bouton perd la classe visible quand on remonte sous le seuil', () => {
    setupBtn();
    COUtils.initBackToTop('backToTop');
    setScrollY(400);
    expect(document.getElementById('backToTop').classList.contains('visible')).toBe(true);
    setScrollY(50);
    expect(document.getElementById('backToTop').classList.contains('visible')).toBe(false);
  });

  test('exactement au seuil (300) → pas encore visible', () => {
    setupBtn();
    COUtils.initBackToTop('backToTop', 300);
    setScrollY(300);
    expect(document.getElementById('backToTop').classList.contains('visible')).toBe(false);
  });

  test('un pixel au-delà du seuil → visible', () => {
    setupBtn();
    COUtils.initBackToTop('backToTop', 300);
    setScrollY(301);
    expect(document.getElementById('backToTop').classList.contains('visible')).toBe(true);
  });

  // ── Seuil personnalisé ────────────────────────────────────────────────────

  test('seuil personnalisé — visible si scroll > seuil custom', () => {
    setupBtn();
    COUtils.initBackToTop('backToTop', 100);
    setScrollY(101);
    expect(document.getElementById('backToTop').classList.contains('visible')).toBe(true);
  });

  test('seuil personnalisé — pas visible si scroll ≤ seuil custom', () => {
    setupBtn();
    COUtils.initBackToTop('backToTop', 100);
    setScrollY(50);
    expect(document.getElementById('backToTop').classList.contains('visible')).toBe(false);
  });

  test('seuil 0 → visible dès le moindre scroll', () => {
    setupBtn();
    COUtils.initBackToTop('backToTop', 0);
    setScrollY(1);
    expect(document.getElementById('backToTop').classList.contains('visible')).toBe(true);
  });

  // ── Appel de scrollTo au clic ────────────────────────────────────────────

  test('un clic sur le bouton appelle window.scrollTo vers 0', () => {
    setupBtn();
    const scrollToMock = jest.fn();
    window.scrollTo = scrollToMock;

    COUtils.initBackToTop('backToTop');
    document.getElementById('backToTop').click();

    expect(scrollToMock).toHaveBeenCalledTimes(1);
    expect(scrollToMock).toHaveBeenCalledWith({ top: 0, behavior: 'smooth' });
  });

  test('plusieurs clics → plusieurs appels à scrollTo', () => {
    setupBtn();
    const scrollToMock = jest.fn();
    window.scrollTo = scrollToMock;

    COUtils.initBackToTop('backToTop');
    document.getElementById('backToTop').click();
    document.getElementById('backToTop').click();

    expect(scrollToMock).toHaveBeenCalledTimes(2);
  });

  // ── Synchronisation initiale ─────────────────────────────────────────────

  test('synchronisation initiale : bouton visible si la page est déjà scrollée', () => {
    setupBtn();
    // Simuler une page déjà scrollée avant l'init
    Object.defineProperty(window, 'pageYOffset', { writable: true, configurable: true, value: 500 });
    COUtils.initBackToTop('backToTop', 300);
    // Après l'init, le bouton doit déjà être visible sans attendre un scroll
    expect(document.getElementById('backToTop').classList.contains('visible')).toBe(true);
  });

  test('synchronisation initiale : bouton masqué si la page n\'est pas scrollée', () => {
    setupBtn();
    Object.defineProperty(window, 'pageYOffset', { writable: true, configurable: true, value: 0 });
    COUtils.initBackToTop('backToTop', 300);
    expect(document.getElementById('backToTop').classList.contains('visible')).toBe(false);
  });

  // ── Appels multiples ──────────────────────────────────────────────────────

  test('initialiser deux fois avec le même bouton ne provoque pas d\'erreur', () => {
    setupBtn();
    expect(() => {
      COUtils.initBackToTop('backToTop', 300);
      COUtils.initBackToTop('backToTop', 300);
    }).not.toThrow();
  });

  // ── Valeur de seuil par défaut ────────────────────────────────────────────

  test('seuil par défaut est 300 (visible à 301, pas à 300)', () => {
    setupBtn();
    COUtils.initBackToTop('backToTop');  // sans passer de seuil

    setScrollY(300);
    expect(document.getElementById('backToTop').classList.contains('visible')).toBe(false);

    setScrollY(301);
    expect(document.getElementById('backToTop').classList.contains('visible')).toBe(true);
  });

  test('seuil undefined utilise la valeur par défaut (300)', () => {
    setupBtn();
    COUtils.initBackToTop('backToTop', undefined);
    setScrollY(301);
    expect(document.getElementById('backToTop').classList.contains('visible')).toBe(true);
  });

  test('seuil null utilise la valeur par défaut (300)', () => {
    setupBtn();
    COUtils.initBackToTop('backToTop', null);
    setScrollY(301);
    expect(document.getElementById('backToTop').classList.contains('visible')).toBe(true);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// initFileInputs (champ fichier personnalisé — remplace le widget natif du
// navigateur, qui parle la langue du navigateur et non celle du site)
// ─────────────────────────────────────────────────────────────────────────────
describe('COUtils.initFileInputs', () => {
  const FORM_HTML = `
    <form id="uploadForm">
      <div class="co-file">
        <input type="file" class="co-file-input" id="meosfile"
               data-default="Aucun fichier choisi">
        <label for="meosfile">Choisir un fichier</label>
        <span class="co-file-name">Aucun fichier choisi</span>
      </div>
    </form>`;

  function mount(html) {
    document.body.innerHTML = html;
    COUtils.initFileInputs();
  }

  function selectFile(input, name) {
    Object.defineProperty(input, 'files', { value: [{ name }], configurable: true });
    input.dispatchEvent(new Event('change'));
  }

  test('au chargement, le texte par défaut est conservé', () => {
    mount(FORM_HTML);
    expect(document.querySelector('.co-file-name').textContent).toBe('Aucun fichier choisi');
    expect(document.querySelector('.co-file').classList.contains('has-file')).toBe(false);
  });

  test('change → nom du fichier + classe has-file', () => {
    mount(FORM_HTML);
    selectFile(document.getElementById('meosfile'), 'tirage.meosxml');
    expect(document.querySelector('.co-file-name').textContent).toBe('tirage.meosxml');
    expect(document.querySelector('.co-file').classList.contains('has-file')).toBe(true);
  });

  test('reset du formulaire → retour au texte par défaut', async () => {
    mount(FORM_HTML);
    const input = document.getElementById('meosfile');
    selectFile(input, 'tirage.meosxml');

    document.getElementById('uploadForm').dispatchEvent(new Event('reset'));
    // Le navigateur vide input.files lors du reset — le simulons ici,
    // la synchro étant différée (setTimeout) pour lire la valeur post-reset.
    Object.defineProperty(input, 'files', { value: [], configurable: true });
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(document.querySelector('.co-file-name').textContent).toBe('Aucun fichier choisi');
    expect(document.querySelector('.co-file').classList.contains('has-file')).toBe(false);
  });

  test('input sans wrapper .co-file ignoré sans erreur', () => {
    document.body.innerHTML = '<input type="file" class="co-file-input">';
    expect(() => COUtils.initFileInputs()).not.toThrow();
  });

  test('wrapper sans .co-file-name ignoré sans erreur', () => {
    document.body.innerHTML = '<div class="co-file"><input type="file" class="co-file-input"></div>';
    expect(() => COUtils.initFileInputs()).not.toThrow();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// favs — favoris « Suivre » partagés avec la page LIVE (clé co-live-favs,
// même format que live.js : { "<cid>": [rid, …] })
// ─────────────────────────────────────────────────────────────────────────────
describe('COUtils.favs', () => {
  beforeEach(() => { localStorage.clear(); });

  test('ids() → ensemble vide sans donnée', () => {
    expect(COUtils.favs.ids(4).size).toBe(0);
  });

  test('ids() lit la clé co-live-favs au format du live', () => {
    localStorage.setItem('co-live-favs', JSON.stringify({ '4': [12, 34] }));
    const ids = COUtils.favs.ids(4);
    expect(ids.has(12)).toBe(true);
    expect(ids.has(34)).toBe(true);
    expect(ids.size).toBe(2);
    expect(COUtils.favs.ids(5).size).toBe(0);   // autre compétition isolée
  });

  test('has() compare en numérique (rid string ou number)', () => {
    localStorage.setItem('co-live-favs', '{"4":[12]}');
    expect(COUtils.favs.has(4, 12)).toBe(true);
    expect(COUtils.favs.has('4', '12')).toBe(true);
    expect(COUtils.favs.has(4, 99)).toBe(false);
  });

  test('toggle() ajoute puis retire, en préservant les autres cids', () => {
    localStorage.setItem('co-live-favs', '{"9":[7]}');
    expect(COUtils.favs.toggle(4, 12)).toBe(true);        // suivi
    expect(COUtils.favs.has(4, 12)).toBe(true);
    const all = JSON.parse(localStorage.getItem('co-live-favs'));
    expect(all['9']).toEqual([7]);                          // intact
    expect(all['4']).toEqual([12]);
    expect(COUtils.favs.toggle(4, 12)).toBe(false);        // plus suivi
    expect(COUtils.favs.has(4, 12)).toBe(false);
    expect(JSON.parse(localStorage.getItem('co-live-favs'))['4']).toEqual([]);
  });

  test('toggle() normalise les ids en nombres', () => {
    expect(COUtils.favs.toggle(4, '12')).toBe(true);
    expect(JSON.parse(localStorage.getItem('co-live-favs'))['4']).toEqual([12]);
    expect(COUtils.favs.has(4, 12)).toBe(true);
  });

  test('JSON corrompu → comportement vide, sans lever', () => {
    localStorage.setItem('co-live-favs', '{pas du json');
    expect(COUtils.favs.ids(4).size).toBe(0);
    expect(COUtils.favs.toggle(4, 12)).toBe(true);
    expect(COUtils.favs.has(4, 12)).toBe(true);
  });
});
