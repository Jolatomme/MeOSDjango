"""
import_iof.py — Import d'un fichier IOF Data Standard v3 ``ResultList``.

Usage :
    python manage.py import_iof resultats.xml --cid 12
    python manage.py import_iof resultats.xml --cid 12 --race 2
    python manage.py import_iof resultats.xml --cid 12 --dry-run
    python manage.py import_iof resultats.xml --cid 12 --yes

L'import remplace intégralement les résultats de la course (même sémantique
qu'un ``MOPComplete`` MeOS). Les informations de course saisies sur le site
sont conservées, sauf avec ``--use-event-metadata``.
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from results.iof_importer import (
    IofImportError, import_iof_result_list, inspect_iof_result_list,
)


class Command(BaseCommand):
    help = (
        "Importe un fichier IOF Data Standard v3 ResultList dans une course "
        "(remplacement complet des résultats)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            'file', type=Path,
            help="Fichier XML IOF ResultList à importer.",
        )
        parser.add_argument(
            '--cid', type=int, required=True,
            help="Identifiant interne de la course (cid).",
        )
        parser.add_argument(
            '--race', dest='race_number', type=int, default=None,
            help="Numéro de course à importer (fichier multi-course).",
        )
        parser.add_argument(
            '--use-event-metadata', action='store_true',
            help=(
                "Utilise le nom, la date, l'organisateur et le site web du "
                "fichier IOF au lieu des informations saisies sur le site."
            ),
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help="Analyse le fichier sans écrire en base.",
        )
        parser.add_argument(
            '--yes', action='store_true',
            help="Ne pas demander de confirmation avant de remplacer les résultats.",
        )

    def handle(self, *args, **options):
        path = options['file']
        cid = options['cid']
        race_number = options['race_number']
        use_event_metadata = options['use_event_metadata']
        dry_run = options['dry_run']

        try:
            xml_data = path.read_bytes()
        except OSError as exc:
            raise CommandError(
                f"Impossible de lire le fichier « {path} » : {exc}"
            ) from exc

        if not dry_run and not options['yes']:
            self._confirm(cid)

        try:
            if dry_run:
                report = inspect_iof_result_list(
                    xml_data,
                    cid=cid,
                    race_number=race_number,
                    use_event_metadata=use_event_metadata,
                )
            else:
                report = import_iof_result_list(
                    cid,
                    xml_data,
                    race_number=race_number,
                    use_event_metadata=use_event_metadata,
                )
        except IofImportError as exc:
            raise CommandError(str(exc)) from exc

        if report.status == 'FROZEN':
            raise CommandError(
                f"La course cid={cid} est gelée : aucun résultat n'a été importé. "
                "Dégèle-la dans MeOS avant de réessayer."
            )

        self._print_report(report, dry_run=dry_run)

    def _confirm(self, cid):
        try:
            answer = input(
                f"Remplacer tous les résultats de la course cid={cid} ? [y/N] "
            )
        except EOFError:
            answer = ''
        if answer.strip().lower() not in ('y', 'yes', 'o', 'oui'):
            raise CommandError("Import annulé.")

    def _print_report(self, report, *, dry_run):
        heading = "Analyse terminée (aucune écriture)" if dry_run else "Import terminé"
        self.stdout.write(self.style.SUCCESS(heading))
        self.stdout.write(f"  Course          : {report.competition_name}")
        if report.race_number is not None:
            self.stdout.write(f"  Numéro de course: {report.race_number}")
        self.stdout.write(f"  Classes         : {report.classes}")
        self.stdout.write(f"  Concurrents     : {report.competitors}")
        self.stdout.write(f"  Équipes         : {report.teams}")
        self.stdout.write(f"  Postes          : {report.controls}")
        self.stdout.write(f"  Pointages       : {report.splits}")

        if report.warnings:
            self.stdout.write(self.style.WARNING(
                f"  Avertissements  : {len(report.warnings)}"
            ))
            for warning in report.warnings:
                self.stdout.write(f"    - {warning}")
        else:
            self.stdout.write("  Avertissements  : aucun")
