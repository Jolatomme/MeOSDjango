import json
import re
import markdown
from markdown.extensions.toc import slugify_unicode

from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse

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
)
from .meos_checker import check_meos_file
from .verifie_moi import generate_verifie_moi_csv


# ─── Ordre de tri des non-classés ─────────────────────────────────────────────
# Groupe 1 : NC / Hors compét. / No Timing / H.T. / DSQ
# Groupe 2 : PM (poinçons manquants)
# Groupe 3 : Abandon (DNF)
# Groupe 4 : Non-partants (DNS, NP, Cancel)
# Groupe 5 : tout autre statut inconnu

_NON_FINISHER_ORDER = {
    STAT_OCC:    1,   # Hors compét. (NC)
    STAT_NT:     1,   # No Timing
    STAT_OT:     1,   # H.T.
    STAT_DQ:     1,   # DSQ
    STAT_MP:     2,   # PM
    STAT_DNF:    3,   # Abandon
    STAT_DNS:    4,   # Non partant
    STAT_NP:     4,   # Non participant
    STAT_CANCEL: 4,   # Cancel
}


# ─── Helpers internes ─────────────────────────────────────────────────────────

def _resolve_class_id(cid, class_id):
    if isinstance(class_id, str) and not class_id.isdigit():
        cls = get_object_or_404(Mopclass, cid=cid, name=class_id)
        return cls.id
    return int(class_id) if isinstance(class_id, str) else class_id


def _load_class_context(cid, class_id):
    competition = get_object_or_404(Mopcompetition, cid=cid)
    class_id = _resolve_class_id(cid, class_id)
    cls = get_object_or_404(Mopclass, cid=cid, id=class_id)
    competitors = list(Mopcompetitor.objects.filter(cid=cid, cls=class_id))
    return competition, cls, competitors


def _get_adjacent_classes(cid, class_id):
    """Retourne (prev_cls, next_cls) dans l'ordre (ord, name) de la compétition."""
    all_classes = list(Mopclass.objects.filter(cid=cid).order_by('ord', 'name'))
    current_idx = next((i for i, c in enumerate(all_classes) if c.id == class_id), None)
    if current_idx is None:
        return None, None
    prev_cls = all_classes[current_idx - 1] if current_idx > 0 else None
    next_cls = all_classes[current_idx + 1] if current_idx < len(all_classes) - 1 else None
    return prev_cls, next_cls


def _sort_non_finishers(non_finishers):
    """Trie les non-classés par groupe de statut puis par ordre alphabétique.

    Ordre des groupes :
      1 – NC / Hors compét. / No Timing / H.T. / DSQ
      2 – PM (poinçons manquants)
      3 – Abandon (DNF)
      4 – Non-partants (DNS, NP, Cancel)
      5 – tout autre statut

    Args:
        non_finishers: liste de Mopcompetitor non classés.

    Returns:
        Nouvelle liste triée (l'originale n'est pas modifiée).
    """
    return sorted(
        non_finishers,
        key=lambda c: (_NON_FINISHER_ORDER.get(c.stat, 5), c.name.lower()),
    )


# ─── Pages statiques ──────────────────────────────────────────────────────────

_PREFIX_RE = re.compile(r'^\d+(\.\d+)*\.?\s+')


def _slugify_no_prefix(value, separator):
    return slugify_unicode(_PREFIX_RE.sub('', value), separator)


def MarkdownView(request, article_id):
    md = markdown.Markdown(
        extensions=["fenced_code", "toc", "tables"],
        extension_configs={"toc": {"slugify": _slugify_no_prefix}},
    )
    markdown_content = MeosTutorial.objects.get(pk=article_id)
    markdown_content.content = md.convert(markdown_content.text)
    return render(request, "results/markdown_content.html",
                  {'markdown_content': markdown_content})


def etiquettes(request):
    return render(request, "results/etiquettes.html")


def drivers(request):
    return render(request, "results/drivers.html")


