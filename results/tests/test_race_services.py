"""
Tests des services de création de courses (DB mockée).

Couvre :
  - next_cid         : max(mopCompetition, results_competitionconfig) + 1
  - create_race      : config + ligne mopCompetition pré-remplie, secrets
  - regenerate_api_key
  - find_race_by_key
"""

import re
from unittest.mock import patch, MagicMock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import override_settings

PNG_MAGIC = b'\x89PNG\r\n\x1a\n'


# ─── next_cid ──────────────────────────────────────────────────────────────────

def _patched_connection(mop_max, cfg_max):
    """Patch results.services.connection avec deux fetchone() successifs."""
    cur = MagicMock()
    cur.fetchone.side_effect = [(mop_max,), (cfg_max,)]
    patcher = patch('results.services.connection')
    mock_conn = patcher.start()
    mock_conn.cursor.return_value.__enter__ = lambda s: cur
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return patcher, cur


class TestNextCid:

    def test_max_des_deux_tables(self):
        from results.services import next_cid
        patcher, cur = _patched_connection(5, 9)
        try:
            assert next_cid() == 10
        finally:
            patcher.stop()
        sqls = [c[0][0] for c in cur.execute.call_args_list]
        assert any('mopCompetition' in s for s in sqls)
        assert any('results_competitionconfig' in s for s in sqls)

    def test_tables_vides(self):
        from results.services import next_cid
        patcher, _ = _patched_connection(None, None)
        try:
            assert next_cid() == 1
        finally:
            patcher.stop()

    def test_mop_max_plus_grand(self):
        from results.services import next_cid
        patcher, _ = _patched_connection(42, 3)
        try:
            assert next_cid() == 43
        finally:
            patcher.stop()


# ─── create_race ───────────────────────────────────────────────────────────────

class TestCreateRace:

    @patch('results.services.transaction.atomic')
    @patch('results.services.Mopcompetition')
    @patch('results.services.CompetitionConfig')
    @patch('results.services.next_cid', return_value=11)
    def test_cree_config_et_competition(
        self, mock_next, MockConfig, MockComp, mock_atomic,
    ):
        from results.services import create_race
        config = MagicMock(manage_token='t' * 43)
        MockConfig.objects.create.return_value = config

        result = create_race(
            name='Trail', date='2026-05-17', organizer='COCS',
            homepage='https://example.org',
            livelox='https://livelox.example/42',
            logo='logo-abc123def456.png',
        )

        assert result is config
        mock_next.assert_called_once()
        kwargs = MockConfig.objects.create.call_args.kwargs
        assert kwargs['cid'] == 11
        assert len(kwargs['api_key']) == 43       # token_urlsafe(32)
        assert len(kwargs['manage_token']) == 43
        assert kwargs['visible'] is True
        assert kwargs['frozen'] is False
        assert kwargs['deleted'] is False
        MockComp.objects.create.assert_called_once_with(
            cid=11, id=1, name='Trail', date='2026-05-17',
            organizer='COCS', homepage='https://example.org',
            livelox='https://livelox.example/42',
            logo='logo-abc123def456.png',
        )

    @patch('results.services.transaction.atomic')
    @patch('results.services.Mopcompetition')
    @patch('results.services.CompetitionConfig')
    @patch('results.services.next_cid', return_value=11)
    def test_cree_sans_livelox_ni_logo_vide(
        self, mock_next, MockConfig, MockComp, mock_atomic,
    ):
        """livelox/logo absents → chaînes vides stockées dans mopCompetition."""
        MockConfig.objects.create.return_value = MagicMock()

        from results.services import create_race
        create_race(name='Trail', date='2026-05-17', organizer='COCS')

        kwargs = MockComp.objects.create.call_args.kwargs
        assert kwargs['livelox'] == ''
        assert kwargs['logo'] == ''

    @patch('results.services.transaction.atomic')
    @patch('results.services.Mopcompetition')
    @patch('results.services.CompetitionConfig')
    @patch('results.services.next_cid', side_effect=[11, 12])
    def test_reessaie_sur_conflit_cid(
        self, mock_next, MockConfig, MockComp, mock_atomic,
    ):
        """Un conflit de CID (course créée entre-temps) déclenche une nouvelle tentative."""
        from results.services import create_race
        MockConfig.objects.create.side_effect = [IntegrityError('dup'), MagicMock()]

        create_race(name='Trail', date='2026-05-17', organizer='COCS')

        assert mock_next.call_count == 2
        assert MockConfig.objects.create.call_count == 2
        assert MockConfig.objects.create.call_args_list[1].kwargs['cid'] == 12

    @patch('results.services.transaction.atomic')
    @patch('results.services.Mopcompetition')
    @patch('results.services.CompetitionConfig')
    @patch('results.services.next_cid', side_effect=[11, 12, 13])
    def test_echec_apres_3_tentatives(
        self, mock_next, MockConfig, MockComp, mock_atomic,
    ):
        from results.services import create_race
        MockConfig.objects.create.side_effect = IntegrityError('dup')

        with pytest.raises(IntegrityError):
            create_race(name='Trail', date='2026-05-17', organizer='COCS')
        assert mock_next.call_count == 3


# ─── save_org_logo / delete_org_logo ──────────────────────────────────────────

