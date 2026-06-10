import json
import re
from types import SimpleNamespace
from django.shortcuts import render, get_object_or_404, redirect
from django.http import Http404, HttpResponse, JsonResponse


from .forms import MeosFileForm, VerifieMoiFileForm

from .models import (
    Mopcompetition, Mopclass, Moporganization, Mopcompetitor,
    Mopteam, Mopteammember, MeosTutorial,
    format_time, STAT_OK, STATUS_LABELS,
    STAT_NT, STAT_MP, STAT_DNF, STAT_DQ, STAT_OT,
    STAT_OCC, STAT_DNS, STAT_CANCEL, STAT_NP,
)
from .services import (
    get_org_map, get_class_controls, get_controls_by_leg,
    get_radio_map, compute_splits, mark_best_splits, rank_splits,
    rank_finishers, build_rank_map,
    build_leg_matrix, compute_leg_refs,
    build_abs_time_series, compute_error_estimates,
    compute_grouping_index, compute_regularity_analysis,
    compute_course_hash, get_courses_map,
    slugify_no_prefix,
)
from .meos_checker import check_meos_file
from .verifie_moi import generate_verifie_moi_csv


# ─── Ordre de tri des non-classés ─────────────────────────────────────────────

_NON_FINISHER_ORDER = {
    STAT_OCC: 1, STAT_NT: 1, STAT_OT: 1, STAT_DQ: 1,
    STAT_MP:  2,
    STAT_DNF: 3,
    STAT_DNS: 4, STAT_NP: 4, STAT_CANCEL: 4,
}

# Hash de circuit : exactement 8 caractères hexadécimaux minuscules
_COURSE_HASH_RE = re.compile(r'^[0-9a-f]{8}$')


# ══════════════════════════════════════════════════════════════════════════════
# Helpers internes
# ══════════════════════════════════════════════════════════════════════════════

def _resolve_class_id(cid, class_id):
    """Convert a class identifier to a numeric ID.

    Accepts a numeric string, an integer, or a class name string.
    When given a class name, performs a DB lookup to resolve it.
    """
    if isinstance(class_id, str) and not class_id.isdigit():
        cls = get_object_or_404(Mopclass, cid=cid, name=class_id)
        return cls.id
    return int(class_id) if isinstance(class_id, str) else class_id


def _load_class_context(cid, class_id):
    """Charge le contexte commun à toutes les vues catégorie **et circuit**.

    Si ``class_id`` est un hash de circuit (8 chars hex), charge automatiquement
    tous les coureurs du circuit et renvoie un ``cls`` pseudo-objet compatible
    avec les templates.

    Returns
    -------
    (competition, cls, competitors, course)
        - ``course`` : dict issu de ``get_courses_map``, ou ``None`` pour une
          vraie catégorie.
        - ``cls``    : Mopclass réel, ou SimpleNamespace(id, name, cid,
          display_name) pour un circuit (``name`` = hash, utilisé dans les
          URLs).
    """
    competition = get_object_or_404(Mopcompetition, cid=cid)

    # ── Cas circuit ───────────────────────────────────────────────────────────
    if isinstance(class_id, str) and _COURSE_HASH_RE.match(class_id):
        courses_map = get_courses_map(cid)
        course      = courses_map.get(class_id)
        if not course:
            raise Http404("Circuit non trouvé")

        cls = SimpleNamespace(
            id=class_id, name=class_id, cid=cid,
            display_name=course['display_name'],
        )
        competitors = []
        for cls_id in course['class_ids']:
            competitors.extend(list(Mopcompetitor.objects.filter(cid=cid, cls=cls_id)))

        cls_map = {c.id: c for c in course['classes']}
        for comp in competitors:
            comp.class_obj = cls_map.get(comp.cls)

        return competition, cls, competitors, course

    # ── Cas catégorie normale ──────────────────────────────────────────────────
    class_id    = _resolve_class_id(cid, class_id)
    cls         = get_object_or_404(Mopclass, cid=cid, id=class_id)
    competitors = list(Mopcompetitor.objects.filter(cid=cid, cls=class_id))
    return competition, cls, competitors, None


def _get_adjacent_classes(cid, class_id):
    """Return the previous and next class in ordering for navigation links.

    Returns (prev_cls, next_cls), where either can be None at boundaries
    or when ``class_id`` is not found.
    """
    all_classes = list(Mopclass.objects.filter(cid=cid).order_by('ord', 'name'))
    current_idx = next((i for i, c in enumerate(all_classes) if c.id == class_id), None)
    if current_idx is None:
        return None, None
    prev_cls = all_classes[current_idx - 1] if current_idx > 0 else None
    next_cls = all_classes[current_idx + 1] if current_idx < len(all_classes) - 1 else None
    return prev_cls, next_cls


def _sort_non_finishers(non_finishers):
    """Sort non-finishing competitors by a fixed status priority, then name.

    Priority order: OCC/NT/OT/DQ (1), MP (2), DNF (3), DNS/NP/CANCEL (4),
    unknown status (5). Within each group, alphabetical by name.
    """
    return sorted(
        non_finishers,
        key=lambda c: (_NON_FINISHER_ORDER.get(c.stat, 5), c.name.lower()),
    )


