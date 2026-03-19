/**
 * test_site_js.test.js
 *
 * Tests unitaires pour COUtils (results/static/results/js/site.js).
 * Exécuter avec : npx jest test_site_js.test.js
 *
 * Dépendances : jest, jest-environment-jsdom
 *   npm install --save-dev jest jest-environment-jsdom
 *
 * Configuration jest dans package.json :
 *   { "jest": { "testEnvironment": "jsdom" } }
 */

'use strict';

// ── Charger COUtils dans l'environnement jsdom ────────────────────────────────
const fs   = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, 'site.js'), 'utf8');

// Injecte le script dans le contexte global jsdom
// (eval dans le contexte global pour que COUtils soit accessible)
beforeEach(() => {
  // Réinitialise le DOM entre chaque test
  document.body.innerHTML = '';
  document.body.dataset.medalGold   = '/static/medal-gold.svg';
  document.body.dataset.medalSilver = '/static/medal-silver.svg';
  document.body.dataset.medalBronze = '/static/medal-bronze.svg';
  // eslint-disable-next-line no-eval
  eval(src);
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

  test('fonctionne avec des caractères spéciaux dans le nom', () => {
    const html = COUtils.renderRunnerDot('#000', 'Ève O\'Brien');
    expect(html).toContain("Ève O'Brien");
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// makeNonFinisherToggle
// ─────────────────────────────────────────────────────────────────────────────
describe('COUtils.makeNonFinisherToggle', () => {
  function setupDOM() {
    document.body.innerHTML = `
      <span id="toggleLabel">Masquer abandons</span>
      <tr class="non-finisher"></tr>
      <tr class="non-finisher"></tr>
      <tr class="result-row"></tr>
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
    document.body.innerHTML = `<tr class="non-finisher"></tr>`;
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
