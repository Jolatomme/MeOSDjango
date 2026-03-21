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


# ─── Indice de regroupement (lièvre / suiveur) ────────────────────────────────

def _hare_integral(d0, d1, T1, T2):
    """Intègre la fonction lièvre sur f ∈ [0, 1] pour une paire de coureurs.

    delta(f) = d0 + f * (d1 - d0) est la différence de temps absolue interpolée
    linéairement.  delta > 0 signifie que le coureur « self » est en avance sur
    le coureur « autre » de delta dixièmes de seconde.

    Fonction lièvre h(d) :
        d ≤ 0          → 0        (self est derrière)
        0 < d ≤ T1     → 1        (self totalement en tête)
        T1 < d ≤ T2    → (T2-d) / (T2-T1)   (zone de transition linéaire)
        d > T2         → 0        (trop d'avance, aucune interaction)

    T1 et T2 sont exprimés en dixièmes de seconde.

    L'intégrale est calculée analytiquement par découpage en sous-intervalles
    aux points de transition de h (d = 0, T1, T2).

    Retourne un flottant dans [0, 1].
    """
    # Cas ex-aequo strict : les deux coureurs ont les mêmes heures de passage
    # à tous les postes → h = 0.5 par convention (spec).
    if d0 == 0 and d1 == 0:
        return 0.5

    slope = d1 - d0

    # Calcule les valeurs de f où delta franchit 0, T1 ou T2.
    breakpoints = {0.0, 1.0}
    if abs(slope) > 1e-9:
        for d_crit in (0.0, float(T1), float(T2)):
            f_c = (d_crit - d0) / slope
            if 0.0 < f_c < 1.0:
                breakpoints.add(f_c)

    total = 0.0
    fps = sorted(breakpoints)
    for idx in range(len(fps) - 1):
        fa, fb = fps[idx], fps[idx + 1]
        da = d0 + fa * slope
        db = d0 + fb * slope
        avg_d = (da + db) / 2.0
        w = fb - fa

        if avg_d <= 0 or avg_d > T2:
            pass                                   # h = 0
        elif avg_d <= T1:
            total += w                             # h = 1
        else:
            total += w * (T2 - avg_d) / (T2 - T1) # h linéaire

    return total