def _controls_for(cid, cls, course):
    """Retourne controls_seq selon qu'on est en mode catégorie ou circuit."""
    if course is not None:
        return course['controls_seq']
    seq, _ = get_class_controls(cid, cls.id)
    return seq






    # Sort by start time
    rows.sort(key=lambda r: r['start_time_sort'])

    # Group by category
    from collections import defaultdict
    by_category = defaultdict(list)
    for row in rows:
        by_category[row['category']].append(row)

    # Group by club
    by_club = defaultdict(list)
    for row in rows:
        by_club[row['club_display']].append(row)

    # Group by exact start time
    by_start_time = defaultdict(list)
    for row in rows:
        if row['start_time']:
            by_start_time[row['start_time']].append(row)

    def make_groups(group_dict, sort_key=None):
        groups = []
        for key, items in group_dict.items():
            if not key:
                continue
            slug = re.sub(r'[^a-z0-9]+', '-', key.lower()).strip('-')
            groups.append({
                'name': key,
                'slug': slug,
                'rows': items,
            })
        if sort_key:
            groups.sort(key=sort_key)
        else:
            groups.sort(key=lambda g: g['name'])
        return groups

    data = {
        'meta': {
            'event_name': competition.name,
            'event_date': competition.date.strftime('%Y-%m-%d') if competition.date else '',
        },
        'groups': {
            'category': make_groups(by_category),
            'club': make_groups(by_club),
            'start_time': make_groups(by_start_time, sort_key=lambda g: g['name']),
        }
    }

    return render(request, 'results/start_list.html', {
        'competition': competition,
        'start_list_data': json.dumps(data),
    })


# ══════════════════════════════════════════════════════════════════════════════
# Résultats — catégorie ET circuit
# (class_id peut être un nom/identifiant de catégorie OU un hash de circuit)
# ══════════════════════════════════════════════════════════════════════════════

def class_results(request, cid, class_id):
    """Results page for a single class or course.

    Handles both regular categories and course (circuit) views.
    Computes splits, best split markers, leg ranks, and error estimates.
    Redirects to relay_results when the class has teams.
    """
    competition, cls, competitors, course = _load_class_context(cid, class_id)

    # Redirect vers relais seulement pour les vraies catégories
    if course is None and Mopteam.objects.filter(cid=cid, cls=cls.id).exists():
        return redirect('results:relay_results', cid=cid, class_id=class_id)

    # Navigation catégorie adjacente (non pertinent pour un circuit)
    prev_cls, next_cls = (None, None)
    if course is None:
        prev_cls, next_cls = _get_adjacent_classes(cid, cls.id)

    org_map = get_org_map(cid, as_objects=True)
    for c in competitors:
        c.org_obj = org_map.get(c.org)

    finishers, non_finishers, leader_time = rank_finishers(competitors)

    # Rang dans la catégorie d'origine pour les vues circuit
    if course is not None:
        class_rank_cache: dict = {}
        for c in competitors:
            cls_id = c.cls
            if cls_id not in class_rank_cache:
                all_in_cls = [x for x in competitors if x.cls == cls_id]
                cls_finishers = sorted(
                    [x for x in all_in_cls if x.is_ok],
                    key=lambda x: x.rt,
                )
                class_rank_cache[cls_id] = {x.id: i+1 for i, x in enumerate(cls_finishers)}
            c.cat_rank = class_rank_cache[cls_id].get(c.id)

    results      = finishers + _sort_non_finishers(non_finishers)
    controls_seq = _controls_for(cid, cls, course)
    radio_map    = get_radio_map(cid, [c.id for c in results])

    for c in results:
        c.splits = compute_splits(c.id, controls_seq, radio_map)

    # Ajout du tronçon arrivée pour tous (cohérence mark_best_splits / rank_splits)
    for c in results:
        if c.rt > 0:
            last_abs = c.splits[-1]['abs_raw'] if c.splits else None
            leg_raw = c.rt - last_abs if last_abs else c.rt
            c.splits.append({
                'ctrl_name': 'Arrivée',
                'abs_time':  format_time(c.rt),
                'leg_time':  format_time(leg_raw) if leg_raw else '-',
                'leg_raw':   leg_raw,
                'abs_raw':   c.rt,
                'is_best':   False,
                'leg_rank':  None,
                'abs_rank':  None,
            })
        else:
            c.splits.append({
                'ctrl_name': 'Arrivée',
                'abs_time':  '-',
                'leg_time':  '-',
                'leg_raw':   None,
                'abs_raw':   None,
                'is_best':   False,
                'leg_rank':  None,
                'abs_rank':  None,
            })

    mark_best_splits(finishers, results)
    rank_splits(finishers, results)

    error_map = {}
    if controls_seq and finishers:
        error_map = compute_error_estimates(finishers, controls_seq, radio_map)
        for c in results:
            errs = error_map.get(c.id, [])
            for idx, sp in enumerate(c.splits):
                e = errs[idx] if idx < len(errs) else None
                sp['error_time'] = round(e['error_time']) if e and e['error_time'] is not None else None
                sp['error_pct']  = round(e['error_pct']) if e and e['error_pct'] is not None else None

    leg_error_data = []
    if controls_seq and finishers:
        for j, ctrl in enumerate(controls_seq):
            entry = {'ctrl_name': ctrl['ctrl_name'], 'errors': []}
            for c in finishers:
                errs = error_map.get(c.id, [])
                if j < len(errs) and errs[j]['error_time'] is not None:
                    entry['errors'].append({
                        'et': round(errs[j]['error_time']),
                        'ep': round(errs[j]['error_pct']),
                    })
            leg_error_data.append(entry)

    # ← Le seul branchement template : circuit ou catégorie
    template = 'results/course_results.html' if course else 'results/class_results.html'
    return render(request, template, {
        'competition':         competition,
        'cls':                 cls,
        'course':              course,
        'results':             results,
        'leader_time':         format_time(leader_time) if leader_time else '-',
        'controls_seq':        controls_seq,
        'has_splits':          bool(controls_seq),
        'current_analysis':    'results',
        'leg_error_data_json': json.dumps(leg_error_data),
        'prev_cls':            prev_cls,
        'next_cls':            next_cls,
        'course_hash':         course['hash'] if course else compute_course_hash(controls_seq),
    })


