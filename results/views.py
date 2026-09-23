import hashlib
import json
import re
from collections import Counter
from types import SimpleNamespace
from datetime import date, datetime
from django.core.cache import cache
from django.shortcuts import render, get_object_or_404, redirect
from django.http import Http404, HttpResponse, JsonResponse


from .models import (
    Mopcompetition, Mopclass, Moporganization, Mopcompetitor,
    Mopteam, Mopteammember,
    format_time, STAT_OK,
    STAT_NT, STAT_MP, STAT_DNF, STAT_DQ, STAT_OT,
    STAT_OCC, STAT_DNS, STAT_CANCEL, STAT_NP,
)
from .services import (
    get_org_map, get_class_controls, get_controls_by_leg,
    get_radio_map, compute_splits, build_finish_split,
    get_negative_time_stats,
    attested_ctrls, detect_prestart_ctrls,
    mark_best_splits, rank_splits,
    rank_finishers, build_rank_map,
    build_leg_matrix, compute_leg_refs,
    build_abs_time_series, compute_error_estimates,
    compute_grouping_index, compute_regularity_analysis,
    compute_course_hash, get_courses_map,
    competition_visible, run_controls_only,
    rank_live, race_start_clock, race_end_clock, race_state,
    race_in_progress, mark_negative_times, clock_tenths, _now_abs, _st_abs,
    LIVE_GROUPS, has_completed,
)


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
    if not competition_visible(cid):
        raise Http404
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
    # Per-category gate: hide punches until one runner has finished (OK or prel)
    can_show_splits = has_completed(competitors)

    if can_show_splits:
        radio_map    = get_radio_map(cid, [c.id for c in results])
        attested     = attested_ctrls(radio_map)

        for c in results:
            c.splits = compute_splits(
                c.id, controls_seq, radio_map,
                detect_prestart_ctrls(c, controls_seq, radio_map, attested))

        # Ajout du tronçon arrivée pour tous (cohérence mark_best_splits / rank_splits)
        for c in results:
            last_abs = c.splits[-1]['abs_raw'] if c.splits else None
            c.splits.append(build_finish_split(c.rt, last_abs))
            c.neg_time = any(sp.get('neg_leg') for sp in c.splits)

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
    else:
        for c in results:
            c.splits = []
            c.neg_time = False
        leg_error_data = []

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
        'can_show_splits':     can_show_splits,
        'current_analysis':    'results',
        'leg_error_data_json': json.dumps(leg_error_data),
        'prev_cls':            prev_cls,
        'next_cls':            next_cls,
        'course_hash':         course['hash'] if course else compute_course_hash(controls_seq),
        'neg_time_warning':    get_negative_time_stats(cid),
    })


# ══════════════════════════════════════════════════════════════════════════════
# Fiche concurrent & organisation
# ══════════════════════════════════════════════════════════════════════════════

def competitor_detail(request, cid, competitor_id):
    """Individual competitor detail page with split times."""
    competition = get_object_or_404(Mopcompetition, cid=cid)
    if not competition_visible(cid):
        raise Http404
    competitor  = get_object_or_404(Mopcompetitor, cid=cid, id=competitor_id)
    org = Moporganization.objects.filter(cid=cid, id=competitor.org).first()
    cls = Mopclass.objects.filter(cid=cid, id=competitor.cls).first()
    # Relais : fraction du coureur — mopClassControl contient l'union de
    # toutes les fractions/fourches, inapplicable ici.
    member = Mopteammember.objects.filter(cid=cid, rid=competitor_id).first()
    if member is not None:
        controls_seq, _ = get_class_controls(cid, competitor.cls, leg=member.leg)
    else:
        controls_seq, _ = get_class_controls(cid, competitor.cls)
    class_competitors = list(Mopcompetitor.objects.filter(cid=cid, cls=competitor.cls))
    # Per-category gate: hide punches until one runner in the category has finished
    # Fallback for legacy mocks (empty list) — treat as can_show to keep old tests
    if not class_competitors:
        can_show = True
    else:
        can_show = has_completed(class_competitors) or has_completed([competitor])
    if can_show:
        radio_map = get_radio_map(cid, [c.id for c in class_competitors])
        attested  = attested_ctrls(radio_map)
        # Fourches : n'afficher que les postes poinçonnés par CE coureur.
        if member is not None:
            controls_seq = run_controls_only(controls_seq, radio_map.get(competitor_id, {}))
        splits = compute_splits(
            competitor_id, controls_seq, radio_map,
            detect_prestart_ctrls(competitor, controls_seq, radio_map, attested))
        # Tronçon arrivée : tout coureur avec un temps de course a franchi la
        # ligne, y compris les non-classés (PM/DQ/OT…) — le temps est alors
        # visible sur sa fiche, sans valeur de classement.
        if splits and competitor.rt > 0:
            last_abs = splits[-1]['abs_raw']
            splits.append(build_finish_split(competitor.rt, last_abs))
        competitor.neg_time = any(sp.get('neg_leg') for sp in splits)
    else:
        splits = []
        competitor.neg_time = False
    return render(request, 'results/competitor_detail.html', {
        'competition': competition, 'competitor': competitor,
        'org': org, 'cls': cls, 'splits': splits,
        'can_show_splits': can_show,
        'neg_time_warning': get_negative_time_stats(cid),
        'total_time': format_time(competitor.rt) if competitor.is_ok else competitor.status_label,
    })


