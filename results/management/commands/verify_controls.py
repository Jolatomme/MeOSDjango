"""
verify_controls.py — Vérification des poinçons radio d'un relayeur.

Usage:
    python manage.py verify_controls --cid 1 --class H21 --leg 1 --name "Rudy GOUY"
    python manage.py verify_controls --cid 1 --class H21 --leg 1 --rid 160
    python manage.py verify_controls --cid 1 --class H21 --leg 1           # liste tous les relayeurs leg1

Tables: mopTeam, mopTeamMember, mopCompetitor, mopRadio, mopControl
        (managed=False, voir results/models.py)
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from results.models import format_time


def _resolve_class_id(cid, class_arg):
    """Accepte id numérique ou nom de catégorie."""
    if str(class_arg).isdigit():
        return int(class_arg)
    with connection.cursor() as cur:
        cur.execute(
            "SELECT id, name FROM mopClass WHERE cid=%s AND name=%s",
            [cid, class_arg],
        )
        row = cur.fetchone()
        if not row:
            raise CommandError(f"Classe '{class_arg}' introuvable pour cid={cid}")
        return row[0]


def _class_name(cid, class_id):
    with connection.cursor() as cur:
        cur.execute("SELECT name FROM mopClass WHERE cid=%s AND id=%s", [cid, class_id])
        row = cur.fetchone()
        return row[0] if row else str(class_id)


class Command(BaseCommand):
    help = "Vérifie les poinçons mopRadio d'un relayeur (par leg)."

    def add_arguments(self, parser):
        parser.add_argument("--cid", type=int, required=True, help="Competition id (cid)")
        parser.add_argument("--class", dest="class_arg", required=True, help="Classe id ou nom (ex: 1 ou H21)")
        parser.add_argument("--leg", type=int, required=True, help="Fraction relais 1-based (1..n)")
        parser.add_argument("--name", dest="runner_name", default=None, help="Nom exact du coureur (ex: 'Rudy GOUY')")
        parser.add_argument("--rid", type=int, default=None, help="Id coureur (alternative à --name)")
        parser.add_argument("--verbose", action="store_true", help="Affiche détails équipe + tronçons (sans attente vs parcours)")
        parser.add_argument("--sql-only", action="store_true", help="Affiche les requêtes SQL équivalentes")

    def handle(self, *args, **options):
        cid = options["cid"]
        class_arg = options["class_arg"]
        leg = options["leg"]
        runner_name = options["runner_name"]
        rid_filter = options["rid"]
        verbose = options["verbose"]
        sql_only = options["sql_only"]

        class_id = _resolve_class_id(cid, class_arg)
        cls_name = _class_name(cid, class_id)

        # — competition label
        comp_label = f"cid={cid}"
        with connection.cursor() as cur:
            cur.execute("SELECT name, date FROM mopCompetition WHERE cid=%s", [cid])
            row = cur.fetchone()
            if row:
                comp_label = f"{row[0]} (cid={cid} {row[1]})"

        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{comp_label} — classe {cls_name} leg {leg}"))

        # — relayeurs du leg
        with connection.cursor() as cur:
            if runner_name and rid_filter:
                raise CommandError("Utiliser --name OU --rid, pas les deux")
            if rid_filter is not None:
                cur.execute(
                    """
                    SELECT tm.rid, c.name, t.id, t.name, c.st, c.rt, c.stat, c.tstat
                    FROM mopTeamMember tm
                    JOIN mopTeam t ON t.cid=tm.cid AND t.id=tm.id
                    JOIN mopCompetitor c ON c.cid=tm.cid AND c.id=tm.rid
                    WHERE tm.cid=%s AND t.cls=%s AND tm.leg=%s AND tm.rid=%s
                    """,
                    [cid, class_id, leg, rid_filter],
                )
            elif runner_name:
                cur.execute(
                    """
                    SELECT tm.rid, c.name, t.id, t.name, c.st, c.rt, c.stat, c.tstat
                    FROM mopTeamMember tm
                    JOIN mopTeam t ON t.cid=tm.cid AND t.id=tm.id
                    JOIN mopCompetitor c ON c.cid=tm.cid AND c.id=tm.rid
                    WHERE tm.cid=%s AND t.cls=%s AND tm.leg=%s AND c.name=%s
                    """,
                    [cid, class_id, leg, runner_name],
                )
            else:
                cur.execute(
                    """
                    SELECT tm.rid, c.name, t.id, t.name, c.st, c.rt, c.stat, c.tstat
                    FROM mopTeamMember tm
                    JOIN mopTeam t ON t.cid=tm.cid AND t.id=tm.id
                    JOIN mopCompetitor c ON c.cid=tm.cid AND c.id=tm.rid
                    WHERE tm.cid=%s AND t.cls=%s AND tm.leg=%s
                    ORDER BY t.id
                    """,
                    [cid, class_id, leg],
                )
            rows = cur.fetchall()

        if not rows:
            crit = f"rid={rid_filter}" if rid_filter is not None else f"name='{runner_name}'" if runner_name else f"leg={leg}"
            raise CommandError(f"Aucun relayeur trouvé pour {crit} en {cls_name} leg {leg}")

        if sql_only:
            self.stdout.write("\n-- SQL équivalents --")
            self.stdout.write("SELECT tm.rid, c.name, t.name FROM mopTeamMember tm "
                              f"JOIN mopTeam t ON t.id=tm.id JOIN mopCompetitor c ON c.id=tm.rid "
                              f"WHERE tm.cid={cid} AND t.cls={class_id} AND tm.leg={leg};")
            self.stdout.write("SELECT cid, id AS rid, ctrl, rt FROM mopRadio WHERE cid=%s AND id IN (%s) ORDER BY rt;" % (cid, ",".join(str(r[0]) for r in rows)))
            return

        for rid, name, tid, tname, st, rt, stat, tstat in rows:
            self.stdout.write(self.style.SUCCESS(f"\n— Relayeur rid={rid}  {name}  (team {tid} {tname})  stat={stat}/{tstat} st={format_time(st) if st else '-'} rt={format_time(rt) if rt else '-'} ({rt})"))

            with connection.cursor() as cur:
                cur.execute("SELECT ctrl, rt FROM mopRadio WHERE cid=%s AND id=%s ORDER BY rt", [cid, rid])
                radios = cur.fetchall()

            if not radios:
                self.stdout.write(self.style.WARNING("  mopRadio: 0 lignes"))
                continue

            # Récupère les noms de contrôles pour les radios présents uniquement
            ctrl_ids = [c for c, _ in radios]
            ctrl_name_map = {}
            with connection.cursor() as cur:
                if ctrl_ids:
                    placeholders = ",".join(["%s"] * len(ctrl_ids))
                    cur.execute(
                        f"SELECT id, name FROM mopControl WHERE cid=%s AND id IN ({placeholders})",
                        [cid] + ctrl_ids,
                    )
                    ctrl_name_map = dict(cur.fetchall())

            self.stdout.write(f"  mopRadio: {len(radios)} poinçons")
            self.stdout.write(f"  {'ctrl':>6} | {'rt':>8} | {'running':>10} | {'name':>8}")
            self.stdout.write("  " + "-" * 44)
            for ctrl, rt_val in radios:
                cname = ctrl_name_map.get(ctrl, str(ctrl))
                self.stdout.write(f"  {ctrl:6} | {rt_val:8} | {format_time(rt_val):>10} | {cname:>8}")

            if verbose:
                # Tronçons entre poinçons présents uniquement (pas de comparaison à un parcours attendu)
                self.stdout.write(f"\n  Tronçons (entre poinçons présents):")
                prev = None
                for ctrl, rt_val in radios:
                    if prev is None:
                        leg_str = "-"
                    else:
                        leg = rt_val - prev
                        leg_str = f"{format_time(leg)} ({leg})" + (" NEG" if leg < 0 else "")
                    self.stdout.write(f"    {ctrl_name_map.get(ctrl, ctrl)}: abs {format_time(rt_val)} ({rt_val}) leg {leg_str}")
                    prev = rt_val
                # Arrivée
                last_abs = radios[-1][1] if radios else None
                if rt and rt > 0 and last_abs:
                    self.stdout.write(f"    Arrivée: rt total {format_time(rt)} ({rt})  last {format_time(last_abs)}  finish leg {format_time(rt-last_abs)}")

        self.stdout.write("")