# ══════════════════════════════════════════════════════════════════════════════
# Fiche concurrent & organisation
# ══════════════════════════════════════════════════════════════════════════════

def competitor_detail(request, cid, competitor_id):
    """Individual competitor detail page with split times."""
    competition = get_object_or_404(Mopcompetition, cid=cid)
    competitor  = get_object_or_404(Mopcompetitor, cid=cid, id=competitor_id)
    org = Moporganization.objects.filter(cid=cid, id=competitor.org).first()
    cls = Mopclass.objects.filter(cid=cid, id=competitor.cls).first()
    controls_seq, _ = get_class_controls(cid, competitor.cls)
    radio_map       = get_radio_map(cid, [competitor_id])
    splits          = compute_splits(competitor_id, controls_seq, radio_map)
    # Ajout du tronçon arrivée
    if competitor.is_ok and splits and competitor.rt > 0:
        last_abs = splits[-1]['abs_raw']
        leg_raw = competitor.rt - last_abs if last_abs else competitor.rt
        splits.append({
            'ctrl_name': 'Arrivée',
            'abs_time':  format_time(competitor.rt),
            'leg_time':  format_time(leg_raw) if leg_raw else '-',
            'leg_raw':   leg_raw,
            'abs_raw':   competitor.rt,
            'is_best':   False,
            'leg_rank':  None,
            'abs_rank':  None,
        })
    return render(request, 'results/competitor_detail.html', {
        'competition': competition, 'competitor': competitor,
        'org': org, 'cls': cls, 'splits': splits,
        'total_time': format_time(competitor.rt) if competitor.is_ok else competitor.status_label,
    })


def org_results(request, cid, org_id):
    """Results page for a single organisation — all runners grouped by class."""
    competition  = get_object_or_404(Mopcompetition, cid=cid)
    organization = get_object_or_404(Moporganization, cid=cid, id=org_id)
    org_competitors = list(Mopcompetitor.objects.filter(cid=cid, org=org_id))
    class_map = {c.id: c for c in Mopclass.objects.filter(cid=cid)}
    for c in org_competitors:
        c.class_obj = class_map.get(c.cls)

    class_ids = {c.cls for c in org_competitors}
    class_rank_maps = {}
    for cls_id in class_ids:
        all_in_class = list(Mopcompetitor.objects.filter(cid=cid, cls=cls_id))
        finishers_in_class, _, _ = rank_finishers(all_in_class)
        class_rank_maps[cls_id] = {c.id: c.rank for c in finishers_in_class}

    for c in org_competitors:
        c.cat_rank = class_rank_maps.get(c.cls, {}).get(c.id)

    finishers = sorted(
        [c for c in org_competitors if c.is_ok],
        key=lambda c: (
            c.cat_rank if c.cat_rank is not None else 9999,
            c.class_obj.ord  if c.class_obj else 9999,
            c.class_obj.name if c.class_obj else '',
        ),
    )
    non_finishers = _sort_non_finishers([c for c in org_competitors if not c.is_ok])
    return render(request, 'results/org_results.html', {
        'competition': competition, 'organization': organization,
        'competitors': finishers + non_finishers,
    })


# ══════════════════════════════════════════════════════════════════════════════
# Statistiques & API
# ══════════════════════════════════════════════════════════════════════════════




def api_class_results(request, cid, class_id):
    """JSON API — returns ranked finishers for a class with times and gaps."""
    class_id        = _resolve_class_id(cid, class_id)
    competitors     = list(Mopcompetitor.objects.filter(cid=cid, cls=class_id))
    org_map         = get_org_map(cid)
    finishers, _, _ = rank_finishers(competitors)
    leader          = finishers[0].rt if finishers else None
    data = [
        {'rank': i + 1, 'name': c.name, 'org': org_map.get(c.org, ''),
         'time': format_time(c.rt),
         'behind': f'+{format_time(c.rt - leader)}' if i > 0 else ''}
        for i, c in enumerate(finishers)
    ]
    return JsonResponse({'results': data})


# ══════════════════════════════════════════════════════════════════════════════
# Analyses — catégorie ET circuit via _load_class_context unifié
#
# class_id peut être :
#   - un nom ou identifiant entier de catégorie → mode catégorie
#   - un hash 8-char hex                        → mode circuit
#
# Aucune vue dupliquée : les templates utilisent {% if course %} pour adapter
# l'affichage (fil d'Ariane, onglets de navigation).
# ══════════════════════════════════════════════════════════════════════════════

