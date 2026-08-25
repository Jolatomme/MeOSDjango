"""
services.py — Helpers métier réutilisables entre les vues MeOS.

Chaque fonction est pure (pas d'effet de bord) et testable sans requête HTTP.
Les accès DB restent ici pour pouvoir les mocker facilement dans les tests.
"""

from .models import (
    Moporganization, Mopcontrol, Mopclasscontrol, Mopradio, Mopclass,
    Mopcompetitor,
    STAT_OK, STATUS_LABELS, format_time,
    STAT_NT, STAT_MP, STAT_DNF, STAT_DQ, STAT_OT,
    STAT_DNS, STAT_CANCEL, STAT_NP,
)

import re
from collections import Counter
from datetime import datetime
from functools import cmp_to_key
from markdown.extensions.toc import slugify_unicode
from django.db import connection

_PREFIX_RE = re.compile(r'^\d+(\.\d+)*\.?\s+')


def competition_visible(cid):
    """Return True if the competition is visible (not deleted, not hidden)."""
    try:
        with connection.cursor() as cur:
            cur.execute(
                "SELECT frozen, visible, deleted FROM results_competitionconfig WHERE cid=%s",
                [cid],
            )
            row = cur.fetchone()
    except Exception:
        return True
    if not row or len(row) < 3:
        return True
    _frozen, visible, deleted = row
    return not deleted and visible


def slugify_no_prefix(value, separator='-'):
    """Slugify after removing numbered prefix (e.g., '1.2. Title' → 'title')."""
    return slugify_unicode(_PREFIX_RE.sub('', value), separator)


# ─── Organisations ─────────────────────────────────────────────────────────────

def get_org_map(cid, *, as_objects=False):
    qs = Moporganization.objects.filter(cid=cid)
    if as_objects:
        return {o.id: o for o in qs}
    return {o.id: o.name for o in qs}


# ─── Contrôles ─────────────────────────────────────────────────────────────────

def get_class_controls(cid, class_id, *, leg=None):
    qs = Mopclasscontrol.objects.filter(cid=cid, id=class_id)
    if leg is not None:
        qs = qs.filter(leg=leg)
    class_controls = list(qs.order_by('leg', 'ord'))
    ctrl_ids = [cc.ctrl for cc in class_controls]
    control_name_map = {}
    if ctrl_ids:
        control_name_map = {
            c.id: c.name
            for c in Mopcontrol.objects.filter(cid=cid, id__in=ctrl_ids)
        }
    controls_seq = [
        {
            'ctrl_id':   cc.ctrl,
            'ctrl_name': f"{cc.ord + 1}-{control_name_map.get(cc.ctrl, str(cc.ctrl))}",
        }
        for cc in class_controls
    ]
    return controls_seq, control_name_map


def get_controls_by_leg(cid, class_id):
    class_controls = list(
        Mopclasscontrol.objects.filter(cid=cid, id=class_id).order_by('leg', 'ord')
    )
    ctrl_ids = list({cc.ctrl for cc in class_controls})
    control_name_map = {}
    if ctrl_ids:
        control_name_map = {
            c.id: c.name
            for c in Mopcontrol.objects.filter(cid=cid, id__in=ctrl_ids)
        }
    controls_by_leg = {}
    for cc in class_controls:
        controls_by_leg.setdefault(cc.leg, []).append(cc.ctrl)
    return controls_by_leg, control_name_map


# ─── Temps radio ───────────────────────────────────────────────────────────────

def get_radio_map(cid, runner_ids):
    radio_map = {}
    for r in Mopradio.objects.filter(cid=cid, id__in=runner_ids):
        radio_map.setdefault(r.id, {})[r.ctrl] = r.rt
    return radio_map


# ─── Temps négatifs & poinçon d'arrivée ────────────────────────────────────────

def _circuit_negatives(controls_seq, radios, prestart=frozenset()):
    """Libellés des postes en anomalie, dans l'ordre du circuit :

      - poste présumé pointé avant le départ (dans ``prestart``) ;
      - tronçon strictement négatif depuis le poinçon connu précédent.

    La chaîne des tronçons est rompue par un poste manquant ou présumé :
    elle reprend au poinçon connu suivant (les tronçons entre deux
    poinçons connus restent comparés).
    """
    names = []
    prev  = 0
    for ctrl in controls_seq:
        cid_ = ctrl['ctrl_id']
        if cid_ in prestart:
            names.append(ctrl['ctrl_name'])
            prev = None
            continue
        abs_t = radios.get(cid_)
        if abs_t is None:
            prev = None
            continue
        if prev is not None and abs_t < prev:
            names.append(ctrl['ctrl_name'])
        prev = abs_t
    return names


def negative_leg_names(runner_id, controls_seq, radio_map):
    """Noms des postes dont le tronçon depuis le poinçon connu précédent
    est strictement négatif (boîtier mal synchronisé, carte SI non
    effacée — poinçon antérieur au départ)."""
    return _circuit_negatives(controls_seq, radio_map.get(runner_id, {}))


def is_definitive_ok(c):
    """Coureur classé OK avec un statut définitif (carte lue à la GEC).

    ``stat`` est le statut courant ; ``tstat`` est le statut attribué à la
    lecture de la puce. Un résultat préliminaire (arrivé, carte non lue)
    n'est pas définitif.
    """
    return (
        getattr(c, 'stat', None) == STAT_OK
        and getattr(c, 'tstat', None) == STAT_OK
        and (getattr(c, 'rt', 0) or 0) > 0
    )


def attested_ctrls(radio_map):
    """Nombre de coureurs ayant transmis un poinçon, par poste.

    Un poste jamais pointé par personne (boîtier mort, configuration
    partielle) ne peut pas servir à diagnostiquer un trou individuel."""
    attested = Counter()
    for radios in radio_map.values():
        attested.update(radios.keys())
    return attested


