"""
services.py — Helpers métier réutilisables entre les vues MeOS.

Chaque fonction est pure (pas d'effet de bord) et testable sans requête HTTP.
Les accès DB restent ici pour pouvoir les mocker facilement dans les tests.
"""

from .models import (
    Moporganization, Mopcontrol, Mopclasscontrol, Mopradio,
    STAT_OK, STATUS_LABELS, format_time,
)


# ─── Organisations ─────────────────────────────────────────────────────────────

def get_org_map(cid, *, as_objects=False):
    """Retourne un dict {org_id: org_name} ou {org_id: Moporganization}.

    Args:
        cid: identifiant de la compétition.
        as_objects: si True, retourne les objets Moporganization complets.
    """
    qs = Moporganization.objects.filter(cid=cid)
    if as_objects:
        return {o.id: o for o in qs}
    return {o.id: o.name for o in qs}


# ─── Contrôles ─────────────────────────────────────────────────────────────────

def get_class_controls(cid, class_id, *, leg=None):
    """Charge la séquence des contrôles d'une catégorie (ou d'une fraction).

    Args:
        cid: identifiant de la compétition.
        class_id: identifiant de la catégorie.
        leg: si fourni, filtre sur ce numéro de fraction (relais).

    Returns:
        controls_seq: liste ordonnée de dicts
            {'ctrl_id': int, 'ctrl_name': str}
        control_name_map: dict {ctrl_id: ctrl_name}
    """
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
            'ctrl_name': control_name_map.get(cc.ctrl, str(cc.ctrl)),
        }
        for cc in class_controls
    ]
    return controls_seq, control_name_map


def get_controls_by_leg(cid, class_id):
    """Retourne les contrôles groupés par fraction pour un relais.

    Returns:
        controls_by_leg: dict {leg_num: [ctrl_id, ...]}
        control_name_map: dict {ctrl_id: ctrl_name}
    """
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
    """Charge tous les temps intermédiaires en un seul appel DB.

    Returns:
        radio_map: dict {runner_id: {ctrl_id: rt}}
    """
    radio_map = {}
    for r in Mopradio.objects.filter(cid=cid, id__in=runner_ids):
        radio_map.setdefault(r.id, {})[r.ctrl] = r.rt
    return radio_map


# ─── Calcul des splits ─────────────────────────────────────────────────────────

def compute_splits(runner_id, controls_seq, radio_map):
    """Calcule les temps intermédiaires pour un coureur.

    Args:
        runner_id: identifiant du coureur.
        controls_seq: liste de {'ctrl_id', 'ctrl_name'} dans l'ordre.
        radio_map: dict {runner_id: {ctrl_id: rt}} issu de get_radio_map().

    Returns:
        Liste de dicts :
            ctrl_name, abs_time (str), leg_time (str),
            leg_raw (int|None), abs_raw (int|None),
            is_best (bool, initialisé à False),
            leg_rank (int|None), abs_rank (int|None)
    """
    radios = radio_map.get(runner_id, {})
    splits = []
    prev   = 0
    for ctrl in controls_seq:
        abs_t = radios.get(ctrl['ctrl_id'], -1)
        leg   = abs_t - prev if abs_t > 0 and prev >= 0 else None
        splits.append({
            'ctrl_name': ctrl['ctrl_name'],
            'abs_time':  format_time(abs_t) if abs_t > 0 else '-',
            'leg_time':  format_time(leg)   if leg is not None else '-',
            'leg_raw':   leg,
            'abs_raw':   abs_t if abs_t > 0 else None,
            'is_best':   False,
            'leg_rank':  None,
            'abs_rank':  None,
        })
        # Si le poste est manquant, prev passe à -1 pour invalider
        # tous les tronçons suivants (chaîne cassée)
        prev = abs_t if abs_t > 0 else -1
    return splits


def mark_best_splits(finishers, all_results):
    """Marque is_best=True sur le meilleur tronçon de chaque contrôle.

    Seuls les classés (finishers) participent à la compétition pour le
    meilleur tronçon, mais la marque est apposée sur tous (all_results)
    afin que les non-classés ayant le même temps soient aussi mis en valeur.

    Args:
        finishers: coureurs classés (possèdent .splits).
        all_results: tous les coureurs (finishers + non_finishers).
    """
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
    """Construit un dict {runner_id: rang} avec gestion des ex-æquo.

    Les coureurs ayant le même temps reçoivent le même rang (classement olympique).
    Exemple : [(1000, 'a'), (1000, 'b'), (1200, 'c')] → {'a': 1, 'b': 1, 'c': 3}.

    Args:
        sorted_times: liste triée de tuples (time, runner_id).
    """
    rank_map = {}
    for i, (t, cid) in enumerate(sorted_times):
        # Rang = position du premier coureur ayant ce temps (base 1)
        rank = next(j + 1 for j, (tt, _) in enumerate(sorted_times) if tt == t)
        rank_map[cid] = rank
    return rank_map