def superman_analysis(request, cid, class_id):
    """Superman (optimal runner) chart — best time on each leg stitched together.

    Renders a line chart comparing each runner's cumulative loss versus the
    theoretical "superman" who takes the best split on every leg.
    """
    competition, cls, competitors, course = _load_class_context(cid, class_id)
    org_map      = get_org_map(cid)
    controls_seq = _controls_for(cid, cls, course)
    controls_labels = [c['ctrl_name'] for c in controls_seq]
    finishers, _, _ = rank_finishers(competitors)

    if not finishers:
        return render(request, 'results/superman.html', {
            'competition': competition, 'cls': cls, 'course': course,
            'no_data': True, 'current_analysis': 'superman',
        })

    radio_map  = get_radio_map(cid, [c.id for c in finishers])
    leg_matrix = build_leg_matrix(finishers, controls_seq, radio_map)
    n_legs     = len(controls_seq) + 1

    superman_legs, superman_leg_names = [], []
    for j in range(n_legs):
        best = None
        for i, legs in enumerate(leg_matrix):
            v = legs[j] if j < len(legs) else None
            if v is not None and v > 0 and (best is None or v < best):
                best = v
        best_names = [finishers[i].name for i, legs in enumerate(leg_matrix)
                      if j < len(legs) and legs[j] == best] if best is not None else ['-']
        superman_legs.append(best)
        superman_leg_names.append(best_names)

    superman_total = sum(v for v in superman_legs if v is not None)
    superman_cum, acc = [], 0
    for v in superman_legs:
        acc += v if v is not None else 0
        superman_cum.append(acc)

    x_labels = ['Départ'] + controls_labels + ['Arrivée']
    series   = []
    for i, c in enumerate(finishers):
        radios = radio_map.get(c.id, {})
        points = [0]; labels = ['+0:00']; valid = True
        for j, ctrl in enumerate(controls_seq):
            abs_t = radios.get(ctrl['ctrl_id'], -1)
            if abs_t <= 0:
                valid = False; break
            loss = int(abs_t - superman_cum[j])
            points.append(loss)
            labels.append(('+' if loss >= 0 else '') + format_time(loss))
        if valid:
            final_loss = int(c.rt - superman_total)
            points.append(final_loss)
            labels.append(('+' if final_loss >= 0 else '') + format_time(final_loss))
        else:
            while len(points) < len(x_labels):
                points.append(None); labels.append(None)
        series.append({
            'id': c.id, 'name': c.name, 'org': org_map.get(c.org, ''),
            'rank': i + 1, 'total': format_time(c.rt),
            'loss': format_time(c.rt - superman_total) if superman_total else '-',
            'points': points, 'labels': labels,
        })

    leg_labels = controls_labels + ['Arrivée']
    superman_leg_data = [
        {'ctrl': leg_labels[j],
         'time': format_time(superman_legs[j]) if superman_legs[j] else '-',
         'names': superman_leg_names[j]}
        for j in range(n_legs)
    ]
    return render(request, 'results/superman.html', {
        'competition': competition, 'cls': cls, 'course': course,
        'series': series, 'series_json': json.dumps(series),
        'x_labels_json': json.dumps(x_labels),
        'superman_total': format_time(superman_total),
        'superman_leg_data': superman_leg_data,
        'controls_labels': controls_labels,
        'no_data': False, 'n_finishers': len(finishers),
        'current_analysis': 'superman',
    })


def performance_analysis(request, cid, class_id):
    """Performance index analysis — ratio of each runner's leg time to a reference.

    The reference is the top-25% average per leg. A lower performance index
    (closer to 0) means the runner is closer to the reference pace.
    """
    competition, cls, competitors, course = _load_class_context(cid, class_id)
    finishers, _, _ = rank_finishers(competitors)
    if not finishers:
        return render(request, 'results/performance.html', {
            'competition': competition, 'cls': cls, 'course': course,
            'no_data': True, 'current_analysis': 'performance',
        })
    org_map         = get_org_map(cid)
    controls_seq    = _controls_for(cid, cls, course)
    controls_labels = [c['ctrl_name'] for c in controls_seq]
    radio_map       = get_radio_map(cid, [c.id for c in finishers])
    leg_matrix      = build_leg_matrix(finishers, controls_seq, radio_map)
    n_legs          = len(controls_seq) + 1
    leg_labels      = controls_labels + ['Arrivée']
    leg_refs        = compute_leg_refs(leg_matrix, n_legs, top_fraction=0.25)

    series = []
    for i, c in enumerate(finishers):
        indices, weights = [], []
        for j in range(n_legs):
            t = leg_matrix[i][j]; ref = leg_refs[j]
            if t and t > 0 and ref and ref > 0:
                indices.append(round(ref / t, 5)); weights.append(round(ref))
            else:
                indices.append(None); weights.append(None)
        valid = [(pi, w) for pi, w in zip(indices, weights) if pi is not None]
        if valid:
            total_w  = sum(w for _, w in valid)
            mean_pi  = sum(pi * w for pi, w in valid) / total_w
            variance = sum(w * (pi - mean_pi) ** 2 for pi, w in valid) / total_w
            std_pi   = variance ** 0.5
        else:
            mean_pi = std_pi = None
        series.append({
            'id': c.id, 'name': c.name, 'org': org_map.get(c.org, ''),
            'rank': i + 1, 'time': format_time(c.rt),
            'indices': indices, 'weights': weights,
            'mean_pi': round(mean_pi, 4) if mean_pi is not None else None,
            'std_pi':  round(std_pi, 4)  if std_pi  is not None else None,
        })
    leg_info = [
        {'label': leg_labels[j], 'ref': format_time(round(leg_refs[j])) if leg_refs[j] else '-'}
        for j in range(n_legs)
    ]
    return render(request, 'results/performance.html', {
        'competition': competition, 'cls': cls, 'course': course,
        'series_json': json.dumps(series), 'leg_info_json': json.dumps(leg_info),
        'n_legs': n_legs, 'n_finishers': len(finishers),
        'no_data': False, 'current_analysis': 'performance',
    })