def detect_prestart_ctrls(c, controls_seq, radio_map, attested=None):
    """Postes manquant des poinçons radio d'un coureur OK définitif.

    MeOS étant configuré avec tous les postes en radio, la lecture de la
    puce à la GEC remonte tout le parcours — sauf les poinçons filtrés à
    l'export MOP (temps de course ≤ 0). Un trou chez un coureur classé OK
    signifie donc « pointé avant le départ » : carte SI non effacée,
    départ avancé. La valeur exacte du temps n'est pas transmise.

    ``attested`` (voir ``attested_ctrls``) évite de flagger un poste dont
    personne n'a jamais transmis (boîtier mort / configuration partielle).

    Returns
    -------
    Ensemble de ctrl_id.
    """
    if not is_definitive_ok(c):
        return set()
    radios = radio_map.get(getattr(c, 'id', None), {})
    return {
        ctrl['ctrl_id'] for ctrl in controls_seq
        if ctrl['ctrl_id'] not in radios
        and (attested is None or attested.get(ctrl['ctrl_id'], 0) > 0)
    }


def collect_negative_ctrls(c, controls_seq, radio_map, attested=None):
    """Liste des libellés en anomalie pour un coureur (source unique du
    badge « Temps négatif » et du bandeau diagnostic), dans l'ordre du
    circuit :

      - postes à tronçon négatif, et postes manquants d'un coureur OK
        définitif attesté (= pointés avant le départ, voir
        ``detect_prestart_ctrls``) ;
      - « Arrivée » si le temps de course (rt > 0 — la sentinelle rt=-1
        des non-classés n'est pas une anomalie) est antérieur au dernier
        poinçon radio présent, ou négatif avec statut OK.

    Le calcul n'a lieu que pour un coureur **classé à l'arrivée**
    (statut et tstat OK — carte lue à la GEC). Avant la lecture de la
    puce (en course, Valid. GEC, résultat préliminaire), les poinçons
    radio seuls et un rt parfois figé par MeOS ne permettent pas de
    conclure : aucune anomalie n'est remontée.
    """
    if (getattr(c, 'stat', None) != STAT_OK
            or getattr(c, 'tstat', None) != STAT_OK):
        return []
    rt     = getattr(c, 'rt', None)
    radios = radio_map.get(getattr(c, 'id', None), {})
    prestart = detect_prestart_ctrls(c, controls_seq, radio_map, attested)
    negs = _circuit_negatives(controls_seq, radios, prestart)
    if getattr(c, 'stat', None) == STAT_OK and rt is not None and rt < 0:
        negs.append('Arrivée')
    elif rt and rt > 0:
        last_abs = None
        for ctrl in controls_seq:
            abs_t = radios.get(ctrl['ctrl_id'], -1)
            if abs_t > 0:
                last_abs = abs_t
        if last_abs and c.rt < last_abs:
            negs.append('Arrivée')
    return negs


def detect_arrival_punch(radios, controls_seq):
    """Détecte le poinçon d'arrivée radio (boîtier d'arrivée équipé).

    Un poinçon dont le poste est hors du circuit (``controls_seq``),
    reçu alors que tous les postes du circuit sont pointés et après le
    dernier d'entre eux, signale l'arrivée : le temps final remonte en
    direct, avant la lecture de la puce à la GEC.

    Returns
    -------
    Tuple ``(ctrl_id, rt)`` si un poinçon d'arrivée est identifié, sinon
    ``None``. Sans ordre de circuit (``controls_seq`` vide), aucun
    poinçon ne peut être qualifié d'« arrivée » par cette heuristique.
    """
    if not radios or not controls_seq:
        return None
    known = {c['ctrl_id'] for c in controls_seq}
    # Parcours complet : chaque poste radio du circuit a un poinçon (un
    # poinçon antérieur au départ, transmis négatif, reste toléré).
    course_times = {ctrl: rt for ctrl, rt in radios.items() if ctrl in known}
    if len(course_times) < len(known):
        return None
    positives = [rt for rt in course_times.values() if rt and rt > 0]
    # Référence temporelle : dernier poinçon positif ; si tous les poinçons
    # du circuit sont antérieurs au départ (négatifs), le plus tardif d'entre
    # eux fait office de référence.
    ref_t = max(positives) if positives else max(course_times.values())
    candidates = [
        (rt, ctrl) for ctrl, rt in radios.items()
        if ctrl not in known and rt and rt > ref_t
    ]
    if not candidates:
        return None
    rt, ctrl = max(candidates)
    return (ctrl, rt)


# ─── Calcul des splits ─────────────────────────────────────────────────────────

def compute_splits(runner_id, controls_seq, radio_map, prestart_ctrls=None):
    """Calcule les temps intermédiaires d'un coureur.

    ``prestart_ctrls`` : postes présumés pointés avant le départ d'un
    coureur OK définitif (voir ``detect_prestart_ctrls``). Leur valeur
    exacte est filtrée par l'export MOP : la cellule affiche
    « Temps négatif », le tronçon est inconnu et marqué négatif.

    Chaîne des tronçons : un poste manquant ou présumé rend les tronçons
    adjacents inconnus, mais la chaîne reprend au poinçon connu suivant
    (les tronçons entre deux poinçons connus restent valides). Un tronçon
    négatif est signalé via ``neg_leg``.
    """
    radios = radio_map.get(runner_id, {})
    prestart_ctrls = prestart_ctrls or set()
    splits = []
    prev   = 0
    for ctrl in controls_seq:
        abs_t = radios.get(ctrl['ctrl_id'])
        if ctrl['ctrl_id'] in prestart_ctrls:
            splits.append({
                'ctrl_name': ctrl['ctrl_name'],
                'abs_time':  '-',
                'leg_time':  'Temps négatif',
                'leg_raw':   None,
                'abs_raw':   None,
                'neg_leg':   True,
                'is_best':   False,
                'leg_rank':  None,
                'abs_rank':  None,
            })
            prev = None
            continue
        if abs_t is not None and prev is not None:
            leg     = abs_t - prev
            neg_leg = leg < 0
        else:
            leg, neg_leg = None, False
        splits.append({
            'ctrl_name': ctrl['ctrl_name'],
            'abs_time':  format_time(abs_t) if abs_t is not None else '-',
            'leg_time':  format_time(leg)   if leg is not None else '-',
            'leg_raw':   leg,
            'abs_raw':   abs_t,
            'neg_leg':   neg_leg,
            'is_best':   False,
            'leg_rank':  None,
            'abs_rank':  None,
        })
        prev = abs_t
    return splits


