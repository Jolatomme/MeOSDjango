"""
simulate_live.py — Simule un flux MOP « temps réel » pour tester la page Live.

Pousse périodiquement des MOPDiff vers l'endpoint /mop/update/ (via le client
de test Django, qui appelle la vue en interne — pas besoin de réseau), comme le
ferait MeOS : les coureurs partent les uns après les autres, pointent leurs
postes radio, certains abandonnent / sont PM / DNS, d'autres finissent.

Comme dans MeOS (tous les postes cochés « radio »), l'attribut radio du <cls>
contient TOUS les postes du parcours ; seuls les postes réellement équipés
transmettent leurs poinçons pendant la course. La puce complète n'arrive
qu'à la lecture à la GEC : le statut OK est attribué après un délai
(--gec-delay) — entre le dernier poste radio et la validation, la page Live
affiche « Valid. GEC ».

Usage :
    python manage.py simulate_live [--cid 9001] [--runners 14] [--posts 9]
                                   [--controls 4] [--interval 4] [--scale 0.3]

La simulation tourne en temps réel : l'option --scale compresse les durées
(tronçons, écarts de départ, délai GEC) et l'intervalle d'envoi — ex.
--scale 0.3 pour une vérification rapide (~10 min au lieu de ~30).

Cas de figure simulés :
  - départs échelonnés : les sans-info radio sont virtuellement en tête,
    puis les informés progressent selon leur dernier poste ;
  - un coureur lent (×1,8) : dépassé par les sans-info puis rattrapé ;
  - un poste radio en panne : poinçon jamais émis en course pour un coureur
    (présent sur la puce complète à l'arrivée) ;
  - un poinçon hors parcours (poste 900), ignoré par la progression ;
  - « Valid. GEC » : le dernier poste est radio, chaque finissant affiche ce
    statut entre le dernier poinçon et la validation à la GEC ;
  - DNS / PM / Abandon.

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
from django.core.management.base import BaseCommand, CommandError
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
        parser.add_argument('--posts', type=int, default=9,
                            help='Nombre total de postes du parcours (défaut: 9)')
        parser.add_argument('--controls', type=int, default=4,
                            help='Nombre de postes radio parmi les postes du '
                                 'parcours (défaut: 4)')
        parser.add_argument('--radio-positions', default=None,
                            help="Positions (1-based) des postes radio, séparées "
                                 "par des virgules, ex. '3,5,7,9' (défaut: tirage "
                                 'aléatoire sans le poste 1, dernier poste inclus)')
        parser.add_argument('--gec-delay', type=float, default=2.0,
                            help="Minutes entre l'arrivée du coureur et la "
                                 'lecture de sa puce à la GEC (défaut: 2)')
        parser.add_argument('--interval', type=float, default=4.0,
                            help='Secondes entre deux envois MOPDiff (défaut: 4)')
        parser.add_argument('--scale', type=float, default=1.0,
                            help='Facteur de temps global : multiplie leg-time, '
                                 'stagger, gec-delay et intervalle (défaut: 1). '
                                 "Ex. --scale 0.3 pour vérifier rapidement.")
        parser.add_argument('--leg-time', type=float, default=2.0,
                            help='Temps moyen entre deux postes, minutes (défaut: 2)')
        parser.add_argument('--elapsed', type=float, default=16.0,
                            help="Temps de course écoulé au lancement, minutes (défaut: 16)")
        parser.add_argument('--stagger', type=float, default=1.5,
                            help='Écart entre deux départs, minutes (défaut: 1.5)')
        parser.add_argument('--competition', default='Course simulée — Live',
                            help="Nom de la compétition (défaut: 'Course simulée — Live')")

    # ─── Plan de simulation ─────────────────────────────────────────────────

    def _select_radio_positions(self, n_posts, n_controls, override):
        """Positions (1-based) des postes radio du parcours.

        Jamais le poste 1 (le premier poinçon radio arrive après le départ),
        toujours le dernier poste (démo « Valid. GEC »). ``override``
        (ex. '3,5,7,9') impose les positions exactes.
        """
        if override:
            positions = [int(p.strip()) for p in override.split(',')]
            if any(p < 1 or p > n_posts for p in positions):
                raise CommandError(
                    '--radio-positions doit contenir des positions entre 1 et --posts'
                )
            return sorted(set(positions))
        if n_controls >= n_posts:
            return list(range(1, n_posts + 1))
        if n_controls == 1:
            return [n_posts]
        return sorted(
            random.sample(range(2, n_posts), n_controls - 1) + [n_posts]
        )

    def _plan_runner(self, index, st):
        """Plan d'un coureur : st (1/10 s), temps absolus aux postes, statut final."""
        factor = 1.8 if index == self.slow_index else 1.0
        legs = [
            random.uniform(0.6, 1.4) * self.leg_tenths * factor
            for _ in range(self.n_posts)
        ]
        post_times = []
        acc = 0
        for leg in legs:
            acc += leg
            post_times.append(round(acc))      # relatif au départ (1/10 s)
        finish_leg = round(sum(legs) * random.uniform(0.2, 0.3))
        return {
            'st':          st,
            'post_times':  post_times,
            'finish':      st + round(sum(legs)) + finish_leg,  # absolu (1/10 s)
            'end_status':  None,     # None → finit OK
            'skip_punch':  None,     # position d'un poste radio jamais émis
            'extra_punch': None,     # (ctrl, t) poinçon hors parcours
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
            f'<ctrl id="{101 + j}">{101 + j}</ctrl>' for j in range(self.n_posts)
        )
        # Poste hors parcours (coureur de démonstration) : poinçon émis mais
        # absent du parcours → ignoré par la progression et le classement.
        ctrls += '<ctrl id="900">900</ctrl>'
        # Comme dans MeOS (tous les postes cochés « radio ») : l'attribut radio
        # du <cls> contient TOUS les postes du parcours ; seuls les postes
        # réellement équipés transmettent leurs poinçons pendant la course.
        radio_attr = ','.join(str(101 + j) for j in range(self.n_posts))
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
            finished = plan.get('stat') == STAT_OK
            is_dns = plan['end_status'] and plan['end_status'][1] == STAT_DNS
            if is_dns:
                # Jamais parti (DNS) : aucun poinçon radio ne remonte, même
                # après son heure de départ planifiée (l'heure reste affichée
                # dans « En attente » jusqu'au passage en Non partant).
                positions = []
            elif finished:
                # Puce lue à la GEC : tous les poinçons du parcours remontent.
                positions = list(range(1, self.n_posts + 1))
            else:
                # En course : seuls les postes radio équipés transmettent.
                positions = [
                    p for p in self.radio_positions
                    if plan['post_times'][p - 1] <= elapsed
                ]
                if plan['skip_punch'] in positions:
                    positions.remove(plan['skip_punch'])
            # Statut définitif de ce diff (avant le calcul des poinçons du
            # passage en Arrivés).
            if plan['end_status']:
                after, status = plan['end_status']
                if len(positions) >= after and status in (STAT_DNF, STAT_MP):
                    plan['stat'], plan['rt'] = status, None
                elif status == STAT_DNS and sim_t >= plan['st']:
                    # DNS dès son heure de départ : il n'est jamais parti.
                    plan['stat'], plan['rt'] = status, None
            elif sim_t >= plan['finish'] + self.gec_delay_tenths and not finished:
                # Valid. GEC → Arrivés : la puce est lue à la GEC, tous les
                # poinçons du parcours remontent dès ce même diff (évite un
                # intervalle où l'arrivant n'affiche que les postes radio).
                plan['stat'], plan['rt'] = STAT_OK, plan['finish'] - plan['st']
                positions = list(range(1, self.n_posts + 1))
            now_punches = [
                (101 + p - 1, plan['post_times'][p - 1]) for p in positions
            ]
            if plan['extra_punch'] and not finished:
                ctrl, t = plan['extra_punch']
                if t <= elapsed:
                    now_punches.append((ctrl, t))
            now_punches.sort(key=lambda x: x[1])
            elems.append(self._cmp_xml(runner, plan, now_punches))
        return f'<MOPDiff xmlns="{MOP_NS}">{"" .join(elems)}</MOPDiff>'

    # ── Boucle principale ─────────────────────────────────────────────────────

    def handle(self, *args, **options):
        random.seed()
        self.cid        = options['cid']
        self.cls_name   = options['class_name']
        self.cls_id     = 10
        self.n_runners  = options['runners']
        self.n_posts    = options['posts']
        if self.n_posts < 1:
            raise CommandError('--posts doit être >= 1')
        self.leg_tenths = int(options['leg_time'] * 600)
        self.gec_delay_tenths = int(options['gec_delay'] * 600)
        self.comp_name  = options['competition']
        scale = max(0.05, options['scale'])
        # Le facteur --scale compresse les durées simulées (tronçons, écarts de
        # départ, délai GEC) et l'intervalle d'envoi pour une vérification rapide.
        self.leg_tenths = int(self.leg_tenths * scale)
        self.gec_delay_tenths = int(self.gec_delay_tenths * scale)
        self.stagger_tenths = int(options['stagger'] * scale * 600)
        self.interval   = max(0.3, options['interval'] * scale)
        self.today      = datetime.now().date().isoformat()

        self.radio_positions = self._select_radio_positions(
            self.n_posts, options['controls'], options['radio_positions']
        )
        self.n_ctrl = len(self.radio_positions)

        # Coureurs de démonstration (tous finissent OK)
        self.slow_index  = 0   # lent (×1,8) : descend puis est rattrapé
        self.skip_index  = 1   # poste radio en panne (jamais émis en course)
        self.extra_index = 2   # poinçon hors parcours (poste 900)

        # Heure locale (datetime.now() naïve) : cohérente avec les vues du
        # site (clock_tenths(datetime.now())) et avec l'horloge murale MeOS.
        base_t = clock_tenths(datetime.now()) - int(options['elapsed'] * 600)
        self.plans = []
        for i in range(self.n_runners):
            org = ORGS[i % len(ORGS)]
            first, last = NAMES[i % len(NAMES)]
            plan = self._plan_runner(i, base_t + int(i * self.stagger_tenths))
            plan['org']  = org[1]
            plan['name'] = f'{first} {last}'
            plan['stat'] = 0          # Unknown (en course) au départ
            plan['rt']   = None
            plan['end_status'] = self._end_status_for(i)
            # Le DNS garde son heure de départ planifiée (affichée côté site
            # dans « En attente ») mais ne pointe jamais de poste.
            if plan['end_status'] is None:
                if i == self.skip_index and len(self.radio_positions) >= 3:
                    plan['skip_punch'] = (
                        self.radio_positions[len(self.radio_positions) // 2]
                    )
                elif i == self.extra_index:
                    first_radio = self.radio_positions[0]
                    plan['extra_punch'] = (
                        900,
                        round(plan['post_times'][first_radio - 1] + 0.7 * self.leg_tenths),
                    )
            self.plans.append(plan)
        self.race_end_t = max(p['finish'] for p in self.plans)
        # réserve de temps propre (départ du 1er au dernier départ)
        self.race_end_t = max(self.race_end_t, base_t + self.n_runners * self.stagger_tenths)

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
            f'({self.n_runners} coureurs, {self.n_posts} postes de parcours, '
            f'{self.n_ctrl} postes radio : positions {self.radio_positions})'
        ))
        self.stdout.write(
            f'Temps : tronçons ~{self.leg_tenths / 600:.1f} min, '
            f'écarts départ {self.stagger_tenths / 600:.1f} min, '
            f'GEC {self.gec_delay_tenths / 600:.1f} min, '
            f'intervalle {self.interval:.1f} s'
        )
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