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
)
from .services import (
    get_org_map, get_class_controls, get_controls_by_leg,
    get_radio_map, compute_splits, mark_best_splits, rank_splits,
    rank_finishers, build_rank_map,
    build_leg_matrix, compute_leg_refs,
    build_abs_time_series, compute_error_estimates,
    compute_grouping_index, compute_regularity_analysis,
)


# ─── Helpers internes ─────────────────────────────────────────────────────────

def _load_class_context(cid, class_id):
    """Charge compétition, catégorie et liste des concurrents.

    Facteur commun aux vues d'analyse (superman, performance, regroupement, duel).
    Lève Http404 si la compétition ou la catégorie est introuvable.

    Returns:
        (competition, cls, competitors)
    """
    competition = get_object_or_404(Mopcompetition, cid=cid)
    cls         = get_object_or_404(Mopclass, cid=cid, id=class_id)
    competitors = list(Mopcompetitor.objects.filter(cid=cid, cls=class_id))
    return competition, cls, competitors


# ─── Pages statiques / utilitaires ────────────────────────────────────────────

_PREFIX_RE = re.compile(r'^\d+(\.\d+)*\.?\s+')


def _slugify_no_prefix(value, separator):
    """Slugifie un titre Markdown en retirant d'abord son préfixe numérique.

    Exemples :
        "1 En amont"               → "en-amont"
        "1.1 Créer la compétition" → "créer-la-compétition"
        "5. Statuts des coureurs"  → "statuts-des-coureurs"
    Cela garantit que les ancres générées correspondent aux liens de la table
    des matières qui ne répètent pas les numéros.
    """
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


# ─── Accueil ───────────────────────────────────────────────────────────────────

def home(request):
    competitions = Mopcompetition.objects.all()
    return render(request, 'results/home.html', {'competitions': competitions})


# ─── Détail compétition — liste des catégories ─────────────────────────────────

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


# ─── Classement individuel ─────────────────────────────────────────────────────

def class_results(request, cid, class_id):
    if Mopteam.objects.filter(cid=cid, cls=class_id).exists():
        return redirect('results:relay_results', cid=cid, class_id=class_id)

    competition, cls, competitors = _load_class_context(cid, class_id)

    org_map = get_org_map(cid, as_objects=True)
    for c in competitors:
        c.org_obj = org_map.get(c.org)

    finishers, non_finishers, leader_time = rank_finishers(competitors)
    results = finishers + non_finishers

    controls_seq, _ = get_class_controls(cid, class_id)
    radio_map       = get_radio_map(cid, [c.id for c in results])

    for c in results:
        c.splits = compute_splits(c.id, controls_seq, radio_map)

    mark_best_splits(finishers, results)
    rank_splits(finishers, results)

    # ── Estimation des erreurs ────────────────────────────────────────────────
    error_map = {}
    if controls_seq and finishers:
        error_map = compute_error_estimates(finishers, controls_seq, radio_map)
        for c in results:
            errs = error_map.get(c.id, [])
            for idx, sp in enumerate(c.splits):
                e = errs[idx] if idx < len(errs) else None
                sp['error_time'] = round(e['error_time']) if e and e['error_time'] is not None else None
                sp['error_pct']  = round(e['error_pct'], 1) if e and e['error_pct']  is not None else None

    # ── Statistiques d'erreur par tronçon (pour le graphique) ─────────────────
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
    })


# ─── Fiche concurrent ──────────────────────────────────────────────────────────

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


# ─── Résultats par organisation ────────────────────────────────────────────────

def org_results(request, cid, org_id):
    competition  = get_object_or_404(Mopcompetition, cid=cid)
    organization = get_object_or_404(Moporganization, cid=cid, id=org_id)

    competitors = Mopcompetitor.objects.filter(cid=cid, org=org_id).order_by('cls', 'rt')
    class_map   = {c.id: c for c in Mopclass.objects.filter(cid=cid)}
    for c in competitors:
        c.class_obj = class_map.get(c.cls)

    return render(request, 'results/org_results.html', {
        'competition':  competition,
        'organization': organization,
        'competitors':  competitors,
    })


# ─── Statistiques ──────────────────────────────────────────────────────────────

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