def build_finish_split(rt, last_abs, *, leg_full_race_if_missing=True):
    """Construit le dict du tronçon 'Arrivée'.

    Un temps d'arrivée antérieur au dernier poste (boîtier mal
    synchronisé) produit un tronçon négatif, signalé via 'neg_leg'.

    Args:
        rt: temps de course (en 1/10 s). Si absent ou négatif
            (non classé), renvoie un tronçon vide.
        last_abs: temps du dernier poste (en 1/10 s) ou None.
        leg_full_race_if_missing: si True et qu'aucun dernier poste
            n'est connu, le tronçon vaut rt (temps total) ; si False,
            le tronçon reste inconnu ('-').
    """
    if rt is None or rt <= 0:
        return {
            'ctrl_name': 'Arrivée',
            'abs_time':  '-',
            'leg_time':  '-',
            'leg_raw':   None,
            'abs_raw':   None,
            'neg_leg':   False,
            'is_best':   False,
            'leg_rank':  None,
            'abs_rank':  None,
        }
    if last_abs:
        leg_raw = rt - last_abs
    elif leg_full_race_if_missing:
        leg_raw = rt
    else:
        leg_raw = None
    return {
        'ctrl_name': 'Arrivée',
        'abs_time':  format_time(rt),
        'leg_time':  format_time(leg_raw) if leg_raw else '-',
        'leg_raw':   leg_raw,
        'abs_raw':   rt,
        'neg_leg':   leg_raw is not None and leg_raw < 0,
        'is_best':   False,
        'leg_rank':  None,
        'abs_rank':  None,
    }


