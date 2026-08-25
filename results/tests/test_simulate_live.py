"""
Tests de simulate_live.py — génération MOP sans base de données.

Couvre la construction des plans et des XML (MOPComplete / MOPDiff) :
postes radio vs parcours complet, lecture de puce à la GEC (gec_delay),
scénarios de démonstration (coureur lent, panne d'unité, poinçon hors
parcours).
"""

import random
import re
from datetime import datetime

import pytest

from results.management.commands.simulate_live import (
    Command, STAT_OK, STAT_DNS, STAT_MP, STAT_DNF, is_plan_final,
    race_base_time,
)

POST_TIMES = [600, 1200, 1800, 2400, 3000, 3600, 4200, 4800, 5400]


def make_command(**overrides):
    cmd = Command()
    cmd.today = datetime(2025, 8, 14).date().isoformat()
    cmd.cls_id = 10
    cmd.cls_name = 'H21'
    cmd.comp_name = 'Test'
    cmd.n_runners = 6
    cmd.n_posts = overrides.get('n_posts', 9)
    cmd.radio_positions = overrides.get('radio_positions', [3, 5, 7, 9])
    cmd.n_ctrl = len(cmd.radio_positions)
    cmd.leg_tenths = 1200
    cmd.gec_delay_tenths = overrides.get('gec_delay_tenths', 1200)
    cmd.slow_index = 0
    cmd.skip_index = 1
    cmd.extra_index = 2
    cmd.race_end_t = 10 ** 9
    cmd.radio_finish = overrides.get('radio_finish', False)
    cmd.finish_ctrl = overrides.get('finish_ctrl', -77)
    return cmd


# Poinçon d'arrivée radio par défaut (hors circuit).
FINISH_CTRL = -77


def make_plan(st=100000, post_times=None, finish=None, end_status=None,
              skip_punch=None, extra_punch=None, stat=0, rt=None,
              org=1, name='A', prel=False, gec_read=False):
    return {
        'st':         st,
        'post_times': list(post_times) if post_times else list(POST_TIMES),
        'finish':     finish if finish is not None else st + 6000,
        'end_status': end_status,
        'skip_punch': skip_punch,
        'extra_punch': extra_punch,
        'stat':       stat,
        'rt':         rt,
        'org':        org,
        'name':       name,
        'prel':       prel,
        'gec_read':   gec_read,
    }


def radio_of(xml):
    m = re.search(r'<radio>(.*?)</radio>', xml, re.S)
    return m.group(1) if m else ''


def punches(xml):
    """Poinçons du <radio> sous forme {ctrl: temps}."""
    return {
        int(k): int(v) for k, v in
        (p.split(',') for p in radio_of(xml).split(';') if p)
    }


def diff(cmd, plan, sim_t):
    cmd.plans = [plan]
    return cmd._diff_xml(sim_t)


# ══════════════════════════════════════════════════════════════════════════════
# _select_radio_positions
# ══════════════════════════════════════════════════════════════════════════════

class TestSelectRadioPositions:
    def test_defaut_dernier_poste_inclus_sans_poste_1(self):
        random.seed(1)
        pos = make_command()._select_radio_positions(9, 4, None)
        assert len(pos) == 4
        assert pos == sorted(pos)
        assert pos[-1] == 9          # dernier poste toujours radio
        assert 1 not in pos

    def test_defaut_tous_postes_radio(self):
        assert make_command()._select_radio_positions(5, 5, None) == [1, 2, 3, 4, 5]

    def test_defaut_controls_superieur_a_posts(self):
        assert make_command()._select_radio_positions(5, 9, None) == [1, 2, 3, 4, 5]

    def test_defaut_un_seul_radio_dernier_poste(self):
        assert make_command()._select_radio_positions(5, 1, None) == [5]

    def test_override_positions_exactes(self):
        assert make_command()._select_radio_positions(9, 4, '3,5,7,9') == [3, 5, 7, 9]

    def test_override_positions_dedupliquees(self):
        assert make_command()._select_radio_positions(9, 4, '5,3,5') == [3, 5]

    def test_override_hors_parcours_refuse(self):
        with pytest.raises(Exception) as exc:
            make_command()._select_radio_positions(9, 4, '3,12')
        assert 'radio-positions' in str(exc.value)