def rank_splits(finishers, all_results):
    """Calcule les classements par tronçon et au cumulé pour chaque poste.

    Pour chaque poste de contrôle :
      - leg_rank  : classement du coureur sur ce seul tronçon
      - abs_rank  : classement du coureur au temps cumulé (du départ à ce poste)

    Seuls les finissants avec un temps valide participent au classement.
    Les non-classés reçoivent None.

    Args:
        finishers: coureurs classés (possèdent .splits avec leg_raw et abs_raw).
        all_results: tous les coureurs (finishers + non_finishers).
    """
    if not finishers:
        return

    n_controls = len(finishers[0].splits)

    for idx in range(n_controls):
        # ── Classement sur le tronçon ──────────────────────────────────────
        leg_times = sorted(
            (c.splits[idx]['leg_raw'], c.id)
            for c in finishers
            if c.splits[idx]['leg_raw'] is not None and c.splits[idx]['leg_raw'] > 0
        )
        leg_rank_map = build_rank_map(leg_times)

        # ── Classement au cumulé ───────────────────────────────────────────
        abs_times = sorted(
            (c.splits[idx]['abs_raw'], c.id)
            for c in finishers
            if c.splits[idx]['abs_raw'] is not None
        )
        abs_rank_map = build_rank_map(abs_times)

        # ── Injection sur tous les coureurs ────────────────────────────────
        for c in all_results:
            c.splits[idx]['leg_rank'] = leg_rank_map.get(c.id)
            c.splits[idx]['abs_rank'] = abs_rank_map.get(c.id)


# ─── Classement ────────────────────────────────────────────────────────────────

def rank_finishers(entries, *, time_field='rt', ok_predicate=None):
    """Trie et classe une liste de coureurs ou d'équipes.

    Assigne les attributs .rank et .time_behind sur chaque entrée.

    Args:
        entries: itérable de coureurs/équipes (objets Django).
        time_field: nom de l'attribut contenant le temps de course.
        ok_predicate: callable(entry) → bool indiquant si l'entrée est classée.
                      Par défaut : entry.is_ok pour les coureurs.

    Returns:
        (finishers, non_finishers, leader_time)
    """
    if ok_predicate is None:
        # Coureurs individuels : utilise la property is_ok
        ok_predicate = lambda e: getattr(e, 'is_ok', False)

    finishers     = sorted(
        [e for e in entries if ok_predicate(e)],
        key=lambda e: getattr(e, time_field),
    )
    non_finishers = [e for e in entries if not ok_predicate(e)]

    leader_time = getattr(finishers[0], time_field) if finishers else None

    for i, entry in enumerate(finishers):
        entry.rank        = i + 1
        entry.time_behind = getattr(entry, time_field) - leader_time if i > 0 else 0

    for entry in non_finishers:
        entry.rank        = None
        entry.time_behind = None

    return finishers, non_finishers, leader_time


# ─── Matrice des tronçons ──────────────────────────────────────────────────────

def build_leg_matrix(finishers, controls_seq, radio_map):
    """Calcule les temps de tronçon pour chaque classé.

    Returns:
        leg_matrix[i][j] = durée du tronçon j pour finishers[i]
                           (en dixièmes de seconde, None si invalide)
        Le dernier tronçon (j = n_controls) est le tronçon d'arrivée.
    """
    leg_matrix = []
    for c in finishers:
        radios     = radio_map.get(c.id, {})
        legs, prev = [], 0
        for ctrl in controls_seq:
            abs_t = radios.get(ctrl['ctrl_id'], -1)
            if abs_t > 0 and prev >= 0:
                legs.append(abs_t - prev)
                prev = abs_t
            else:
                legs.append(None)
                prev = -1
        # Dernier tronçon : jusqu'à l'arrivée
        legs.append(c.rt - prev if prev >= 0 and c.rt > 0 else None)
        leg_matrix.append(legs)
    return leg_matrix


def compute_leg_refs(leg_matrix, n_legs, top_fraction=0.25):
    """Calcule le temps de référence de chaque tronçon = moyenne du top N%.

    Args:
        leg_matrix: matrice [runner][leg] de temps (dixièmes, None si absent)
        n_legs: nombre total de tronçons
        top_fraction: fraction des meilleurs temps à retenir (défaut 25%)

    Returns:
        leg_refs[j] = temps de référence du tronçon j (float, None si pas de données)
    """
    import math
    leg_refs = []
    for j in range(n_legs):
        times = sorted(
            t for row in leg_matrix
            if j < len(row) and (t := row[j]) is not None and t > 0
        )
        if not times:
            leg_refs.append(None)
            continue
        k     = max(1, math.ceil(len(times) * top_fraction))
        leg_refs.append(sum(times[:k]) / k)
    return leg_refs


# ─── Temps absolus (regroupement) ─────────────────────────────────────────────