def get_negative_time_stats(cid):
    """Compte les coureurs de la compétition ayant au moins un temps négatif.

    Seuls les coureurs classés à l'arrivée sont pris en compte
    (statut et tstat OK — voir ``collect_negative_ctrls``).

    Diagnostic :
      - boîtier mal synchronisé ('multiple') si plusieurs coureurs ont un
        temps négatif au même poste (le boîtier est commun) ;
      - carte SI non effacée ('single') sinon, même si plusieurs coureurs
        sont affectés mais sur des postes différents.

    Returns:
        None si aucun coureur affecté, sinon un dict avec
        {'count', 'kind', 'message', 'tooltip', 'box_controls', 'runners'} :
        - count : nombre de coureurs affectés ;
        - kind : 'single' (doigt non effacé) ou 'multiple' (boîtier) ;
        - box_controls : {poste: nb de coureurs} pour les postes où ≥ 2
          coureurs ont un temps négatif (triés par nombre décroissant) ;
        - runners : liste triée (classe, nom) des coureurs affectés avec
          {'id', 'name', 'cls_name', 'controls'} — controls étant la
          liste des postes (et éventuellement 'Arrivée') au temps négatif.
    """
    affected    = {}
    ctrl_counts = Counter()
    for cls in Mopclass.objects.filter(cid=cid):
        competitors = list(Mopcompetitor.objects.filter(cid=cid, cls=cls.id))
        if not competitors:
            continue
        controls_seq, _ = get_class_controls(cid, cls.id)
        radio_map       = get_radio_map(cid, [c.id for c in competitors])
        attested        = attested_ctrls(radio_map)
        for c in competitors:
            if c.id in affected:
                continue
            neg_ctrls = collect_negative_ctrls(c, controls_seq, radio_map,
                                               attested)
            if neg_ctrls:
                affected[c.id] = {
                    'name':    c.name,
                    'cls_name': cls.name,
                    'controls': neg_ctrls,
                }
                ctrl_counts.update(neg_ctrls)

    if not affected:
        return None
    count = len(affected)

    # Boîtiers suspectés : postes où plusieurs coureurs ont un temps négatif
    box_controls = {
        name: n
        for name, n in sorted(ctrl_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        if n >= 2
    }

    if box_controls:
        kind     = 'multiple'
        box_names = ', '.join(box_controls)
        if len(box_controls) == 1:
            postes = f"au poste {box_names}"
        else:
            postes = f"aux postes {box_names}"
        message = (
            f"{count} coureurs ont des temps négatifs {postes} : "
            "probable boîtier mal synchronisé."
        )
        tooltip = 'Temps négatif : boîtier probablement mal synchronisé'
    elif count == 1:
        kind = 'single'
        message = (
            "1 coureur a un temps négatif : probable carte SI non effacée "
            "(problème d'effacement de doigts)."
        )
        tooltip = 'Temps négatif : carte SI probablement non effacée'
    else:
        kind = 'single'
        message = (
            f"{count} coureurs ont des temps négatifs sur des postes "
            "différents : probables cartes SI non effacées "
            "(effacement de doigts)."
        )
        tooltip = ('Temps négatifs sur des postes différents : '
                   'cartes SI probablement non effacées')

    runners = sorted(
        ({'id': cid_, **info} for cid_, info in affected.items()),
        key=lambda r: (r['cls_name'], r['name']),
    )
    return {'count': count, 'kind': kind, 'message': message, 'tooltip': tooltip,
            'box_controls': box_controls, 'runners': runners}


def mark_best_splits(finishers, all_results):
    if not finishers:
        return
    n_controls = len(finishers[0].splits)
    for idx in range(n_controls):
        best = None
        for c in finishers:
            raw = c.splits[idx]['leg_raw']
            if raw is not None and raw > 0:
                if best is None or raw < best:
                    best = raw
        if best is not None:
            for c in all_results:
                if c.splits[idx]['leg_raw'] == best:
                    c.splits[idx]['is_best'] = True


def build_rank_map(sorted_times):
    rank_map = {}
    for i, (t, cid) in enumerate(sorted_times):
        rank = next(j + 1 for j, (tt, _) in enumerate(sorted_times) if tt == t)
        rank_map[cid] = rank
    return rank_map


def rank_splits(finishers, all_results):
    if not finishers:
        return
    n_controls = len(finishers[0].splits)
    for idx in range(n_controls):
        leg_times = sorted(
            (c.splits[idx]['leg_raw'], c.id)
            for c in finishers
            if c.splits[idx]['leg_raw'] is not None and c.splits[idx]['leg_raw'] > 0
        )
        abs_times = sorted(
            (c.splits[idx]['abs_raw'], c.id)
            for c in finishers
            if c.splits[idx]['abs_raw'] is not None
        )
        leg_rank_map = build_rank_map(leg_times)
        abs_rank_map = build_rank_map(abs_times)
        for c in all_results:
            c.splits[idx]['leg_rank'] = leg_rank_map.get(c.id)
            c.splits[idx]['abs_rank'] = abs_rank_map.get(c.id)


# ─── Classement ────────────────────────────────────────────────────────────────

def rank_finishers(entries, *, time_field='rt', ok_predicate=None):
    if ok_predicate is None:
        ok_predicate = lambda e: getattr(e, 'is_ok', False)
    finishers = sorted(
        [e for e in entries if ok_predicate(e)],
        key=lambda e: getattr(e, time_field),
    )
    non_finishers = [e for e in entries if not ok_predicate(e)]
    leader_time   = getattr(finishers[0], time_field) if finishers else None
    for i, entry in enumerate(finishers):
        entry.rank        = i + 1
        entry.time_behind = getattr(entry, time_field) - leader_time if i > 0 else 0
    for entry in non_finishers:
        entry.rank = None; entry.time_behind = None
    return finishers, non_finishers, leader_time


# ─── Matrice des tronçons ──────────────────────────────────────────────────────

def build_leg_matrix(finishers, controls_seq, radio_map):
    leg_matrix = []
    for c in finishers:
        radios     = radio_map.get(c.id, {})
        legs, prev = [], 0
        for ctrl in controls_seq:
            abs_t = radios.get(ctrl['ctrl_id'], -1)
            if abs_t > 0 and prev >= 0:
                legs.append(abs_t - prev); prev = abs_t
            else:
                legs.append(None); prev = -1
        legs.append(c.rt - prev if prev >= 0 and c.rt > 0 else None)
        leg_matrix.append(legs)
    return leg_matrix


def compute_leg_refs(leg_matrix, n_legs, top_fraction=0.25):
    import math
    leg_refs = []
    for j in range(n_legs):
        times = sorted(
            t for row in leg_matrix
            if j < len(row) and (t := row[j]) is not None and t > 0
        )
        if not times:
            leg_refs.append(None); continue
        k = max(1, math.ceil(len(times) * top_fraction))
        leg_refs.append(sum(times[:k]) / k)
    return leg_refs


# ─── Temps absolus (regroupement) ─────────────────────────────────────────────

def build_abs_time_series(runners, controls_seq, radio_map):
    series = []
    for rank, c in enumerate(runners, start=1):
        if c.st <= 0:
            continue
        radios = radio_map.get(c.id, {})
        points = [c.st]
        for ctrl in controls_seq:
            abs_radio = radios.get(ctrl['ctrl_id'], -1)
            points.append(c.st + abs_radio if abs_radio > 0 else None)
        if c.rt > 0:
            points.append(c.st + c.rt); has_finish = True
        else:
            points.append(None); has_finish = False
        series.append({
            'id': c.id, 'name': c.name, 'rank': rank,
            'time': c.rt, 'st_abs': c.st,
            'points': points, 'has_finish': has_finish,
        })
    return series


# ─── Estimation des erreurs ───────────────────────────────────────────────────

def _weighted_median(values_weights):
    vw = [(v, w) for v, w in values_weights if v is not None and w is not None and w > 0]
    if not vw:
        return None
    vw.sort(key=lambda x: x[0])
    total = sum(w for _, w in vw); cum = 0.0
    for v, w in vw:
        cum += w
        if cum >= total / 2:
            return v


def compute_error_estimates(finishers, controls_seq, radio_map, top_fraction=0.25):
    import math
    leg_matrix  = build_leg_matrix(finishers, controls_seq, radio_map)
    n_legs_full = len(controls_seq) + 1
    leg_refs = []
    for j in range(n_legs_full):
        times = sorted(
            t for row in leg_matrix
            if j < len(row) and (t := row[j]) is not None and t > 0
        )
        if not times:
            leg_refs.append(None); continue
        k = max(1, math.ceil(len(times) * top_fraction))
        leg_refs.append(sum(times[:k]) / k)
    result = {}
    for i, c in enumerate(finishers):
        legs = leg_matrix[i]
        perf_pairs = []
        for j in range(n_legs_full):
            ref = leg_refs[j]; t = legs[j] if j < len(legs) else None
            if ref and t and t > 0:
                perf_pairs.append((ref / t, ref))
            else:
                perf_pairs.append(None)
        normal_perf = _weighted_median([p for p in perf_pairs if p is not None])
        errors = []
        for j in range(n_legs_full):
            ref = leg_refs[j]; t = legs[j] if j < len(legs) else None
            if ref and t and t > 0 and normal_perf and normal_perf > 0:
                expected   = ref / normal_perf
                error_time = t - expected
                error_pct  = (error_time / expected) * 100
                errors.append({'error_time': error_time, 'error_pct': error_pct})
            else:
                errors.append({'error_time': None, 'error_pct': None})
        result[c.id] = errors
    return result


# ─── Indice de regroupement ────────────────────────────────────────────────────

def _hare_integral(d0, d1, T1, T2):
    if d0 == 0 and d1 == 0:
        return 0.5
    slope = d1 - d0
    breakpoints = {0.0, 1.0}
    if abs(slope) > 1e-9:
        for d_crit in (0.0, float(T1), float(T2)):
            f_c = (d_crit - d0) / slope
            if 0.0 < f_c < 1.0:
                breakpoints.add(f_c)
    total = 0.0
    fps   = sorted(breakpoints)
    for idx in range(len(fps) - 1):
        fa, fb   = fps[idx], fps[idx + 1]
        avg_d    = (d0 + fa * slope + d0 + fb * slope) / 2.0
        w        = fb - fa
        if avg_d <= 0 or avg_d > T2:
            pass
        elif avg_d <= T1:
            total += w
        else:
            total += w * (T2 - avg_d) / (T2 - T1)
    return total


def compute_grouping_index(runners, controls_seq, radio_map, t1_sec=7, t2_sec=20):
    T1 = int(t1_sec * 10); T2 = int(t2_sec * 10)
    n_ctrls = len(controls_seq); n_legs = n_ctrls + 1
    abs_pts = []
    for c in runners:
        if c.st <= 0:
            abs_pts.append(None); continue
        radios = radio_map.get(c.id, {})
        pts    = [c.st]
        for ctrl in controls_seq:
            rt = radios.get(ctrl['ctrl_id'], -1)
            pts.append(c.st + rt if rt > 0 else None)
        pts.append(c.st + c.rt if c.rt > 0 else None)
        abs_pts.append(pts)
    n = len(runners); results = []
    for i in range(n):
        pts_i = abs_pts[i]
        if pts_i is None:
            results.append({'id': runners[i].id, 'leg_indices': [None] * n_legs,
                            'leg_ref_ids': [None] * n_legs, 'global_index': None})
            continue
        leg_indices = []; leg_ref_ids = []; leg_weights = []
        for leg_j in range(n_legs):
            t_start = pts_i[leg_j]; t_end = pts_i[leg_j + 1]
            if t_start is None or t_end is None or t_end <= t_start:
                leg_indices.append(None); leg_ref_ids.append(None); leg_weights.append(0)
                continue
            net_sum = 0.0; n_valid = 0; best_ref_id = None; best_abs_net = -1.0
            for k in range(n):
                if k == i: continue
                pts_k = abs_pts[k]
                if pts_k is None: continue
                t_k_start = pts_k[leg_j]; t_k_end = pts_k[leg_j + 1]
                if t_k_start is None or t_k_end is None: continue
                if abs(t_start - t_k_start) > T2: continue
                d0 = t_k_start - t_start; d1 = t_k_end - t_end
                hare_ik   = _hare_integral(d0,  d1,  T1, T2)
                follow_ik = _hare_integral(-d0, -d1, T1, T2)
                net_ik    = follow_ik - hare_ik
                net_sum  += net_ik; n_valid += 1
                if abs(net_ik) > best_abs_net:
                    best_abs_net = abs(net_ik); best_ref_id = runners[k].id
            if n_valid == 0:
                leg_indices.append(None); leg_ref_ids.append(None); leg_weights.append(0)
            else:
                leg_indices.append(net_sum / n_valid); leg_ref_ids.append(best_ref_id)
                leg_weights.append(t_end - t_start)
        valid_pairs = [
            (leg_indices[j], leg_weights[j]) for j in range(n_legs)
            if leg_indices[j] is not None and leg_weights[j] > 0
        ]
        if valid_pairs:
            total_w    = sum(w for _, w in valid_pairs)
            global_idx = sum(v * w for v, w in valid_pairs) / total_w if total_w > 0 else None
        else:
            global_idx = None
        results.append({'id': runners[i].id, 'leg_indices': leg_indices,
                        'leg_ref_ids': leg_ref_ids, 'global_index': global_idx})
    return results


# ─── Régularité ───────────────────────────────────────────────────────────────

def compute_regularity_analysis(finishers, controls_seq, radio_map, top_fraction=0.25):
    import math
    if not finishers:
        return {'runner_regularity': [], 'leg_stds': [], 'leg_refs': [],
                'category_regularity': None, 'n_legs': 0}
    leg_matrix = build_leg_matrix(finishers, controls_seq, radio_map)
    n_legs     = len(controls_seq) + 1
    leg_refs   = compute_leg_refs(leg_matrix, n_legs, top_fraction)
    pi_matrix  = []
    for i in range(len(finishers)):
        pis, weights = [], []
        for j in range(n_legs):
            t = leg_matrix[i][j]; ref = leg_refs[j]
            if t and t > 0 and ref and ref > 0:
                pis.append(ref / t); weights.append(ref)
            else:
                pis.append(None); weights.append(None)
        pi_matrix.append({'pis': pis, 'weights': weights})
    runner_regularity = []
    for i, c in enumerate(finishers):
        pis     = pi_matrix[i]['pis']; weights = pi_matrix[i]['weights']
        valid   = [(pi, w) for pi, w in zip(pis, weights) if pi is not None and w is not None]
        if len(valid) >= 2:
            total_w  = sum(w for _, w in valid)
            mean_pi  = sum(pi * w for pi, w in valid) / total_w
            variance = sum(w * (pi - mean_pi) ** 2 for pi, w in valid) / total_w
            wstd     = math.sqrt(variance)
        elif len(valid) == 1:
            mean_pi = valid[0][0]; wstd = 0.0
        else:
            mean_pi = None; wstd = None
        runner_regularity.append({'id': c.id, 'weighted_std': wstd, 'mean_pi': mean_pi,
                                   'leg_pis': pis, 'leg_weights': weights})
    leg_stds = []
    for j in range(n_legs):
        col_pis = [pi_matrix[i]['pis'][j] for i in range(len(finishers))
                   if pi_matrix[i]['pis'][j] is not None]
        if len(col_pis) >= 2:
            mean     = sum(col_pis) / len(col_pis)
            variance = sum((pi - mean) ** 2 for pi in col_pis) / len(col_pis)
            leg_stds.append(math.sqrt(variance))
        else:
            leg_stds.append(None)
    valid_stds          = [r['weighted_std'] for r in runner_regularity if r['weighted_std'] is not None]
    category_regularity = sum(valid_stds) / len(valid_stds) if valid_stds else None
    return {'runner_regularity': runner_regularity, 'leg_stds': leg_stds, 'leg_refs': leg_refs,
            'category_regularity': category_regularity, 'n_legs': n_legs}


# ─── Circuits ──────────────────────────────────────────────────────────────────

def compute_course_hash(controls_seq):
    """Hash MD5 tronqué 8 chars identifiant un circuit par sa séquence de ctrl_id.

    Retourne '00000000' pour une séquence vide.
    """
    import hashlib
    if not controls_seq:
        return '00000000'
    key = ','.join(str(c['ctrl_id']) for c in controls_seq)
    return hashlib.md5(key.encode()).hexdigest()[:8]


def get_courses_map(cid, relay_class_ids=None, class_totals=None):
    """Charge tous les circuits d'une compétition (3 requêtes DB).

    Un circuit = groupe de catégories partageant la même séquence de postes.

    Args
    ----
    cid : int
        Competition ID.
    relay_class_ids : set or None
        If provided, relay classes are excluded from the courses map
        (relay classes have different circuits per leg, not suitable for course grouping).
    class_totals : dict or None
        If provided, courses with no participants (all classes have 0 total) are excluded.
        Dict mapping class_id -> total number of participants.

    Returns
    -------
    dict { hash_8chars: course_dict }
    """
    from collections import defaultdict

    if relay_class_ids is None:
        relay_class_ids = set()
    if class_totals is None:
        class_totals = {}

    all_classes = list(Mopclass.objects.filter(cid=cid).order_by('ord', 'name'))
    all_classes = [c for c in all_classes if c.id not in relay_class_ids]
    if not all_classes:
        return {}

    all_cc = list(Mopclasscontrol.objects.filter(cid=cid).order_by('id', 'leg', 'ord'))
    cc_by_cls = defaultdict(list)
    for cc in all_cc:
        cc_by_cls[cc.id].append(cc)

    ctrl_ids = list({cc.ctrl for cc in all_cc})
    control_name_map = {}
    if ctrl_ids:
        control_name_map = {
            c.id: c.name
            for c in Mopcontrol.objects.filter(cid=cid, id__in=ctrl_ids)
        }

    courses: dict = {}
    for cls in all_classes:
        ccs      = cc_by_cls.get(cls.id, [])
        ctrl_seq = [
            {
                'ctrl_id':   cc.ctrl,
                'ctrl_name': f"{cc.ord + 1}-{control_name_map.get(cc.ctrl, str(cc.ctrl))}",
            }
            for cc in ccs
        ]
        h = compute_course_hash(ctrl_seq)
        if h not in courses:
            courses[h] = {
                'hash':             h,
                'raw_key':          ','.join(str(c['ctrl_id']) for c in ctrl_seq),
                'controls_seq':     ctrl_seq,
                'control_name_map': control_name_map,
                'class_ids':        [],
                'classes':          [],
                'n_controls':       len(ctrl_seq),
                'display_name':     '',
            }
        courses[h]['class_ids'].append(cls.id)
        courses[h]['classes'].append(cls)

    for course in courses.values():
        names  = [c.name for c in course['classes'][:4]]
        extra  = len(course['classes']) - 4
        course['display_name'] = ' / '.join(names) + (f' +{extra}' if extra > 0 else '')

    if class_totals:
        courses = {
            h: c for h, c in courses.items()
            if any(class_totals.get(cls.id, 0) > 0 for cls in c['classes'])
        }

    return courses


# ══════════════════════════════════════════════════════════════════════════════
# Suivi live (postes radio)
#
# Groupes :
#   en_course  — heure de départ passée, sans statut définitif. Les coureurs
#                sans poinçon radio sont virtuellement en tête (triés par
#                heure de départ), puis viennent ceux qui ont pointé (triés
#                par progression : plus de postes devant, à égalité le temps
#                au dernier poste radio départage).
#   valid_gec  — parcours terminé mais statut officiel pas encore attribué :
#                soit un coureur en_course ayant pointé le dernier poste du
#                parcours (poste radio), soit un résultat préliminaire MOP
#                (prel="true" : arrivé par poinçon radio, carte pas encore
#                lue à la GEC). Trié comme en_course (progression identique
#                → temps au dernier poste radio départage).
#   arrives    — données complètes : statut OK et rt > 0 (carte vidée à la
#                GEC + statut attribué par MeOS). Tri par rt.
#   en_attente — st == 0 (départ inconnu) ou départ dans le futur.
#   termine    — statuts définitifs non-OK (PM, Abandon, DNS, …).
# ══════════════════════════════════════════════════════════════════════════════

_DAY_TENTHS = 24 * 3600 * 10

# Priorité de tri dans le groupe 'termine' (même ordre que _NON_FINISHER_ORDER)
LIVE_DONE_PRIORITY = {
    STAT_NT: 1, STAT_OT: 1, STAT_DQ: 1,
    STAT_MP:  2,
    STAT_DNF: 3,
    STAT_DNS: 4, STAT_NP: 4, STAT_CANCEL: 4,
}

LIVE_GROUPS = ('en_course', 'valid_gec', 'arrives', 'en_attente', 'termine')


def clock_tenths(dt):
    """Convertit un datetime en 1/10 s écoulées depuis minuit (format st MeOS)."""
    return (dt.hour * 3600 + dt.minute * 60 + dt.second) * 10


def format_clock(tenths):
    """Formate une heure murale (1/10 s depuis minuit) en 'HH:MM:SS'.

    Gère le passage de minuit (valeur > 24 h ramenée dans la journée) et
    les valeurs négatives (préfixe '-').
    """
    try:
        tenths = int(tenths)
    except (TypeError, ValueError):
        return '-'
    if tenths < 0:
        return '-' + format_clock(-tenths)
    total = (tenths % _DAY_TENTHS) // 10
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d}'