class TestSaveOrgLogo:

    def test_ecrit_sous_un_nom_unique(self, tmp_path):
        from results.services import save_org_logo
        f = SimpleUploadedFile(
            'Mon Logo (1).png', PNG_MAGIC + b'\x00' * 16,
            content_type='image/png',
        )
        with override_settings(ORG_LOGO_DIR=tmp_path):
            name = save_org_logo(f)
        assert re.fullmatch(r'logo-[0-9a-f]{12}\.png', name)
        assert (tmp_path / name).read_bytes().startswith(PNG_MAGIC)
        assert not (tmp_path / 'Mon Logo (1).png').exists()   # nom utilisateur absent

    def test_deux_sauvegardes_ne_collident_pas(self, tmp_path):
        from results.services import save_org_logo
        with override_settings(ORG_LOGO_DIR=tmp_path):
            n1 = save_org_logo(SimpleUploadedFile('a.svg', b'<svg/>'))
            n2 = save_org_logo(SimpleUploadedFile('a.svg', b'<svg/>'))
        assert n1 != n2

    def test_cree_le_dossier_manquant(self, tmp_path):
        from results.services import save_org_logo
        target = tmp_path / 'nested' / 'org_logo'
        with override_settings(ORG_LOGO_DIR=target):
            name = save_org_logo(SimpleUploadedFile('a.jpg', b'\xff\xd8\xff\x00'))
        assert (target / name).is_file()


class TestDeleteOrgLogo:

    def test_supprime_le_fichier(self, tmp_path):
        from results.services import delete_org_logo
        target = tmp_path / 'logo-abc.svg'
        target.write_text('<svg/>')
        with override_settings(ORG_LOGO_DIR=tmp_path):
            delete_org_logo('logo-abc.svg')
        assert not target.exists()

    def test_nom_vide_ou_invalide_ne_fait_rien(self, tmp_path):
        from results.services import delete_org_logo
        outside = tmp_path / 'secret.txt'
        outside.write_text('x')
        parent_file = tmp_path.parent / 'logo-x.svg'
        parent_file.write_text('<svg/>')
        try:
            with override_settings(ORG_LOGO_DIR=tmp_path):
                delete_org_logo('')
                delete_org_logo(None)
                delete_org_logo('../logo-x.svg')
                delete_org_logo('a/b.svg')
                delete_org_logo('a\\b.svg')
            assert outside.exists()
            assert parent_file.exists()
        finally:
            parent_file.unlink(missing_ok=True)

    def test_fichier_absent_ne_plante_pas(self, tmp_path):
        from results.services import delete_org_logo
        with override_settings(ORG_LOGO_DIR=tmp_path):
            delete_org_logo('logo-inexistant.svg')

    def test_erreur_os_avertit_sans_propager(self, tmp_path):
        """Un dossier homonyme provoque OSError : simple warning, pas d'erreur."""
        from results.services import delete_org_logo
        (tmp_path / 'logo-bloquant.svg').mkdir()
        with override_settings(ORG_LOGO_DIR=tmp_path):
            with patch('results.services.logger') as mock_logger:
                delete_org_logo('logo-bloquant.svg')
        mock_logger.warning.assert_called_once()
        assert 'logo-bloquant.svg' in mock_logger.warning.call_args[0][-1]


# ─── regenerate_api_key / find_race_by_key ────────────────────────────────────

class TestKeyServices:

    @patch('results.services.CompetitionConfig')
    def test_regenerate_remplace_la_cle(self, MockConfig):
        from results.services import regenerate_api_key
        config = MagicMock()
        config.api_key = 'ancienne-cle'

        new_key = regenerate_api_key(config)

        assert new_key != 'ancienne-cle'
        assert len(new_key) == 43
        assert config.api_key == new_key
        config.save.assert_called_once_with(update_fields=['api_key'])

    @patch('results.services.CompetitionConfig')
    def test_regenerate_remplace_le_jeton(self, MockConfig):
        from results.services import regenerate_manage_token
        config = MagicMock()
        config.manage_token = 'ancien-jeton'

        new_token = regenerate_manage_token(config)

        assert new_token != 'ancien-jeton'
        assert len(new_token) == 43
        assert config.manage_token == new_token
        config.save.assert_called_once_with(update_fields=['manage_token'])

    @patch('results.services.CompetitionConfig')
    def test_find_race_by_key(self, MockConfig):
        from results.services import find_race_by_key
        config = MagicMock()
        MockConfig.objects.filter.return_value.first.return_value = config

        result = find_race_by_key('ma-cle')

        assert result is config
        MockConfig.objects.filter.assert_called_once_with(api_key='ma-cle')

    @patch('results.services.CompetitionConfig')
    def test_find_race_by_key_vide(self, MockConfig):
        from results.services import find_race_by_key
        assert find_race_by_key('') is None
        assert find_race_by_key(None) is None
        MockConfig.objects.filter.assert_not_called()

    @patch('results.services.CompetitionConfig')
    def test_find_race_by_key_erreur_db_retourne_none(self, MockConfig):
        from results.services import find_race_by_key
        MockConfig.objects.filter.side_effect = RuntimeError('db down')
        assert find_race_by_key('ma-cle') is None
