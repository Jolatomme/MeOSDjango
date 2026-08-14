"""
simulate_live.py — Simule un flux MOP « temps réel » pour tester la page Live.

Pousse périodiquement des MOPDiff vers l'endpoint /mop/update/ (via le client
de test Django, qui appelle la vue en interne — pas besoin de réseau), comme le
ferait MeOS : les coureurs partent les uns après les autres, pointent leurs
postes radio, certains abandonnent / sont PM / DNS, d'autres finissent.

Usage :
    python manage.py simulate_live [--cid 9001] [--runners 14] [--interval 4]

La base doit contenir les tables mop* (lancer `manage.py setup_db` au besoin) ;
lancer le serveur de dev à côté puis ouvrir :
    http://127.0.0.1:8000/competition/<cid>/class/H21/live/

Arrêt : Ctrl+C (le fichier CompetitionConfig reste en place pour naviguer).
"""

import itertools
import random
import time
from datetime import datetime
from xml.sax.saxutils import escape

from django.conf import settings
from django.core.management.base import BaseCommand
from django.test import Client

from results.models import CompetitionConfig
from results.services import clock_tenths

MOP_NS = 'http://www.melin.nu/mop'

NAMES = [
    ('Martin', 'Luc'), ('Emma', 'Durand'), ('Léa', 'Moreau'), ('Hugo', 'Lefebvre'),
    ('Chloé', 'Girard'), ('Lucas', 'Roux'), ('Manon', 'Fournier'), ('Léo', 'Mercier'),
    ('Camille', 'Lambert'), ('Nathan', 'Bonnet'), ('Inès', 'François'), ('Tom', 'Garnier'),
    ('Sarah', 'Faure'), ('Louis', 'Rousseau'), ('Julia', 'Marchand'), ('Adrien', 'Henry'),
    ('Zoé', 'Guérin'), ('Antoine', 'Nicolas'), ('Alice', 'Carpentier'), ('Paul', 'Roy'),
    ('Margaux', 'Colin'), ('Théo', 'Dupont'), ('Lola', 'Renard'), ('Baptiste', 'Simon'),
]

ORGS = [
    ('Club des Cimes', 1), ('SCRAM', 2), ('Sardines CO', 3),
    ('ELO Grenoble', 4), ('CO Colmar', 5), ('Haut-Jura Ski', 6),
]

# Codes statut MeOS (voir results/models.py)
STAT_OK = 1
STAT_MP = 3
STAT_DNF = 4
STAT_DNS = 20


