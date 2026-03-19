/**
 * COUtils — utilitaires JavaScript partagés pour les templates de résultats.
 * Chargé après Bootstrap dans base.html.
 *
 * Les URLs des médailles sont lues depuis les data-attributes de <body> :
 *   data-medal-gold, data-medal-silver, data-medal-bronze
 * (définis dans base.html via {% static %}).
 */
const COUtils = (() => {
  'use strict';

  // ── Médailles ──────────────────────────────────────────────────────────────

  function _medalUrls() {
    const b = document.body;
    return {
      gold:   b.dataset.medalGold   || '',
      silver: b.dataset.medalSilver || '',
      bronze: b.dataset.medalBronze || '',
    };
  }

  /**
   * Retourne le HTML d'affichage du rang (image médaille ou badge texte).
   * @param {number|null} rank
   * @returns {string} HTML string
   */
  function renderMedal(rank) {
    const { gold, silver, bronze } = _medalUrls();
    if (rank === 1) return `<img src="${gold}"   width="22" height="22" alt="1er">`;
    if (rank === 2) return `<img src="${silver}" width="22" height="22" alt="2e">`;
    if (rank === 3) return `<img src="${bronze}" width="22" height="22" alt="3e">`;
    if (rank)       return `<span class="rank-n">${rank}</span>`;
    return `<span class="text-muted">—</span>`;
  }

  // ── Dot de couleur coureur ─────────────────────────────────────────────────

  /**
   * Retourne le HTML d'un disque coloré suivi du nom du coureur.
   * @param {string} color - couleur CSS (hex, rgb…)
   * @param {string} name
   * @returns {string} HTML string
   */
  function renderRunnerDot(color, name) {
    return `<span style="display:inline-block;width:10px;height:10px;border-radius:50%;` +
           `background:${color};margin-right:5px"></span>${name}`;
  }

  // ── Toggle non-classés ────────────────────────────────────────────────────

  /**
   * Crée et retourne une fonction de bascule masquer/afficher les non-classés.
   * Les éléments ciblés doivent porter la classe CSS `.non-finisher`.
   *
   * @param {string} toggleLabelId - ID du <span> portant le libellé du bouton
   * @returns {function} toggleNonFinishers()
   */
  function makeNonFinisherToggle(toggleLabelId) {
    let hidden = false;
    return function () {
      hidden = !hidden;
      document.querySelectorAll('.non-finisher').forEach(r => {
        r.style.display = hidden ? 'none' : '';
      });
      const lbl = document.getElementById(toggleLabelId);
      if (lbl) lbl.textContent = hidden ? 'Afficher abandons' : 'Masquer abandons';
    };
  }

  // ── Recherche / filtre dans un tableau ────────────────────────────────────

  /**
   * Branche un listener de recherche sur un champ texte pour filtrer des lignes
   * de tableau. Les lignes doivent avoir `data-name` et optionnellement `data-org`.
   *
   * @param {string}      inputId     - ID du champ de saisie
   * @param {string}      rowSelector - sélecteur CSS des lignes principales
   * @param {string|null} detailClass - classe CSS des lignes de détail adjacentes
   *                                    à masquer quand la ligne parente est cachée
   */
  function bindRowSearch(inputId, rowSelector, detailClass) {
    const input = document.getElementById(inputId);
    if (!input) return;
    input.addEventListener('input', function () {
      const q = this.value.toLowerCase();
      document.querySelectorAll(rowSelector).forEach(row => {
        const match = row.dataset.name.includes(q) || (row.dataset.org || '').includes(q);
        row.style.display = match ? '' : 'none';
        if (detailClass) {
          const next = row.nextElementSibling;
          if (next && next.classList.contains(detailClass) && !match) {
            next.style.display = 'none';
          }
        }
      });
    });
  }

  // ── Toggle une ligne de détail ────────────────────────────────────────────

  /**
   * Bascule la visibilité d'une ligne de détail identifiée par son ID.
   *
   * @param {string}        id     - ID de l'élément à basculer
   * @param {Element|null}  btn    - bouton toggle (reçoit/perd la classe `.open`)
   * @param {function?}     onOpen - callback appelé à l'ouverture (après affichage)
   */
  function toggleDetailRow(id, btn, onOpen) {
    const row = document.getElementById(id);
    if (!row) return;
    const isOpen = !row.classList.contains('d-none');
    row.classList.toggle('d-none', isOpen);
    if (btn) btn.classList.toggle('open', !isOpen);
    if (!isOpen && onOpen) onOpen();
  }

  // ── Toggle toutes les lignes de détail ────────────────────────────────────

  /**
   * Crée et retourne une fonction de bascule globale ouvrir/fermer toutes
   * les lignes de détail d'une liste.
   *
   * @param {Object}    opts
   * @param {string}    opts.rowSelector - sélecteur des lignes de détail
   * @param {string}    opts.btnSelector - sélecteur des boutons toggle individuels
   * @param {string}    opts.labelId     - ID du <span> portant le libellé
   * @param {string}    opts.openText    - libellé affiché quand tout est ouvert
   * @param {string}    opts.closeText   - libellé affiché quand tout est fermé
   * @param {function?} opts.onOpen      - callback global à l'ouverture
   * @param {function?} opts.onClose     - callback global à la fermeture
   * @returns {function} toggleAll()
   */
  function makeAllToggle(opts) {
    let allOpen = false;
    return function () {
      allOpen = !allOpen;
      document.querySelectorAll(opts.rowSelector).forEach(r => r.classList.toggle('d-none', !allOpen));
      document.querySelectorAll(opts.btnSelector).forEach(b => b.classList.toggle('open', allOpen));
      const lbl = document.getElementById(opts.labelId);
      if (lbl) lbl.textContent = allOpen ? opts.openText : opts.closeText;
      if (allOpen  && opts.onOpen)  opts.onOpen();
      if (!allOpen && opts.onClose) opts.onClose();
    };
  }

  // ── Recherche simple (grille de catégories, etc.) ─────────────────────────

  /**
   * Branche un listener de recherche sur un champ texte pour filtrer des
   * éléments selon un data-attribute.
   *
   * @param {string} inputId      - ID du champ de saisie
   * @param {string} itemSelector - sélecteur CSS des éléments à filtrer
   * @param {string} dataKey      - clé du dataset à comparer (camelCase de data-xxx)
   */
  function bindSimpleSearch(inputId, itemSelector, dataKey) {
    const input = document.getElementById(inputId);
    if (!input) return;
    input.addEventListener('input', function () {
      const q = this.value.toLowerCase();
      document.querySelectorAll(itemSelector).forEach(el => {
        el.style.display = (el.dataset[dataKey] || '').includes(q) ? '' : 'none';
      });
    });
  }

  // ── Bouton retour en haut ─────────────────────────────────────────────────

  /**
   * Initialise le bouton "retour en haut de page".
   *
   * Le bouton devient visible (classe `.visible`) une fois que l'utilisateur
   * a scrollé au-delà du seuil `threshold` (pixels depuis le haut).
   * Un clic provoque un défilement fluide vers le sommet de la page.
   *
   * @param {string} btnId     - ID du bouton dans le DOM
   * @param {number} threshold - Distance de scroll (px) avant apparition (défaut : 300)
   */
  function initBackToTop(btnId, threshold) {
    threshold = (threshold === undefined || threshold === null) ? 300 : threshold;
    const btn = document.getElementById(btnId);
    if (!btn) return;

    function _update() {
      const scrolled = window.pageYOffset || document.documentElement.scrollTop;
      btn.classList.toggle('visible', scrolled > threshold);
    }

    window.addEventListener('scroll', _update, { passive: true });
    btn.addEventListener('click', function () {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });

    // Synchroniser l'état initial (utile si la page est déjà scrollée au chargement)
    _update();
  }

  // ── API publique ──────────────────────────────────────────────────────────
  return {
    renderMedal,
    renderRunnerDot,
    makeNonFinisherToggle,
    bindRowSearch,
    toggleDetailRow,
    makeAllToggle,
    bindSimpleSearch,
    initBackToTop,
  };
})();