# ─── API JSON (refresh live) ───────────────────────────────────────────────────

def api_class_results(request, cid, class_id):
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


# ─── Analyse Superman ──────────────────────────────────────────────────────────

def superman_analysis(request, cid, class_id):
    competition, cls, competitors = _load_class_context(cid, class_id)
    finishers, _, _ = rank_finishers(competitors)

    if not finishers:
        return render(request, 'results/superman.html', {
            'competition':      competition,
            'cls':              cls,
            'no_data':          True,
            'current_analysis': 'superman',
        })

    org_map         = get_org_map(cid)
    controls_seq, _ = get_class_controls(cid, class_id)
    controls_labels = [c['ctrl_name'] for c in controls_seq]
    radio_map       = get_radio_map(cid, [c.id for c in finishers])

    # ── Matrice des tronçons ──────────────────────────────────────────────────
    leg_matrix = build_leg_matrix(finishers, controls_seq, radio_map)
    n_legs     = len(controls_seq) + 1

    # ── Meilleur tronçon + auteurs (ex-æquo inclus) ──────────────────────────
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

    # ── Temps cumulé Superman ─────────────────────────────────────────────────
    superman_cum, acc = [], 0
    for v in superman_legs:
        acc += v if v is not None else 0
        superman_cum.append(acc)

    # ── Séries de retards pour le graphique ──────────────────────────────────
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
            'id':     c.id,
            'name':   c.name,
            'org':    org_map.get(c.org, ''),
            'rank':   i + 1,
            'total':  format_time(c.rt),
            'loss':   format_time(c.rt - superman_total) if superman_total else '-',
            'points': points,
            'labels': labels,
        })

    # ── Données des tronçons pour le template ────────────────────────────────
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
        'competition':       competition,
        'cls':               cls,
        'series':            series,
        'series_json':       json.dumps(series),
        'x_labels_json':     json.dumps(x_labels),
        'superman_total':    format_time(superman_total),
        'current_analysis':  'superman',
        'superman_leg_data': superman_leg_data,
        'controls_labels':   controls_labels,
        'no_data':           False,
        'n_finishers':       len(finishers),
    })


# ─── Indice de performance ────────────────────────────────────────────────────

def performance_analysis(request, cid, class_id):
    """Analyse de l'indice de performance (KDE par coureur).

    Indice de performance d'un coureur sur un tronçon =
        moyenne des 25% meilleurs temps sur ce tronçon / temps du coureur

    Un indice proche de 1.0 = tronçon réalisé au niveau des meilleurs.
    Chaque tronçon est pondéré par son temps de référence (proxy de longueur).
    La courbe de densité (KDE) est calculée côté JS pour permettre
    l'ajustement interactif du lissage (sigma).
    """
    competition, cls, competitors = _load_class_context(cid, class_id)
    finishers, _, _ = rank_finishers(competitors)

    if not finishers:
        return render(request, 'results/performance.html', {
            'competition':      competition,
            'cls':              cls,
            'no_data':          True,
            'current_analysis': 'performance',
        })

    org_map                  = get_org_map(cid)
    controls_seq, _          = get_class_controls(cid, class_id)
    controls_labels          = [c['ctrl_name'] for c in controls_seq]
    radio_map                = get_radio_map(cid, [c.id for c in finishers])

    leg_matrix = build_leg_matrix(finishers, controls_seq, radio_map)
    n_legs     = len(controls_seq) + 1
    leg_labels = controls_labels + ['Arrivée']

    # ── Temps de référence : moyenne du top 25% par tronçon ───────────────────
    leg_refs = compute_leg_refs(leg_matrix, n_legs, top_fraction=0.25)

    # ── Indice de performance par coureur et par tronçon ──────────────────────
    # pi_ij = ref_j / runner_time_ij   (1.0 = parfait, <1 = moins bon)
    series = []
    for i, c in enumerate(finishers):
        indices, weights = [], []
        for j in range(n_legs):
            t   = leg_matrix[i][j]
            ref = leg_refs[j]
            if t and t > 0 and ref and ref > 0:
                indices.append(round(ref / t, 5))
                weights.append(round(ref))      # poids = ref = proxy longueur
            else:
                indices.append(None)
                weights.append(None)

        # Statistiques pondérées
        valid = [(pi, w) for pi, w in zip(indices, weights) if pi is not None]
        if valid:
            total_w  = sum(w for _, w in valid)
            mean_pi  = sum(pi * w for pi, w in valid) / total_w
            variance = sum(w * (pi - mean_pi) ** 2 for pi, w in valid) / total_w
            std_pi   = variance ** 0.5
        else:
            mean_pi = std_pi = None

        series.append({
            'id':      c.id,
            'name':    c.name,
            'org':     org_map.get(c.org, ''),
            'rank':    i + 1,
            'time':    format_time(c.rt),
            'indices': indices,           # liste PI par tronçon
            'weights': weights,           # poids (ref_j) par tronçon
            'mean_pi': round(mean_pi, 4) if mean_pi is not None else None,
            'std_pi':  round(std_pi, 4)  if std_pi  is not None else None,
        })

    # Résumé des tronçons pour l'affichage
    leg_info = [
        {
            'label': leg_labels[j],
            'ref':   format_time(leg_refs[j]) if leg_refs[j] else '-',
        }
        for j in range(n_legs)
    ]

    return render(request, 'results/performance.html', {
        'competition':      competition,
        'cls':              cls,
        'series_json':      json.dumps(series),
        'leg_info_json':    json.dumps(leg_info),
        'n_legs':           n_legs,
        'n_finishers':      len(finishers),
        'no_data':          False,
        'current_analysis': 'performance',
    })


