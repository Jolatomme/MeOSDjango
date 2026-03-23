"""
Tests unitaires pour verifie_moi.py et la vue verifie_moi_view.

Couvre :
  - _fmt_hms()                 : formatage de l'heure
  - generate_verifie_moi_csv() : génération du CSV (une ligne par coureur)
  - verifie_moi_view()         : vue Django (GET, POST valide, POST invalide)
"""

import pytest
from io import BytesIO
from unittest.mock import patch


# ─── Helpers XML ──────────────────────────────────────────────────────────────

def _xml(body: str, zero_time: int = 45000, name: str = 'Test') -> bytes:
    """Enveloppe un corps XML dans un document meosxml minimal.

    Note : parse_meosxml utilise findtext('Name', '') → balise <Name>.
    """
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<meosdata version="5.0">'
        f'<Name>{name}</Name><Date>2026-01-01</Date>'
        f'<ZeroTime>{zero_time}</ZeroTime>'
        f'{body}'
        f'</meosdata>'
    ).encode('utf-8')


def _club_list(*clubs):
    """clubs: (id, name)"""
    return '<ClubList>' + ''.join(
        f'<Club><Id>{cid}</Id><Name>{name}</Name></Club>'
        for cid, name in clubs
    ) + '</ClubList>'


def _class_list(*classes):
    """classes: (id, name, course_id)"""
    return '<ClassList>' + ''.join(
        f'<Class><Id>{cid}</Id><Name>{name}</Name><Course>{course}</Course></Class>'
        for cid, name, course in classes
    ) + '</ClassList>'


def _runner_list(*runners):
    """runners: (id, name, start, club_id, class_id, card_no)"""
    items = []
    for rid, name, start, club_id, class_id, card_no in runners:
        start_tag = f'<Start>{start}</Start>' if start is not None else ''
        card_tag  = f'<CardNo>{card_no}</CardNo>' if card_no else ''
        club_tag  = f'<Club>{club_id}</Club>' if club_id else ''
        class_tag = f'<Class>{class_id}</Class>' if class_id else ''
        items.append(
            f'<Runner><Id>{rid}</Id><Name>{name}</Name>'
            f'{start_tag}{card_tag}{club_tag}{class_tag}</Runner>'
        )
    return '<RunnerList>' + ''.join(items) + '</RunnerList>'


def _minimal_body(**kwargs):
    clubs   = kwargs.get('clubs',   _club_list(('10', 'COCS')))
    classes = kwargs.get('classes', _class_list(('100', 'H21E', '1')))
    runners = kwargs.get('runners', _runner_list(
        ('1', 'Alice Martin', 3600, '10', '100', '314159'),
    ))
    return clubs + classes + runners


# ─── Tests _fmt_hms ───────────────────────────────────────────────────────────

class TestFmtHms:

    def _call(self, seconds):
        from results.verifie_moi import _fmt_hms
        return _fmt_hms(seconds)

    def test_heure_simple(self):
        # ZeroTime=45000s (12:30:00) + start=3600s → 13:30:00
        assert self._call(45000 + 3600) == '13:30:00'

    def test_minuit(self):
        assert self._call(0) == '00:00:00'

    def test_format_deux_chiffres(self):
        assert self._call(9 * 3600 + 5 * 60 + 30) == '09:05:30'

    def test_passage_minuit(self):
        assert self._call(25 * 3600) == '01:00:00'

    def test_secondes(self):
        assert self._call(10 * 3600 + 2 * 60 + 45) == '10:02:45'


# ─── Tests generate_verifie_moi_csv ───────────────────────────────────────────