def compute_grouping_index(runners, controls_seq, radio_map, t1_sec=7, t2_sec=20):
    """Calcule l'indice de regroupement (lièvre/suiveur) par coureur et par tronçon.

    Pour chaque tronçon, on compare chaque paire de coureurs ayant tous les deux
    des temps valides aux deux postes encadrant ce tronçon.  Si leur écart au
    poste de départ du tronçon est supérieur à T2, la paire est ignorée pour ce
    tronçon (ils ne sont pas dans le même groupe).

    L'interpolation linéaire des temps de passage permet de suivre en continu
    l'évolution de l'écart entre deux coureurs au fil du tronçon et d'intégrer
    la fonction lièvre analytiquement.

    Indice net par tronçon = moyenne sur tous les adversaires valides de
        (indice_suiveur_ik - indice_lièvre_ik)  ∈ [-1, 1]
        · négatif → coureur en tête (lièvre, vert)
        · positif → coureur qui suit (suiveur, rouge)

    Indice global = moyenne pondérée des indices de tronçon, pondérée par la
    durée du tronçon du coureur (proxy de la longueur physique du tronçon).

    Note : la règle "un coureur en 2e position d'un groupe ne peut pas avoir
    d'indice lièvre vis-à-vis du 3e" n'est pas implémentée ; on utilise la
    moyenne pair-à-pair.

    Args:
        runners      : liste d'objets Mopcompetitor (attributs .id, .st, .rt)
        controls_seq : liste de {'ctrl_id': int, 'ctrl_name': str} dans l'ordre
        radio_map    : {runner_id: {ctrl_id: rt}} — temps cumulés depuis le départ
        t1_sec       : seuil « lièvre à 100% » en secondes (défaut : 7)
        t2_sec       : seuil « aucune interaction » en secondes (défaut : 20)

    Returns:
        Liste de dicts (un par coureur dans le même ordre que `runners`) :
        {
            'id'          : int,
            'leg_indices' : [float|None, ...],  # n_legs valeurs
            'leg_ref_ids' : [int|None, ...],    # id du partenaire dominant par tronçon
            'global_index': float|None,
        }
        Le partenaire dominant est celui dont |follow_ik - hare_ik| est le plus grand
        sur ce tronçon — i.e. le coureur qui influence le plus l'indice.
    """
    T1 = int(t1_sec * 10)
    T2 = int(t2_sec * 10)
    n_ctrls = len(controls_seq)
    n_legs  = n_ctrls + 1          # n intermédiaires + 1 tronçon final

    # ── Construction des tableaux de temps absolus ────────────────────────────
    # abs_pts[i][j] = heure absolue du coureur i à la frontière j du tronçon
    #   j = 0          → heure de départ (c.st)
    #   j = 1..n_ctrls → c.st + radio[ctrl_id]  (None si poste manquant)
    #   j = n_ctrls+1  → c.st + c.rt            (None si pas d'arrivée)
    abs_pts = []
    for c in runners:
        if c.st <= 0:
            abs_pts.append(None)
            continue
        radios = radio_map.get(c.id, {})
        pts    = [c.st]
        for ctrl in controls_seq:
            rt = radios.get(ctrl['ctrl_id'], -1)
            pts.append(c.st + rt if rt > 0 else None)
        pts.append(c.st + c.rt if c.rt > 0 else None)
        abs_pts.append(pts)

    n = len(runners)
    results = []

    for i in range(n):
        pts_i = abs_pts[i]
        if pts_i is None:
            results.append({'id': runners[i].id,
                            'leg_indices': [None] * n_legs,
                            'leg_ref_ids': [None] * n_legs,
                            'global_index': None})
            continue

        leg_indices = []
        leg_ref_ids = []
        leg_weights = []

        for leg_j in range(n_legs):
            t_start = pts_i[leg_j]
            t_end   = pts_i[leg_j + 1]

            if t_start is None or t_end is None or t_end <= t_start:
                leg_indices.append(None)
                leg_ref_ids.append(None)
                leg_weights.append(0)
                continue

            net_sum      = 0.0
            n_valid      = 0
            best_ref_id  = None
            best_abs_net = -1.0

            for k in range(n):
                if k == i:
                    continue
                pts_k = abs_pts[k]
                if pts_k is None:
                    continue
                t_k_start = pts_k[leg_j]
                t_k_end   = pts_k[leg_j + 1]
                if t_k_start is None or t_k_end is None:
                    continue
                # Ignorer si l'écart au poste de départ du tronçon dépasse T2
                if abs(t_start - t_k_start) > T2:
                    continue

                # d > 0  ↔  coureur i est en avance sur coureur k
                d0 = t_k_start - t_start
                d1 = t_k_end   - t_end

                hare_ik   = _hare_integral(d0,  d1,  T1, T2)  # i devant k
                follow_ik = _hare_integral(-d0, -d1, T1, T2)  # k devant i
                net_ik    = follow_ik - hare_ik
                net_sum  += net_ik
                n_valid  += 1

                # Coureur dominant : celui dont la contribution absolue est la plus grande
                if abs(net_ik) > best_abs_net:
                    best_abs_net = abs(net_ik)
                    best_ref_id  = runners[k].id

            if n_valid == 0:
                leg_indices.append(None)
                leg_ref_ids.append(None)
                leg_weights.append(0)
            else:
                leg_indices.append(net_sum / n_valid)
                leg_ref_ids.append(best_ref_id)
                leg_weights.append(t_end - t_start)

        # ── Indice global : moyenne pondérée par durée de tronçon ─────────────
        valid_pairs = [
            (leg_indices[j], leg_weights[j])
            for j in range(n_legs)
            if leg_indices[j] is not None and leg_weights[j] > 0
        ]
        if valid_pairs:
            total_w    = sum(w for _, w in valid_pairs)
            global_idx = sum(v * w for v, w in valid_pairs) / total_w if total_w > 0 else None
        else:
            global_idx = None

        results.append({
            'id':           runners[i].id,
            'leg_indices':  leg_indices,
            'leg_ref_ids':  leg_ref_ids,
            'global_index': global_idx,
        })

    return results


# ─── Régularité ───────────────────────────────────────────────────────────────

