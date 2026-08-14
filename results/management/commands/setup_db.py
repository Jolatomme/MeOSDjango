from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction


CREATE_TABLES = {
    "mopCompetition": """CREATE TABLE IF NOT EXISTS `mopCompetition` (
        `cid` INT NOT NULL,
        `id` INT NOT NULL,
        PRIMARY KEY (`cid`, `id`),
        `name` VARCHAR(64) NOT NULL DEFAULT '',
        `date` DATE NOT NULL DEFAULT '2013-11-04',
        `organizer` VARCHAR(64) NOT NULL DEFAULT '',
        `homepage` VARCHAR(128) NOT NULL DEFAULT ''
    ) ENGINE = InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",

    "mopControl": """CREATE TABLE IF NOT EXISTS `mopControl` (
        `cid` INT NOT NULL,
        `id` INT NOT NULL,
        PRIMARY KEY (`cid`, `id`),
        `name` VARCHAR(64) NOT NULL DEFAULT ''
    ) ENGINE = InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",

    "mopClass": """CREATE TABLE IF NOT EXISTS `mopClass` (
        `cid` INT NOT NULL,
        `id` INT NOT NULL,
        PRIMARY KEY (`cid`, `id`),
        `name` VARCHAR(64) NOT NULL DEFAULT '',
        `ord` INT NOT NULL DEFAULT 0,
        INDEX(`ord`)
    ) ENGINE = InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",

    "mopOrganization": """CREATE TABLE IF NOT EXISTS `mopOrganization` (
        `cid` INT NOT NULL,
        `id` INT NOT NULL,
        PRIMARY KEY (`cid`, `id`),
        `name` VARCHAR(64) NOT NULL DEFAULT ''
    ) ENGINE = InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",

    "mopCompetitor": """CREATE TABLE IF NOT EXISTS `mopCompetitor` (
        `cid` INT NOT NULL,
        `id` INT NOT NULL,
        PRIMARY KEY (`cid`, `id`),
        `name` VARCHAR(64) NOT NULL DEFAULT '',
        `card` VARCHAR(32) NOT NULL DEFAULT '',
        `bib` VARCHAR(32) NOT NULL DEFAULT '',
        `org` INT NOT NULL DEFAULT 0,
        `cls` INT NOT NULL DEFAULT 0,
        `stat` TINYINT NOT NULL DEFAULT 0,
        `st` INT NOT NULL DEFAULT 0,
        `rt` INT NOT NULL DEFAULT 0,
        INDEX(`org`),
        INDEX(`cls`),
        INDEX(`stat`, `rt`),
        INDEX(`st`),
        `tstat` TINYINT NOT NULL DEFAULT 0,
        `it` INT NOT NULL DEFAULT 0
    ) ENGINE = InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",

    "mopTeam": """CREATE TABLE IF NOT EXISTS `mopTeam` (
        `cid` INT NOT NULL,
        `id` INT NOT NULL,
        PRIMARY KEY (`cid`, `id`),
        `name` VARCHAR(64) NOT NULL DEFAULT '',
        `org` INT NOT NULL DEFAULT 0,
        `cls` INT NOT NULL DEFAULT 0,
        `stat` TINYINT NOT NULL DEFAULT 0,
        `st` INT NOT NULL DEFAULT 0,
        `rt` INT NOT NULL DEFAULT 0,
        INDEX(`org`),
        INDEX(`cls`),
        INDEX(`stat`, `rt`),
        INDEX(`st`)
    ) ENGINE = InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",

    "mopTeamMember": """CREATE TABLE IF NOT EXISTS `mopTeamMember` (
        `cid` INT NOT NULL,
        `id` INT NOT NULL,
        `leg` TINYINT NOT NULL,
        `ord` TINYINT NOT NULL,
        PRIMARY KEY(`cid`, `id`, `leg`, `ord`),
        `rid` INT NOT NULL DEFAULT 0
    ) ENGINE = InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",

    "mopClassControl": """CREATE TABLE IF NOT EXISTS `mopClassControl` (
        `cid` INT NOT NULL,
        `id` INT NOT NULL,
        `leg` TINYINT NOT NULL,
        `ord` TINYINT NOT NULL,
        PRIMARY KEY(`cid`, `id`, `leg`, `ord`),
        `ctrl` INT NOT NULL DEFAULT 0
    ) ENGINE = InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",

    "mopRadio": """CREATE TABLE IF NOT EXISTS `mopRadio` (
        `cid` INT NOT NULL,
        `id` INT NOT NULL,
        `ctrl` INT NOT NULL,
        PRIMARY KEY(`cid`, `id`, `ctrl`),
        `rt` INT NOT NULL DEFAULT 0
    ) ENGINE = InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
}

TABLE_ORDER = [
    "mopCompetition",
    "mopControl",
    "mopClass",
    "mopOrganization",
    "mopCompetitor",
    "mopTeam",
    "mopTeamMember",
    "mopClassControl",
    "mopRadio",
]

# Colonnes ajoutées après la création d'origine des tables (bases existantes).
MISSING_COLUMN_ALTERS = {
    "mopCompetitor": {
        "card": "ALTER TABLE `mopCompetitor` "
                "ADD COLUMN `card` VARCHAR(32) NOT NULL DEFAULT ''",
        "bib": "ALTER TABLE `mopCompetitor` "
               "ADD COLUMN `bib` VARCHAR(32) NOT NULL DEFAULT ''",
    },
}


class Command(BaseCommand):
    help = "Create the MeOS mop* tables (InnoDB, utf8mb4) in the database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show SQL that would be executed without running it.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Drop existing tables before creating (DANGEROUS).",
        )
        parser.add_argument(
            "--fake-initial",
            action="store_true",
            help="Mark tables as already created in django_migrations (for existing DBs).",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        force = options["force"]
        fake_initial = options["fake_initial"]

        if force and dry_run:
            raise CommandError("Cannot use --force with --dry-run (use --dry-run alone to preview without --force)")

        with connection.cursor() as cursor:
            cursor.execute("SHOW TABLES LIKE 'mop%%'")
            existing = {row[0] for row in cursor.fetchall()}

        to_create = [t for t in TABLE_ORDER if t not in existing]
        to_drop = [t for t in TABLE_ORDER if t in existing] if force else []

        if dry_run:
            self.stdout.write(self.style.NOTICE("DRY RUN - SQL that would be executed:"))
            self.stdout.write("")
            if to_drop:
                self.stdout.write(self.style.WARNING("-- DROP TABLES --"))
                for t in to_drop:
                    self.stdout.write(f"DROP TABLE IF EXISTS `{t}`;")
                self.stdout.write("")
            if to_create:
                self.stdout.write(self.style.NOTICE("-- CREATE TABLES --"))
                for t in to_create:
                    self.stdout.write(CREATE_TABLES[t] + ";")
                self.stdout.write("")
            missing_alters = self._missing_columns(existing)
            if missing_alters:
                self.stdout.write(self.style.NOTICE("-- ALTER TABLES --"))
                for sql in missing_alters:
                    self.stdout.write(sql + ";")
                self.stdout.write("")
            if not to_create and not to_drop and not missing_alters:
                self.stdout.write(self.style.WARNING("No tables to create or drop."))
            return

        if to_drop:
            self.stdout.write(self.style.WARNING(f"Dropping {len(to_drop)} existing table(s)..."))
            with connection.cursor() as cursor:
                for t in to_drop:
                    cursor.execute(f"DROP TABLE IF EXISTS `{t}`")
                    self.stdout.write(f"  Dropped `{t}`")

        if to_create:
            self.stdout.write(self.style.NOTICE(f"Creating {len(to_create)} table(s)..."))
            created = []

            with transaction.atomic():
                with connection.cursor() as cursor:
                    for t in to_create:
                        try:
                            cursor.execute(CREATE_TABLES[t])
                            created.append(t)
                            self.stdout.write(self.style.SUCCESS(f"  [OK] Created `{t}`"))
                        except Exception as e:
                            self.stdout.write(self.style.ERROR(f"  [FAIL] Failed `{t}`: {e}"))
                            raise

                if fake_initial:
                    from django.db.migrations.recorder import MigrationRecorder
                    recorder = MigrationRecorder(connection)
                    recorder.record_applied("results", "0001_initial")

            self.stdout.write(self.style.SUCCESS(f"\nDone. Created {len(created)} table(s)."))

        missing_alters = self._missing_columns(existing | set(to_create))
        if missing_alters:
            self.stdout.write(self.style.NOTICE("Adding missing columns..."))
            for sql in missing_alters:
                with connection.cursor() as cursor:
                    try:
                        cursor.execute(sql)
                        self.stdout.write(self.style.SUCCESS(f"  [OK] {sql}"))
                    except Exception as e:
                        self.stdout.write(self.style.ERROR(f"  [FAIL] {sql}: {e}"))
                        raise

    def _missing_columns(self, existing: set) -> list:
        """Retourne les ALTER TABLE nécessaires pour les colonnes manquantes."""
        missing = []
        for table, columns in MISSING_COLUMN_ALTERS.items():
            if table not in existing:
                continue
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
                    [table],
                )
                present = {row[0] for row in cursor.fetchall()}
            missing += [sql for col, sql in columns.items() if col not in present]
        return missing