def regularity_analysis(request, cid, class_id):
    """Regularity analysis — weighted standard deviation of leg performance indices.

    A lower weighted std means the runner maintains a more consistent pace
    relative to the field across all legs. Requires at least 2 finishers.
    """
    competition, cls, competitors, course = _load_class_context(cid, class_id)
    finishers, _, _ = rank_finishers(competitors)
    if len(finishers) < 2:
        return render(request, 'results/regularity.html', {
            'competition': competition, 'cls': cls, 'course': course,
            'no_data': True, 'current_analysis': 'regularity',
        })
    org_map         = get_org_map(cid)
    controls_seq    = _controls_for(cid, cls, course)
    controls_labels = [c['ctrl_name'] for c in controls_seq]
    radio_map       = get_radio_map(cid, [c.id for c in finishers])
    reg_data        = compute_regularity_analysis(finishers, controls_seq, radio_map)
    leg_labels      = controls_labels + ['Arrivée']

    series = []
    for i, c in enumerate(finishers):
        reg = reg_data['runner_regularity'][i]
        series.append({
            'id': c.id, 'name': c.name, 'org': org_map.get(c.org, ''),
            'rank': i + 1, 'time': format_time(c.rt),
            'weighted_std': round(reg['weighted_std'], 4) if reg['weighted_std'] is not None else None,
            'mean_pi':      round(reg['mean_pi'], 4)      if reg['mean_pi']      is not None else None,
            'leg_pis':      [round(pi, 4) if pi is not None else None for pi in reg['leg_pis']],
            'leg_weights':  [round(w) if w is not None else None for w in reg['leg_weights']],
        })
    leg_info = [
        {'label':   leg_labels[j],
         'ref':     format_time(round(reg_data['leg_refs'][j])) if reg_data['leg_refs'][j] else '-',
         'leg_std': round(reg_data['leg_stds'][j], 4) if reg_data['leg_stds'][j] is not None else None}
        for j in range(reg_data['n_legs'])
    ]
    cat_reg = reg_data['category_regularity']
    return render(request, 'results/regularity.html', {
        'competition': competition, 'cls': cls, 'course': course,
        'series_json': json.dumps(series), 'leg_info_json': json.dumps(leg_info),
        'category_regularity': round(cat_reg, 4) if cat_reg is not None else None,
        'n_legs': reg_data['n_legs'], 'n_finishers': len(finishers),
        'no_data': False, 'current_analysis': 'regularity',
    })


def grouping_analysis(request, cid, class_id):
    """Grouping chart — absolute time at each control for runners with a start time.

    Useful for detecting groups/clusters on the course. Renders a scatter-style
    chart of cumulative time at each control point.
    """
    competition, cls, competitors, course = _load_class_context(cid, class_id)
    runners_with_start = sorted([c for c in competitors if c.st > 0], key=lambda c: c.st)
    if not runners_with_start:
        return render(request, 'results/grouping.html', {
            'competition': competition, 'cls': cls, 'course': course,
            'no_data': True, 'current_analysis': 'grouping',
        })
    org_map         = get_org_map(cid)
    controls_seq    = _controls_for(cid, cls, course)
    controls_labels = [c['ctrl_name'] for c in controls_seq]
    radio_map       = get_radio_map(cid, [c.id for c in runners_with_start])

    series = build_abs_time_series(runners_with_start, controls_seq, radio_map)
    finishers_rank, _, _ = rank_finishers(competitors)
    result_rank = {c.id: c.rank for c in finishers_rank}
    for s in series:
        runner = next((c for c in runners_with_start if c.id == s['id']), None)
        s['org']      = org_map.get(runner.org, '') if runner else ''
        s['stat']     = runner.stat if runner else 0
        s['rank']     = result_rank.get(s['id'])
        s['time_fmt'] = format_time(s['time']) if s['time'] > 0 else '—'

    x_labels = ['Départ'] + controls_labels + ['Arrivée']
    return render(request, 'results/grouping.html', {
        'competition': competition, 'cls': cls, 'course': course,
        'series_json': json.dumps(series), 'x_labels_json': json.dumps(x_labels),
        'n_runners': len(series), 'n_controls': len(controls_seq),
        'no_data': False, 'current_analysis': 'grouping',
    })