def _is_definitive(stat):
    """Statut définitif non-OK (le coureur ne peut plus être en course)."""
    return stat in LIVE_DONE_PRIORITY


def race_start_clock(competitors):
    """1/10 s depuis minuit du premier départ valide, ou None."""
    starts = [c.st for c in competitors if c.st and c.st > 0]
    return min(starts) if starts else None


def race_end_clock(competitors):
    """1/10 s depuis minuit de la dernière arrivée (st + rt), ou None."""
    ends = [c.st + c.rt for c in competitors
            if c.is_ok and c.st and c.st > 0 and c.rt and c.rt > 0]
    return max(ends) if ends else None


def race_state(competitors, now=None, race_start=None):
    """État de la course : ``'upcoming'``, ``'live'`` ou ``'finished'``.

    - ``'finished'`` : plus aucun coureur en course ni en attente de départ
      (les coureurs st=0 restent « en attente » et bloquent cet état).
    - ``'upcoming'`` : aucun départ donné (ou premier départ dans le futur).
    - ``'live'``     : course en cours.

    ``competitors`` doit avoir l'attribut ``live_group`` (posé par
    ``rank_live``). ``race_start`` doit être fourni (voir
    ``race_start_clock``) ; ``None`` signifie qu'aucun départ n'est connu.
    """
    now_t = clock_tenths(now or datetime.now())

    en_course  = [c for c in competitors if getattr(c, 'live_group', None) == 'en_course']
    en_attente = [c for c in competitors if getattr(c, 'live_group', None) == 'en_attente']
    if not en_course and not en_attente:
        return 'finished'
    if race_start is None or now_t < race_start:
        return 'upcoming'
    return 'live'