# ─── Régularité ───────────────────────────────────────────────────────────────

def regularity_analysis(request, cid, class_id):
    """Analyse de régularité : σ pondéré des indices de performance.

    Trois niveaux de régularité (σ — valeur plus faible = meilleure régularité) :
      · Coureur   : σ pondéré de ses IP sur tous les tronçons (pondéré par longueur).
      · Tronçon   : σ des IP de tous les coureurs sur ce tronçon.
      · Catégorie : moyenne des σ pondérés de tous les coureurs.

    Nécessite au moins 2 coureurs classés pour que les σ par tronçon soient calculables.
    """
    competition, cls, competitors = _load_class_context(cid, class_id)
    finishers, _, _ = rank_finishers(competitors)

    if len(finishers) < 2:
        return render(request, 'results/regularity.html', {
            'competition':      competition,
            'cls':              cls,
            'no_data':          True,
            'current_analysis': 'regularity',
        })

    org_map                  = get_org_map(cid)
    controls_seq, _          = get_class_controls(cid, class_id)
    controls_labels          = [c['ctrl_name'] for c in controls_seq]
    radio_map                = get_radio_map(cid, [c.id for c in finishers])

    reg_data   = compute_regularity_analysis(finishers, controls_seq, radio_map)
    leg_labels = controls_labels + ['Arrivée']

    # ── Séries JSON (ordre classement course) ─────────────────────────────────
    series = []
    for i, c in enumerate(finishers):
        reg = reg_data['runner_regularity'][i]
        series.append({
            'id':           c.id,
            'name':         c.name,
            'org':          org_map.get(c.org, ''),
            'rank':         i + 1,
            'time':         format_time(c.rt),
            'weighted_std': round(reg['weighted_std'], 4) if reg['weighted_std'] is not None else None,
            'mean_pi':      round(reg['mean_pi'], 4)      if reg['mean_pi']      is not None else None,
            'leg_pis':      [round(pi, 4) if pi is not None else None for pi in reg['leg_pis']],
            'leg_weights':  [round(w) if w is not None else None for w in reg['leg_weights']],
        })

    # ── Infos par tronçon ─────────────────────────────────────────────────────
    leg_info = [
        {
            'label':   leg_labels[j],
            'ref':     format_time(round(reg_data['leg_refs'][j]))
                       if reg_data['leg_refs'][j] else '-',
            'leg_std': round(reg_data['leg_stds'][j], 4)
                       if reg_data['leg_stds'][j] is not None else None,
        }
        for j in range(reg_data['n_legs'])
    ]

    cat_reg = reg_data['category_regularity']

    return render(request, 'results/regularity.html', {
        'competition':         competition,
        'cls':                 cls,
        'series_json':         json.dumps(series),
        'leg_info_json':       json.dumps(leg_info),
        'category_regularity': round(cat_reg, 4) if cat_reg is not None else None,
        'n_legs':              reg_data['n_legs'],
        'n_finishers':         len(finishers),
        'no_data':             False,
        'current_analysis':    'regularity',
    })