def meos_checker_view(request):
    """Vérificateur de conformité réglementaire pour les fichiers .meosxml."""
    report      = None
    parse_error = None

    if request.method == 'POST' and 'meosfile' in request.FILES:
        try:
            xml_bytes = request.FILES['meosfile'].read()
            report = check_meos_file(xml_bytes)
        except ValueError as exc:
            parse_error = str(exc)

    return render(request, 'results/meos_checker.html', {
        'report':      report,
        'parse_error': parse_error,
    })


def verifie_moi_view(request):
    """Génère la liste de départ CSV pour l'application Android O Checklist."""
    parse_error      = None
    result           = None
    csv_content_json = None
    filename_json    = None

    if request.method == 'POST' and 'meosfile' in request.FILES:
        try:
            xml_bytes        = request.FILES['meosfile'].read()
            result           = generate_verifie_moi_csv(xml_bytes)
            csv_content_json = json.dumps(result.csv_content)
            safe_name = re.sub(r'[^\w\-\.\s]', '_', result.competition_name).strip() or 'verifie_moi'
            filename_json = json.dumps(safe_name + '.csv')
        except ValueError as exc:
            parse_error = str(exc)

    return render(request, 'results/verifie_moi.html', {
        'parse_error':      parse_error,
        'result':           result,
        'csv_content_json': csv_content_json,
        'filename_json':    filename_json,
    })


# ─── Accueil ──────────────────────────────────────────────────────────────────

def home(request):
    competitions = Mopcompetition.objects.all()
    return render(request, 'results/home.html', {'competitions': competitions})


# ─── Détail compétition ───────────────────────────────────────────────────────

def competition_detail(request, cid):
    competition = get_object_or_404(Mopcompetition, cid=cid)
    classes     = Mopclass.objects.filter(cid=cid).order_by('ord', 'name')

    relay_class_ids = set(
        Mopteam.objects.filter(cid=cid)
        .values_list('cls', flat=True)
        .distinct()
    )

    class_stats = []
    for cls in classes:
        is_relay = cls.id in relay_class_ids
        if is_relay:
            qs        = Mopteam.objects.filter(cid=cid, cls=cls.id)
            total     = qs.count()
            finishers = qs.filter(stat=STAT_OK).exclude(rt__lte=0).count()
        else:
            qs        = Mopcompetitor.objects.filter(cid=cid, cls=cls.id)
            total     = qs.count()
            finishers = qs.filter(stat=STAT_OK).exclude(rt__lte=0).count()
        class_stats.append({
            'cls':       cls,
            'total':     total,
            'finishers': finishers,
            'is_relay':  is_relay,
        })

    return render(request, 'results/competition_detail.html', {
        'competition': competition,
        'class_stats': class_stats,
    })


# ─── Classement individuel ────────────────────────────────────────────────────

def class_results(request, cid, class_id):
    resolved_class_id = _resolve_class_id(cid, class_id)
    if Mopteam.objects.filter(cid=cid, cls=resolved_class_id).exists():
        return redirect('results:relay_results', cid=cid, class_id=class_id)

    competition, cls, competitors = _load_class_context(cid, resolved_class_id)

    prev_cls, next_cls = _get_adjacent_classes(cid, cls.id)

    org_map = get_org_map(cid, as_objects=True)
    for c in competitors:
        c.org_obj = org_map.get(c.org)

    finishers, non_finishers, leader_time = rank_finishers(competitors)

    non_finishers_sorted = _sort_non_finishers(non_finishers)
    results = finishers + non_finishers_sorted

    controls_seq, _ = get_class_controls(cid, cls.id)
    radio_map       = get_radio_map(cid, [c.id for c in results])

    for c in results:
        c.splits = compute_splits(c.id, controls_seq, radio_map)

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
                sp['error_pct']  = round(e['error_pct'], 1) if e and e['error_pct']  is not None else None

    leg_error_data = []
    if controls_seq and finishers:
        for j, ctrl in enumerate(controls_seq):
            entry = {'ctrl_name': ctrl['ctrl_name'], 'errors': []}
            for c in finishers:
                errs = error_map.get(c.id, [])
                if j < len(errs) and errs[j]['error_time'] is not None:
                    entry['errors'].append({
                        'et': round(errs[j]['error_time']),
                        'ep': round(errs[j]['error_pct'], 1),
                    })
            leg_error_data.append(entry)

    return render(request, 'results/class_results.html', {
        'competition':         competition,
        'cls':                 cls,
        'results':             results,
        'leader_time':         format_time(leader_time) if leader_time else '-',
        'controls_seq':        controls_seq,
        'has_splits':          bool(controls_seq),
        'current_analysis':    'results',
        'leg_error_data_json': json.dumps(leg_error_data),
        'prev_cls':            prev_cls,
        'next_cls':            next_cls,
    })