def race_in_progress(competitors, now=None):
    """True si au moins un coureur est encore en course (départ passé)."""
    now = now or datetime.now()
    now_t = clock_tenths(now)
    return any(
        not c.is_ok and not _is_definitive(c.stat) and c.st > 0 and c.st <= now_t
        for c in competitors
    )


def mark_negative_times(competitors, controls_seq, radio_map):
    """Pose ``c.neg_time`` et ``c.neg_ctrls`` sur les coureurs ayant au
    moins un temps négatif.

    Règles unifiées (voir ``collect_negative_ctrls``, partagées avec
    ``get_negative_time_stats`` et ``compute_splits``), réservées aux
    coureurs classés à l'arrivée (statut et tstat OK) : tronçon radio
    négatif, poste manquant d'un coureur OK définitif attesté (pointé
    avant le départ), arrivée antérieure au dernier poste radio, ou temps
    d'arrivée ``rt`` négatif (seulement si le statut est OK — pour les
    statuts non-OK, ``rt = -1`` est la sentinelle « non classé », pas un
    temps négatif).
    """
    attested = attested_ctrls(radio_map)
    for c in competitors:
        neg_ctrls = collect_negative_ctrls(c, controls_seq, radio_map, attested)
        c.neg_ctrls = neg_ctrls
        c.neg_time  = bool(neg_ctrls)