# ─── Regroupement des coureurs ────────────────────────────────────────────────

def grouping_analysis(request, cid, class_id):
    """Analyse de regroupement : temps de passage absolus à chaque poste.

    L'axe Y est le temps absolu (heure réelle), l'axe X les postes de contrôle.
    Des lignes proches → coureurs ensemble.
    Une ligne horizontale → coureur rapide sur ce tronçon.
    """
    competition, cls, competitors = _load_class_context(cid, class_id)

    # Inclure tous les coureurs ayant une heure de départ (pas seulement les classés)
    # pour voir les regroupements même en cas de DNF/MP
    runners_with_start = [c for c in competitors if c.st > 0]
    runners_with_start.sort(key=lambda c: c.st)

    if not runners_with_start:
        return render(request, 'results/grouping.html', {
            'competition':      competition,
            'cls':              cls,
            'no_data':          True,
            'current_analysis': 'grouping',
        })

    org_map                  = get_org_map(cid)
    controls_seq, _          = get_class_controls(cid, class_id)
    controls_labels          = [c['ctrl_name'] for c in controls_seq]
    radio_map                = get_radio_map(cid, [c.id for c in runners_with_start])

    series = build_abs_time_series(runners_with_start, controls_seq, radio_map)

    # Calculer le vrai classement (par temps de course) et l'injecter dans chaque série
    finishers_rank, _, _ = rank_finishers(competitors)
    result_rank = {c.id: c.rank for c in finishers_rank}

    # Enrichir avec le nom du club et le classement final
    for s in series:
        runner = next((c for c in runners_with_start if c.id == s['id']), None)
        s['org']  = org_map.get(runner.org, '') if runner else ''
        s['stat'] = runner.stat if runner else 0
        s['rank'] = result_rank.get(s['id'])  # None si DNF/DNS

    x_labels = ['Départ'] + controls_labels + ['Arrivée']

    # Formatter les points pour Chart.js (None → null JSON, valeurs en dixièmes)
    for s in series:
        s['time_fmt'] = format_time(s['time']) if s['time'] > 0 else '—'

    return render(request, 'results/grouping.html', {
        'competition':      competition,
        'cls':              cls,
        'series_json':      json.dumps(series),
        'x_labels_json':    json.dumps(x_labels),
        'n_runners':        len(series),
        'n_controls':       len(controls_seq),
        'no_data':          False,
        'current_analysis': 'grouping',
    })


# ─── Indice de regroupement (lièvre / suiveur) ───────────────────────────────