def org_results(request, cid, org_id):
    """Results page for a single organisation — all runners grouped by class."""
    competition  = get_object_or_404(Mopcompetition, cid=cid)
    if not competition_visible(cid):
        raise Http404
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
    data = []
    for i, c in enumerate(finishers):
        behind = ''
        if i > 0:
            diff = c.rt - leader
            behind = f'+{format_time(diff)}' if diff >= 0 else format_time(diff)
        data.append({
            'rank': i + 1, 'name': c.name, 'org': org_map.get(c.org, ''),
            'time': format_time(c.rt),
            'behind': behind,
        })
    return JsonResponse({'results': data})


# ══════════════════════════════════════════════════════════════════════════════
# Suivi live — catégorie ET circuit (via _load_class_context unifié)
# ══════════════════════════════════════════════════════════════════════════════

def _live_neg_time_warning(cid):
    """Bandeau « Temps négatif » pour l'affichage live.

    Identique à ``get_negative_time_stats`` mais expurge les coureurs en
    validation GEC (``prel=True`` : puce pas encore lue) — leurs poinçons
    sont incomplets, la détection y est sans objet en live. Helper
    strictement live : n'altère pas le diagnostic des pages d'analyse.
    """
    warning = get_negative_time_stats(cid)
    if not warning:
        return None
    valid_gec_ids = set(
        Mopcompetitor.objects.filter(cid=cid, prel=True)
        .values_list('id', flat=True))
    runners = [r for r in warning['runners'] if r['id'] not in valid_gec_ids]
    if not runners:
        return None
    ctrl_counts = Counter(c for r in runners for c in r['controls'])
    box_controls = {
        name: n
        for name, n in sorted(ctrl_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        if n >= 2
    }
    count = len(runners)
    if box_controls:
        kind = 'multiple'
        box_names = ', '.join(box_controls)
        postes = f"au poste {box_names}" if len(box_controls) == 1 else f"aux postes {box_names}"
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
    return {
        'count': count, 'kind': kind, 'message': message, 'tooltip': tooltip,
        'box_controls': box_controls, 'runners': runners,
    }


def live_results(request, cid, class_id):
    """Page live : suivi en temps réel de la progression sur le parcours.

    Aucune analyse n'est calculée ici (données incomplètes tant que les
    coureurs ne sont pas passés à la GEC) — uniquement le classement live.
    """
    competition, cls, competitors, course = _load_class_context(cid, class_id)

    # Redirection relais (live non géré pour les équipes pour l'instant)
    if course is None and Mopteam.objects.filter(cid=cid, cls=cls.id).exists():
        return redirect('results:relay_results', cid=cid, class_id=class_id)

    # Navigation catégorie adjacente (non pertinent pour un circuit)
    prev_cls, next_cls = (None, None)
    if course is None:
        prev_cls, next_cls = _get_adjacent_classes(cid, cls.id)

    org_map = get_org_map(cid, as_objects=True)
    for c in competitors:
        c.org_obj = org_map.get(c.org)

    controls_seq = _controls_for(cid, cls, course)
    radio_map    = get_radio_map(cid, [c.id for c in competitors])
    now          = datetime.now()
    comp_date    = getattr(competition, 'date', None)
    if not isinstance(comp_date, date):
        comp_date = None
    live         = rank_live(competitors, radio_map, now, controls_seq or [], competition_date=comp_date)

    # Validation GEC (prel) : pas de détection des temps négatifs en live.
    mark_negative_times(
        [c for c in live if c.live_group != 'valid_gec'],
        controls_seq or [], radio_map)
    for c in live:
        if c.live_group == 'valid_gec':
            c.neg_time  = False
            c.neg_ctrls = []

    groups = {g: [c for c in live if c.live_group == g] for g in LIVE_GROUPS}

    race_start = race_start_clock(competitors, competition_date=comp_date)
    state      = race_state(live, now, race_start, competition_date=comp_date)
    race_end   = None
    if state == 'finished':
        race_end = race_end_clock(competitors, competition_date=comp_date) or _now_abs(comp_date, now)
    # Horloges absolues pour le JS (gère compétition future et passage minuit)
    server_now_abs = _now_abs(comp_date, now)
    race_start_abs = race_start

    return render(request, 'results/live_results.html', {
        'competition':       competition,
        'cls':               cls,
        'course':            course,
        'controls_seq':      controls_seq or [],
        'live':              live,
        'groups':            groups,
        'race_start_clock':  race_start,
        'race_start_abs':    race_start_abs,
        'race_state':        state,
        'race_end_clock':    race_end,
        'race_end_abs':      race_end,
        'server_now_clock':  clock_tenths(now),
        'server_now_abs':    server_now_abs,
        'competition_date':  comp_date.isoformat() if comp_date else '',
        'course_hash':       course['hash'] if course else compute_course_hash(controls_seq),
        'current_analysis':  'live',
        'neg_time_warning':  _live_neg_time_warning(cid),
        'prev_cls':          prev_cls,
        'next_cls':          next_cls,
    })


_LIVE_CACHE_TTL = 3   # s — < intervalle de polling (5 s) : partage du calcul entre spectateurs


def _build_live_payload(cid, cls, competitors, course, competition=None):
    """Construit le payload live complet (hors champs volatils d'horloge,
    réinjectés à chaque réponse) et son empreinte ETag."""
    org_map      = get_org_map(cid)
    controls_seq = _controls_for(cid, cls, course)
    radio_map    = get_radio_map(cid, [c.id for c in competitors])
    now          = datetime.now()
    # Récupère la date de compétition si non fournie (cache live)
    comp_date = getattr(competition, 'date', None) if competition is not None else None
    if not isinstance(comp_date, date):
        comp_date = None
    if comp_date is None and competition is None:
        # Fallback DB uniquement si aucun objet compétition fourni (ex. appel direct)
        try:
            comp_obj = Mopcompetition.objects.filter(cid=cid).first()
            comp_date = getattr(comp_obj, 'date', None) if comp_obj else None
            if not isinstance(comp_date, date):
                comp_date = None
        except Exception:
            comp_date = None
    live         = rank_live(competitors, radio_map, now, controls_seq or [], competition_date=comp_date)

    # Validation GEC (prel) : pas de détection des temps négatifs en live.
    mark_negative_times(
        [c for c in live if c.live_group != 'valid_gec'],
        controls_seq or [], radio_map)
    for c in live:
        if c.live_group == 'valid_gec':
            c.neg_time  = False
            c.neg_ctrls = []

    race_start = race_start_clock(competitors, competition_date=comp_date)
    state      = race_state(live, now, race_start, competition_date=comp_date)
    race_end   = None
    if state == 'finished':
        race_end = race_end_clock(competitors, competition_date=comp_date) or _now_abs(comp_date, now)

    runners = []
    ctrl_ids = {c['ctrl_id'] for c in controls_seq}
    for c in live:
        # st_abs : si rank_live n'a pas été exécuté (mock), calcule via helper
        _st_abs_val = getattr(c, 'st_abs', None)
        if not isinstance(_st_abs_val, int):
            try:
                _st_abs_val = _st_abs(c.st, comp_date) if isinstance(c.st, int) else c.st
            except Exception:
                _st_abs_val = getattr(c, 'st', None)
            if not isinstance(_st_abs_val, int):
                # MagicMock fallback -> use raw st
                try:
                    _st_abs_val = int(c.st) if c.st is not None else None
                except Exception:
                    _st_abs_val = None
        _lp = getattr(c, 'last_punch_clock', None)
        _lp_abs = _lp if isinstance(_lp, int) else None
        if _lp_abs is None:
            try:
                _lp_abs = int(_lp) if _lp is not None else None
            except Exception:
                _lp_abs = None
        runners.append({
            'id':                c.id,
            'name':              c.name,
            'org':               org_map.get(c.org, ''),
            'class_name':        c.class_obj.name if course and getattr(c, 'class_obj', None) else cls.name,
            'stat':              c.stat,
            'stat_label':        c.status_label,
            'stat_badge':        c.status_badge,
            'group':             c.live_group,
            'rank':              c.live_rank,
            'st':                c.st,
            'st_abs':            _st_abs_val,
            'rt':                c.rt if c.live_group == 'arrives' else None,
            'neg_time':          bool(getattr(c, 'neg_time', False)),
            'neg_ctrls':         list(getattr(c, 'neg_ctrls', []) or []),
            'n_punches':         getattr(c, 'n_punches', 0),
            'progress_pos':      getattr(c, 'progress_pos', 0),
            'progress_count':    getattr(c, 'progress_count', 0),
            'last_ctrl':         getattr(c, 'last_ctrl', None),
            'last_time':         getattr(c, 'last_time', None),
            'last_punch_clock':  _lp if isinstance(_lp, int) else None,
            # Horloge absolue du dernier poinçon (pour « il y a X »)
            'last_punch_clock_abs': _lp_abs,
            # Temps final provisoire (valid. GEC) : rt préliminaire MeOS ou
            # temps au poinçon d'arrivée radio détecté par rank_live.
            'provisional_rt':    (
                (c.rt if (getattr(c, 'rt', None) or 0) > 0 else None)
                or getattr(c, 'arrival_rt', None)
            ),
            'radio_punches':     [
                {'ctrl': ctrl, 'time': rt}
                for ctrl, rt in sorted(
                    radio_map.get(c.id, {}).items(), key=lambda x: x[1]
                )
                if ctrl in ctrl_ids
            ],
        })

    payload = {
        'success':            True,
        'race_start_clock':   race_start,
        'race_start_abs':     race_start,
        'race_state':         state,
        'race_end_clock':     race_end,
        'race_end_abs':       race_end,
        'competition_date':   comp_date.isoformat() if comp_date else None,
        'is_course':          bool(course),
        'cls_name':           cls.name,
        'course':             {'hash': course['hash'], 'display_name': course['display_name']} if course else None,
        'controls':           controls_seq,
        'n_controls':         len(controls_seq),
        'runners':            runners,
    }
    etag = '"%s"' % hashlib.sha1(
        json.dumps(payload, sort_keys=True).encode('utf-8')
    ).hexdigest()
    return payload, etag


def api_live_results(request, cid, class_id):
    """JSON API — données live pour le polling JS (catégorie ou circuit).

    Charge partagée : le calcul complet est mis en cache ~3 s par
    classe/circuit — N spectateurs ne coûtent qu'un calcul. Réponses
    conditionnelles : l'empreinte porte sur les champs stables uniquement
    (les horloges serveur sont réinjectées fraîches), donc un poll sans
    nouvelle donnée MeOS renvoie un 304 sans corps.
    """
    cache_key = f'live:{cid}:{class_id}'
    cached = cache.get(cache_key)
    if cached is not None:
        payload, etag = cached
    else:
        competition, cls, competitors, course = _load_class_context(cid, class_id)

        if course is None and Mopteam.objects.filter(cid=cid, cls=cls.id).exists():
            return JsonResponse({'success': False, 'error': 'relay'}, status=422)

        payload, etag = _build_live_payload(cid, cls, competitors, course, competition=competition)
        cache.set(cache_key, (payload, etag), _LIVE_CACHE_TTL)

    if request.headers.get('If-None-Match') == etag:
        return HttpResponse(status=304, headers={'ETag': etag, 'Cache-Control': 'no-cache'})

    now = datetime.now()
    # Date de compétition pour horloge absolue (gère futur + passage minuit)
    comp_date = None
    try:
        # payload contient déjà competition_date
        from datetime import date as _date
        cd_str = payload.get('competition_date')
        if cd_str:
            comp_date = _date.fromisoformat(cd_str)
    except Exception:
        comp_date = None
    data = dict(payload)
    data['server_now']       = int(now.timestamp() * 1000)
    data['server_now_clock'] = clock_tenths(now)
    data['server_now_abs']   = _now_abs(comp_date, now)
    resp = JsonResponse(data)
    resp['ETag'] = etag
    resp['Cache-Control'] = 'no-cache'
    return resp


# ══════════════════════════════════════════════════════════════════════════════
# Analyses — catégorie ET circuit via _load_class_context unifié
#
# class_id peut être :
#   - un nom ou identifiant entier de catégorie → mode catégorie
#   - un hash 8-char hex                        → mode circuit
#
# Aucune vue dupliquée : les templates utilisent {% if course %} pour adapter
# l'affichage (fil d'Ariane, onglets de navigation).
#
# Les analyses ne sont PLUS bloquées pendant la course : elles se calculent
# dès les premières arrivées, sur les coureurs ayant un statut OK (stat = 1,
# puce lue à la GEC). Les coureurs encore en course (stat = 0), non partis
# (st = 0) ou avec un statut non-OK n'apparaissent pas dans les analyses.
# Tant que la course est en cours, un bandeau « analyse partielle » est affiché
# (voir ``_partial_analysis_info``).
# ══════════════════════════════════════════════════════════════════════════════

def _partial_analysis_info(competitors):
    """Infos du bandeau « analyse partielle » tant que la course est en cours.

    Retourne ``(partial, n_ok, n_total)`` : ``partial`` est True dès qu'un
    coureur parti n'a pas de statut définitif (``race_in_progress``) ;
    ``n_ok`` compte les coureurs OK pris en compte dans les analyses.
    """
    n_ok = sum(1 for c in competitors if c.is_ok)
    return race_in_progress(competitors), n_ok, len(competitors)


def superman_analysis(request, cid, class_id):
    """Superman (optimal runner) chart — best time on each leg stitched together.

    Renders a line chart comparing each runner's cumulative loss versus the
    theoretical "superman" who takes the best split on every leg.
    """
    competition, cls, competitors, course = _load_class_context(cid, class_id)
    partial, n_ok, n_total = _partial_analysis_info(competitors)
    org_map      = get_org_map(cid)
    controls_seq = _controls_for(cid, cls, course)
    controls_labels = [c['ctrl_name'] for c in controls_seq]
    finishers, _, _ = rank_finishers(competitors)

    if not finishers:
        return render(request, 'results/superman.html', {
            'competition': competition, 'cls': cls, 'course': course,
            'no_data': True, 'current_analysis': 'superman',
            'partial_analysis': partial, 'n_ok': n_ok, 'n_total': n_total,
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
        'partial_analysis': partial, 'n_ok': n_ok, 'n_total': n_total,
    })


def performance_analysis(request, cid, class_id):
    """Performance index analysis — ratio of each runner's leg time to a reference.

    The reference is the top-25% average per leg. A lower performance index
    (closer to 0) means the runner is closer to the reference pace.
    """
    competition, cls, competitors, course = _load_class_context(cid, class_id)
    partial, n_ok, n_total = _partial_analysis_info(competitors)
    finishers, _, _ = rank_finishers(competitors)
    if not finishers:
        return render(request, 'results/performance.html', {
            'competition': competition, 'cls': cls, 'course': course,
            'no_data': True, 'current_analysis': 'performance',
            'partial_analysis': partial, 'n_ok': n_ok, 'n_total': n_total,
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
        'partial_analysis': partial, 'n_ok': n_ok, 'n_total': n_total,
    })


def regularity_analysis(request, cid, class_id):
    """Regularity analysis — weighted standard deviation of leg performance indices.

    A lower weighted std means the runner maintains a more consistent pace
    relative to the field across all legs. Requires at least 2 finishers.
    """
    competition, cls, competitors, course = _load_class_context(cid, class_id)
    partial, n_ok, n_total = _partial_analysis_info(competitors)
    finishers, _, _ = rank_finishers(competitors)
    if len(finishers) < 2:
        return render(request, 'results/regularity.html', {
            'competition': competition, 'cls': cls, 'course': course,
            'no_data': True, 'current_analysis': 'regularity',
            'partial_analysis': partial, 'n_ok': n_ok, 'n_total': n_total,
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
        'partial_analysis': partial, 'n_ok': n_ok, 'n_total': n_total,
    })


def grouping_analysis(request, cid, class_id):
    """Grouping chart — absolute time at each control for runners with a start time.

    Useful for detecting groups/clusters on the course. Renders a scatter-style
    chart of cumulative time at each control point.
    """
    competition, cls, competitors, course = _load_class_context(cid, class_id)
    partial, n_ok, n_total = _partial_analysis_info(competitors)
    runners_with_start = sorted([c for c in competitors if c.is_ok and c.st > 0],
                            key=lambda c: c.st)
    if not runners_with_start:
        return render(request, 'results/grouping.html', {
            'competition': competition, 'cls': cls, 'course': course,
            'no_data': True, 'current_analysis': 'grouping',
            'partial_analysis': partial, 'n_ok': n_ok, 'n_total': n_total,
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
        'partial_analysis': partial, 'n_ok': n_ok, 'n_total': n_total,
    })


def grouping_index_analysis(request, cid, class_id):
    """Grouping index — quantitative measure of how clustered runners are per leg.

    Accepts optional ``t1`` and ``t2`` query parameters (in minutes) that define
    the "close" and "far" time thresholds. Defaults: t1=7, t2=20.
    """
    competition, cls, competitors, course = _load_class_context(cid, class_id)
    partial, n_ok, n_total = _partial_analysis_info(competitors)
    runners = sorted([c for c in competitors if c.is_ok and c.st > 0], key=lambda c: c.st)
    if not runners:
        return render(request, 'results/grouping_index.html', {
            'competition': competition, 'cls': cls, 'course': course,
            'no_data': True, 'current_analysis': 'grouping_index',
            'partial_analysis': partial, 'n_ok': n_ok, 'n_total': n_total,
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
        'partial_analysis': partial, 'n_ok': n_ok, 'n_total': n_total,
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

    partial, n_ok, n_total = _partial_analysis_info(competitors)
    all_results, _, _ = rank_finishers(competitors)
    if not all_results:
        return render(request, 'results/duel.html', {
            'competition': competition, 'cls': cls, 'course': course,
            'no_data': True, 'current_analysis': 'duel',
            'partial_analysis': partial, 'n_ok': n_ok, 'n_total': n_total,
        })
    org_map      = get_org_map(cid)
    controls_seq = _controls_for(cid, cls, course)
    radio_map    = get_radio_map(cid, [c.id for c in competitors])
    attested     = attested_ctrls(radio_map)
    runners_data = []
    for c in all_results:
        splits = compute_splits(
            c.id, controls_seq, radio_map,
            detect_prestart_ctrls(c, controls_seq, radio_map, attested))
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
        'neg_time_warning': get_negative_time_stats(cid),
        'runners_json': json.dumps(runners_data), 'n_runners': len(runners_data),
        'partial_analysis': partial, 'n_ok': n_ok, 'n_total': n_total,
    })


# ══════════════════════════════════════════════════════════════════════════════
# Récapitulatif — tableau récapitulatif des temps intermédiaires (style WinSplits)
# ══════════════════════════════════════════════════════════════════════════════

def _load_recapitulatif_data(cid, class_id, context=None):
    """Charge et prépare les données pour le récapitulatif (HTML et CSV).

    Ne prend en compte que les coureurs OK (statut attribué par MeOS, puce
    lue) : les coureurs encore en course, non partis ou non classés
    n'apparaissent pas (analyse partielle pendant la course).
    """
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

    finishers, _, leader_time = rank_finishers(competitors)

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

    results      = finishers
    controls_seq = _controls_for(cid, cls, course)
    # Per-category gate for recapitulatif (hide punches until one finisher)
    can_show = has_completed(competitors)
    if can_show:
        radio_map   = get_radio_map(cid, [c.id for c in competitors])
        attested    = attested_ctrls(radio_map)

        for c in results:
            c.splits = compute_splits(
                c.id, controls_seq, radio_map,
                detect_prestart_ctrls(c, controls_seq, radio_map, attested))
            last_abs = c.splits[-1]['abs_raw'] if c.splits else None
            c.splits.append(build_finish_split(c.rt, last_abs))
            c.neg_time = any(sp.get('neg_leg') for sp in c.splits)

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
    else:
        for c in results:
            c.splits = []
            c.neg_time = False
        leg_error_data = []

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

    partial, n_ok, n_total = _partial_analysis_info(competitors)

    _, _, _, results, controls_seq, prev_cls, next_cls, leader_time, leg_error_data = \
        _load_recapitulatif_data(cid, class_id, context=context)
    can_show = has_completed(competitors)

    return render(request, 'results/recapitulatif.html', {
        'competition':         competition,
        'cls':                 cls,
        'course':              course,
        'results':             results,
        'leader_time':         format_time(leader_time) if leader_time else '-',
        'controls_seq':        controls_seq or [],
        'has_splits':          bool(controls_seq),
        'can_show_splits':     can_show,
        'current_analysis':    'recapitulatif',
        'prev_cls':            prev_cls,
        'next_cls':            next_cls,
        'neg_time_warning':    get_negative_time_stats(cid),
        'leg_error_data_json': json.dumps(leg_error_data),
        'partial_analysis':    partial, 'n_ok': n_ok, 'n_total': n_total,
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

    can_show = has_completed(_competitors)
    has_splits = bool(controls_seq) and can_show
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
    if not competition_visible(cid):
        raise Http404
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

    # Attestation et postes présumés pointés avant le départ, par manche
    # (l'attestation se juge parmi les coureurs de la même manche).
    # En relais avec fourches, chaque coureur ne court qu'une sous-séquence
    # de la fraction : la détection se fait sur ses seuls poinçons.
    prestart_by_leg = {}
    for leg_num in range(1, n_legs + 1):
        leg_runners = [competitors[m.rid] for m in all_members
                       if m.leg == leg_num and m.rid in competitors]
        ctrl_seq_full = [
            {'ctrl_id': cv, 'ctrl_name': f"{idx+1}-{control_name_map.get(cv, str(cv))}"}
            for idx, cv in enumerate(controls_by_leg.get(leg_num, []))
        ]
        attested = attested_ctrls({r.id: radio_map.get(r.id, {})
                                   for r in leg_runners})
        prestart_by_leg[leg_num] = {
            r.id: detect_prestart_ctrls(
                r, run_controls_only(ctrl_seq_full, radio_map.get(r.id, {})),
                radio_map, attested)
            for r in leg_runners
        }

    # Per-category gate for relay (hide punches until one team has finished)
    can_show_splits = has_completed(teams_qs)

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
                if can_show_splits:
                    ctrl_seq_full = [
                        {'ctrl_id': cv, 'ctrl_name': f"{idx+1}-{control_name_map.get(cv, str(cv))}"}
                        for idx, cv in enumerate(controls_by_leg.get(leg_num, []))
                    ]
                    # Fourches : n'afficher que les postes poinçonnés par CE coureur.
                    ctrl_seq = run_controls_only(
                        ctrl_seq_full, radio_map.get(runner.id, {}))
                    splits = compute_splits(
                        runner.id, ctrl_seq, radio_map,
                        prestart_by_leg.get(leg_num, {}).get(runner.id))
                    last_ctrl_abs = splits[-1]['abs_raw'] if splits and splits[-1]['abs_raw'] is not None else None
                    splits.append(build_finish_split(leg_time_raw, last_ctrl_abs, leg_full_race_if_missing=False))
                else:
                    splits = []
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
        t.neg_time = any(
            sp.get('neg_leg') for leg in legs_data for sp in leg['splits']
        )
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
        'neg_time_warning': get_negative_time_stats(cid),
        'n_legs': n_legs,
        'can_show_splits': can_show_splits,
    })