def grouping_index_analysis(request, cid, class_id):
    """Grouping index — quantitative measure of how clustered runners are per leg.

    Accepts optional ``t1`` and ``t2`` query parameters (in minutes) that define
    the "close" and "far" time thresholds. Defaults: t1=7, t2=20.
    """
    competition, cls, competitors, course = _load_class_context(cid, class_id)
    runners = sorted([c for c in competitors if c.st > 0], key=lambda c: c.st)
    if not runners:
        return render(request, 'results/grouping_index.html', {
            'competition': competition, 'cls': cls, 'course': course,
            'no_data': True, 'current_analysis': 'grouping_index',
        })
    try:
        t1 = max(1, min(int(request.GET.get('t1', 7)), 30))
        t2 = max(t1 + 1, min(int(request.GET.get('t2', 20)), 60))
    except (ValueError, TypeError):
        t1, t2 = 7, 20

    org_map      = get_org_map(cid)
    controls_seq = _controls_for(cid, cls, course)
    radio_map    = get_radio_map(cid, [c.id for c in runners])
    finishers, _, _ = rank_finishers(competitors)
    rank_map     = {c.id: c.rank for c in finishers}
    for c in runners:
        c.rank = rank_map.get(c.id)

    raw = compute_grouping_index(runners, controls_seq, radio_map, t1, t2)
    runner_map = {c.id: c for c in runners}
    id_to_name = {c.id: c.name for c in runners}
    for r in raw:
        c = runner_map.get(r['id'])
        if c:
            r['name'] = c.name; r['rank'] = getattr(c, 'rank', None)
            r['org']  = org_map.get(c.org, '')
        r['leg_ref_names'] = [
            id_to_name.get(rid) if rid is not None else None
            for rid in r.get('leg_ref_ids', [])
        ]
    raw.sort(key=lambda r: (r['rank'] is None, r['rank'] or 0, r.get('name', '')))
    for r in raw:
        r['leg_indices']  = [round(v, 3) if v is not None else None for v in r['leg_indices']]
        r['global_index'] = round(r['global_index'], 3) if r['global_index'] is not None else None
        del r['leg_ref_ids']

    ctrl_names = [c['ctrl_name'] for c in controls_seq]
    all_names  = ['Dép.'] + ctrl_names + ['Arr.']
    leg_labels = [f"{all_names[j]}\u2192{all_names[j+1]}" for j in range(len(all_names) - 1)]

    return render(request, 'results/grouping_index.html', {
        'competition': competition, 'cls': cls, 'course': course,
        'results_json': json.dumps(raw), 'leg_labels_json': json.dumps(leg_labels),
        'n_runners': len(raw), 'n_legs': len(leg_labels),
        't1': t1, 't2': t2, 'no_data': False, 'current_analysis': 'grouping_index',
    })


def duel_analysis(request, cid, class_id):
    """Duel chart — head-to-head split comparison for all runners.

    Renders a table where every runner's splits are shown side-by-side,
    allowing direct comparison of leg times across the field.
    Redirects to relay_results for relay classes.
    """
    competition, cls, competitors, course = _load_class_context(cid, class_id)

    # Redirect vers relais seulement pour les vraies catégories
    if course is None and Mopteam.objects.filter(cid=cid, cls=cls.id).exists():
        return redirect('results:relay_results', cid=cid, class_id=class_id)

    finishers, non_finishers, _ = rank_finishers(competitors)
    all_results = finishers + non_finishers
    if not all_results:
        return render(request, 'results/duel.html', {
            'competition': competition, 'cls': cls, 'course': course,
            'no_data': True, 'current_analysis': 'duel',
        })
    org_map      = get_org_map(cid)
    controls_seq = _controls_for(cid, cls, course)
    radio_map    = get_radio_map(cid, [c.id for c in all_results])
    runners_data = []
    for c in all_results:
        splits = compute_splits(c.id, controls_seq, radio_map)
        runners_data.append({
            'id': c.id, 'name': c.name, 'org': org_map.get(c.org, ''),
            'rank': getattr(c, 'rank', None),
            'rt_raw': c.rt if c.is_ok else None,
            'rt_fmt': format_time(c.rt) if c.is_ok else '—',
            'splits': [{'ctrl_name': sp['ctrl_name'], 'leg_raw': sp['leg_raw'],
                        'leg_fmt': sp['leg_time'], 'abs_raw': sp['abs_raw'],
                        'abs_fmt': sp['abs_time']} for sp in splits],
        })
    return render(request, 'results/duel.html', {
        'competition': competition, 'cls': cls, 'course': course,
        'no_data': False, 'current_analysis': 'duel',
        'runners_json': json.dumps(runners_data), 'n_runners': len(runners_data),
    })


# ══════════════════════════════════════════════════════════════════════════════
# Récapitulatif — tableau récapitulatif des temps intermédiaires (style WinSplits)
# ══════════════════════════════════════════════════════════════════════════════