def build_abs_time_series(runners, controls_seq, radio_map):
    """Calcule les temps de passage absolus (depuis minuit) pour chaque coureur.

    Temps absolu à un poste = st + temps_radio_cumulé
    Tous les temps sont en dixièmes de secondes (unité MeOS).

    Pour le graphique de regroupement :
      - L'axe X représente les postes (Départ, P1, P2, ..., Arrivée)
      - L'axe Y représente l'heure absolue
      - Des lignes proches = coureurs ensemble
      - Une ligne horizontale = coureur rapide sur ce tronçon

    Args:
        runners    : liste de Mopcompetitor (classés ou non, avec st > 0)
        controls_seq : liste ordonnée de {'ctrl_id': ..., 'ctrl_name': ...}
        radio_map  : {runner_id: {ctrl_id: rt}} — temps de course cumulés

    Returns:
        Liste de dicts :
          id, name, org, rank, time (formaté), st_abs (dixièmes),
          points [abs_time|None, ...],   # longueur = n_controls + 2 (départ + arrivée)
          has_finish (bool)
    """
    series = []
    for rank, c in enumerate(runners, start=1):
        if c.st <= 0:          # coureur sans heure de départ → ignorer
            continue

        radios = radio_map.get(c.id, {})
        points = [c.st]        # point 0 = départ (temps absolu)
        valid  = True

        for ctrl in controls_seq:
            abs_radio = radios.get(ctrl['ctrl_id'], -1)
            if abs_radio > 0:
                points.append(c.st + abs_radio)
            else:
                points.append(None)   # poste non pointé ou non reçu
                valid = False

        # Arrivée
        if c.rt > 0:
            points.append(c.st + c.rt)
            has_finish = True
        else:
            points.append(None)
            has_finish = False

        series.append({
            'id':         c.id,
            'name':       c.name,
            'rank':       rank,
            'time':       c.rt,          # dixièmes, pour tri/affichage
            'st_abs':     c.st,          # heure de départ absolue (dixièmes)
            'points':     points,        # temps absolus à chaque poste
            'has_finish': has_finish,
        })

    return series


# ─── Estimation des erreurs par tronçon ───────────────────────────────────────

def _weighted_median(values_weights):
    """Médiane pondérée.

    Args:
        values_weights: liste de (value, weight), weight > 0.

    Returns:
        float ou None si liste vide.
    """
    vw = [(v, w) for v, w in values_weights if v is not None and w is not None and w > 0]
    if not vw:
        return None
    vw.sort(key=lambda x: x[0])
    total = sum(w for _, w in vw)
    cum   = 0.0
    for v, w in vw:
        cum += w
        if cum >= total / 2:
            return v
    return vw[-1][0]


def compute_error_estimates(finishers, controls_seq, radio_map, top_fraction=0.25):
    """Estime la perte de temps due aux erreurs pour chaque tronçon de chaque coureur.

    Algorithme :
      1. Calcule les temps de référence (moyenne top 25%) pour chaque tronçon.
      2. Pour chaque coureur et tronçon, calcule l'indice de performance =
         ref / temps_coureur (proche de 1 = au niveau des meilleurs).
      3. Le niveau de performance normal du coureur = médiane pondérée de ses
         indices de performance, pondérée par les temps de référence des tronçons.
      4. Temps attendu sur le tronçon = ref / perf_normale.
      5. Erreur (dixièmes) = temps_coureur - temps_attendu.
         Erreur (%) = erreur / temps_attendu × 100.

    Returns:
        dict {runner_id: [{'error_time': float|None, 'error_pct': float|None}, ...]}
        Une entrée par poste dans controls_seq. None si tronçon invalide.
    """
    import math

    leg_matrix    = build_leg_matrix(finishers, controls_seq, radio_map)
    n_legs_full   = len(controls_seq)   # tronçons intermédiaires uniquement

    # ── Références (top 25% des classés, tronçons intermédiaires uniquement) ──
    leg_refs = []
    for j in range(n_legs_full):
        times = sorted(
            t for row in leg_matrix
            if j < len(row) and (t := row[j]) is not None and t > 0
        )
        if not times:
            leg_refs.append(None)
            continue
        k = max(1, math.ceil(len(times) * top_fraction))
        leg_refs.append(sum(times[:k]) / k)

    result = {}
    for i, c in enumerate(finishers):
        legs = leg_matrix[i]

        # ── Indices de performance du coureur ────────────────────────────────
        perf_pairs = []
        for j in range(n_legs_full):
            ref = leg_refs[j]
            t   = legs[j] if j < len(legs) else None
            if ref and t and t > 0:
                perf_pairs.append((ref / t, ref))   # (indice, poids=ref)
            else:
                perf_pairs.append(None)

        # ── Niveau normal (médiane pondérée des indices valides) ─────────────
        normal_perf = _weighted_median(
            [p for p in perf_pairs if p is not None]
        )

        # ── Erreur par tronçon ───────────────────────────────────────────────
        errors = []
        for j in range(n_legs_full):
            ref = leg_refs[j]
            t   = legs[j] if j < len(legs) else None
            if ref and t and t > 0 and normal_perf and normal_perf > 0:
                expected   = ref / normal_perf
                error_time = t - expected           # dixièmes de seconde
                error_pct  = (error_time / expected) * 100
                errors.append({'error_time': error_time, 'error_pct': error_pct})
            else:
                errors.append({'error_time': None, 'error_pct': None})

        result[c.id] = errors

    return result