# ══════════════════════════════════════════════════════════════════════════════
# _plan_runner
# ══════════════════════════════════════════════════════════════════════════════

class TestPlanRunner:
    def test_coureur_lent_plus_de_temps_aux_postes(self):
        random.seed(2)
        cmd = make_command()
        lent = cmd._plan_runner(0, 100000)
        normal = cmd._plan_runner(3, 100000)
        assert lent['post_times'][-1] > normal['post_times'][-1]
        assert lent['finish'] > normal['finish']


# ══════════════════════════════════════════════════════════════════════════════
# _complete_xml
# ══════════════════════════════════════════════════════════════════════════════

class TestCompleteXml:
    def test_radio_attr_contient_tous_les_postes(self):
        cmd = make_command()
        cmd.plans = [make_plan()]
        xml = cmd._complete_xml()
        assert 'radio="101,102,103,104,105,106,107,108,109"' in xml

    def test_poste_hors_parcours_900_declare(self):
        cmd = make_command()
        cmd.plans = [make_plan()]
        xml = cmd._complete_xml()
        assert '<ctrl id="900">900</ctrl>' in xml

    def test_plus_d_astuce_901_902(self):
        cmd = make_command()
        cmd.plans = [make_plan()]
        xml = cmd._complete_xml()
        assert '901' not in xml and '902' not in xml

    def test_radio_attr_suit_n_posts(self):
        cmd = make_command(n_posts=5)
        cmd.plans = [make_plan(post_times=POST_TIMES[:5])]
        xml = cmd._complete_xml()
        assert 'radio="101,102,103,104,105"' in xml


# ══════════════════════════════════════════════════════════════════════════════
# _diff_xml
# ══════════════════════════════════════════════════════════════════════════════