def _load_recapitulatif_data(cid, class_id, context=None):
    """Charge et prépare les données pour le récapitulatif (HTML et CSV)."""
    if context is not None:
        competition, cls, competitors, course = context
    else:
        competition, cls, competitors, course = _load_class_context(cid, class_id)

    prev_cls, next_cls = (None, None)
    if course is None:
        prev_cls, next_cls = _get_adjacent_classes(cid, cls.id)

    org_map = get_org_map(cid, as_objects=True)
    for c in competitors:
        c.org_obj = org_map.get(c.org)

    finishers, non_finishers, leader_time = rank_finishers(competitors)

    if course is not None:
        class_rank_cache = {}
        for c in competitors:
            cls_id = c.cls
            if cls_id not in class_rank_cache:
                all_in_cls = [x for x in competitors if x.cls == cls_id]
                cls_finishers = sorted(
                    [x for x in all_in_cls if x.is_ok],
                    key=lambda x: x.rt,
                )
                class_rank_cache[cls_id] = {x.id: i + 1 for i, x in enumerate(cls_finishers)}
            c.cat_rank = class_rank_cache[cls_id].get(c.id)

    results     = finishers + _sort_non_finishers(non_finishers)
    controls_seq = _controls_for(cid, cls, course)
    radio_map   = get_radio_map(cid, [c.id for c in results])

    for c in results:
        c.splits = compute_splits(c.id, controls_seq, radio_map)
        if c.rt > 0:
            last_abs = c.splits[-1]['abs_raw'] if c.splits else None
            leg_raw  = c.rt - last_abs if last_abs else c.rt
            c.splits.append({
                'ctrl_name': 'Arrivée',
                'abs_time':  format_time(c.rt),
                'leg_time':  format_time(leg_raw) if leg_raw else '-',
                'leg_raw':   leg_raw,
                'abs_raw':   c.rt,
                'is_best':   False,
                'leg_rank':  None,
                'abs_rank':  None,
            })
        else:
            c.splits.append({
                'ctrl_name': 'Arrivée',
                'abs_time':  '-',
                'leg_time':  '-',
                'leg_raw':   None,
                'abs_raw':   None,
                'is_best':   False,
                'leg_rank':  None,
                'abs_rank':  None,
            })

    mark_best_splits(finishers, results)
    rank_splits(finishers, results)

    error_map = {}
    if controls_seq and finishers:
        error_map = compute_error_estimates(finishers, controls_seq, radio_map)
        for c in results:
            errs = error_map.get(c.id, [])
            for idx, sp in enumerate(c.splits):
                e = errs[idx] if idx < len(errs) else None
                sp['error_time'] = round(e['error_time']) if e and e['error_time'] is not None else None
                sp['error_pct']  = round(e['error_pct']) if e and e['error_pct'] is not None else None

    leg_error_data = []
    if controls_seq and finishers:
        for j, ctrl in enumerate(controls_seq):
            entry = {'ctrl_name': ctrl['ctrl_name'], 'errors': []}
            for c in finishers:
                errs = error_map.get(c.id, [])
                if j < len(errs) and errs[j]['error_time'] is not None:
                    entry['errors'].append({
                        'et': round(errs[j]['error_time']),
                        'ep': round(errs[j]['error_pct']),
                    })
            leg_error_data.append(entry)

    return competition, cls, course, results, controls_seq, prev_cls, next_cls, leader_time, leg_error_data


def _is_relay(cid, cls, course):
    """Return True if the class has teams (relay), excluding course (circuit) mode."""
    return course is None and Mopteam.objects.filter(cid=cid, cls=cls.id).exists()


def recapitulatif_analysis(request, cid, class_id):
    """Recapitulatif (WinSplits-style) table — all splits in a single grid.

    Shows every finisher's leg and cumulative times with ranks, plus error
    estimates per control. Redirects to relay_results for relay classes.
    """
    context = _load_class_context(cid, class_id)
    competition, cls, competitors, course = context
    if _is_relay(cid, cls, course):
        return redirect('results:relay_results', cid=cid, class_id=class_id)

    _, _, _, results, controls_seq, prev_cls, next_cls, leader_time, leg_error_data = \
        _load_recapitulatif_data(cid, class_id, context=context)

    return render(request, 'results/recapitulatif.html', {
        'competition':         competition,
        'cls':                 cls,
        'course':              course,
        'results':             results,
        'leader_time':         format_time(leader_time) if leader_time else '-',
        'controls_seq':        controls_seq or [],
        'has_splits':          bool(controls_seq),
        'current_analysis':    'recapitulatif',
        'prev_cls':            prev_cls,
        'next_cls':            next_cls,
        'leg_error_data_json': json.dumps(leg_error_data),
    })


def recapitulatif_csv(request, cid, class_id):
    """CSV download of the recapitulatif table (leg and cumulative times with ranks).

    Two-row format per competitor: leg times on the first row,
    cumulative times on the second. Redirects to relay_results for relays.
    """
    import csv

    context = _load_class_context(cid, class_id)
    competition, cls, _competitors, course = context
    if _is_relay(cid, cls, course):
        return redirect('results:relay_results', cid=cid, class_id=class_id)

    _comp, _cls, _course, results, controls_seq, _prev, _next, _leader, _leg_error = \
        _load_recapitulatif_data(cid, class_id, context=context)

    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = (
        f'attachment; filename="recapitulatif_{cls.name}_{competition.cid}.csv"'
    )
    writer = csv.writer(response)

    has_splits = bool(controls_seq)
    header = ['#', 'Concurrent']
    if course:
        header.append('Catégorie')
    header.append('Club')
    if has_splits:
        for ctrl in controls_seq:
            header.append(ctrl['ctrl_name'])
        header.append('Arr.')
    writer.writerow(header)

    for c in results:
        info = [c.rank or '', c.name]
        if course:
            info.append(c.class_obj.name if c.class_obj else '')
        info.append(c.org_obj.name if c.org_obj else '')
        blanks = [''] * len(info)

        if has_splits and c.is_ok:
            leg_cells  = []
            cumul_cells = []
            for sp in c.splits:
                l = sp['leg_time']
                r = sp['leg_rank']
                leg_cells.append(f'{l} ({r})' if r else l)
                a = sp['abs_time']
                ar = sp['abs_rank']
                cumul_cells.append(f'{a} ({ar})' if ar else a)
            writer.writerow(info + leg_cells)
            writer.writerow(blanks + cumul_cells)
        elif has_splits:
            dashes = ['—'] * len(c.splits)
            writer.writerow(info + dashes)
        else:
            writer.writerow(info)

    return response