# ─── Fiche concurrent ─────────────────────────────────────────────────────────

def competitor_detail(request, cid, competitor_id):
    competition = get_object_or_404(Mopcompetition, cid=cid)
    competitor  = get_object_or_404(Mopcompetitor, cid=cid, id=competitor_id)

    org = Moporganization.objects.filter(cid=cid, id=competitor.org).first()
    cls = Mopclass.objects.filter(cid=cid, id=competitor.cls).first()

    controls_seq, _ = get_class_controls(cid, competitor.cls)
    radio_map       = get_radio_map(cid, [competitor_id])
    splits          = compute_splits(competitor_id, controls_seq, radio_map)

    return render(request, 'results/competitor_detail.html', {
        'competition': competition,
        'competitor':  competitor,
        'org':         org,
        'cls':         cls,
        'splits':      splits,
        'total_time':  (
            format_time(competitor.rt) if competitor.is_ok
            else competitor.status_label
        ),
    })


# ─── Résultats par organisation ───────────────────────────────────────────────

def org_results(request, cid, org_id):
    competition  = get_object_or_404(Mopcompetition, cid=cid)
    organization = get_object_or_404(Moporganization, cid=cid, id=org_id)

    # Récupérer les coureurs du club
    org_competitors = list(Mopcompetitor.objects.filter(cid=cid, org=org_id))

    # Associer l'objet catégorie à chaque coureur
    class_map = {c.id: c for c in Mopclass.objects.filter(cid=cid)}
    for c in org_competitors:
        c.class_obj = class_map.get(c.cls)

    # Calculer le classement de chaque coureur dans SA catégorie (tous compétiteurs,
    # pas seulement ceux du club)
    class_ids = {c.cls for c in org_competitors}
    class_rank_maps = {}   # {cls_id: {competitor_id: rank}}
    for cls_id in class_ids:
        all_in_class = list(Mopcompetitor.objects.filter(cid=cid, cls=cls_id))
        finishers_in_class, _, _ = rank_finishers(all_in_class)
        # rank_finishers assigne .rank sur chaque objet finisher
        class_rank_maps[cls_id] = {c.id: c.rank for c in finishers_in_class}

    for c in org_competitors:
        c.cat_rank = class_rank_maps.get(c.cls, {}).get(c.id)  # None si non classé

    # ── Classés : triés par rang, puis pour les ex-æquo par ord/nom de catégorie ──
    finishers = sorted(
        [c for c in org_competitors if c.is_ok],
        key=lambda c: (
            c.cat_rank if c.cat_rank is not None else 9999,
            c.class_obj.ord  if c.class_obj else 9999,
            c.class_obj.name if c.class_obj else '',
        ),
    )

    # ── Non-classés : NC → PM → Abandon → Non-partants, puis alpha ──
    non_finishers = _sort_non_finishers([c for c in org_competitors if not c.is_ok])

    return render(request, 'results/org_results.html', {
        'competition':  competition,
        'organization': organization,
        'competitors':  finishers + non_finishers,
    })


# ─── Statistiques ─────────────────────────────────────────────────────────────