def grouping_index_analysis(request, cid, class_id):
    """Analyse lièvre / suiveur : indice de regroupement par coureur et par tronçon.

    L'indice est calculé à partir des heures absolues de passage aux postes.
    Une interpolation linéaire entre chaque paire de postes consécutifs permet
    d'intégrer en continu la fonction lièvre sur chaque tronçon.

    · Indice négatif (vert)  → coureur en tête de groupe (lièvre)
    · Indice positif (rouge) → coureur qui en suit un autre (suiveur)

    T1 et T2 (seuils en secondes) sont ajustables via les paramètres GET `t1`
    et `t2` (défauts : 7 s et 20 s).
    """
    competition, cls, competitors = _load_class_context(cid, class_id)

    runners = [c for c in competitors if c.st > 0]
    runners.sort(key=lambda c: c.st)

    if not runners:
        return render(request, 'results/grouping_index.html', {
            'competition':      competition,
            'cls':              cls,
            'no_data':          True,
            'current_analysis': 'grouping_index',
        })

    # ── Paramètres de seuil (GET, avec garde-fous) ────────────────────────────
    try:
        t1 = max(1,       min(int(request.GET.get('t1', 7)),  30))
        t2 = max(t1 + 1,  min(int(request.GET.get('t2', 20)), 60))
    except (ValueError, TypeError):
        t1, t2 = 7, 20

    # ── Données de base ───────────────────────────────────────────────────────
    org_map         = get_org_map(cid)
    controls_seq, _ = get_class_controls(cid, class_id)
    radio_map       = get_radio_map(cid, [c.id for c in runners])

    # Classement final (pour affichage dans le tableau)
    finishers, _, _ = rank_finishers(competitors)
    rank_map        = {c.id: c.rank for c in finishers}
    for c in runners:
        c.rank = rank_map.get(c.id)

    # ── Calcul des indices ────────────────────────────────────────────────────
    raw = compute_grouping_index(runners, controls_seq, radio_map, t1, t2)

    # Enrichissement (nom, rang, club)
    runner_map = {c.id: c for c in runners}
    id_to_firstname = {
        c.id: c.name if c.name else ''
        for c in runners
    }
    for r in raw:
        c = runner_map.get(r['id'])
        if c:
            r['name'] = c.name
            r['rank'] = getattr(c, 'rank', None)
            r['org']  = org_map.get(c.org, '')
        # Résolution des partenaires dominants en prénoms
        r['leg_ref_names'] = [
            id_to_firstname.get(rid) if rid is not None else None
            for rid in r.get('leg_ref_ids', [])
        ]

    # Tri : classés par rang, puis non-classés par nom
    raw.sort(key=lambda r: (r['rank'] is None, r['rank'] or 0, r.get('name', '')))

    # Arrondi des indices et nettoyage pour alléger le JSON
    for r in raw:
        r['leg_indices']  = [round(v, 3) if v is not None else None
                             for v in r['leg_indices']]
        r['global_index'] = round(r['global_index'], 3) \
                            if r['global_index'] is not None else None
        del r['leg_ref_ids']   # remplacé par leg_ref_names côté client

    # ── Labels des tronçons ───────────────────────────────────────────────────
    ctrl_names = [c['ctrl_name'] for c in controls_seq]
    all_names  = ['Dép.'] + ctrl_names + ['Arr.']
    leg_labels = [f"{all_names[j]}→{all_names[j + 1]}"
                  for j in range(len(all_names) - 1)]

    return render(request, 'results/grouping_index.html', {
        'competition':     competition,
        'cls':             cls,
        'results_json':    json.dumps(raw),
        'leg_labels_json': json.dumps(leg_labels),
        'n_runners':       len(raw),
        'n_legs':          len(leg_labels),
        't1':              t1,
        't2':              t2,
        'no_data':         False,
        'current_analysis': 'grouping_index',
    })


# ─── Duel de coureurs ────────────────────────────────────────────────────────

def duel_analysis(request, cid, class_id):
    """Compare tronçon par tronçon deux coureurs choisis interactivement.

    Toutes les données (splits de tous les coureurs) sont sérialisées en JSON
    et envoyées au template ; la sélection et l'affichage sont 100 % client-side.
    """
    if Mopteam.objects.filter(cid=cid, cls=class_id).exists():
        return redirect('results:relay_results', cid=cid, class_id=class_id)

    competition, cls, competitors = _load_class_context(cid, class_id)

    finishers, non_finishers, _ = rank_finishers(competitors)
    all_results = finishers + non_finishers

    if not all_results:
        return render(request, 'results/duel.html', {
            'competition':      competition,
            'cls':              cls,
            'no_data':          True,
            'current_analysis': 'duel',
        })

    org_map         = get_org_map(cid)
    controls_seq, _ = get_class_controls(cid, class_id)
    radio_map       = get_radio_map(cid, [c.id for c in all_results])

    runners_data = []
    for c in all_results:
        splits = compute_splits(c.id, controls_seq, radio_map)
        runners_data.append({
            'id':     c.id,
            'name':   c.name,
            'org':    org_map.get(c.org, ''),
            'rank':   getattr(c, 'rank', None),
            'rt_raw': c.rt if c.is_ok else None,
            'rt_fmt': format_time(c.rt) if c.is_ok else '—',
            'splits': [
                {
                    'ctrl_name': sp['ctrl_name'],
                    'leg_raw':   sp['leg_raw'],
                    'leg_fmt':   sp['leg_time'],
                    'abs_raw':   sp['abs_raw'],
                    'abs_fmt':   sp['abs_time'],
                }
                for sp in splits
            ],
        })

    return render(request, 'results/duel.html', {
        'competition':      competition,
        'cls':              cls,
        'no_data':          False,
        'current_analysis': 'duel',
        'runners_json':     json.dumps(runners_data),
        'n_runners':        len(runners_data),
    })