# ══════════════════════════════════════════════════════════════════════════════
# Relais (catégories uniquement)
# ══════════════════════════════════════════════════════════════════════════════

def relay_results(request, cid, class_id):
    """Relay results page — per-leg split tables for each team.

    Renders teams ranked by total time, with per-leg cumulative splits,
    leg ranks, and cumulative ranks.
    """
    competition = get_object_or_404(Mopcompetition, cid=cid)
    class_id    = _resolve_class_id(cid, class_id)
    cls         = get_object_or_404(Mopclass, cid=cid, id=class_id)
    teams_qs    = list(Mopteam.objects.filter(cid=cid, cls=class_id))
    org_map     = get_org_map(cid)
    finishers, non_finishers, leader_time = rank_finishers(
        teams_qs, ok_predicate=lambda t: t.stat == STAT_OK and t.rt > 0,
    )
    all_teams   = finishers + non_finishers
    team_ids    = [t.id for t in all_teams]
    all_members = list(
        Mopteammember.objects.filter(cid=cid, id__in=team_ids).order_by('id', 'leg', 'ord')
    )
    members_by_team = {}
    for m in all_members:
        members_by_team.setdefault(m.id, []).append(m)
    runner_ids  = [m.rid for m in all_members]
    competitors = {c.id: c for c in Mopcompetitor.objects.filter(cid=cid, id__in=runner_ids)}
    n_legs      = max((m.leg for m in all_members), default=0)
    controls_by_leg, control_name_map = get_controls_by_leg(cid, class_id)
    radio_map = get_radio_map(cid, runner_ids)

    teams_data = []
    for t in all_teams:
        members = members_by_team.get(t.id, [])
        legs_data = []
        cum_time  = 0
        for leg_num in range(1, n_legs + 1):
            leg_members = sorted([m for m in members if m.leg == leg_num], key=lambda m: m.ord)
            runner = competitors.get(leg_members[0].rid) if leg_members else None
            if runner:
                leg_time_raw = runner.rt if runner.rt > 0 else None
                cum_time    += leg_time_raw or 0
                cum_time_raw = cum_time if leg_time_raw else None
                ctrl_seq     = [
                    {'ctrl_id': cv, 'ctrl_name': f"{idx+1}-{control_name_map.get(cv, str(cv))}"}
                    for idx, cv in enumerate(controls_by_leg.get(leg_num, []))
                ]
                splits = compute_splits(runner.id, ctrl_seq, radio_map)
                last_ctrl_abs = splits[-1]['abs_raw'] if splits and splits[-1]['abs_raw'] is not None else None
                finish_leg_raw = (leg_time_raw - last_ctrl_abs) if leg_time_raw and last_ctrl_abs else None
                splits.append({
                    'ctrl_name': 'Arrivée',
                    'abs_time': format_time(leg_time_raw) if leg_time_raw else '-',
                    'leg_time': format_time(finish_leg_raw) if finish_leg_raw else '-',
                    'leg_raw': finish_leg_raw,
                    'abs_raw': leg_time_raw,
                    'is_best': False,
                    'leg_rank': None,
                    'abs_rank': None,
                })
                legs_data.append({
                    'leg': leg_num, 'runner_id': runner.id, 'name': runner.name,
                    'leg_time': format_time(leg_time_raw) if leg_time_raw else '-',
                    'leg_time_raw': leg_time_raw,
                    'cum_time': format_time(cum_time_raw) if cum_time_raw else '-',
                    'cum_time_raw': cum_time_raw,
                    'stat': runner.stat, 'stat_label': runner.status_label,
                    'stat_badge': runner.status_badge,
                    'splits': splits, 'leg_rank': None, 'cum_rank': None,
                })
            else:
                legs_data.append({
                    'leg': leg_num, 'runner_id': None, 'name': '—',
                    'leg_time': '-', 'leg_time_raw': None,
                    'cum_time': '-', 'cum_time_raw': None,
                    'stat': 0, 'stat_label': '-', 'stat_badge': 'secondary',
                    'splits': [], 'leg_rank': None, 'cum_rank': None,
                })
        teams_data.append({'team': t, 'org_name': org_map.get(t.org, ''), 'legs': legs_data})

    for leg_num in range(1, n_legs + 1):
        idx = leg_num - 1
        leg_entries = sorted(
            (td['legs'][idx]['leg_time_raw'], td['team'].id)
            for td in teams_data
            if idx < len(td['legs']) and td['legs'][idx]['leg_time_raw'] is not None
        )
        cum_entries = sorted(
            (td['legs'][idx]['cum_time_raw'], td['team'].id)
            for td in teams_data
            if idx < len(td['legs']) and td['legs'][idx]['cum_time_raw'] is not None
        )
        leg_rank_map = build_rank_map(leg_entries)
        cum_rank_map = build_rank_map(cum_entries)
        for td in teams_data:
            if idx < len(td['legs']):
                td['legs'][idx]['leg_rank'] = leg_rank_map.get(td['team'].id)
                td['legs'][idx]['cum_rank'] = cum_rank_map.get(td['team'].id)

    return render(request, 'results/relay_results.html', {
        'competition': competition, 'cls': cls,
        'teams_data': teams_data,
        'leader_time': format_time(leader_time) if leader_time else '-',
        'n_legs': n_legs,
    })