def statistics(request, cid):
    competition = get_object_or_404(Mopcompetition, cid=cid)
    total    = Mopcompetitor.objects.filter(cid=cid).count()
    finished = Mopcompetitor.objects.filter(cid=cid, stat=STAT_OK).exclude(rt__lte=0).count()

    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT o.name, COUNT(c.id) AS cnt
            FROM mopCompetitor c
            JOIN mopOrganization o ON o.cid = c.cid AND o.id = c.org
            WHERE c.cid = %s AND c.stat = %s AND c.rt > 0
            GROUP BY o.id, o.name
            ORDER BY cnt DESC
            LIMIT 10
        """, [cid, STAT_OK])
        top_orgs = cursor.fetchall()

    return render(request, 'results/statistics.html', {
        'competition': competition,
        'total':       total,
        'finished':    finished,
        'top_orgs':    top_orgs,
    })


# ─── API JSON ─────────────────────────────────────────────────────────────────

def api_class_results(request, cid, class_id):
    class_id = _resolve_class_id(cid, class_id)
    competitors     = list(Mopcompetitor.objects.filter(cid=cid, cls=class_id))
    org_map         = get_org_map(cid)
    finishers, _, _ = rank_finishers(competitors)
    leader          = finishers[0].rt if finishers else None

    data = [
        {
            'rank':   i + 1,
            'name':   c.name,
            'org':    org_map.get(c.org, ''),
            'time':   format_time(c.rt),
            'behind': f'+{format_time(c.rt - leader)}' if i > 0 else '',
        }
        for i, c in enumerate(finishers)
    ]
    return JsonResponse({'results': data})


# ─── Superman ─────────────────────────────────────────────────────────────────

def superman_analysis(request, cid, class_id):
    competition, cls, competitors = _load_class_context(cid, class_id)
    finishers, _, _ = rank_finishers(competitors)

    if not finishers:
        return render(request, 'results/superman.html', {
            'competition': competition, 'cls': cls,
            'no_data': True, 'current_analysis': 'superman',
        })

    org_map         = get_org_map(cid)
    controls_seq, _ = get_class_controls(cid, cls.id)
    controls_labels = [c['ctrl_name'] for c in controls_seq]
    radio_map       = get_radio_map(cid, [c.id for c in finishers])

    leg_matrix = build_leg_matrix(finishers, controls_seq, radio_map)
    n_legs     = len(controls_seq) + 1

    superman_legs, superman_leg_names = [], []
    for j in range(n_legs):
        best = None
        for i, legs in enumerate(leg_matrix):
            v = legs[j] if j < len(legs) else None
            if v is not None and v > 0 and (best is None or v < best):
                best = v
        best_names = [
            finishers[i].name
            for i, legs in enumerate(leg_matrix)
            if j < len(legs) and legs[j] == best
        ] if best is not None else ['-']
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
        points = [0]
        labels = ['+0:00']
        valid  = True

        for j, ctrl in enumerate(controls_seq):
            abs_t = radios.get(ctrl['ctrl_id'], -1)
            if abs_t <= 0:
                valid = False
                break
            loss = int(abs_t - superman_cum[j])
            points.append(loss)
            labels.append(('+' if loss >= 0 else '') + format_time(loss))

        if valid:
            final_loss = int(c.rt - superman_total)
            points.append(final_loss)
            labels.append(('+' if final_loss >= 0 else '') + format_time(final_loss))
        else:
            while len(points) < len(x_labels):
                points.append(None)
                labels.append(None)

        series.append({
            'id': c.id, 'name': c.name, 'org': org_map.get(c.org, ''),
            'rank': i + 1, 'total': format_time(c.rt),
            'loss': format_time(c.rt - superman_total) if superman_total else '-',
            'points': points, 'labels': labels,
        })

    leg_labels        = controls_labels + ['Arrivée']
    superman_leg_data = [
        {
            'ctrl':  leg_labels[j],
            'time':  format_time(superman_legs[j]) if superman_legs[j] else '-',
            'names': superman_leg_names[j],
        }
        for j in range(n_legs)
    ]

    return render(request, 'results/superman.html', {
        'competition': competition, 'cls': cls,
        'series': series, 'series_json': json.dumps(series),
        'x_labels_json': json.dumps(x_labels),
        'superman_total': format_time(superman_total),
        'current_analysis': 'superman',
        'superman_leg_data': superman_leg_data,
        'controls_labels': controls_labels,
        'no_data': False, 'n_finishers': len(finishers),
    })


# ─── Indice de performance ────────────────────────────────────────────────────

def performance_analysis(request, cid, class_id):
    competition, cls, competitors = _load_class_context(cid, class_id)
    finishers, _, _ = rank_finishers(competitors)

    if not finishers:
        return render(request, 'results/performance.html', {
            'competition': competition, 'cls': cls,
            'no_data': True, 'current_analysis': 'performance',
        })

    org_map         = get_org_map(cid)
    controls_seq, _ = get_class_controls(cid, cls.id)
    controls_labels = [c['ctrl_name'] for c in controls_seq]
    radio_map       = get_radio_map(cid, [c.id for c in finishers])

    leg_matrix = build_leg_matrix(finishers, controls_seq, radio_map)
    n_legs     = len(controls_seq) + 1
    leg_labels = controls_labels + ['Arrivée']
    leg_refs   = compute_leg_refs(leg_matrix, n_legs, top_fraction=0.25)

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
        {'label': leg_labels[j], 'ref': format_time(leg_refs[j]) if leg_refs[j] else '-'}
        for j in range(n_legs)
    ]

    return render(request, 'results/performance.html', {
        'competition': competition, 'cls': cls,
        'series_json': json.dumps(series), 'leg_info_json': json.dumps(leg_info),
        'n_legs': n_legs, 'n_finishers': len(finishers),
        'no_data': False, 'current_analysis': 'performance',
    })


# ─── Régularité ───────────────────────────────────────────────────────────────

def regularity_analysis(request, cid, class_id):
    competition, cls, competitors = _load_class_context(cid, class_id)
    finishers, _, _ = rank_finishers(competitors)

    if len(finishers) < 2:
        return render(request, 'results/regularity.html', {
            'competition': competition, 'cls': cls,
            'no_data': True, 'current_analysis': 'regularity',
        })

    org_map         = get_org_map(cid)
    controls_seq, _ = get_class_controls(cid, cls.id)
    controls_labels = [c['ctrl_name'] for c in controls_seq]
    radio_map       = get_radio_map(cid, [c.id for c in finishers])

    reg_data   = compute_regularity_analysis(finishers, controls_seq, radio_map)
    leg_labels = controls_labels + ['Arrivée']

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
        {
            'label':   leg_labels[j],
            'ref':     format_time(round(reg_data['leg_refs'][j])) if reg_data['leg_refs'][j] else '-',
            'leg_std': round(reg_data['leg_stds'][j], 4) if reg_data['leg_stds'][j] is not None else None,
        }
        for j in range(reg_data['n_legs'])
    ]

    cat_reg = reg_data['category_regularity']
    return render(request, 'results/regularity.html', {
        'competition': competition, 'cls': cls,
        'series_json': json.dumps(series), 'leg_info_json': json.dumps(leg_info),
        'category_regularity': round(cat_reg, 4) if cat_reg is not None else None,
        'n_legs': reg_data['n_legs'], 'n_finishers': len(finishers),
        'no_data': False, 'current_analysis': 'regularity',
    })


# ─── Regroupement ─────────────────────────────────────────────────────────────

def grouping_analysis(request, cid, class_id):
    competition, cls, competitors = _load_class_context(cid, class_id)

    runners_with_start = sorted(
        [c for c in competitors if c.st > 0], key=lambda c: c.st
    )

    if not runners_with_start:
        return render(request, 'results/grouping.html', {
            'competition': competition, 'cls': cls,
            'no_data': True, 'current_analysis': 'grouping',
        })

    org_map         = get_org_map(cid)
    controls_seq, _ = get_class_controls(cid, cls.id)
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
        'competition': competition, 'cls': cls,
        'series_json': json.dumps(series), 'x_labels_json': json.dumps(x_labels),
        'n_runners': len(series), 'n_controls': len(controls_seq),
        'no_data': False, 'current_analysis': 'grouping',
    })


# ─── Indice lièvre / suiveur ──────────────────────────────────────────────────

def grouping_index_analysis(request, cid, class_id):
    competition, cls, competitors = _load_class_context(cid, class_id)

    runners = sorted([c for c in competitors if c.st > 0], key=lambda c: c.st)

    if not runners:
        return render(request, 'results/grouping_index.html', {
            'competition': competition, 'cls': cls,
            'no_data': True, 'current_analysis': 'grouping_index',
        })

    try:
        t1 = max(1,      min(int(request.GET.get('t1', 7)),  30))
        t2 = max(t1 + 1, min(int(request.GET.get('t2', 20)), 60))
    except (ValueError, TypeError):
        t1, t2 = 7, 20

    org_map         = get_org_map(cid)
    controls_seq, _ = get_class_controls(cid, cls.id)
    radio_map       = get_radio_map(cid, [c.id for c in runners])

    finishers, _, _ = rank_finishers(competitors)
    rank_map = {c.id: c.rank for c in finishers}
    for c in runners:
        c.rank = rank_map.get(c.id)

    raw = compute_grouping_index(runners, controls_seq, radio_map, t1, t2)

    runner_map      = {c.id: c for c in runners}
    id_to_name      = {c.id: c.name for c in runners}
    for r in raw:
        c = runner_map.get(r['id'])
        if c:
            r['name'] = c.name
            r['rank'] = getattr(c, 'rank', None)
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
        'competition': competition, 'cls': cls,
        'results_json': json.dumps(raw), 'leg_labels_json': json.dumps(leg_labels),
        'n_runners': len(raw), 'n_legs': len(leg_labels),
        't1': t1, 't2': t2, 'no_data': False, 'current_analysis': 'grouping_index',
    })


# ─── Duel ─────────────────────────────────────────────────────────────────────

def duel_analysis(request, cid, class_id):
    resolved_class_id = _resolve_class_id(cid, class_id)
    if Mopteam.objects.filter(cid=cid, cls=resolved_class_id).exists():
        return redirect('results:relay_results', cid=cid, class_id=class_id)

    competition, cls, competitors = _load_class_context(cid, resolved_class_id)
    finishers, non_finishers, _   = rank_finishers(competitors)
    all_results = finishers + non_finishers

    if not all_results:
        return render(request, 'results/duel.html', {
            'competition': competition, 'cls': cls,
            'no_data': True, 'current_analysis': 'duel',
        })

    org_map         = get_org_map(cid)
    controls_seq, _ = get_class_controls(cid, cls.id)
    radio_map       = get_radio_map(cid, [c.id for c in all_results])

    runners_data = []
    for c in all_results:
        splits = compute_splits(c.id, controls_seq, radio_map)
        runners_data.append({
            'id': c.id, 'name': c.name, 'org': org_map.get(c.org, ''),
            'rank': getattr(c, 'rank', None),
            'rt_raw': c.rt if c.is_ok else None,
            'rt_fmt': format_time(c.rt) if c.is_ok else '—',
            'splits': [
                {
                    'ctrl_name': sp['ctrl_name'],
                    'leg_raw': sp['leg_raw'], 'leg_fmt': sp['leg_time'],
                    'abs_raw': sp['abs_raw'], 'abs_fmt': sp['abs_time'],
                }
                for sp in splits
            ],
        })

    return render(request, 'results/duel.html', {
        'competition': competition, 'cls': cls,
        'no_data': False, 'current_analysis': 'duel',
        'runners_json': json.dumps(runners_data), 'n_runners': len(runners_data),
    })


# ─── Relais ───────────────────────────────────────────────────────────────────

def relay_results(request, cid, class_id):
    competition = get_object_or_404(Mopcompetition, cid=cid)
    class_id = _resolve_class_id(cid, class_id)
    cls         = get_object_or_404(Mopclass, cid=cid, id=class_id)

    teams_qs = list(Mopteam.objects.filter(cid=cid, cls=class_id))
    org_map  = get_org_map(cid)

    finishers, non_finishers, leader_time = rank_finishers(
        teams_qs, ok_predicate=lambda t: t.stat == STAT_OK and t.rt > 0,
    )
    all_teams = finishers + non_finishers

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
            leg_members = sorted(
                [m for m in members if m.leg == leg_num], key=lambda m: m.ord
            )
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