class Command(BaseCommand):
    help = ('Simule un flux MOP temps réel (postes radio + statuts) '
            'vers /mop/update/ pour tester la page Live.')

    def add_arguments(self, parser):
        parser.add_argument('--cid', type=int, default=9001,
                            help="Identifiant de compétition simulée (défaut: 9001)")
        parser.add_argument('--class-name', default='H21',
                            help="Nom de la catégorie simulée (défaut: H21)")
        parser.add_argument('--runners', type=int, default=14,
                            help="Nombre de coureurs (défaut: 14)")
        parser.add_argument('--controls', type=int, default=4,
                            help='Nombre de postes radio (défaut: 4)')
        parser.add_argument('--interval', type=float, default=4.0,
                            help='Secondes entre deux envois MOPDiff (défaut: 4)')
        parser.add_argument('--leg-time', type=float, default=2.0,
                            help='Temps moyen entre deux postes, minutes (défaut: 2)')
        parser.add_argument('--elapsed', type=float, default=16.0,
                            help="Temps de course écoulé au lancement, minutes (défaut: 16)")
        parser.add_argument('--stagger', type=float, default=1.5,
                            help='Écart entre deux départs, minutes (défaut: 1.5)')
        parser.add_argument('--competition', default='Course simulée — Live',
                            help="Nom de la compétition (défaut: 'Course simulée — Live')")

    # ─── Plan de simulation ─────────────────────────────────────────────────

    def _plan_runner(self, index, st):
        """Plan d'un coureur : st (1/10 s), temps absolus aux postes, statut final."""
        legs = []
        total = 0
        for _ in range(self.n_ctrl):
            leg = random.uniform(0.6, 1.4) * self.leg_tenths
            legs.append(leg)
            total += leg
        punches = []
        acc = 0
        for leg in legs:
            acc += leg
            punches.append(round(acc))      # relatif au départ (1/10 s)
        finish_leg = round(total * random.uniform(0.2, 0.3))
        return {
            'st':         st,
            'punches':    punches,
            'finish':     st + round(total) + finish_leg,   # absolu (1/10 s)
            'end_status': None,     # None → finit OK
        }

    def _end_status_for(self, index):
        """Statut définitif de démonstration pour quelques coureurs."""
        if index == self.n_runners - 1:
            return (0, STAT_DNS)          # ne part jamais
        if index == self.n_runners - 2:
            return (1, STAT_MP)           # PM après le 1er poste
        if index % 5 == 4:
            return (2, STAT_DNF)          # Abandon après 2 postes
        return None

    # ── XML ───────────────────────────────────────────────────────────────────

    def _cmp_xml(self, runner, plan, punches_now):
        st, rt, stat = plan['st'], 0, 0
        radio = ';'.join(
            f'{ctrl},{t}' for ctrl, t in punches_now
        )
        if plan.get('rt') is not None:
            rt = plan['rt']
        if plan.get('stat') is not None:
            stat = plan['stat']
        bib = 100 + runner
        return (
            f'<cmp id="{runner}" card="{100000 + runner}">'
            f'<base org="{plan["org"]}" cls="{self.cls_id}" stat="{stat}" '
            f'st="{st}" rt="{rt}" bib="{bib}">{escape(plan["name"])}</base>'
            f'<input it="0" tstat="0"/>'
            f'<radio>{escape(radio)}</radio>'
            f'</cmp>'
        )

    def _complete_xml(self):
        ctrls = ''.join(
            f'<ctrl id="{101 + j}">{101 + j}</ctrl>' for j in range(self.n_ctrl)
        )
        # Postes non-radio (jamais dans l'attribut radio du <cls>, donc
        # invisibles pour le site) — prouve que seuls les postes radio comptent.
        ctrls += '<ctrl id="901">901</ctrl><ctrl id="902">902</ctrl>'
        radio_attr = ','.join(str(101 + j) for j in range(self.n_ctrl))
        orgs = ''.join(
            f'<org id="{org_id}">{escape(name)}</org>' for name, org_id in ORGS
        )
        cmp_elems = []
        for runner, plan in enumerate(self.plans):
            cmp_elems.append(self._cmp_xml(runner, plan, []))
        return (
            f'<MOPComplete xmlns="{MOP_NS}">'
            f'<competition date="{self.today}" organizer="Simulation DOM">'
            f'{escape(self.comp_name)}</competition>'
            f'{ctrls}'
            f'<cls id="{self.cls_id}" ord="10" radio="{radio_attr}">{escape(self.cls_name)}</cls>'
            f'{orgs}'
            f"{''.join(cmp_elems)}"
            f'</MOPComplete>'
        )

    def _diff_xml(self, sim_t):
        """MOPDiff avec l'état de chaque coureur au temps simulé sim_t."""
        elems = []
        for runner, plan in enumerate(self.plans):
            elapsed = sim_t - plan['st']     # temps écoulé depuis son départ
            punches = [p for p in plan['punches'] if p <= elapsed]
            now_punches = [
                (101 + j, t) for j, t in enumerate(punches)
            ]
            if plan['end_status']:
                after, status = plan['end_status']
                if len(punches) >= after and status == STAT_DNF:
                    plan['stat'], plan['rt'] = status, None
                elif len(punches) >= after and status == STAT_MP:
                    plan['stat'], plan['rt'] = status, None
                elif status == STAT_DNS and sim_t >= self.race_end_t:
                    plan['stat'], plan['rt'] = status, None
            elif sim_t >= plan['finish']:
                plan['stat'], plan['rt'] = STAT_OK, plan['finish'] - plan['st']
            elems.append(self._cmp_xml(runner, plan, now_punches))
        return f'<MOPDiff xmlns="{MOP_NS}">{"" .join(elems)}</MOPDiff>'

    # ── Boucle principale ─────────────────────────────────────────────────────

    def handle(self, *args, **options):
        random.seed()
        self.cid        = options['cid']
        self.cls_name   = options['class_name']
        self.cls_id     = 10
        self.n_runners  = options['runners']
        self.n_ctrl     = options['controls']
        self.leg_tenths = int(options['leg_time'] * 600)
        self.comp_name  = options['competition']
        self.interval   = options['interval']
        self.today      = datetime.now().date().isoformat()

        # Heure locale (datetime.now() naïve) : cohérente avec les vues du
        # site (clock_tenths(datetime.now())) et avec l'horloge murale MeOS.
        base_t = clock_tenths(datetime.now()) - int(options['elapsed'] * 600)
        self.plans = []
        for i in range(self.n_runners):
            org = ORGS[i % len(ORGS)]
            first, last = NAMES[i % len(NAMES)]
            plan = self._plan_runner(i, base_t + int(i * options['stagger'] * 600))
            plan['org']  = org[1]
            plan['name'] = f'{first} {last}'
            plan['stat'] = 0          # Unknown (en course) au départ
            plan['rt']   = None
            plan['end_status'] = self._end_status_for(i)
            self.plans.append(plan)
        self.race_end_t = max(p['finish'] for p in self.plans)
        # réserve de temps propre (départ du 1er au dernier départ)
        self.race_end_t = max(self.race_end_t, base_t + self.n_runners * int(options['stagger'] * 600))

        # Compétition visible côté site
        CompetitionConfig.objects.update_or_create(
            cid=self.cid,
            defaults={'visible': True, 'frozen': False, 'deleted': False},
        )

        client     = Client()
        password   = getattr(settings, 'MOP_PASSWORD', '')

        def push(xml):
            return client.post(
                '/mop/update/', data=xml.encode('utf-8'),
                content_type='application/xml',
                HTTP_COMPETITION=str(self.cid),
                HTTP_PWD=password,
            )

        self.stdout.write(self.style.MIGRATE_HEADING(
            f'Simulation live — cid={self.cid} classe={self.cls_name} '
            f'({self.n_runners} coureurs, {self.n_ctrl} postes radio)'
        ))
        self.stdout.write('Ouvrir la page :  '
                          f'http://127.0.0.1:8000/competition/{self.cid}/class/{self.cls_name}/live/')
        self.stdout.write('API :             '
                          f'http://127.0.0.1:8000/api/{self.cid}/class/{self.cls_name}/live/')
        self.stdout.write('Arrêt : Ctrl+C\n')

        first = True
        for step in itertools.count(1):
            if first:
                xml = self._complete_xml()
                driver = 'MOPComplete'
                first = False
            else:
                xml = self._diff_xml(clock_tenths(datetime.now()))
                driver = 'MOPDiff'
            try:
                resp = push(xml)
            except Exception as exc:  # table manquante, connexion DB…
                self.stderr.write(self.style.ERROR(
                    f'Envoi impossible ({exc.__class__.__name__}: {exc}) — '
                    'vérifier la base (manage.py setup_db)'
                ))
                return
            if resp.status_code != 200:
                self.stderr.write(self.style.ERROR(
                    f'{driver} refusé — HTTP {resp.status_code} ({resp.content.decode(errors="replace")})'
                ))
                return

            finished = sum(1 for p in self.plans if p['stat'])
            self.stdout.write(
                f'{step:>4} · {driver:<11} → 200 OK   '
                f'({finished}/{self.n_runners} statuts définitifs)'
            )

            if all(p['stat'] for p in self.plans):
                self.stdout.write(self.style.SUCCESS(
                    '\nTous les coureurs ont un statut définitif — simulation terminée.'
                ))
                return
            time.sleep(self.interval)