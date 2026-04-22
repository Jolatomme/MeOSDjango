"""
services.py — Helpers métier réutilisables entre les vues MeOS.

Chaque fonction est pure (pas d'effet de bord) et testable sans requête HTTP.
Les accès DB restent ici pour pouvoir les mocker facilement dans les tests.
"""

from .models import (
    Moporganization, Mopcontrol, Mopclasscontrol, Mopradio, Mopclass,
    STAT_OK, STATUS_LABELS, format_time,
)


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


# ─── Calcul des splits ─────────────────────────────────────────────────────────

def compute_splits(runner_id, controls_seq, radio_map):
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
        prev = abs_t if abs_t > 0 else -1
    return splits


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
    return vw[-1][0]


def compute_error_estimates(finishers, controls_seq, radio_map, top_fraction=0.25):
    import math
    leg_matrix  = build_leg_matrix(finishers, controls_seq, radio_map)
    n_legs_full = len(controls_seq)
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


def get_courses_map(cid):
    """Charge tous les circuits d'une compétition (3 requêtes DB).

    Un circuit = groupe de catégories partageant la même séquence de postes.

    Returns
    -------
    dict { hash_8chars: course_dict }
    """
    from collections import defaultdict

    all_classes = list(Mopclass.objects.filter(cid=cid).order_by('ord', 'name'))
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

    return courses