class TestDiffXml:
    def test_en_course_seuls_les_postes_radio_transmettent(self):
        cmd = make_command()
        plan = make_plan()
        xml = diff(cmd, plan, sim_t=plan['st'] + 3500)
        assert punches(xml) == {103: 1800, 105: 3000}

    def test_aucun_poincon_avant_premier_radio(self):
        cmd = make_command()
        plan = make_plan()
        xml = diff(cmd, plan, sim_t=plan['st'] + 500)
        assert punches(xml) == {}

    def test_puce_complete_des_le_passage_arrivees(self):
        """Le passage Valid. GEC → Arrivés est atomique : le diff qui attribue
        le statut OK contient déjà tous les poinçons du parcours (pas seulement
        les postes radio)."""
        cmd = make_command()
        plan = make_plan()
        sim_t = plan['finish'] + cmd.gec_delay_tenths + 1
        xml = diff(cmd, plan, sim_t=sim_t)
        assert re.search(r'stat="1"', xml)
        assert re.search(r'rt="6000"', xml)
        assert punches(xml) == {101 + i: t for i, t in enumerate(POST_TIMES)}

    def test_statut_ok_apres_delai_gec(self):
        cmd = make_command()
        plan = make_plan()
        xml = diff(cmd, plan, sim_t=plan['finish'] + cmd.gec_delay_tenths - 1)
        assert re.search(r'stat="0"', xml)
        xml = diff(cmd, plan, sim_t=plan['finish'] + cmd.gec_delay_tenths + 1)
        assert re.search(r'stat="1"', xml)

    def test_fenetre_valid_gec_avant_validation(self):
        """Après le dernier poste radio et avant la GEC : poinçons radio
        complets (dernier poste inclus) mais statut pas encore attribué."""
        cmd = make_command()
        plan = make_plan()
        sim_t = plan['st'] + POST_TIMES[-1] + 100   # dernier poste pointé
        xml = diff(cmd, plan, sim_t=sim_t)
        assert punches(xml) == {103: 1800, 105: 3000, 107: 4200, 109: 5400}
        assert re.search(r'stat="0"', xml)

    def test_poste_radio_en_panne_jamais_emis_en_course(self):
        cmd = make_command()
        plan = make_plan(skip_punch=5)
        xml = diff(cmd, plan, sim_t=plan['st'] + 5000)
        assert 105 not in punches(xml)
        assert punches(xml) == {103: 1800, 107: 4200}
        # … mais présent sur la puce complète à l'arrivée
        sim_t = plan['finish'] + cmd.gec_delay_tenths + 1
        diff(cmd, plan, sim_t=sim_t)
        xml = diff(cmd, plan, sim_t=sim_t + 1)
        assert punches(xml)[105] == 3000

    def test_poincon_hors_parcours_transmis_mais_ignore(self):
        cmd = make_command()
        plan = make_plan(extra_punch=(900, 2100))
        xml = diff(cmd, plan, sim_t=plan['st'] + 3500)
        assert punches(xml) == {103: 1800, 900: 2100, 105: 3000}

    def test_poincon_hors_parcours_absent_avant_son_temps(self):
        cmd = make_command()
        plan = make_plan(extra_punch=(900, 2100))
        xml = diff(cmd, plan, sim_t=plan['st'] + 1900)
        assert punches(xml) == {103: 1800}

    def test_mp_apres_premier_poste(self):
        cmd = make_command()
        plan = make_plan(end_status=(1, STAT_MP))
        xml = diff(cmd, plan, sim_t=plan['st'] + 3500)
        assert re.search(r'stat="3"', xml)

    def test_dns_jamais_partis_sans_poincons(self):
        """Un « Non partant » ne pointe jamais, même après son heure de départ.

        Son heure de départ planifiée reste transmise (affichée dans
        « En attente ») et il passe Non partant dès cette heure.
        """
        cmd = make_command()
        cmd.race_end_t = 200000
        plan = make_plan(st=100000, end_status=(0, STAT_DNS))
        xml = diff(cmd, plan, sim_t=50000)
        assert punches(xml) == {}
        assert re.search(r'st="100000"', xml)
        assert re.search(r'stat="0"', xml)
        # Après son heure de départ planifiée : toujours aucun poinçon,
        # mais statut Non partant (et non plus « En attente »).
        xml = diff(cmd, plan, sim_t=plan['st'] + 1000)
        assert punches(xml) == {}
        assert re.search(r'stat="20"', xml)


# ══════════════════════════════════════════════════════════════════════════════
# _cmp_xml / _diff_xml — arrivée radio (prel)
# ══════════════════════════════════════════════════════════════════════════════