def _cmp_en_course(a, b):
    """Compare deux coureurs « en course » pour le classement live.

    Un coureur est « informé » dès qu'il a pointé un poste du parcours
    (``progress_pos > 0``). Règles :
      - deux informés : le plus avancé d'abord, départagé à égalité par
        le meilleur temps au poste le plus avancé (``ref_time``) ;
      - deux sans info : le départ le plus tôt d'abord ;
      - informé vs sans-info : l'informé passe devant si son temps au
        premier poste radio est inférieur au temps de course écoulé du
        sans-info, sinon le sans-info reste devant (virtuellement en tête).
    """
    a_info = getattr(a, 'progress_pos', 0) > 0
    b_info = getattr(b, 'progress_pos', 0) > 0

    if a_info and b_info:
        if a.progress_pos != b.progress_pos:
            return b.progress_pos - a.progress_pos
        a_ref = a.ref_time if a.ref_time is not None else 0
        b_ref = b.ref_time if b.ref_time is not None else 0
        return (a_ref > b_ref) - (a_ref < b_ref)

    if not a_info and not b_info:
        return (a.st > b.st) - (a.st < b.st)

    informed, noinfo = (a, b) if a_info else (b, a)
    inf_first  = informed.first_radio_time
    no_elapsed = noinfo.elapsed
    if inf_first is not None and no_elapsed is not None and inf_first < no_elapsed:
        return -1 if a_info else 1
    return 1 if a_info else -1


