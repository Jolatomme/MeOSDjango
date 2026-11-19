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
import json
from unittest.mock import patch, MagicMock

import pytest
import yaml
from django.test import RequestFactory
from django.http import Http404, HttpResponse

from ochecklist import views as ochecklist_views
from ochecklist.models import OchecklistReport
from ochecklist.views import (
    build_report_version,
    ochecklist_update,
    report_list,
    report_version,
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

    def test_gzip_bombe_retourne_413(self, factory):
        """Un corps décompressé au-delà de la limite est refusé (413)."""
        compressed = gzip.compress(b'a' * 5000)
        with patch.object(ochecklist_views, 'MAX_DECOMPRESSED_SIZE', 100):
            request = factory.post(
                '/ochecklist/update/',
                data=compressed,
                content_type='application/yaml',
                HTTP_CONTENT_ENCODING='gzip',
            )
            response = ochecklist_update(request)
            assert response.status_code == 413
            assert b'Payload too large' in response.content


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


# ─── Tests ochecklist_update : validation du format ───────────────────────────

class TestOchecklistUpdateValidation:
    """Un rapport mal formé doit retourner 400, jamais 500."""

    def _post(self, factory, payload):
        body = yaml.dump(payload, default_flow_style=False).encode('utf-8')
        return ochecklist_update(factory.post(
            '/ochecklist/update/',
            data=body,
            content_type='application/yaml',
        ))

    def _base(self, **overrides):
        payload = {
            'Version': '1.6',
            'Creator': 'O Checklist v5.5',
            'Created': '2026-08-30T10:05:45+02:00',
            'Event': 'Demo',
            'Data': [],
        }
        payload.update(overrides)
        return payload

    def test_data_dict_retourne_400(self, factory):
        response = self._post(factory, self._base(Data={'Runner': {}}))
        assert response.status_code == 400
        assert b'Data must be a list' in response.content

    def test_entree_non_dict_retourne_400(self, factory):
        response = self._post(factory, self._base(Data=['pas-un-dict']))
        assert response.status_code == 400
        assert b'expected a mapping' in response.content

    def test_runner_manquant_retourne_400(self, factory):
        response = self._post(factory, self._base(Data=[{}]))
        assert response.status_code == 400
        assert b'missing Runner mapping' in response.content

    def test_runner_non_dict_retourne_400(self, factory):
        response = self._post(factory, self._base(Data=[{'Runner': 'x'}]))
        assert response.status_code == 400
        assert b'missing Runner mapping' in response.content

    def test_name_manquant_retourne_400(self, factory):
        response = self._post(factory, self._base(Data=[{
            'Runner': {'StartStatus': 'DNS'},
        }]))
        assert response.status_code == 400
        assert b'missing Name' in response.content

    def test_start_status_manquant_retourne_400(self, factory):
        response = self._post(factory, self._base(Data=[{
            'Runner': {'Name': 'Alice'},
        }]))
        assert response.status_code == 400
        assert b'missing StartStatus' in response.content

    def test_start_status_inconnu_retourne_400(self, factory):
        response = self._post(factory, self._base(Data=[{
            'Runner': {'Name': 'Alice', 'StartStatus': 'En course'},
        }]))
        assert response.status_code == 400
        assert b'unsupported StartStatus' in response.content

    def test_start_status_vide_retourne_400(self, factory):
        response = self._post(factory, self._base(Data=[{
            'Runner': {'Name': 'Alice', 'StartStatus': '   '},
        }]))
        assert response.status_code == 400
        assert b'missing StartStatus' in response.content

    def test_changelog_non_dict_retourne_400(self, factory):
        response = self._post(factory, self._base(Data=[{
            'Runner': {'Name': 'Alice', 'StartStatus': 'DNS'},
            'ChangeLog': 'pas-un-dict',
        }]))
        assert response.status_code == 400
        assert b'ChangeLog must be a mapping' in response.content

    def test_created_manquant_retourne_400(self, factory):
        payload = self._base()
        del payload['Created']
        response = self._post(factory, payload)
        assert response.status_code == 400
        assert b'missing or invalid Created' in response.content

    def test_utf8_invalide_retourne_400(self, factory):
        response = ochecklist_update(factory.post(
            '/ochecklist/update/',
            data=b'\xff\xfe\x00invalid',
            content_type='application/yaml',
        ))
        assert response.status_code == 400
        assert b'UTF-8 required' in response.content

    def test_champs_obligatoires_minimaux_acceptes(self, factory):
        """Name + StartStatus suffisent : Org/ClassName absents → chaîne vide."""
        with patch('ochecklist.views.OchecklistReport') as MockReport, \
             patch('ochecklist.views.OchecklistRunner') as MockRunner, \
             patch('ochecklist.views.OchecklistChangeLog'), \
             patch('ochecklist.views.transaction') as mock_tx:
            mock_tx.atomic.return_value.__enter__ = lambda s: s
            mock_tx.atomic.return_value.__exit__ = MagicMock(return_value=False)
            MockReport.objects.filter.return_value.order_by.return_value.first.return_value = None
            new_report = MagicMock()
            new_report.runners.filter.return_value.first.return_value = None
            MockReport.objects.create.return_value = new_report

            response = self._post(factory, self._base(Data=[{
                'Runner': {'Name': 'Alice', 'StartStatus': 'DNS'},
            }]))
            assert response.status_code == 200
            kwargs = MockRunner.objects.create.call_args.kwargs
            assert kwargs['name'] == 'Alice'
            assert kwargs['org'] == ''
            assert kwargs['class_name'] == ''


# ─── Tests ochecklist_update : payload officiel de l'application ──────────────

class TestOchecklistUpdateOfficialPayload:
    """Le rapport YAML v1.6 documenté par O'checklist est accepté tel quel."""

    OFFICIAL_YAML = """\
Version: 1.6
Creator: "O Checklist v5.5"
Created: 2026-08-30T10:05:45+02:00
Event:   "Demo"
Data:
  - Runner:
      NewCard:     354852
      StartStatus: Started OK
      Id:          null
      Bib:         "1"
      Name:        "Olivia Smith"
      Org:         "Birmingham"
      Card:        215847
      StartTime:   10:00:00
      StartType:   Fixed
      ClassName:   "W21E"
    ChangeLog:
      NewCard:     2026-08-30T09:57:15+02:00
      TickedOff:   2026-08-30T09:57:16+02:00
  - Runner:
      StartStatus: Late start
      Id:          null
      Bib:         "101"
      Name:        "Liam Wilson"
      Org:         "Liverpool"
      Card:        173904
      StartTime:   10:01:00
      StartType:   Fixed
      ClassName:   "M21E"
      Comment:     "Sorry for being late."
    ChangeLog:
      LateStart:   2026-08-30T10:03:35+02:00
      DNS:         2026-08-30T10:01:29+02:00
      Comment:     2026-08-30T10:03:46+02:00
  - Runner:
      StartStatus: DNS
      Id:          null
      Bib:         null
      Name:        "Maya Bennett"
      Org:         "Leicester"
      Card:        257863
      StartTime:   null
      StartType:   Free
      ClassName:   "Open"
    ChangeLog:
      DNS:         2026-08-30T10:04:36+02:00
  - Runner:
      StartStatus: DNS
      Id:          null
      Bib:         "2"
      Name:        "Emma Jones"
      Org:         "Leeds"
      Card:        384126
      StartTime:   10:02:00
      StartType:   Fixed
      ClassName:   "W21E"
    ChangeLog:
      DNS:         2026-08-30T10:02:33+02:00
  - Runner:
      StartStatus: Started OK
      Id:          null
      Bib:         null
      Name:        "Olivia Gray"
      Org:         "Rochdale"
      Card:        1861555
      StartTime:   null
      StartType:   Free
      ClassName:   "Open"
    ChangeLog:
      TickedOff:   2026-08-30T09:58:17+02:00
EndOfData:
  NumRunners: 5
  NumLines:   73
"""

    def test_payload_v16_complet(self, factory):
        with patch('ochecklist.views.OchecklistReport') as MockReport, \
             patch('ochecklist.views.OchecklistRunner') as MockRunner, \
             patch('ochecklist.views.OchecklistChangeLog') as MockChangeLog, \
             patch('ochecklist.views.transaction') as mock_tx:
            mock_tx.atomic.return_value.__enter__ = lambda s: s
            mock_tx.atomic.return_value.__exit__ = MagicMock(return_value=False)
            MockReport.objects.filter.return_value.order_by.return_value.first.return_value = None
            new_report = MagicMock()
            new_report.runners.filter.return_value.first.return_value = None
            MockReport.objects.create.return_value = new_report

            request = factory.post(
                '/ochecklist/update/',
                data=self.OFFICIAL_YAML.encode('utf-8'),
                content_type='application/yaml',
            )
            response = ochecklist_update(request)
            assert response.status_code == 200
            assert response.content == b'OK'

            report_kwargs = MockReport.objects.create.call_args.kwargs
            assert report_kwargs['version'] == '1.6'
            assert report_kwargs['creator'] == 'O Checklist v5.5'
            assert report_kwargs['event'] == 'Demo'

            assert MockRunner.objects.create.call_count == 5
            runners = [c.kwargs for c in MockRunner.objects.create.call_args_list]
            assert runners[0]['name'] == 'Olivia Smith'
            assert runners[0]['start_type'] == 'Fixed'
            assert runners[0]['start_time'].hour == 10
            assert runners[0]['new_card'] == '354852'
            assert runners[2]['start_type'] == 'Free'
            assert runners[2]['start_time'] is None

            assert MockChangeLog.objects.create.call_count == 5
            logs = [c.kwargs for c in MockChangeLog.objects.create.call_args_list]
            assert logs[0]['ticked_off'].hour == 9
            assert logs[0]['ticked_off'].minute == 57
            assert logs[0]['new_card'].minute == 57
            assert logs[4]['ticked_off'].minute == 58
            assert logs[4]['dns'] is None


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

    def test_upsert_par_bib_quand_id_absent(self, factory):
        """Sans Id IOF, le dossard sert de clé avant le nom."""
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
                    'Bib': '7',
                    'Name': 'Alice',
                    'Org': 'CO',
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
            report_mock.runners.filter.assert_any_call(bib='7')
            runner_mock.save.assert_called_once()
            m['Runner'].objects.create.assert_not_called()
        finally:
            self._teardown_mocks()

    def test_upsert_par_nom_quand_id_et_bib_absents(self, factory):
        """Sans Id ni dossard, le nom reste le dernier recours."""
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
                    'Name': 'Alice',
                    'Org': 'CO',
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
            report_mock.runners.filter.assert_any_call(name='Alice')
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

    def test_created_invalide_retourne_400(self, factory):
        """Si Created n'est pas str/datetime/int, la requête est rejetée."""
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
            assert response.status_code == 400
            m['Report'].objects.create.assert_not_called()
        finally:
            self._teardown_mocks()


# ─── Tests ochecklist_update : branches restantes de to_datetime ───────────────

class TestOchecklistUpdateToDatetime:
    """Branches peu fréquentes de to_datetime (naïf, bool, heure seule, secondes)."""

    def _post_created(self, factory, value):
        payload = {
            'Version': '1.5',
            'Creator': 'App',
            'Created': value,
            'Event': 'Evt',
            'Data': [],
        }
        body = yaml.dump(payload, default_flow_style=False).encode('utf-8')
        with patch('ochecklist.views.OchecklistReport') as MockReport, \
             patch('ochecklist.views.OchecklistRunner'), \
             patch('ochecklist.views.OchecklistChangeLog'), \
             patch('ochecklist.views.transaction') as mock_tx:
            mock_tx.atomic.return_value.__enter__ = lambda s: s
            mock_tx.atomic.return_value.__exit__ = MagicMock(return_value=False)
            MockReport.objects.filter.return_value.order_by.return_value.first.return_value = None
            request = factory.post(
                '/ochecklist/update/',
                data=body,
                content_type='application/yaml',
            )
            response = ochecklist_update(request)
            return response, MockReport

    def test_datetime_naif_devient_aware(self, factory):
        """datetime sans tzinfo → timezone.make_aware."""
        response, MockReport = self._post_created(
            factory, datetime.datetime(2024, 10, 12, 12, 45, 4))
        assert response.status_code == 200
        created = MockReport.objects.create.call_args.kwargs['created']
        assert created.tzinfo is not None

    def test_bool_retourne_400(self, factory):
        response, MockReport = self._post_created(factory, True)
        assert response.status_code == 400
        MockReport.objects.create.assert_not_called()

    def test_string_vide_retourne_400(self, factory):
        response, MockReport = self._post_created(factory, '')
        assert response.status_code == 400
        MockReport.objects.create.assert_not_called()

    def test_iso_sans_tz_devient_aware(self, factory):
        response, MockReport = self._post_created(factory, '2024-10-12T12:45:04')
        assert response.status_code == 200
        created = MockReport.objects.create.call_args.kwargs['created']
        assert created.year == 2024 and created.hour == 12
        assert created.tzinfo is not None

    def test_heure_seule_hhmm(self, factory):
        """'12:45' → 2000-01-01 12:45 aware."""
        response, MockReport = self._post_created(factory, '12:45')
        assert response.status_code == 200
        created = MockReport.objects.create.call_args.kwargs['created']
        assert created.year == 2000 and created.hour == 12 and created.minute == 45
        assert created.tzinfo is not None

    def test_heure_seule_hhmmss(self, factory):
        """'12:45:30' → 2000-01-01 12:45:30 aware."""
        response, MockReport = self._post_created(factory, '12:45:30')
        assert response.status_code == 200
        created = MockReport.objects.create.call_args.kwargs['created']
        assert created.second == 30

    def test_string_invalide_retourne_400(self, factory):
        """Ni ISO ni heure seule → 400 (Created est obligatoire)."""
        response, MockReport = self._post_created(factory, 'pas-une-date')
        assert response.status_code == 400
        MockReport.objects.create.assert_not_called()

    def test_secondes_converties(self, factory):
        """45000 s → 2000-01-01 12:30:00 aware."""
        response, MockReport = self._post_created(factory, 45000)
        assert response.status_code == 200
        created = MockReport.objects.create.call_args.kwargs['created']
        assert created.hour == 12 and created.minute == 30 and created.second == 0

    def test_secondes_au_dela_24h_rebouclent(self, factory):
        """90000 s → modulo 86400 → 01:00:00."""
        response, MockReport = self._post_created(factory, 90000)
        assert response.status_code == 200
        created = MockReport.objects.create.call_args.kwargs['created']
        assert created.hour == 1 and created.minute == 0


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
            'TickedOff': '2024-10-12T12:30:00+02:00',
            'DNS': '2024-10-12T12:31:22+02:00',
            'LateStart': '2024-10-12T12:37:02+02:00',
            'NewCard': '2024-10-12T12:35:34+02:00',
            'Comment': '2024-10-12T12:40:08+02:00',
            'NewRunner': '2024-10-12T12:43:14+02:00',
        }
        cl_expected = {
            'ticked_off': datetime.datetime(2024, 10, 12, 12, 30, 0, tzinfo=tz),
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
            assert kwargs['ticked_off'] == cl_expected['ticked_off']
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

    def test_mise_a_jour_runner_existant_tous_champs_changelog(self, factory):
        """Runner existant : Bib + StartType + NewCard + Comment, et changelog complet."""
        changelog_mock = MagicMock()
        report_mock = MagicMock()
        report_mock.version = 'old'
        report_mock.creator = 'old'
        report_mock.created = None
        runner_mock = MagicMock()
        report_mock.runners.filter.return_value.first.return_value = runner_mock
        cl = {
            'TickedOff': '2024-10-12T12:30:00+02:00',
            'LateStart': '2024-10-12T12:37:02+02:00',
            'NewCard': '2024-10-12T12:35:34+02:00',
            'Comment': '2024-10-12T12:40:08+02:00',
            'NewRunner': '2024-10-12T12:43:14+02:00',
        }
        m = self._setup(cl, existing_report=report_mock)
        m['ChangeLog'].objects.get_or_create.return_value = (changelog_mock, False)
        try:
            runner = make_runner(name='Alice', new_card='222', comment='En retard',
                                 changelog=cl)
            runner['Runner']['Bib'] = '7'
            runner['Runner']['StartType'] = 'Free'
            body = make_yaml(event='Same Event', runners=[runner])
            response = ochecklist_update(self._post(factory, body))
            assert response.status_code == 200
            assert runner_mock.bib == '7'
            assert runner_mock.start_type == 'Free'
            assert runner_mock.new_card == '222'
            assert runner_mock.comment == 'En retard'
            changelog_mock.save.assert_called_once()
            assert changelog_mock.ticked_off is not None
            assert changelog_mock.late_start is not None
            assert changelog_mock.new_card is not None
            assert changelog_mock.comment is not None
            assert changelog_mock.new_runner is not None
            m['ChangeLog'].objects.create.assert_not_called()
        finally:
            self._teardown()

    def test_changelog_cle_inconnue_ne_cree_rien(self, factory):
        """Une clé ChangeLog non reconnue ne doit pas créer de ligne vide."""
        m = self._setup({'CleInconnue': '2024-10-12T12:34:56+02:00'})
        try:
            body = make_yaml(runners=[make_runner(
                changelog={'CleInconnue': '2024-10-12T12:34:56+02:00'},
            )])
            response = ochecklist_update(self._post(factory, body))
            assert response.status_code == 200
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

class TestBuildReportVersion:

    def test_version_globale(self):
        with patch('ochecklist.views.OchecklistReport') as MockReport:
            MockReport.objects.aggregate.return_value = {
                'latest_created': datetime.datetime(2024, 10, 12, 12, 0),
                'latest_received': datetime.datetime(2024, 10, 12, 12, 1),
                'report_count': 2,
                'runner_count': 5,
                'latest_runner': 9,
            }
            version = build_report_version()
            assert version == '2024-10-12 12:00:00|2024-10-12 12:01:00|2|5|9'
            MockReport.objects.aggregate.assert_called_once()

    def test_version_globale_vide(self):
        with patch('ochecklist.views.OchecklistReport') as MockReport:
            MockReport.objects.aggregate.return_value = {
                'latest_created': None,
                'latest_received': None,
                'report_count': 0,
                'runner_count': 0,
                'latest_runner': None,
            }
            assert build_report_version() == '||0|0|'

    def test_version_rapport(self):
        report = MagicMock(created=datetime.datetime(2024, 10, 12, 12, 0))
        report.runners.aggregate.return_value = {
            'runner_count': 5,
            'latest_runner': 9,
        }
        assert build_report_version(report) == '2024-10-12 12:00:00|5|9'
        report.runners.aggregate.assert_called_once()


class TestReportVersionView:

    def test_version_globale_json(self, factory):
        request = factory.get('/ochecklist/version/')
        with patch('ochecklist.views.build_report_version', return_value='v1'):
            response = report_version(request)
        assert response.status_code == 200
        assert response['Content-Type'] == 'application/json'
        assert json.loads(response.content) == {'version': 'v1'}

    def test_version_par_rapport(self, factory):
        report = MagicMock(id=3)
        request = factory.get('/ochecklist/version/', data={'report': '3'})
        with patch('ochecklist.views.get_object_or_404', return_value=report) as mock_get, \
             patch('ochecklist.views.build_report_version', return_value='v3') as mock_version:
            response = report_version(request)
        mock_get.assert_called_once_with(OchecklistReport, id=3)
        mock_version.assert_called_once_with(report)
        assert json.loads(response.content) == {'version': 'v3'}

    def test_id_invalide(self, factory):
        request = factory.get('/ochecklist/version/', data={'report': 'abc'})
        with patch('ochecklist.views.get_object_or_404') as mock_get:
            response = report_version(request)
        assert response.status_code == 400
        assert response.content == b'Invalid report id'
        mock_get.assert_not_called()

    def test_rapport_introuvable(self, factory):
        request = factory.get('/ochecklist/version/', data={'report': '999'})
        with patch('ochecklist.views.get_object_or_404',
                   side_effect=Http404('not found')):
            with pytest.raises(Http404):
                report_version(request)

    def test_post_refuse(self, factory):
        request = factory.post('/ochecklist/version/')
        response = report_version(request)
        assert response.status_code == 405

    def test_reponse_non_cachee(self, factory):
        request = factory.get('/ochecklist/version/')
        with patch('ochecklist.views.build_report_version', return_value='v1'):
            response = report_version(request)
        assert 'no-cache' in response['Cache-Control']
        assert 'no-store' in response['Cache-Control']


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

    def test_contexte_version(self, factory):
        request = factory.get('/ochecklist/')
        with patch('ochecklist.views.OchecklistReport') as MockReport, \
             patch('ochecklist.views.build_report_version', return_value='v-list'), \
             patch('ochecklist.views.render') as mock_render:
            MockReport.objects.all.return_value = []
            mock_render.return_value = HttpResponse('ok')
            report_list(request)
            assert mock_render.call_args[0][2]['ochecklist_version'] == 'v-list'


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
             patch('ochecklist.views.build_report_version', return_value='v-report'), \
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
            assert ctx['ochecklist_version'] == 'v-report'

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
             patch('ochecklist.views.build_report_version', return_value='v-runner') as mock_version, \
             patch('ochecklist.views.render') as mock_render:
            mock_render.return_value = HttpResponse('ok')
            request = factory.get('/ochecklist/runner/42/')
            response = runner_detail(request, runner_id=42)
            assert response.status_code == 200
            assert mock_render.call_args[0][1] == 'ochecklist/runner_detail.html'
            assert mock_render.call_args[0][2] == {
                'runner': runner,
                'ochecklist_version': 'v-runner',
            }
            mock_version.assert_called_once_with(runner.report)

    def test_404_si_runner_introuvable(self, factory):
        with patch('ochecklist.views.get_object_or_404',
                   side_effect=Http404('not found')):
            request = factory.get('/ochecklist/runner/999/')
            with pytest.raises(Http404):
                runner_detail(request, runner_id=999)