def compute_regularity_analysis(finishers, controls_seq, radio_map, top_fraction=0.25):
    """Calcule les indices de régularité par coureur, par tronçon et pour la catégorie.

    La régularité est mesurée par la déviation standard (σ) des indices de
    performance. Une valeur plus faible indique une meilleure régularité.

    Trois niveaux :
      · Coureur   : σ pondéré des IP du coureur sur l'ensemble des tronçons,
                    pondéré par le temps de référence de chaque tronçon
                    (proxy de la longueur physique).
      · Tronçon   : σ simple des IP de tous les coureurs sur ce tronçon.
      · Catégorie : moyenne des σ pondérés de tous les coureurs.

    Args:
        finishers      : liste de coureurs classés (stat=OK, rt>0).
        controls_seq   : liste ordonnée de {'ctrl_id': int, 'ctrl_name': str}.
        radio_map      : {runner_id: {ctrl_id: rt}} — temps cumulés depuis le départ.
        top_fraction   : fraction des meilleurs temps pour la référence (défaut 25 %).

    Returns:
        dict avec :
          'runner_regularity'   : liste de dicts (un par coureur, même ordre que finishers)
              {'id', 'weighted_std', 'mean_pi', 'leg_pis', 'leg_weights'}
          'leg_stds'            : [float|None, ...]  — σ par tronçon (n_legs valeurs)
          'leg_refs'            : [float|None, ...]  — temps de référence par tronçon
          'category_regularity' : float|None         — moyenne des σ pondérés
          'n_legs'              : int
    """
    import math

    if not finishers:
        return {
            'runner_regularity':   [],
            'leg_stds':            [],
            'leg_refs':            [],
            'category_regularity': None,
            'n_legs':              0,
        }

    leg_matrix = build_leg_matrix(finishers, controls_seq, radio_map)
    n_legs     = len(controls_seq) + 1
    leg_refs   = compute_leg_refs(leg_matrix, n_legs, top_fraction)

    # ── Matrice des indices de performance ────────────────────────────────────
    # pi_matrix[i] = {'pis': [...], 'weights': [...]}
    pi_matrix = []
    for i in range(len(finishers)):
        pis, weights = [], []
        for j in range(n_legs):
            t   = leg_matrix[i][j]
            ref = leg_refs[j]
            if t and t > 0 and ref and ref > 0:
                pis.append(ref / t)
                weights.append(ref)
            else:
                pis.append(None)
                weights.append(None)
        pi_matrix.append({'pis': pis, 'weights': weights})

    # ── Régularité par coureur : σ pondéré de ses propres IP ─────────────────
    runner_regularity = []
    for i, c in enumerate(finishers):
        pis     = pi_matrix[i]['pis']
        weights = pi_matrix[i]['weights']
        valid   = [
            (pi, w) for pi, w in zip(pis, weights)
            if pi is not None and w is not None
        ]
        if len(valid) >= 2:
            total_w  = sum(w for _, w in valid)
            mean_pi  = sum(pi * w for pi, w in valid) / total_w
            variance = sum(w * (pi - mean_pi) ** 2 for pi, w in valid) / total_w
            wstd     = math.sqrt(variance)
        elif len(valid) == 1:
            mean_pi = valid[0][0]
            wstd    = 0.0
        else:
            mean_pi = None
            wstd    = None

        runner_regularity.append({
            'id':           c.id,
            'weighted_std': wstd,
            'mean_pi':      mean_pi,
            'leg_pis':      pis,
            'leg_weights':  weights,
        })

    # ── Régularité par tronçon : σ simple sur tous les coureurs ───────────────
    leg_stds = []
    for j in range(n_legs):
        col_pis = [
            pi_matrix[i]['pis'][j]
            for i in range(len(finishers))
            if pi_matrix[i]['pis'][j] is not None
        ]
        if len(col_pis) >= 2:
            mean     = sum(col_pis) / len(col_pis)
            variance = sum((pi - mean) ** 2 for pi in col_pis) / len(col_pis)
            leg_stds.append(math.sqrt(variance))
        else:
            leg_stds.append(None)

    # ── Régularité catégorie : moyenne des σ pondérés des coureurs ────────────
    valid_stds          = [
        r['weighted_std'] for r in runner_regularity
        if r['weighted_std'] is not None
    ]
    category_regularity = sum(valid_stds) / len(valid_stds) if valid_stds else None

    return {
        'runner_regularity':   runner_regularity,
        'leg_stds':            leg_stds,
        'leg_refs':            leg_refs,
        'category_regularity': category_regularity,
        'n_legs':              n_legs,
    }
