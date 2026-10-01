"""
Tests des services de création de courses (DB mockée).

Couvre :
  - next_cid         : max(mopCompetition, results_competitionconfig) + 1
  - create_race      : config + ligne mopCompetition pré-remplie, secrets
  - regenerate_api_key
  - find_race_by_key
"""

from unittest.mock import patch, MagicMock

import pytest
from django.db import IntegrityError


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
        )

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
