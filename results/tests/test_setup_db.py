"""
Tests du schéma mop* géré par `python manage.py setup_db`.

Les tables mop* ne sont pas créées par Django (models managed=False) :
setup_db crée les tables manquantes et ajoute les colonnes absentes des
bases existantes (MISSING_COLUMN_ALTERS).
"""

from results.management.commands.setup_db import (
    CREATE_TABLES,
    MISSING_COLUMN_ALTERS,
)


class TestLiveloxColumn:
    """Colonne mopCompetition.livelox (site Livelox renseigné côté formulaire)."""

    def test_present_dans_le_create_table(self):
        sql = CREATE_TABLES['mopCompetition']
        assert "`livelox` VARCHAR(128) NOT NULL DEFAULT ''" in sql

    def test_alter_pour_les_bases_existantes(self):
        sql = MISSING_COLUMN_ALTERS['mopCompetition']['livelox']
        assert sql.startswith('ALTER TABLE `mopCompetition`')
        assert 'ADD COLUMN `livelox` VARCHAR(128)' in sql

    def test_colonne_ajoutee_apres_coup_memes_bibliotheques_que_card(self):
        """Le mécanisme historique (mopCompetitor.card) reste en place."""
        assert 'livelox' in MISSING_COLUMN_ALTERS['mopCompetition']
        assert 'card' in MISSING_COLUMN_ALTERS['mopCompetitor']


class TestLogoColumn:
    """Colonne mopCompetition.logo (fichier de logo de l'organisateur)."""

    def test_present_dans_le_create_table(self):
        sql = CREATE_TABLES['mopCompetition']
        assert "`logo` VARCHAR(128) NOT NULL DEFAULT ''" in sql

    def test_alter_pour_les_bases_existantes(self):
        sql = MISSING_COLUMN_ALTERS['mopCompetition']['logo']
        assert sql.startswith('ALTER TABLE `mopCompetition`')
        assert 'ADD COLUMN `logo` VARCHAR(128)' in sql

    def test_livelox_et_logo_presents(self):
        assert 'livelox' in MISSING_COLUMN_ALTERS['mopCompetition']
        assert 'logo' in MISSING_COLUMN_ALTERS['mopCompetition']