class TestGenerateVerifieMoiCsv:

    def _call(self, xml_bytes):
        from results.verifie_moi import generate_verifie_moi_csv
        return generate_verifie_moi_csv(xml_bytes)

    def _data_lines(self, csv_content):
        """Retourne les lignes de données (hors commentaires)."""
        return [l for l in csv_content.splitlines() if not l.startswith('//')]

    # ── Cas limites ────────────────────────────────────────────────────────────

    def test_xml_invalide_leve_valueerror(self):
        from results.verifie_moi import generate_verifie_moi_csv
        with pytest.raises(ValueError):
            generate_verifie_moi_csv(b'pas du xml')

    def test_retourne_csvresult(self):
        from results.verifie_moi import CsvResult
        result = self._call(_xml(_minimal_body()))
        assert isinstance(result, CsvResult)

    def test_aucun_coureur_csv_vide(self):
        body   = _minimal_body(runners=_runner_list())
        result = self._call(_xml(body))
        assert result.n_runners == 0
        assert self._data_lines(result.csv_content) == []

    # ── competition_name ───────────────────────────────────────────────────────

    def test_competition_name_dans_csvresult(self):
        """competition_name doit contenir le nom lu dans la balise <Name>."""
        result = self._call(_xml(_minimal_body(), name='Championnat Regional'))
        assert result.competition_name == 'Championnat Regional'

    def test_competition_name_vide_si_absent(self):
        """competition_name vaut '' si la balise <Name> est absente."""
        xml = (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<meosdata version="5.0">'
            b'<ZeroTime>32400</ZeroTime>'
            + _minimal_body().encode('utf-8') +
            b'</meosdata>'
        )
        result = self._call(xml)
        assert result.competition_name == ''

    def test_competition_name_avec_accents(self):
        """Les accents dans le nom de compétition sont conservés."""
        result = self._call(_xml(_minimal_body(), name='Épreuve régionale'))
        assert result.competition_name == 'Épreuve régionale'

    # ── Exclusion des coureurs sans heure de départ ───────────────────────────

    def test_coureur_sans_heure_exclu(self):
        """Un coureur sans heure de départ ne doit pas figurer dans le CSV."""
        body   = _minimal_body(runners=_runner_list(
            ('1', 'Alice', 3600, '10', '100', '1'),
            ('2', 'Bob',   None, '10', '100', '2'),  # pas de départ
        ))
        result = self._call(_xml(body))
        assert result.n_runners == 1
        lines = self._data_lines(result.csv_content)
        assert len(lines) == 1
        assert 'Alice' in lines[0]
        assert 'Bob' not in result.csv_content

    def test_n_skipped_compte_les_exclus(self):
        """n_skipped doit refléter le nombre de coureurs sans heure exclus."""
        body   = _minimal_body(runners=_runner_list(
            ('1', 'Alice', 3600, '10', '100', '1'),
            ('2', 'Bob',   None, '10', '100', '2'),
            ('3', 'Carol', None, '10', '100', '3'),
        ))
        result = self._call(_xml(body))
        assert result.n_skipped == 2

    def test_n_skipped_zero_si_tous_ont_heure(self):
        result = self._call(_xml(_minimal_body()))
        assert result.n_skipped == 0

    def test_tous_sans_heure_csv_vide(self):
        body   = _minimal_body(runners=_runner_list(
            ('1', 'Alice', None, '10', '100', '1'),
            ('2', 'Bob',   None, '10', '100', '2'),
        ))
        result = self._call(_xml(body))
        assert result.n_runners == 0
        assert result.n_skipped == 2
        assert self._data_lines(result.csv_content) == []

    # ── Exclusion des vacants ─────────────────────────────────────────────────

    def test_vacant_exclu(self):
        body   = _minimal_body(runners=_runner_list(
            ('1', 'Alice',  3600, '10', '100', '1'),
            ('2', 'vacant', 3720, '10', '100', ''),
            ('3', 'Vacant', 3840, '10', '100', ''),
        ))
        result = self._call(_xml(body))
        assert result.n_runners == 1

    def test_vacant_sans_heure_non_compte_dans_n_skipped(self):
        """Un vacant sans heure ne doit pas incrémenter n_skipped."""
        body   = _minimal_body(runners=_runner_list(
            ('1', 'Alice',  3600, '10', '100', '1'),
            ('2', 'vacant', None, '10', '100', ''),
        ))
        result = self._call(_xml(body))
        assert result.n_skipped == 0

    # ── Format général ────────────────────────────────────────────────────────

    def test_une_ligne_par_coureur(self):
        body   = _minimal_body(runners=_runner_list(
            ('1', 'Alice', 3600, '10', '100', '1'),
            ('2', 'Bob',   3720, '10', '100', '2'),
        ))
        result = self._call(_xml(body))
        assert len(self._data_lines(result.csv_content)) == 2

    def test_separateur_est_virgule(self):
        result = self._call(_xml(_minimal_body()))
        lines  = self._data_lines(result.csv_content)
        assert ',' in lines[0]
        assert ';' not in lines[0]

    def test_sept_colonnes_par_ligne(self):
        """Format : Nom, Club, Catégorie, Dossard, Heure, Puce, Départ → 7 colonnes."""
        result = self._call(_xml(_minimal_body()))
        cols   = self._data_lines(result.csv_content)[0].split(',')
        assert len(cols) == 7

    # ── Contenu des colonnes ──────────────────────────────────────────────────

    def test_colonne_nom(self):
        result = self._call(_xml(_minimal_body()))
        assert self._data_lines(result.csv_content)[0].startswith('Alice Martin,')

    def test_colonne_club(self):
        result = self._call(_xml(_minimal_body()))
        cols   = self._data_lines(result.csv_content)[0].split(',')
        assert cols[1] == 'COCS'

    def test_colonne_categorie(self):
        result = self._call(_xml(_minimal_body()))
        cols   = self._data_lines(result.csv_content)[0].split(',')
        assert cols[2] == 'H21E'

    def test_colonne_heure_format_hhmmss(self):
        """ZeroTime=45000 (12:30:00), start=3600 → 13:30:00."""
        result = self._call(_xml(_minimal_body(), zero_time=45000))
        cols   = self._data_lines(result.csv_content)[0].split(',')
        assert cols[4] == '13:30:00'

    def test_colonne_puce(self):
        result = self._call(_xml(_minimal_body()))
        cols   = self._data_lines(result.csv_content)[0].split(',')
        assert cols[5] == '314159'

    def test_colonne_puce_vide_si_absente(self):
        body   = _minimal_body(runners=_runner_list(
            ('1', 'Alice', 3600, '10', '100', None),
        ))
        result = self._call(_xml(body))
        cols   = self._data_lines(result.csv_content)[0].split(',')
        assert cols[5] == ''

    # ── Valeur par défaut du club ─────────────────────────────────────────────

    def test_club_inconnu_retourne_pas_de_club(self):
        """Club ID inexistant dans la liste des clubs → 'Pas de club'."""
        body   = _minimal_body(runners=_runner_list(
            ('1', 'Alice', 3600, '99', '100', '1'),
        ))
        result = self._call(_xml(body))
        cols   = self._data_lines(result.csv_content)[0].split(',')
        assert cols[1] == 'Pas de club'

    def test_coureur_sans_club_id_retourne_pas_de_club(self):
        """club_id absent (None) → 'Pas de club'."""
        body   = _minimal_body(runners=_runner_list(
            ('1', 'Alice', 3600, None, '100', '1'),
        ))
        result = self._call(_xml(body))
        cols   = self._data_lines(result.csv_content)[0].split(',')
        assert cols[1] == 'Pas de club'

    def test_club_connu_affiche_son_nom(self):
        result = self._call(_xml(_minimal_body()))
        cols   = self._data_lines(result.csv_content)[0].split(',')
        assert cols[1] == 'COCS'

    # ── Catégorie inconnue ────────────────────────────────────────────────────

    def test_categorie_inconnue_retourne_chaine_vide(self):
        body   = _minimal_body(runners=_runner_list(
            ('1', 'Alice', 3600, '10', '999', '1'),
        ))
        result = self._call(_xml(body))
        cols   = self._data_lines(result.csv_content)[0].split(',')
        assert cols[2] == ''

    # ── Tri ───────────────────────────────────────────────────────────────────

    def test_trie_par_heure_de_depart(self):
        """Bob part avant Alice → Bob en premier dans le CSV."""
        body   = _minimal_body(runners=_runner_list(
            ('1', 'Alice', 3720, '10', '100', '1'),
            ('2', 'Bob',   3600, '10', '100', '2'),
        ))
        result = self._call(_xml(body, zero_time=45000))
        lines  = self._data_lines(result.csv_content)
        assert lines[0].startswith('Bob,')
        assert lines[1].startswith('Alice,')

    # ── En-têtes commentés ────────────────────────────────────────────────────

    def test_entete_commence_par_commentaire(self):
        result = self._call(_xml(_minimal_body()))
        assert result.csv_content.startswith('//')

    def test_contient_coldefs(self):
        result = self._call(_xml(_minimal_body()))
        assert '@colDefs' in result.csv_content

    # ── Accents et virgules ───────────────────────────────────────────────────

    def test_noms_accentes_conserves(self):
        body   = _minimal_body(runners=_runner_list(
            ('1', 'Élodie Lefèvre', 3600, '10', '100', '1'),
        ))
        result = self._call(_xml(body))
        assert 'Élodie Lefèvre' in result.csv_content

    def test_nom_avec_virgule_entre_guillemets(self):
        body   = _minimal_body(runners=_runner_list(
            ('1', 'Dupont, Jean', 3600, '10', '100', '1'),
        ))
        result = self._call(_xml(body))
        assert '"Dupont, Jean"' in result.csv_content

    # ── ZeroTime ─────────────────────────────────────────────────────────────

    def test_zero_time_applique(self):
        """ZeroTime=32400 (09:00:00) + start=600 → 09:10:00."""
        body   = _minimal_body(runners=_runner_list(
            ('1', 'Alice', 600, '10', '100', '1'),
        ))
        result = self._call(_xml(body, zero_time=32400))
        cols   = self._data_lines(result.csv_content)[0].split(',')
        assert cols[4] == '09:10:00'

    # ── Statistiques ─────────────────────────────────────────────────────────

    def test_n_runners_correct(self):
        body   = _minimal_body(runners=_runner_list(
            ('1', 'Alice', 3600, '10', '100', '1'),
            ('2', 'Bob',   3720, '10', '100', '2'),
        ))
        result = self._call(_xml(body))
        assert result.n_runners == 2

    def test_n_with_card_correct(self):
        body   = _minimal_body(runners=_runner_list(
            ('1', 'Alice', 3600, '10', '100', '1'),
            ('2', 'Bob',   3720, '10', '100', None),
        ))
        result = self._call(_xml(body))
        assert result.n_with_card == 1