def rank_live(competitors, radio_map, now, controls_seq=None):
    """Classe les coureurs pour l'affichage live.

    Mutates : attache à chaque coureur ``live_group``, ``live_rank``,
    ``n_punches``, ``last_ctrl``, ``last_time`` (1/10 s de course),
    ``last_punch_clock`` (horloge murale = st + last_time), ``ref_time``,
    ``progress_pos`` (position 1-based dans ``controls_seq`` du poste le
    plus avancé ; 0 si aucun poinçon de parcours connu) et
    ``arrival_rt`` (temps au poinçon d'arrivée radio, sinon None).

    La progression suit l'ordre imposé par le circuit (``controls_seq``) :
    ``last_ctrl`` / ``progress_pos`` désignent le poste le plus avancé
    dans cet ordre, et non le poinçon le plus récent ou le poste au plus
    grand identifiant. ``controls_seq`` contient les postes radio
    déclarés pour la classe ; seuls les poinçons des postes réellement
    équipés remontent en direct.

    Passage en ``valid_gec`` sur preuve d'arrivée uniquement :
      - résultat préliminaire MeOS (``prel`` = True : poinçon d'arrivée
        radio traité par MeOS, carte pas encore lue) ;
      - ou poinçon d'arrivée radio détecté (voir
        ``detect_arrival_punch`` : poste hors circuit, reçu une fois le
        parcours complet). Dans ce cas ``last_time`` porte le temps
        d'arrivée (provisoire) et le chrono s'arrête.

    Sans arrivée radio, pointer le dernier poste ne change pas de groupe :
    le coureur reste « en course » (chrono qui tourne) jusqu'à la lecture
    de la puce, qui le fait passer « arrives » (statut OK) ou « termine ».

    Classement « en course » :
      - deux coureurs sans info radio (``progress_pos = 0``) : le départ
        le plus tôt d'abord (virtuellement en tête) ;
      - deux coureurs informés : le plus avancé d'abord, départagé à
        égalité par le meilleur temps au poste le plus avancé ;
      - informé vs sans-info : l'informé passe devant si son temps au
        premier poste radio est inférieur au temps de course écoulé du
        sans-info, sinon le sans-info reste devant.

    Les coureurs marqués ``neg_time`` (badge « Temps négatif ») gardent
    leur rang : le badge signale l'anomalie sans les exclure du
    classement. Un ``rt < 0`` avec statut OK est classé « arrives ».

    Returns
    -------
    Liste ordonnée des coureurs : en_course, valid_gec, arrives,
    en_attente, termine.
    """
    now_t = clock_tenths(now)
    ctrl_order = {
        ctrl['ctrl_id']: i for i, ctrl in enumerate(controls_seq or [])
    }

    for c in competitors:
        c.neg_time = getattr(c, 'neg_time', False) is True or (
            c.stat == STAT_OK and c.rt is not None and c.rt < 0
        )
        radios  = radio_map.get(c.id, {})
        punches = [
            (ctrl, rt) for ctrl, rt in radios.items() if rt and rt > 0
        ]
        c.n_punches = len(punches)
        # Postes du parcours pointés (position 1-based + temps de course)
        positions = [
            (ctrl_order[ctrl] + 1, rt, ctrl)
            for ctrl, rt in punches if ctrl in ctrl_order
        ]
        c.progress_pos      = max((p for p, _, _ in positions), default=0)
        c.first_radio_time  = min(positions, default=None)[1] if positions else None
        c.elapsed           = (now_t - c.st) if c.st and c.st > 0 and c.st <= now_t else None
        arrival             = detect_arrival_punch(radios, controls_seq or [])
        c.arrival_ctrl      = arrival[0] if arrival else None
        c.arrival_rt        = arrival[1] if arrival else None
        if positions:
            furthest = max(positions)          # poste le plus avancé, puis temps
            c.last_ctrl         = furthest[2]
            c.last_time         = furthest[1]
            c.last_punch_clock  = (c.st + c.last_time) if c.st and c.st > 0 else None
        elif punches:
            # Repli sans ordre de circuit : poste au temps de poinçon le plus grand
            fallback = max(punches, key=lambda p: p[1])
            c.last_ctrl         = fallback[0]
            c.last_time         = fallback[1]
            c.last_punch_clock  = (c.st + c.last_time) if c.st and c.st > 0 else None
        else:
            c.last_ctrl = None
            c.last_time = None
            c.last_punch_clock = None
        if arrival is not None:
            # Poinçon d'arrivée reçu : le temps affiché devient le temps
            # d'arrivée (provisoire — carte pas encore lue à la GEC).
            c.last_ctrl        = arrival[0]
            c.last_time        = arrival[1]
            c.last_punch_clock = (c.st + c.last_time) if c.st and c.st > 0 else None
        c.ref_time = c.last_time

        if c.is_ok:
            # Résultat préliminaire (arrivée radio, carte pas encore lue à la
            # GEC — attribut MOP prel="true") : pas encore « Arrivé » officiel.
            if getattr(c, 'prel', False) == True:
                c.live_group = 'valid_gec'
            else:
                c.live_group = 'arrives'
        elif _is_definitive(c.stat):
            c.live_group = 'termine'
        elif c.stat == STAT_OK and c.rt is not None and c.rt < 0:
            c.live_group = 'arrives'
        elif arrival is not None:
            # Poinçon d'arrivée radio reçu : course terminée, carte pas
            # encore lue à la GEC et statut pas encore attribué par MeOS.
            c.live_group = 'valid_gec'
        elif c.st > 0 and c.st <= now_t:
            c.live_group = 'en_course'
        else:
            c.live_group = 'en_attente'

    en_course = sorted(
        [c for c in competitors if c.live_group == 'en_course'],
        key=cmp_to_key(_cmp_en_course),
    )
    for i, c in enumerate(en_course, start=1):
        c.live_rank = i   # les temps négatifs n'excluent plus du classement live

    valid_gec = sorted(
        [c for c in competitors if c.live_group == 'valid_gec'],
        key=cmp_to_key(_cmp_en_course),
    )
    for i, c in enumerate(valid_gec, start=1):
        c.live_rank = i   # les temps négatifs n'excluent plus du classement live

    arrives = sorted(
        [c for c in competitors if c.live_group == 'arrives'],
        key=lambda c: c.rt,
    )
    for i, c in enumerate(arrives, start=1):
        c.live_rank = i   # les temps négatifs n'excluent plus du classement live

    en_attente = sorted(
        [c for c in competitors if c.live_group == 'en_attente'],
        key=lambda c: (c.st == 0, c.st),      # st=0 (départ inconnu) en dernier
    )
    termine = sorted(
        [c for c in competitors if c.live_group == 'termine'],
        key=lambda c: (LIVE_DONE_PRIORITY.get(c.stat, 5), c.name.lower()),
    )
    for c in en_attente + termine:
        c.live_rank = None

    return en_course + valid_gec + arrives + en_attente + termine