class TestRadioFinish:
    def test_cmp_xml_prel_true_emette(self):
        """plan['prel']=True → attribut prel="true" sur <base>."""
        cmd = make_command()
        cmd.plans = [make_plan(prel=True)]
        xml = cmd._cmp_xml(0, cmd.plans[0], [])
        assert 'prel="true"' in xml

    def test_cmp_xml_sans_prel_pas_d_attribut(self):
        cmd = make_command()
        cmd.plans = [make_plan(prel=False)]
        xml = cmd._cmp_xml(0, cmd.plans[0], [])
        assert 'prel' not in xml

    def test_arrivee_radio_emmet_prel_des_le_poincon_finish(self):
        """Au poinçon d'arrivée (avant GEC) : stat=1, rt, prel="true",
        poinçons radio en direct + poinçon d'arrivée sous finish-ctrl."""
        cmd = make_command(radio_positions=[3, 5, 7, 9], radio_finish=True)
        plan = make_plan()
        xml = diff(cmd, plan, sim_t=plan['finish'] + 1)
        assert re.search(r'stat="1"', xml)
        assert re.search(r'rt="6000"', xml)
        assert 'prel="true"' in xml
        assert punches(xml) == {103: 1800, 105: 3000, 107: 4200, 109: 5400,
                                FINISH_CTRL: 6000}

    def test_poincon_arrivee_pas_emis_avant_la_ligne(self):
        """Avant le franchissement de la ligne : pas de poinçon d'arrivée."""
        cmd = make_command(radio_positions=[3, 5, 7, 9], radio_finish=True)
        plan = make_plan()
        xml = diff(cmd, plan, sim_t=plan['finish'] - 1)
        assert FINISH_CTRL not in punches(xml)

    def test_poincon_arrivee_pas_emis_pour_abandon(self):
        """Un coureur qui n'atteint pas la ligne (DNF/DNS) n'émet jamais
        de poinçon d'arrivée."""
        cmd = make_command(radio_positions=[3, 5, 7, 9], radio_finish=True)
        dnf = make_plan(end_status=(2, STAT_DNF))
        xml = diff(cmd, dnf, sim_t=dnf['finish'] + 500)
        assert FINISH_CTRL not in punches(xml)

    def test_arrivee_radio_fenetre_avant_gec_garde_prel(self):
        """Entre l'arrivée radio et la lecture GEC : le diff suivant garde
        prel (la carte n'est toujours pas lue)."""
        cmd = make_command(radio_positions=[3, 5, 7, 9], radio_finish=True)
        plan = make_plan()
        diff(cmd, plan, sim_t=plan['finish'] + 1)
        xml = diff(cmd, plan, sim_t=plan['finish'] + cmd.gec_delay_tenths - 1)
        assert 'prel="true"' in xml
        assert re.search(r'stat="1"', xml)

    def test_arrivee_radio_apres_gec_prel_retire(self):
        """Après la lecture GEC : prel retiré, puce complète (tous les
        poinçons du parcours + arrivée conservée)."""
        cmd = make_command(radio_positions=[3, 5, 7, 9], radio_finish=True)
        plan = make_plan()
        xml = diff(cmd, plan, sim_t=plan['finish'] + cmd.gec_delay_tenths + 1)
        assert re.search(r'stat="1"', xml)
        assert re.search(r'rt="6000"', xml)
        assert 'prel' not in xml
        expected = {101 + i: t for i, t in enumerate(POST_TIMES)}
        expected[FINISH_CTRL] = 6000
        assert punches(xml) == expected

    def test_poste_en_panne_revele_a_la_gec_radio_finish(self):
        """Arrivée radio : le poinçon jamais émis en course n'apparaît
        qu'à la lecture GEC."""
        cmd = make_command(radio_positions=[3, 5, 7, 9], radio_finish=True)
        plan = make_plan(skip_punch=5)
        xml = diff(cmd, plan, sim_t=plan['finish'] + 1)
        assert 105 not in punches(xml)
        assert 'prel="true"' in xml
        xml = diff(cmd, plan, sim_t=plan['finish'] + cmd.gec_delay_tenths + 1)
        assert punches(xml)[105] == 3000
        assert 'prel' not in xml

    def test_sans_radio_finish_aucun_prel(self):
        """Sans --radio-finish, aucun prel ni poinçon d'arrivée."""
        cmd = make_command(radio_finish=False)
        plan = make_plan()
        xml = diff(cmd, plan, sim_t=plan['finish'] + cmd.gec_delay_tenths + 1)
        assert 'prel' not in xml
        assert FINISH_CTRL not in punches(xml)
        assert re.search(r'stat="1"', xml)


# ══════════════════════════════════════════════════════════════════════════════
# Condition d'arrêt de la boucle — is_plan_final
# ══════════════════════════════════════════════════════════════════════════════

