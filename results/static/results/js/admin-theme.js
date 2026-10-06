/* ─── Thème partagé avec le site (clé localStorage « co-theme ») ───────────────
   Le script inline de templates/admin/base_site.html applique le thème avant le
   premier rendu ; ce fichier branche les boutons de bascule de l'admin :
   - #darkModeToggle   : bouton lune/soleil du bandeau (mêmes ids que le site) ;
   - .theme-toggle     : bouton natif de Django conservé sur certaines pages
                         (changement de mot de passe), piloté par les mêmes
                         règles html[data-theme] de admin/css/dark_mode.css.
   admin/js/theme.js (clé « theme ») est retiré : un seul réglage pour tout le
   site. */
(function () {
  'use strict';

  var KEY = 'co-theme';

  function current() {
    var t = document.documentElement.getAttribute('data-theme');
    if (t === 'dark' || t === 'light') {
      return t;
    }
    try {
      t = localStorage.getItem(KEY);
      if (t === 'dark' || t === 'light') {
        return t;
      }
    } catch (e) {}
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }

  function set(theme, persist) {
    document.documentElement.setAttribute('data-theme', theme);
    if (persist) {
      try { localStorage.setItem(KEY, theme); } catch (e) {}
    }
    var icon = document.getElementById('darkModeIcon');
    if (icon) {
      icon.className = theme === 'dark' ? 'bi bi-sun-fill' : 'bi bi-moon-stars-fill';
    }
  }

  function toggle() {
    set(current() === 'dark' ? 'light' : 'dark', true);
  }

  set(current(), false);

  document.addEventListener('DOMContentLoaded', function () {
    var btn = document.getElementById('darkModeToggle');
    if (btn) {
      btn.addEventListener('click', toggle);
    }
    var natives = document.querySelectorAll('.theme-toggle');
    for (var i = 0; i < natives.length; i++) {
      natives[i].addEventListener('click', toggle);
    }
  });
})();
