"""
Tests pour les vues de ochecklist (DB entièrement mockée).

Couvre :
  - ochecklist_update : auth header, Content-Digest, gzip, YAML valide,
    YAML invalide, structure invalide, event manquant, mise à jour d'un
    rapport existant, gestion des ChangeLogs
  - report_list
  - clear_reports : GET/POST sans/avec IDs
  - report_detail : tri, compteurs, 404
  - runner_detail : 200, 404
"""

import base64
import datetime
import gzip
import hashlib
from unittest.mock import patch, MagicMock

import pytest
import yaml
from django.test import RequestFactory
from django.http import Http404, HttpResponse

from ochecklist import views as ochecklist_views
from ochecklist.views import (
    ochecklist_update,
    report_list,
    clear_reports,
    report_detail,
    runner_detail,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def factory():
    return RequestFactory()


@pytest.fixture(autouse=True)
def _disable_messages():
    """Neutralise django.contrib.messages pour éviter l'accès à request._messages."""
    with patch.object(ochecklist_views, 'messages'):
        yield


@pytest.fixture
def auth_settings():
    """Configure le header d'authentification O'checklist."""
    with patch.object(ochecklist_views.settings, 'OCHECKLIST_HEADER_KEY',
                      'X-Ochecklist-Token'), \
         patch.object(ochecklist_views.settings, 'OCHECKLIST_HEADER_VALUE',
                      'secret-token'):
        yield


# ─── Helpers ─────────────────────────────────────────────────────────────────

def make_yaml(report_version='1.5',
              creator='O Checklist Test',
              created='2024-10-12T12:45:04+02:00',
              event='Test Event',
              runners=None,
              end_of_data=True):
    """Génère un payload YAML complet pour les tests."""
    data = {
        'Version': report_version,
        'Creator': creator,
        'Created': created,
        'Event': event,
        'Data': runners if runners is not None else [],
    }
    if end_of_data:
        data['EndOfData'] = {'Runners': len(data['Data']), 'Lines': 0}
    return yaml.dump(data, default_flow_style=False, allow_unicode=True).encode('utf-8')


def make_runner(name='Alice', status='Started OK', org='CO Test',
                runner_id='RID1', bib='1', card='111',
                start_time='2024-10-12T12:31:00+02:00',
                class_name='H21', new_card=None, comment=None,
                changelog=None):
    """Génère une entrée Data[] pour un runner."""
    runner = {
        'StartStatus': status,
        'Id': runner_id,
        'Name': name,
        'Org': org,
        'Card': card,
        'StartTime': start_time,
        'ClassName': class_name,
    }
    if new_card is not None:
        runner['NewCard'] = new_card
    if comment is not None:
        runner['Comment'] = comment
    return {'Runner': runner, 'ChangeLog': changelog}


def digest_header(body, algo='sha-256', encoding='base64'):
    """Construit une valeur de header Content-Digest valide."""
    hash_obj = {'sha-256': hashlib.sha256,
                'sha-512': hashlib.sha512,
                'md5': hashlib.md5}[algo]
    raw = hash_obj(body).digest()
    if encoding == 'base64':
        return f'{algo}={base64.b64encode(raw).decode("ascii")}'
    return f'{algo}={raw.hex()}'


# ─── Tests ochecklist_update : auth header ────────────────────────────────────

class TestOchecklistUpdateAuthHeader:
    """Authentification par header HTTP configurable."""

    def _post(self, factory, body=b'payload', **headers):
        return factory.post(
            '/ochecklist/update/',
            data=body,
            content_type='application/yaml',
            **headers,
        )

    def test_header_manquant_retourne_401(self, factory, auth_settings):
        request = self._post(factory)
        response = ochecklist_update(request)
        assert response.status_code == 401
        assert b'Unauthorized' in response.content

    def test_header_mauvaise_valeur_retourne_401(self, factory, auth_settings):
        request = self._post(
            factory,
            HTTP_X_OCHECKLIST_TOKEN='wrong-token',
        )
        response = ochecklist_update(request)
        assert response.status_code == 401

    def test_header_correct(self, factory, auth_settings):
        body = make_yaml(runners=[make_runner()])
        with patch('ochecklist.views.OchecklistReport') as MockReport, \
             patch('ochecklist.views.OchecklistRunner'), \
             patch('ochecklist.views.OchecklistChangeLog'), \
             patch('ochecklist.views.transaction') as mock_tx:
            mock_tx.atomic.return_value.__enter__ = lambda s: s
            mock_tx.atomic.return_value.__exit__  = MagicMock(return_value=False)
            MockReport.objects.filter.return_value.order_by.return_value.first.return_value = None

            request = self._post(
                factory,
                body=body,
                HTTP_X_OCHECKLIST_TOKEN='secret-token',
            )
            response = ochecklist_update(request)
            assert response.status_code == 200

    def test_header_vide_settings_pas_de_check(self, factory):
        """Si la clé ou la valeur n'est pas configurée, pas d'auth check."""
        with patch.object(ochecklist_views.settings,
                          'OCHECKLIST_HEADER_KEY', ''), \
             patch.object(ochecklist_views.settings,
                          'OCHECKLIST_HEADER_VALUE', ''):
            body = make_yaml(runners=[make_runner()])
            with patch('ochecklist.views.OchecklistReport') as MockReport, \
                 patch('ochecklist.views.OchecklistRunner'), \
                 patch('ochecklist.views.OchecklistChangeLog'), \
                 patch('ochecklist.views.transaction') as mock_tx:
                mock_tx.atomic.return_value.__enter__ = lambda s: s
                mock_tx.atomic.return_value.__exit__  = MagicMock(return_value=False)
                MockReport.objects.filter.return_value.order_by.return_value.first.return_value = None

                request = factory.post(
                    '/ochecklist/update/',
                    data=body,
                    content_type='application/yaml',
                )
                response = ochecklist_update(request)
                assert response.status_code == 200

    def test_header_key_avec_tirets(self, factory):
        """Les tirets dans la clé sont convertis en underscores pour META."""
        with patch.object(ochecklist_views.settings,
                          'OCHECKLIST_HEADER_KEY', 'X-Custom-Auth'), \
             patch.object(ochecklist_views.settings,
                          'OCHECKLIST_HEADER_VALUE', 'val'):
            body = make_yaml(runners=[make_runner()])
            with patch('ochecklist.views.OchecklistReport') as MockReport, \
                 patch('ochecklist.views.OchecklistRunner'), \
                 patch('ochecklist.views.OchecklistChangeLog'), \
                 patch('ochecklist.views.transaction') as mock_tx:
                mock_tx.atomic.return_value.__enter__ = lambda s: s
                mock_tx.atomic.return_value.__exit__  = MagicMock(return_value=False)
                MockReport.objects.filter.return_value.order_by.return_value.first.return_value = None

                request = factory.post(
                    '/ochecklist/update/',
                    data=body,
                    content_type='application/yaml',
                    HTTP_X_CUSTOM_AUTH='val',
                )
                response = ochecklist_update(request)
                assert response.status_code == 200


# ─── Tests ochecklist_update : Content-Digest ─────────────────────────────────

class TestOchecklistUpdateContentDigest:
    """Vérification du header Content-Digest."""

    def test_digest_invalide_retourne_400(self, factory):
        request = factory.post(
            '/ochecklist/update/',
            data=b'whatever',
            content_type='application/yaml',
            HTTP_CONTENT_DIGEST='sha-256=YWJjZA==',
        )
        response = ochecklist_update(request)
        assert response.status_code == 400
        assert b'Invalid Content-Digest' in response.content

    def test_digest_sha256_match(self, factory):
        body = make_yaml(runners=[make_runner()])
        with patch('ochecklist.views.OchecklistReport') as MockReport, \
             patch('ochecklist.views.OchecklistRunner'), \
             patch('ochecklist.views.OchecklistChangeLog'), \
             patch('ochecklist.views.transaction') as mock_tx:
            mock_tx.atomic.return_value.__enter__ = lambda s: s
            mock_tx.atomic.return_value.__exit__  = MagicMock(return_value=False)
            MockReport.objects.filter.return_value.order_by.return_value.first.return_value = None

            request = factory.post(
                '/ochecklist/update/',
                data=body,
                content_type='application/yaml',
                HTTP_CONTENT_DIGEST=digest_header(body, 'sha-256'),
            )
            response = ochecklist_update(request)
            assert response.status_code == 200

    def test_digest_sha512_match(self, factory):
        body = make_yaml(runners=[make_runner()])
        with patch('ochecklist.views.OchecklistReport') as MockReport, \
             patch('ochecklist.views.OchecklistRunner'), \
             patch('ochecklist.views.OchecklistChangeLog'), \
             patch('ochecklist.views.transaction') as mock_tx:
            mock_tx.atomic.return_value.__enter__ = lambda s: s
            mock_tx.atomic.return_value.__exit__  = MagicMock(return_value=False)
            MockReport.objects.filter.return_value.order_by.return_value.first.return_value = None

            request = factory.post(
                '/ochecklist/update/',
                data=body,
                content_type='application/yaml',
                HTTP_CONTENT_DIGEST=digest_header(body, 'sha-512'),
            )
            response = ochecklist_update(request)
            assert response.status_code == 200

    def test_digest_md5_match(self, factory):
        body = make_yaml(runners=[make_runner()])
        with patch('ochecklist.views.OchecklistReport') as MockReport, \
             patch('ochecklist.views.OchecklistRunner'), \
             patch('ochecklist.views.OchecklistChangeLog'), \
             patch('ochecklist.views.transaction') as mock_tx:
            mock_tx.atomic.return_value.__enter__ = lambda s: s
            mock_tx.atomic.return_value.__exit__  = MagicMock(return_value=False)
            MockReport.objects.filter.return_value.order_by.return_value.first.return_value = None

            request = factory.post(
                '/ochecklist/update/',
                data=body,
                content_type='application/yaml',
                HTTP_CONTENT_DIGEST=digest_header(body, 'md5'),
            )
            response = ochecklist_update(request)
            assert response.status_code == 200


# ─── Tests ochecklist_update : compression gzip ────────────────────────────────

class TestOchecklistUpdateGzip:
    """Décompression gzip : le digest est vérifié AVANT la décompression."""

    def test_gzip_avec_digest_valide(self, factory):
        payload = make_yaml(runners=[make_runner(name='Gzipped')])
        compressed = gzip.compress(payload)
        with patch('ochecklist.views.OchecklistReport') as MockReport, \
             patch('ochecklist.views.OchecklistRunner') as MockRunner, \
             patch('ochecklist.views.OchecklistChangeLog'), \
             patch('ochecklist.views.transaction') as mock_tx:
            mock_tx.atomic.return_value.__enter__ = lambda s: s
            mock_tx.atomic.return_value.__exit__  = MagicMock(return_value=False)
            MockReport.objects.filter.return_value.order_by.return_value.first.return_value = None
            new_report = MagicMock()
            new_report.runners.filter.return_value.first.return_value = None
            MockReport.objects.create.return_value = new_report
            MockRunner.objects.create.return_value = MagicMock()

            request = factory.post(
                '/ochecklist/update/',
                data=compressed,
                content_type='application/yaml',
                HTTP_CONTENT_ENCODING='gzip',
                HTTP_CONTENT_DIGEST=digest_header(compressed, 'sha-256'),
            )
            response = ochecklist_update(request)
            assert response.status_code == 200
            # Le runner créé doit avoir le nom du YAML décompressé
            kwargs = MockRunner.objects.create.call_args.kwargs
            assert kwargs['name'] == 'Gzipped'

    def test_gzip_mais_digest_calcule_sur_brut(self, factory):
        """Le digest est calculé sur le corps AVANT décompression."""
        payload = make_yaml(runners=[make_runner()])
        compressed = gzip.compress(payload)
        # Le digest du payload NON compressé ne matche pas le compressed
        with patch('ochecklist.views.OchecklistReport'), \
             patch('ochecklist.views.OchecklistRunner'), \
             patch('ochecklist.views.OchecklistChangeLog'), \
             patch('ochecklist.views.transaction') as mock_tx:
            mock_tx.atomic.return_value.__enter__ = lambda s: s
            mock_tx.atomic.return_value.__exit__  = MagicMock(return_value=False)

            request = factory.post(
                '/ochecklist/update/',
                data=compressed,
                content_type='application/yaml',
                HTTP_CONTENT_ENCODING='gzip',
                HTTP_CONTENT_DIGEST=digest_header(payload, 'sha-256'),
            )
            response = ochecklist_update(request)
            assert response.status_code == 400


# ─── Tests ochecklist_update : parsing YAML ────────────────────────────────────

class TestOchecklistUpdateYAMLParsing:
    """Validation de la structure YAML."""

    def _post(self, factory, body):
        return factory.post(
            '/ochecklist/update/',
            data=body,
            content_type='application/yaml',
        )

    def test_yaml_invalide(self, factory):
        """Un payload non-YAML retourne 400."""
        request = self._post(factory, b'{ invalid: : yaml :::')
        response = ochecklist_update(request)
        assert response.status_code == 400
        assert b'Invalid YAML' in response.content

    def test_racine_liste(self, factory):
        """La racine YAML doit être un dict, pas une liste."""
        payload = yaml.dump([{'a': 1}]).encode('utf-8')
        request = self._post(factory, payload)
        response = ochecklist_update(request)
        assert response.status_code == 400
        assert b'Invalid' in response.content

    def test_data_manquant(self, factory):
        """Clé 'Data' absente → 400."""
        payload = yaml.dump({'Version': '1.5'}).encode('utf-8')
        request = self._post(factory, payload)
        response = ochecklist_update(request)
        assert response.status_code == 400

    def test_data_vide(self, factory):
        """Data=[] doit fonctionner (rapport sans coureurs)."""
        with patch('ochecklist.views.OchecklistReport') as MockReport, \
             patch('ochecklist.views.OchecklistRunner') as MockRunner, \
             patch('ochecklist.views.OchecklistChangeLog'), \
             patch('ochecklist.views.transaction') as mock_tx:
            mock_tx.atomic.return_value.__enter__ = lambda s: s
            mock_tx.atomic.return_value.__exit__  = MagicMock(return_value=False)
            MockReport.objects.filter.return_value.order_by.return_value.first.return_value = None

            body = make_yaml(runners=[])
            response = ochecklist_update(self._post(factory, body))
            assert response.status_code == 200
            MockRunner.objects.create.assert_not_called()


# ─── Tests ochecklist_update : création et mise à jour ─────────────────────────

class TestOchecklistUpdateReportLifecycle:
    """Création d'un nouveau rapport et mise à jour d'un rapport existant."""

    def _setup_mocks(self, existing_report=None):
        """Helper pour mocker tous les modèles et la transaction."""
        mocks = {
            'Report': patch('ochecklist.views.OchecklistReport').start(),
            'Runner': patch('ochecklist.views.OchecklistRunner').start(),
            'ChangeLog': patch('ochecklist.views.OchecklistChangeLog').start(),
            'tx': patch('ochecklist.views.transaction').start(),
        }
        mocks['tx'].atomic.return_value.__enter__ = lambda s: s
        mocks['tx'].atomic.return_value.__exit__  = MagicMock(return_value=False)
        # When no existing report is found, OchecklistReport.objects.create() is called.
        # By default, that mock report's runner filter returns None so the upsert creates new runners.
        new_report = MagicMock()
        new_report.runners.filter.return_value.first.return_value = None
        mocks['Report'].objects.create.return_value = new_report
        mocks['Report'].objects.filter.return_value.order_by.return_value.first.return_value = existing_report
        return mocks

    def _teardown_mocks(self):
        patch.stopall()

    def test_creation_nouveau_rapport(self, factory):
        m = self._setup_mocks(existing_report=None)
        try:
            body = make_yaml(event='New Event', runners=[make_runner(name='Bob')])
            request = factory.post(
                '/ochecklist/update/',
                data=body,
                content_type='application/yaml',
            )
            response = ochecklist_update(request)
            assert response.status_code == 200
            m['Report'].objects.create.assert_called_once()
            kwargs = m['Report'].objects.create.call_args.kwargs
            assert kwargs['event'] == 'New Event'
            assert kwargs['version'] == '1.5'
            assert kwargs['creator'] == 'O Checklist Test'
            m['Runner'].objects.create.assert_called_once()
        finally:
            self._teardown_mocks()

    def test_event_manquant(self, factory):
        m = self._setup_mocks()
        try:
            body = make_yaml(event=None, runners=[make_runner()])
            request = factory.post(
                '/ochecklist/update/',
                data=body,
                content_type='application/yaml',
            )
            response = ochecklist_update(request)
            assert response.status_code == 200
            kwargs = m['Report'].objects.create.call_args.kwargs
            assert kwargs['event'] is None
        finally:
            self._teardown_mocks()

    def test_event_manquant_via_cle_absente(self, factory):
        m = self._setup_mocks()
        try:
            body = make_yaml(runners=[make_runner()])
            payload = yaml.safe_load(body)
            del payload['Event']
            request = factory.post(
                '/ochecklist/update/',
                data=yaml.dump(payload).encode('utf-8'),
                content_type='application/yaml',
            )
            response = ochecklist_update(request)
            assert response.status_code == 200
            kwargs = m['Report'].objects.create.call_args.kwargs
            assert kwargs['event'] is None
        finally:
            self._teardown_mocks()

    def test_mise_a_jour_rapport_existant_avec_upsert(self, factory):
        report_mock = MagicMock()
        report_mock.version = 'old'
        report_mock.creator = 'old'
        report_mock.created = None
        runner_mock = MagicMock()
        report_mock.runners.filter.return_value.first.return_value = runner_mock
        m = self._setup_mocks(existing_report=report_mock)
        try:
            body = make_yaml(event='Same Event', runners=[make_runner(name='New')])
            request = factory.post(
                '/ochecklist/update/',
                data=body,
                content_type='application/yaml',
            )
            response = ochecklist_update(request)
            assert response.status_code == 200
            report_mock.save.assert_called_once()
            m['Report'].objects.create.assert_not_called()
            runner_mock.save.assert_called_once()
        finally:
            self._teardown_mocks()

    def test_upsert_par_runner_id_quand_nom_vide(self, factory):
        """Quand le Name est vide, le match se fait par runner_id."""
        report_mock = MagicMock()
        report_mock.version = 'old'
        report_mock.creator = 'old'
        report_mock.created = None
        runner_mock = MagicMock()
        report_mock.runners.filter.return_value.first.return_value = runner_mock
        m = self._setup_mocks(existing_report=report_mock)
        try:
            runner = {
                'Runner': {
                    'StartStatus': 'DNS',
                    'Id': 'R42',
                    'Name': '',
                    'Org': 'CO',
                    'Card': '999',
                    'StartTime': '2024-10-12T12:31:00+02:00',
                    'ClassName': 'H21',
                },
                'ChangeLog': None,
            }
            body = make_yaml(event='Same Event', runners=[runner])
            request = factory.post(
                '/ochecklist/update/',
                data=body,
                content_type='application/yaml',
            )
            response = ochecklist_update(request)
            assert response.status_code == 200
            report_mock.runners.filter.assert_any_call(runner_id='R42')
            runner_mock.save.assert_called_once()
            m['Runner'].objects.create.assert_not_called()
        finally:
            self._teardown_mocks()

    def test_diff_ne_supprime_pas_les_anciens_runners(self, factory):
        """Un envoi partiel (diff) ne doit pas effacer les runners absents."""
        report_mock = MagicMock()
        report_mock.version = 'old'
        report_mock.creator = 'old'
        report_mock.created = None
        runner_mock = MagicMock()
        report_mock.runners.filter.return_value.first.return_value = runner_mock
        m = self._setup_mocks(existing_report=report_mock)
        try:
            body = make_yaml(event='Same Event', runners=[make_runner(name='Alice')])
            request = factory.post(
                '/ochecklist/update/',
                data=body,
                content_type='application/yaml',
            )
            response = ochecklist_update(request)
            assert response.status_code == 200
            report_mock.runners.all().delete.assert_not_called()
            runner_mock.save.assert_called_once()
            m['Runner'].objects.create.assert_not_called()
        finally:
            self._teardown_mocks()

    def test_plusieurs_runners(self, factory):
        m = self._setup_mocks()
        try:
            runners = [
                make_runner(name='Runner 1', runner_id='R1'),
                make_runner(name='Runner 2', runner_id='R2', status='DNS'),
                make_runner(name='Runner 3', runner_id='R3', status='Late start'),
            ]
            body = make_yaml(runners=runners)
            request = factory.post(
                '/ochecklist/update/',
                data=body,
                content_type='application/yaml',
            )
            response = ochecklist_update(request)
            assert response.status_code == 200
            assert m['Runner'].objects.create.call_count == 3
        finally:
            self._teardown_mocks()

    def test_champs_optional_absents(self, factory):
        """Runner sans runner_id / bib / card / new_card / comment."""
        m = self._setup_mocks()
        try:
            runner_data = {
                'Runner': {
                    'StartStatus': 'Started OK',
                    'Name': 'Minimal',
                    'Org': 'CO',
                    'ClassName': 'H21',
                },
                'ChangeLog': None,
            }
            body = make_yaml(runners=[runner_data])
            request = factory.post(
                '/ochecklist/update/',
                data=body,
                content_type='application/yaml',
            )
            response = ochecklist_update(request)
            assert response.status_code == 200
            kwargs = m['Runner'].objects.create.call_args.kwargs
            assert kwargs['name'] == 'Minimal'
            assert kwargs['runner_id'] is None
            assert kwargs['bib'] is None
            assert kwargs['card_number'] is None
            assert kwargs['new_card'] is None
            assert kwargs['comment'] is None
        finally:
            self._teardown_mocks()

    def test_datetime_obj_transmis_directement(self, factory):
        """Si un datetime Python est présent, to_datetime le laisse tel quel."""
        m = self._setup_mocks()
        try:
            dt = datetime.datetime(2024, 10, 12, 12, 45, 4,
                                   tzinfo=datetime.timezone(datetime.timedelta(hours=2)))
            payload = {
                'Version': '1.5',
                'Creator': 'App',
                'Created': dt,
                'Event': 'Evt',
                'Data': [],
            }
            body = yaml.dump(payload, default_flow_style=False).encode('utf-8')
            request = factory.post(
                '/ochecklist/update/',
                data=body,
                content_type='application/yaml',
            )
            response = ochecklist_update(request)
            assert response.status_code == 200
            kwargs = m['Report'].objects.create.call_args.kwargs
            assert kwargs['created'] == dt
        finally:
            self._teardown_mocks()

    def test_datetime_str_iso_est_convertie(self, factory):
        """Une string ISO est parsée en datetime par to_datetime."""
        m = self._setup_mocks()
        try:
            payload = {
                'Version': '1.5',
                'Creator': 'App',
                'Created': '2024-10-12T12:45:04+02:00',
                'Event': 'Evt',
                'Data': [],
            }
            expected = datetime.datetime(2024, 10, 12, 12, 45, 4,
                                         tzinfo=datetime.timezone(datetime.timedelta(hours=2)))
            body = yaml.dump(payload, default_flow_style=False).encode('utf-8')
            request = factory.post(
                '/ochecklist/update/',
                data=body,
                content_type='application/yaml',
            )
            response = ochecklist_update(request)
            assert response.status_code == 200
            kwargs = m['Report'].objects.create.call_args.kwargs
            assert kwargs['created'] == expected
        finally:
            self._teardown_mocks()

    def test_event_datetime_converti_en_isoformat(self, factory):
        """Si Event est un datetime, to_str() appelle .isoformat()."""
        m = self._setup_mocks()
        try:
            dt = datetime.datetime(2024, 10, 12, 12, 45, 4,
                                   tzinfo=datetime.timezone(datetime.timedelta(hours=2)))
            payload = {
                'Version': '1.5',
                'Creator': 'App',
                'Created': '2024-10-12T12:45:04+02:00',
                'Event': dt,
                'Data': [],
            }
            body = yaml.dump(payload, default_flow_style=False).encode('utf-8')
            request = factory.post(
                '/ochecklist/update/',
                data=body,
                content_type='application/yaml',
            )
            response = ochecklist_update(request)
            assert response.status_code == 200
            kwargs = m['Report'].objects.create.call_args.kwargs
            assert kwargs['event'] == dt.isoformat()
        finally:
            self._teardown_mocks()

    def test_created_invalide_devient_none(self, factory):
        """Si Created n'est pas str/datetime/int, to_datetime retourne None."""
        m = self._setup_mocks()
        try:
            payload = {
                'Version': '1.5',
                'Creator': 'App',
                'Created': [1, 2, 3],
                'Event': 'Evt',
                'Data': [],
            }
            body = yaml.dump(payload, default_flow_style=False).encode('utf-8')
            request = factory.post(
                '/ochecklist/update/',
                data=body,
                content_type='application/yaml',
            )
            response = ochecklist_update(request)
            assert response.status_code == 200
            kwargs = m['Report'].objects.create.call_args.kwargs
            assert kwargs['created'] is None
        finally:
            self._teardown_mocks()


# ─── Tests ochecklist_update : ChangeLog ───────────────────────────────────────

class TestOchecklistUpdateChangeLog:
    """Création conditionnelle d'un OchecklistChangeLog."""

    def _setup(self, runner, existing_report=None):
        m = {
            'Report': patch('ochecklist.views.OchecklistReport').start(),
            'Runner': patch('ochecklist.views.OchecklistRunner').start(),
            'ChangeLog': patch('ochecklist.views.OchecklistChangeLog').start(),
            'tx': patch('ochecklist.views.transaction').start(),
        }
        m['tx'].atomic.return_value.__enter__ = lambda s: s
        m['tx'].atomic.return_value.__exit__  = MagicMock(return_value=False)
        # When no existing report is found, the newly created report mock
        # returns None from runner filter so the upsert creates new runners.
        new_report = MagicMock()
        new_report.runners.filter.return_value.first.return_value = None
        m['Report'].objects.create.return_value = new_report
        m['Report'].objects.filter.return_value.order_by.return_value.first.return_value = existing_report
        m['Runner'].objects.create.return_value = MagicMock()
        return m

    def _teardown(self):
        patch.stopall()

    def _post(self, factory, body):
        return factory.post(
            '/ochecklist/update/',
            data=body,
            content_type='application/yaml',
        )

    def test_changelog_none(self, factory):
        m = self._setup(None)
        try:
            body = make_yaml(runners=[make_runner(changelog=None)])
            response = ochecklist_update(self._post(factory, body))
            assert response.status_code == 200
            m['ChangeLog'].objects.create.assert_not_called()
        finally:
            self._teardown()

    def test_changelog_vide(self, factory):
        """ChangeLog={} ne doit pas créer d'entrée (any(...)=False)."""
        m = self._setup({})
        try:
            body = make_yaml(runners=[make_runner(changelog={})])
            response = ochecklist_update(self._post(factory, body))
            assert response.status_code == 200
            m['ChangeLog'].objects.create.assert_not_called()
        finally:
            self._teardown()

    def test_changelog_avec_dns(self, factory):
        m = self._setup({'DNS': '2024-10-12T12:34:56+02:00'})
        try:
            expected = datetime.datetime(2024, 10, 12, 12, 34, 56,
                                         tzinfo=datetime.timezone(datetime.timedelta(hours=2)))
            body = make_yaml(runners=[make_runner(
                changelog={'DNS': '2024-10-12T12:34:56+02:00'},
            )])
            response = ochecklist_update(self._post(factory, body))
            assert response.status_code == 200
            m['ChangeLog'].objects.create.assert_called_once()
            kwargs = m['ChangeLog'].objects.create.call_args.kwargs
            assert kwargs['dns'] == expected
        finally:
            self._teardown()

    def test_changelog_avec_tous_les_champs(self, factory):
        tz = datetime.timezone(datetime.timedelta(hours=2))
        cl = {
            'DNS': '2024-10-12T12:31:22+02:00',
            'LateStart': '2024-10-12T12:37:02+02:00',
            'NewCard': '2024-10-12T12:35:34+02:00',
            'Comment': '2024-10-12T12:40:08+02:00',
            'NewRunner': '2024-10-12T12:43:14+02:00',
        }
        cl_expected = {
            'dns': datetime.datetime(2024, 10, 12, 12, 31, 22, tzinfo=tz),
            'late_start': datetime.datetime(2024, 10, 12, 12, 37, 2, tzinfo=tz),
            'new_card': datetime.datetime(2024, 10, 12, 12, 35, 34, tzinfo=tz),
            'comment': datetime.datetime(2024, 10, 12, 12, 40, 8, tzinfo=tz),
            'new_runner': datetime.datetime(2024, 10, 12, 12, 43, 14, tzinfo=tz),
        }
        m = self._setup(cl)
        try:
            body = make_yaml(runners=[make_runner(changelog=cl)])
            response = ochecklist_update(self._post(factory, body))
            assert response.status_code == 200
            m['ChangeLog'].objects.create.assert_called_once()
            kwargs = m['ChangeLog'].objects.create.call_args.kwargs
            assert kwargs['runner'] is not None
            assert kwargs['dns'] == cl_expected['dns']
            assert kwargs['late_start'] == cl_expected['late_start']
            assert kwargs['new_card'] == cl_expected['new_card']
            assert kwargs['comment'] == cl_expected['comment']
            assert kwargs['new_runner'] == cl_expected['new_runner']
        finally:
            self._teardown()

    def test_changelog_datetime_passe_directement(self, factory):
        """Si les valeurs du changelog sont des objets datetime."""
        dt = datetime.datetime(2024, 10, 12, 12, 0,
                               tzinfo=datetime.timezone(datetime.timedelta(hours=2)))
        m = self._setup({'DNS': dt})
        try:
            body = make_yaml(runners=[make_runner(changelog={'DNS': dt})])
            response = ochecklist_update(self._post(factory, body))
            assert response.status_code == 200
            kwargs = m['ChangeLog'].objects.create.call_args.kwargs
            assert kwargs['dns'] == dt
        finally:
            self._teardown()

    def test_changelog_existant_est_mis_a_jour(self, factory):
        """Quand le runner existe déjà, son changelog est mis à jour via get_or_create."""
        changelog_mock = MagicMock()
        report_mock = MagicMock()
        report_mock.version = 'old'
        report_mock.creator = 'old'
        report_mock.created = None
        runner_mock = MagicMock()
        report_mock.runners.filter.return_value.first.return_value = runner_mock
        m = self._setup({'DNS': '2024-10-12T12:34:56+02:00'},
                        existing_report=report_mock)
        m['ChangeLog'].objects.get_or_create.return_value = (changelog_mock, False)
        try:
            body = make_yaml(event='Same Event', runners=[make_runner(
                name='Alice',
                changelog={'DNS': '2024-10-12T12:34:56+02:00'},
            )])
            response = ochecklist_update(self._post(factory, body))
            assert response.status_code == 200
            m['ChangeLog'].objects.get_or_create.assert_called_once()
            changelog_mock.save.assert_called_once()
            m['ChangeLog'].objects.create.assert_not_called()
        finally:
            self._teardown()

    def test_transaction_atomic_appele(self, factory):
        m = self._setup(None)
        try:
            body = make_yaml(runners=[make_runner()])
            response = ochecklist_update(self._post(factory, body))
            assert response.status_code == 200
            m['tx'].atomic.assert_called_once()
        finally:
            self._teardown()


# ─── Tests ochecklist_update : GET non autorisé ────────────────────────────────

class TestOchecklistUpdateMethodNotAllowed:
    """@require_POST rejette les GET."""

    def test_get_retourne_405(self, factory):
        request = factory.get('/ochecklist/update/')
        response = ochecklist_update(request)
        assert response.status_code == 405


# ─── Tests report_list ────────────────────────────────────────────────────────

class TestReportListView:

    def test_retourne_200_avec_reports(self, factory):
        request = factory.get('/ochecklist/')
        with patch('ochecklist.views.OchecklistReport') as MockReport, \
             patch('ochecklist.views.render') as mock_render:
            r1 = MagicMock(name='r1')
            r2 = MagicMock(name='r2')
            MockReport.objects.all.return_value = [r1, r2]
            mock_render.return_value = HttpResponse('ok')

            response = report_list(request)
            assert response.status_code == 200
            mock_render.assert_called_once()
            template, context = mock_render.call_args[0][1], mock_render.call_args[0][2]
            assert template == 'ochecklist/report_list.html'
            assert context['reports'] == [r1, r2]

    def test_appelle_objects_all(self, factory):
        request = factory.get('/ochecklist/')
        with patch('ochecklist.views.OchecklistReport') as MockReport, \
             patch('ochecklist.views.render', return_value=HttpResponse('ok')):
            MockReport.objects.all.return_value = []
            report_list(request)
            MockReport.objects.all.assert_called_once()


# ─── Tests clear_reports ──────────────────────────────────────────────────────

class TestClearReportsView:

    def test_get_redirige(self, factory):
        request = factory.get('/ochecklist/clear/')
        with patch('ochecklist.views.redirect') as mock_redirect:
            mock_redirect.return_value = HttpResponse('redir')
            response = clear_reports(request)
            assert response.status_code == 200

    def test_post_sans_ids_redirige(self, factory):
        request = factory.post('/ochecklist/clear/', data={})
        with patch('ochecklist.views.OchecklistReport') as MockReport, \
             patch('ochecklist.views.redirect') as mock_redirect:
            mock_redirect.return_value = HttpResponse('redir')
            response = clear_reports(request)
            assert response.status_code == 200
            MockReport.objects.filter.assert_not_called()

    def test_post_avec_ids_supprime(self, factory):
        request = factory.post('/ochecklist/clear/', data={'report_ids': ['1', '2', '3']})
        with patch('ochecklist.views.OchecklistReport') as MockReport, \
             patch('ochecklist.views.redirect') as mock_redirect:
            qs = MockReport.objects.filter.return_value
            qs.delete.return_value = (3, {'ochecklist.OchecklistReport': 3})
            mock_redirect.return_value = HttpResponse('redir')
            response = clear_reports(request)
            assert response.status_code == 200
            MockReport.objects.filter.assert_called_once_with(id__in=['1', '2', '3'])
            qs.delete.assert_called_once()

    def test_post_avec_un_seul_id(self, factory):
        request = factory.post('/ochecklist/clear/', data={'report_ids': '5'})
        with patch('ochecklist.views.OchecklistReport') as MockReport, \
             patch('ochecklist.views.redirect') as mock_redirect:
            qs = MockReport.objects.filter.return_value
            qs.delete.return_value = (1, {'ochecklist.OchecklistReport': 1})
            mock_redirect.return_value = HttpResponse('redir')
            clear_reports(request)
            MockReport.objects.filter.assert_called_once_with(id__in=['5'])


# ─── Tests report_detail ──────────────────────────────────────────────────────

class TestReportDetailView:

    def _run(self, factory, report, runners, **get_params):
        request = factory.get(f'/ochecklist/{report.id}/', data=get_params)
        with patch('ochecklist.views.get_object_or_404', return_value=report), \
             patch('ochecklist.views.render') as mock_render:
            qs_mock = MagicMock()
            qs_mock.order_by.return_value = runners
            report.runners.all.return_value.select_related.return_value = qs_mock
            report.runners.filter.return_value.count.return_value = 0
            report.runners.exclude.return_value.exclude.return_value.count.return_value = 0
            mock_render.return_value = HttpResponse('ok')
            response = report_detail(request, report_id=report.id)
            return response, mock_render.call_args[0][2]

    def test_retourne_200_et_contexte(self, factory):
        report = MagicMock(id=1)
        runners = [MagicMock(start_time=datetime.datetime(2024, 10, 12, 12, 0))]

        with patch('ochecklist.views.get_object_or_404', return_value=report), \
             patch('ochecklist.views.render') as mock_render:
            qs_mock = MagicMock()
            qs_mock.order_by.return_value = runners
            report.runners.all.return_value.select_related.return_value = qs_mock
            report.runners.filter.return_value.count.return_value = 1
            report.runners.exclude.return_value.exclude.return_value.count.return_value = 0
            mock_render.return_value = HttpResponse('ok')
            request = factory.get('/ochecklist/1/')
            response = report_detail(request, report_id=1)
            assert response.status_code == 200
            ctx = mock_render.call_args[0][2]
            assert ctx['report'] is report
            assert ctx['runners'] == runners
            assert ctx['current_sort'] == ''
            assert 'started_ok_count' in ctx
            assert 'dns_count' in ctx
            assert 'late_start_count' in ctx
            assert 'new_card_count' in ctx

    def test_404_si_rapport_introuvable(self, factory):
        with patch('ochecklist.views.get_object_or_404',
                   side_effect=Http404('not found')):
            request = factory.get('/ochecklist/999/')
            with pytest.raises(Http404):
                report_detail(request, report_id=999)

    def test_tri_par_defaut(self, factory):
        report = MagicMock(id=1)
        with patch('ochecklist.views.get_object_or_404', return_value=report), \
             patch('ochecklist.views.render', return_value=HttpResponse('ok')):
            qs_mock = MagicMock()
            qs_mock.order_by.return_value = []
            report.runners.all.return_value.select_related.return_value = qs_mock
            report.runners.filter.return_value.count.return_value = 0
            report.runners.exclude.return_value.exclude.return_value.count.return_value = 0
            request = factory.get('/ochecklist/1/')
            report_detail(request, report_id=1)
            qs_mock.order_by.assert_called_with('start_time', 'name')

    def test_tri_status_asc(self, factory):
        report = MagicMock(id=1)
        with patch('ochecklist.views.get_object_or_404', return_value=report), \
             patch('ochecklist.views.render', return_value=HttpResponse('ok')):
            qs_mock = MagicMock()
            qs_mock.order_by.return_value = []
            report.runners.all.return_value.select_related.return_value = qs_mock
            report.runners.filter.return_value.count.return_value = 0
            report.runners.exclude.return_value.exclude.return_value.count.return_value = 0
            request = factory.get('/ochecklist/1/', data={'sort': 'status'})
            report_detail(request, report_id=1)
            qs_mock.order_by.assert_called_with('start_status')

    def test_tri_status_desc(self, factory):
        report = MagicMock(id=1)
        with patch('ochecklist.views.get_object_or_404', return_value=report), \
             patch('ochecklist.views.render', return_value=HttpResponse('ok')):
            qs_mock = MagicMock()
            qs_mock.order_by.return_value = []
            report.runners.all.return_value.select_related.return_value = qs_mock
            report.runners.filter.return_value.count.return_value = 0
            report.runners.exclude.return_value.exclude.return_value.count.return_value = 0
            request = factory.get('/ochecklist/1/', data={'sort': '-status'})
            report_detail(request, report_id=1)
            qs_mock.order_by.assert_called_with('-start_status')

    def test_tri_card_asc(self, factory):
        report = MagicMock(id=1)
        with patch('ochecklist.views.get_object_or_404', return_value=report), \
             patch('ochecklist.views.render', return_value=HttpResponse('ok')):
            qs_mock = MagicMock()
            qs_mock.order_by.return_value = []
            report.runners.all.return_value.select_related.return_value = qs_mock
            report.runners.filter.return_value.count.return_value = 0
            report.runners.exclude.return_value.exclude.return_value.count.return_value = 0
            request = factory.get('/ochecklist/1/', data={'sort': 'card'})
            report_detail(request, report_id=1)
            qs_mock.order_by.assert_called_with('-new_card')

    def test_tri_card_desc(self, factory):
        report = MagicMock(id=1)
        with patch('ochecklist.views.get_object_or_404', return_value=report), \
             patch('ochecklist.views.render', return_value=HttpResponse('ok')):
            qs_mock = MagicMock()
            qs_mock.order_by.return_value = []
            report.runners.all.return_value.select_related.return_value = qs_mock
            report.runners.filter.return_value.count.return_value = 0
            report.runners.exclude.return_value.exclude.return_value.count.return_value = 0
            request = factory.get('/ochecklist/1/', data={'sort': '-card'})
            report_detail(request, report_id=1)
            qs_mock.order_by.assert_called_with('new_card')

    def test_compteurs_appeles(self, factory):
        report = MagicMock(id=1)
        with patch('ochecklist.views.get_object_or_404', return_value=report), \
             patch('ochecklist.views.render', return_value=HttpResponse('ok')):
            qs_mock = MagicMock()
            qs_mock.order_by.return_value = []
            report.runners.all.return_value.select_related.return_value = qs_mock
            report.runners.filter.return_value.count.return_value = 7
            report.runners.exclude.return_value.exclude.return_value.count.return_value = 2
            request = factory.get('/ochecklist/1/')
            report_detail(request, report_id=1)
            started_filter = report.runners.filter.call_args_list[0]
            assert started_filter.kwargs == {'start_status': 'Started OK'}
            dns_filter = report.runners.filter.call_args_list[1]
            assert dns_filter.kwargs == {'start_status': 'DNS'}
            late_filter = report.runners.filter.call_args_list[2]
            assert late_filter.kwargs == {'start_status': 'Late start'}
            exclude_call = report.runners.exclude.call_args_list[0]
            assert exclude_call.kwargs == {'new_card': ''}
            report.runners.exclude.return_value.exclude.assert_called_with(
                new_card__isnull=True,
            )

    def test_template_correct(self, factory):
        report = MagicMock(id=1)
        with patch('ochecklist.views.get_object_or_404', return_value=report), \
             patch('ochecklist.views.render') as mock_render:
            qs_mock = MagicMock()
            qs_mock.order_by.return_value = []
            report.runners.all.return_value.select_related.return_value = qs_mock
            report.runners.filter.return_value.count.return_value = 0
            report.runners.exclude.return_value.exclude.return_value.count.return_value = 0
            mock_render.return_value = HttpResponse('ok')
            request = factory.get('/ochecklist/1/')
            report_detail(request, report_id=1)
            assert mock_render.call_args[0][1] == 'ochecklist/report_detail.html'


# ─── Tests runner_detail ──────────────────────────────────────────────────────

class TestRunnerDetailView:

    def test_retourne_200(self, factory):
        runner = MagicMock(id=42)
        with patch('ochecklist.views.get_object_or_404', return_value=runner), \
             patch('ochecklist.views.render') as mock_render:
            mock_render.return_value = HttpResponse('ok')
            request = factory.get('/ochecklist/runner/42/')
            response = runner_detail(request, runner_id=42)
            assert response.status_code == 200
            assert mock_render.call_args[0][1] == 'ochecklist/runner_detail.html'
            assert mock_render.call_args[0][2] == {'runner': runner}

    def test_404_si_runner_introuvable(self, factory):
        with patch('ochecklist.views.get_object_or_404',
                   side_effect=Http404('not found')):
            request = factory.get('/ochecklist/runner/999/')
            with pytest.raises(Http404):
                runner_detail(request, runner_id=999)