# ─── Tests CsvResult ──────────────────────────────────────────────────────────

class TestCsvResultProperties:

    def _make_row(self, card_no='', start_time='09:00:00'):
        from results.verifie_moi import RunnerRow
        return RunnerRow(
            name='Alice', club='COCS', cls='H21E',
            bib='', start_time=start_time, card_no=card_no, start_name='',
        )

    def _make(self, rows, n_skipped=0):
        from results.verifie_moi import CsvResult
        return CsvResult(csv_content='', rows=rows, n_skipped=n_skipped,
                         competition_name='')

    def test_n_runners(self):
        r = self._make([self._make_row(), self._make_row()])
        assert r.n_runners == 2

    def test_n_with_card(self):
        r = self._make([self._make_row('123'), self._make_row('')])
        assert r.n_with_card == 1

    def test_n_skipped(self):
        r = self._make([self._make_row()], n_skipped=3)
        assert r.n_skipped == 3


# ─── Tests verifie_moi_view ───────────────────────────────────────────────────

class TestVerifieMoiView:

    def _get(self):
        from django.test import RequestFactory
        return RequestFactory().get('/gec/verifie-moi/')

    def _post(self, xml_bytes: bytes):
        from django.test import RequestFactory
        from django.core.files.uploadedfile import InMemoryUploadedFile
        f = InMemoryUploadedFile(
            BytesIO(xml_bytes), 'meosfile', 'test.meosxml',
            'application/xml', len(xml_bytes), None,
        )
        return RequestFactory().post('/gec/verifie-moi/', {'meosfile': f})

    def _post_without_file(self):
        from django.test import RequestFactory
        return RequestFactory().post('/gec/verifie-moi/')

    @patch('results.views.render')
    def test_get_template_correct(self, mock_render):
        from results.views import verifie_moi_view
        verifie_moi_view(self._get())
        _, template, _ = mock_render.call_args[0]
        assert template == 'results/verifie_moi.html'

    @patch('results.views.render')
    def test_get_contexte_vide(self, mock_render):
        from results.views import verifie_moi_view
        verifie_moi_view(self._get())
        _, _, ctx = mock_render.call_args[0]
        assert ctx['parse_error']      is None
        assert ctx['result']           is None
        assert ctx['csv_content_json'] is None

    @patch('results.views.render')
    def test_post_valide_result_present(self, mock_render):
        from results.views import verifie_moi_view
        verifie_moi_view(self._post(_xml(_minimal_body())))
        _, _, ctx = mock_render.call_args[0]
        assert ctx['result'] is not None
        assert ctx['result'].n_runners == 1

    @patch('results.views.render')
    def test_post_valide_csv_content_json_present(self, mock_render):
        import json
        from results.views import verifie_moi_view
        verifie_moi_view(self._post(_xml(_minimal_body())))
        _, _, ctx = mock_render.call_args[0]
        content = json.loads(ctx['csv_content_json'])
        assert 'Alice Martin' in content

    @patch('results.views.render')
    def test_post_valide_filename_json_present(self, mock_render):
        """filename_json doit être du JSON valide contenant le nom de compétition."""
        import json
        from results.views import verifie_moi_view
        verifie_moi_view(self._post(_xml(_minimal_body(), name='Savoie 2026')))
        _, _, ctx = mock_render.call_args[0]
        assert ctx['filename_json'] is not None
        filename = json.loads(ctx['filename_json'])
        assert 'Savoie 2026' in filename
        assert filename.endswith('.csv')

    @patch('results.views.render')
    def test_post_valide_filename_json_fallback_si_nom_vide(self, mock_render):
        """Si le nom de compétition est vide, le nom de fichier est 'verifie_moi.csv'."""
        import json
        from results.views import verifie_moi_view
        xml = (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<meosdata version="5.0">'
            b'<ZeroTime>32400</ZeroTime>'
            + _minimal_body().encode('utf-8') +
            b'</meosdata>'
        )
        verifie_moi_view(self._post(xml))
        _, _, ctx = mock_render.call_args[0]
        filename = json.loads(ctx['filename_json'])
        assert filename == 'verifie_moi.csv'

    @patch('results.views.render')
    def test_post_coureur_sans_heure_exclu(self, mock_render):
        """La vue doit transmettre un résultat avec n_skipped > 0."""
        import json
        body = _minimal_body(runners=_runner_list(
            ('1', 'Alice', 3600, '10', '100', '1'),
            ('2', 'Bob',   None, '10', '100', '2'),
        ))
        from results.views import verifie_moi_view
        verifie_moi_view(self._post(_xml(body)))
        _, _, ctx = mock_render.call_args[0]
        assert ctx['result'].n_runners == 1
        assert ctx['result'].n_skipped == 1
        content = json.loads(ctx['csv_content_json'])
        assert 'Alice' in content
        assert 'Bob' not in content

    @patch('results.views.render')
    def test_post_xml_invalide_affiche_erreur(self, mock_render):
        from results.views import verifie_moi_view
        verifie_moi_view(self._post(b'pas du xml'))
        _, _, ctx = mock_render.call_args[0]
        assert ctx['parse_error'] is not None
        assert ctx['result'] is None

    @patch('results.views.render')
    def test_post_sans_fichier_contexte_vide(self, mock_render):
        from results.views import verifie_moi_view
        verifie_moi_view(self._post_without_file())
        _, _, ctx = mock_render.call_args[0]
        assert ctx['parse_error'] is None
        assert ctx['result'] is None


# ─── Tests URL ────────────────────────────────────────────────────────────────

class TestVerifieMoiUrl:

    def test_url_definie(self):
        from django.urls import reverse
        url = reverse('results:verifie_moi')
        assert url == '/gec/verifie-moi/'

    def test_url_dans_urlpatterns(self):
        from results.urls import urlpatterns
        names = [p.name for p in urlpatterns if hasattr(p, 'name')]
        assert 'verifie_moi' in names