# ─── Résultats de relais ────────────────────────────────────────────────────────

def relay_results(request, cid, class_id):
    competition = get_object_or_404(Mopcompetition, cid=cid)
    cls         = get_object_or_404(Mopclass, cid=cid, id=class_id)

    teams_qs  = list(Mopteam.objects.filter(cid=cid, cls=class_id))
    org_map   = get_org_map(cid)

    finishers, non_finishers, leader_time = rank_finishers(
        teams_qs,
        ok_predicate=lambda t: t.stat == STAT_OK and t.rt > 0,
    )
    all_teams = finishers + non_finishers

    team_ids    = [t.id for t in all_teams]
    all_members = list(
        Mopteammember.objects.filter(cid=cid, id__in=team_ids)
        .order_by('id', 'leg', 'ord')
    )
    members_by_team = {}
    for m in all_members:
        members_by_team.setdefault(m.id, []).append(m)

    runner_ids  = [m.rid for m in all_members]
    competitors = {c.id: c for c in Mopcompetitor.objects.filter(cid=cid, id__in=runner_ids)}
    n_legs      = max((m.leg for m in all_members), default=0)

    controls_by_leg, control_name_map = get_controls_by_leg(cid, class_id)
    radio_map = get_radio_map(cid, runner_ids)

    # ── Passe 1 : construction des fractions avec temps bruts ────────────────
    teams_data = []
    for t in all_teams:
        members   = members_by_team.get(t.id, [])
        legs_data = []
        cum_time  = 0

        for leg_num in range(1, n_legs + 1):
            leg_members = sorted(
                [m for m in members if m.leg == leg_num],
                key=lambda m: m.ord,
            )
            runner = competitors.get(leg_members[0].rid) if leg_members else None

            if runner:
                leg_time_raw  = runner.rt if runner.rt > 0 else None
                cum_time     += leg_time_raw or 0
                cum_time_raw  = cum_time if leg_time_raw else None
                ctrl_seq      = [
                    {'ctrl_id': cid_val,
                     'ctrl_name': control_name_map.get(cid_val, str(cid_val))}
                    for cid_val in controls_by_leg.get(leg_num, [])
                ]
                splits = compute_splits(runner.id, ctrl_seq, radio_map)

                legs_data.append({
                    'leg':          leg_num,
                    'runner_id':    runner.id,
                    'name':         runner.name,
                    'leg_time':     format_time(leg_time_raw) if leg_time_raw else '-',
                    'leg_time_raw': leg_time_raw,
                    'cum_time':     format_time(cum_time_raw) if cum_time_raw else '-',
                    'cum_time_raw': cum_time_raw,
                    'stat':         runner.stat,
                    'stat_label':   runner.status_label,
                    'stat_badge':   runner.status_badge,
                    'splits':       splits,
                    'leg_rank':     None,
                    'cum_rank':     None,
                })
            else:
                legs_data.append({
                    'leg':          leg_num,
                    'runner_id':    None,
                    'name':         '—',
                    'leg_time':     '-',
                    'leg_time_raw': None,
                    'cum_time':     '-',
                    'cum_time_raw': None,
                    'stat':         0,
                    'stat_label':   '-',
                    'stat_badge':   'secondary',
                    'splits':       [],
                    'leg_rank':     None,
                    'cum_rank':     None,
                })

        teams_data.append({
            'team':     t,
            'org_name': org_map.get(t.org, ''),
            'legs':     legs_data,
        })

    # ── Passe 2 : classements par fraction et au cumulé ──────────────────────
    for leg_num in range(1, n_legs + 1):
        idx = leg_num - 1   # index dans legs_data

        # Collecter les temps valides de toutes les équipes pour cette fraction
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
        'competition': competition,
        'cls':         cls,
        'teams_data':  teams_data,
        'leader_time': format_time(leader_time) if leader_time else '-',
        'n_legs':      n_legs,
    })