class TestConditionFin:
    """La simulation ne s'arrête que sur des statuts réellement définitifs.

    Régression : avec --radio-finish, le résultat préliminaire du dernier
    arrivant (prel="true", stat=1) satisfaisait déjà la condition d'arrêt
    « tous les coureurs ont un statut » — la validation GEC n'était jamais
    envoyée et le coureur restait figé en « En attente validation GEC »
    côté site.
    """

    def test_prel_n_est_pas_definitif(self):
        """Résultat préliminaire (arrivée radio, carte non lue) : pas final."""
        assert not is_plan_final(
            make_plan(stat=STAT_OK, rt=6000, prel=True)
        )

    def test_gec_read_est_definitif(self):
        assert is_plan_final(make_plan(stat=STAT_OK, rt=6000, gec_read=True))

    def test_end_status_definitif_sans_gec_read(self):
        """DNS / PM / Abandon : finaux dès l'attribution (jamais de GEC)."""
        for status in (STAT_DNS, STAT_MP, STAT_DNF):
            plan = make_plan(end_status=(1, status), stat=status)
            assert is_plan_final(plan), status

    def test_en_course_n_est_pas_definitif(self):
        assert not is_plan_final(make_plan(stat=0))

    def test_passage_ok_pose_gec_read_sans_radio_finish(self):
        """Sans --radio-finish, le passage OK coïncide avec la lecture GEC."""
        cmd = make_command(radio_finish=False)
        plan = make_plan()
        diff(cmd, plan, sim_t=plan['finish'] + cmd.gec_delay_tenths + 1)
        assert plan['gec_read'] is True

    def test_dernier_arrivant_valide_avant_arret(self):
        """Scénario du bug : rapide déjà final + lent en fenêtre prelim.

        La condition d'arrêt ne doit devenir vraie qu'à la deadline GEC du
        lent, et le diff poussé à ce moment porte le statut officiel sans
        prel (le dernier fragment reçu par le site n'est plus « Valid. GEC »).
        """
        cmd = make_command(radio_positions=[3, 5, 7, 9], radio_finish=True)
        st = 100000
        cmd.plans = [
            make_plan(st=st, name='rapide'),                    # finit à st+6000
            make_plan(st=st, name='lent', finish=st + 12000),   # dernier arrivant
        ]
        deadline = st + 12000 + cmd.gec_delay_tenths
        step = 18                             # pas temps réel (--interval 4 × scale 0.45)
        sim_t = st + 5900                      # avant même l'arrivée du rapide
        flip_xml = flip_t = None
        while sim_t < deadline + 10 * step:
            xml = cmd._diff_xml(sim_t)
            if all(is_plan_final(p) for p in cmd.plans):
                flip_xml, flip_t = xml, sim_t
                break
            sim_t += step
        # L'arrêt n'intervient qu'une fois la deadline GEC dépassée…
        assert flip_t is not None
        assert deadline <= flip_t < deadline + step
        # …et le diff final donne le résultat officiel (plus aucun prel).
        assert 'prel' not in flip_xml
        assert re.search(r'stat="1" st="%d" rt="12000"' % st, flip_xml)

    def test_avant_deadline_gec_la_course_continue(self):
        """Pendant la fenêtre prelim du dernier arrivant : pas d'arrêt."""
        cmd = make_command(radio_positions=[3, 5, 7, 9], radio_finish=True)
        st = 100000
        cmd.plans = [
            make_plan(st=st, name='rapide'),
            make_plan(st=st, name='lent', finish=st + 12000),
        ]
        sim_t = st + 12000 + 50                # lent arrivé, carte pas lue
        cmd._diff_xml(sim_t)
        assert not all(is_plan_final(p) for p in cmd.plans)
        assert cmd.plans[1]['prel'] is True    # en attente validation GEC


# ══════════════════════════════════════════════════════════════════════════════
# Heure de base de la course — race_base_time
# ══════════════════════════════════════════════════════════════════════════════

class TestRaceBaseTime:
    """Lancement autour de minuit : ``--elapsed`` ne doit pas produire des
    heures de départ négatives (« En attente » sans chrono côté site)."""

    def test_en_journee_recul_normal(self):
        assert race_base_time(360000, 9600) == 350400

    def test_juste_apres_minuit_borne_a_zero(self):
        """00:08:40 avec --elapsed 16 min : 5200 − 9600 < 0 → 0."""
        assert race_base_time(5200, 9600) == 0

    def test_limite_exacte(self):
        assert race_base_time(9600, 9600) == 0

    def test_tous_les_departs_restent_positifs(self):
        """Un plan complet construit après clamp n'a que des st >= 0."""
        random.seed(3)
        base_t = race_base_time(3000, int(16.0 * 600))
        assert base_t == 0
        stagger = int(1.5 * 600)
        for i in range(14):
            assert base_t + int(i * stagger) >= 0