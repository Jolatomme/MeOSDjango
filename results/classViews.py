import json
import re
import markdown
from collections import defaultdict
from datetime import date

from django.shortcuts import render, get_object_or_404
from django.http import Http404
from django.views.generic import TemplateView, ListView, DetailView, FormView
from django.db import connection

from .models import (
    Mopcompetition, Mopclass, Mopcompetitor, Mopteam,
    MeosTutorial, STAT_OK,
)
from .services import (
    get_org_map, get_class_controls, get_courses_map,
    slugify_no_prefix, competition_visible,
)

from .meos_checker import check_meos_file
from .verifie_moi import generate_verifie_moi_csv
from .forms import MeosFileForm, VerifieMoiFileForm


def has_individual_competitors(cid, relay_class_ids=None):
    """Return True if the competition has individual (non-relay) runners."""
    if relay_class_ids is None:
        relay_class_ids = set(
            Mopteam.objects.filter(cid=cid).values_list('cls', flat=True).distinct()
        )
    if relay_class_ids:
        return Mopcompetitor.objects.filter(
            cid=cid, st__gt=0
        ).exclude(cls__in=relay_class_ids).exists()
    return Mopcompetitor.objects.filter(cid=cid, st__gt=0).exists()


def _days_in_month(year, month):
    """Number of days in the given month."""
    next_first = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return (next_first - date(year, month, 1)).days


def _months_ago(n, ref=None):
    """Date situated ``n`` months before ``ref`` (today by default).

    Handles month/year rollover and clamps the day to the last day of the
    target month (e.g. Jan 31 minus 1 month → Dec 31).
    """
    ref = ref or date.today()
    total = ref.year * 12 + (ref.month - 1) - n
    year, month0 = divmod(total, 12)
    month = month0 + 1
    day = min(ref.day, _days_in_month(year, month))
    return date(year, month, day)


class RenderShortcutMixin:
    """Mixin that uses Django's render() shortcut for CBV rendering.

    Allows tests to patch ``results.classViews.render`` instead of going through
    Django's TemplateResponse machinery.
    """

    def render_to_response(self, context, **response_kwargs):
        return render(self.request, self.template_name, context)


class HomeView(RenderShortcutMixin, ListView):
    """Landing page listing competitions, grouped by year.

    Three mutually exclusive display modes (most specific wins):
      1. ``?year=YYYY``  — every competition of that year;
      2. ``?months=X``   — competitions from the last X months;
      3. ``?all=1``      — every competition;
      4. no parameter    — the 3 most recent competitions.
    Competitions are always sorted by date, most recent first. The template
    receives ``years`` (list of ``(year, [competitions])``), ``months``,
    ``selected_year`` and ``available_years``.
    """
    template_name = "results/home.html"
    context_object_name = "competitions"
    default_limit = 3

    def get_queryset(self):
        """Return visible competitions, filtered then sorted newest first."""
        qs = list(Mopcompetition.objects.all())
        qs = [c for c in qs if competition_visible(c.cid)]
        rqs = sorted(qs, key=lambda c: c.date or date.min, reverse=True)

        self.available_years = sorted(
            {c.date.year for c in rqs if c.date}, reverse=True
        )

        self.months = None
        self.selected_year = None
        self.show_all = False
        self.active_filter = False
        months_raw = self.request.GET.get('months', '').strip()
        year_raw = self.request.GET.get('year', '').strip()
        all_raw = self.request.GET.get('all', '').strip()

        selected_year = year_raw if year_raw.isdigit() else None
        months_value = months_raw if months_raw.isdigit() else None

        if selected_year is not None and int(selected_year) in self.available_years:
            self.selected_year = int(selected_year)
            self.active_filter = True
            rqs = [c for c in rqs if c.date and c.date.year == self.selected_year]
        elif months_value is not None and int(months_value) >= 1:
            self.months = int(months_value)
            self.active_filter = True
            cutoff = _months_ago(self.months)
            rqs = [c for c in rqs if c.date and c.date >= cutoff]
        elif all_raw == '1':
            self.show_all = True
            self.active_filter = True
        else:
            rqs = rqs[:self.default_limit]

        for comp in rqs:
            comp.has_individual_competitors = has_individual_competitors(comp.cid)

        groups = defaultdict(list)
        for comp in rqs:
            groups[comp.date.year if comp.date else None].append(comp)
        self.years = sorted(
            groups.items(),
            key=lambda item: item[0] if item[0] is not None else -1,
            reverse=True,
        )
        return rqs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['years'] = self.years
        ctx['months'] = self.months
        ctx['selected_year'] = self.selected_year
        ctx['available_years'] = self.available_years
        ctx['active_filter'] = self.active_filter
        ctx['show_all'] = self.show_all
        return ctx


class CompetitionDetailView(RenderShortcutMixin, DetailView):
    """Detail page for a single competition.

    Context includes:
    - ``class_stats`` — list of dicts with class name, total/finished counts,
      relay flag, and optional control count.
    - ``courses_map`` — mapping of course hashes to course info.
    - ``has_individual_competitors`` — whether individual results exist.
    """
    template_name = "results/competition_detail.html"
    context_object_name = "competition"
    pk_url_kwarg = "cid"

    def get_object(self, queryset=None):
        obj = get_object_or_404(Mopcompetition, cid=self.kwargs['cid'])
        if not competition_visible(obj.cid):
            raise Http404
        return obj

    def get_context_data(self, **kwargs):
        """Build the full template context with class stats and courses."""
        context = super().get_context_data(**kwargs)
        cid = self.object.cid

        classes = Mopclass.objects.filter(cid=cid).order_by('ord', 'name')
        relay_class_ids = set(
            Mopteam.objects.filter(cid=cid).values_list('cls', flat=True).distinct()
        )

        has_individual = has_individual_competitors(cid, relay_class_ids)

        class_stats = []
        for cls in classes:
            is_relay = cls.id in relay_class_ids
            if is_relay:
                qs = Mopteam.objects.filter(cid=cid, cls=cls.id)
                total = qs.count()
                if total == 0:
                    continue
                finishers = qs.filter(stat=STAT_OK).exclude(rt__lte=0).count()
                class_stats.append({'cls': cls, 'total': total, 'finishers': finishers,
                                    'is_relay': is_relay})
            else:
                qs = Mopcompetitor.objects.filter(cid=cid, cls=cls.id)
                total = qs.count()
                if total == 0:
                    continue
                finishers = qs.filter(stat=STAT_OK).exclude(rt__lte=0).count()
                controls_seq, _ = get_class_controls(cid, cls.id)
                class_stats.append({'cls': cls, 'total': total, 'finishers': finishers,
                                    'is_relay': is_relay, 'n_controls': len(controls_seq)})

        class_totals = {cs['cls'].id: cs['total'] for cs in class_stats}
        courses_map = get_courses_map(cid, relay_class_ids, class_totals)

        context.update({
            'class_stats': class_stats,
            'courses_map': courses_map,
            'has_individual_competitors': has_individual,
        })
        return context


class StartListView(RenderShortcutMixin, TemplateView):
    """Start list page — groups competitors by category, club, and start time.

    Renders a JSON blob (``start_list_data``) consumed by the DataTables-based
    template to provide searchable/sortable grouped tables.
    """
    template_name = "results/start_list.html"

    def get_context_data(self, **kwargs):
        """Build the grouped start list data structure and add it to context."""
        context = super().get_context_data(**kwargs)
        cid = self.kwargs['cid']
        competition = get_object_or_404(Mopcompetition, cid=cid)
        if not competition_visible(cid):
            raise Http404

        competitors = Mopcompetitor.objects.filter(cid=cid, st__gt=0).select_related()
        class_map = {c.id: c for c in Mopclass.objects.filter(cid=cid)}
        org_map = get_org_map(cid, as_objects=True)

        rows = []
        for comp in competitors:
            cls_obj = class_map.get(comp.cls)
            org_obj = org_map.get(comp.org)

            name_parts = comp.name.split(' ', 1)
            family = name_parts[0] if name_parts else comp.name
            given = name_parts[1] if len(name_parts) > 1 else ''

            start_time = ''
            start_time_sort = '99:99'
            if comp.st and comp.st > 0:
                total_seconds = comp.st // 10
                hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60
                start_time = f"{hours:02d}:{minutes:02d}"
                start_time_sort = f"{hours:02d}:{minutes:02d}"

            rows.append({
                'family': family,
                'given': given,
                'full_name': comp.name,
                'category': cls_obj.name if cls_obj else '',
                'club_id': comp.org,
                'club_short': f"{comp.org:04d}" if comp.org else '',
                'club_name': org_obj.name if org_obj else '',
                'club_display': f"{comp.org:04d} - {org_obj.name}" if org_obj else 'Sans club',
                'start_time': start_time,
                'start_time_sort': start_time_sort,
                'control_card': '',
            })

        rows.sort(key=lambda r: r['start_time_sort'])

        by_category = defaultdict(list)
        for row in rows:
            by_category[row['category']].append(row)

        by_club = defaultdict(list)
        for row in rows:
            by_club[row['club_display']].append(row)

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
                groups.append({'name': key, 'slug': slug, 'rows': items})
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

        context.update({
            'competition': competition,
            'start_list_data': json.dumps(data),
        })
        return context


class StatisticsView(RenderShortcutMixin, TemplateView):
    """Statistics page — shows total/finished counts and top-10 organisations.

    Uses a raw SQL query on the MeOS-managed tables to aggregate finisher
    counts per organisation.
    """
    template_name = "results/statistics.html"

    def get_context_data(self, **kwargs):
        """Query aggregate stats (total, finished, top orgs) and add to context."""
        context = super().get_context_data(**kwargs)
        cid = self.kwargs['cid']
        competition = get_object_or_404(Mopcompetition, cid=cid)
        if not competition_visible(cid):
            raise Http404

        total = Mopcompetitor.objects.filter(cid=cid).count()
        finished = Mopcompetitor.objects.filter(cid=cid, stat=STAT_OK).exclude(rt__lte=0).count()

        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT o.name, COUNT(c.id) AS cnt
                FROM mopCompetitor c
                JOIN mopOrganization o ON o.cid = c.cid AND o.id = c.org
                WHERE c.cid = %s AND c.stat = %s AND c.rt > 0
                GROUP BY o.id, o.name ORDER BY cnt DESC LIMIT 10
            """, [cid, STAT_OK])
            top_orgs = cursor.fetchall()

        context.update({
            'competition': competition, 'total': total,
            'finished': finished, 'top_orgs': top_orgs,
        })
        return context


class EtiquettesView(RenderShortcutMixin, TemplateView):
    """Static page: SI card numbering rules / étiquetage."""
    template_name = "results/etiquettes.html"


class DriversView(RenderShortcutMixin, TemplateView):
    """Static page: printer drivers download."""
    template_name = "results/drivers.html"


class TutoView(ListView):
    """Tutorial / help article list page."""
    template_name = "results/tuto.html"

    def get_queryset(self):
        return MeosTutorial.objects.all()


class MarkdownDetailView(RenderShortcutMixin, DetailView):
    """Single tutorial article page — renders MeosTutorial markdown as HTML.

    Uses Python-Markdown with fenced code, TOC, and table extensions.
    """
    template_name = "results/markdown_content.html"
    context_object_name = "markdown_content"
    pk_url_kwarg = "article_id"

    def get_object(self, queryset=None):
        """Fetch the tutorial by pk, raising 404 if not found."""
        try:
            return MeosTutorial.objects.get(pk=self.kwargs['article_id'])
        except MeosTutorial.DoesNotExist:
            raise Http404

    def get_context_data(self, **kwargs):
        """Convert the tutorial's markdown body to HTML before returning context."""
        context = super().get_context_data(**kwargs)
        md = markdown.Markdown(
            extensions=["fenced_code", "toc", "tables"],
            extension_configs={"toc": {"slugify": slugify_no_prefix}},
        )
        context['markdown_content'].content = md.convert(self.object.text)
        return context


class MeosCheckerView(RenderShortcutMixin, FormView):
    """GEC MeOS file checker — validates an uploaded .meosxml file.

    Runs a series of consistency checks (club consecutivity, control
    coordinates, empty categories, etc.) and displays the report.
    """
    template_name = "results/meos_checker.html"
    form_class = MeosFileForm

    def get_context_data(self, **kwargs):
        """Ensure ``report`` and ``parse_error`` default to None."""
        context = super().get_context_data(**kwargs)
        context.setdefault('report', None)
        context.setdefault('parse_error', None)
        return context

    def form_valid(self, form):
        """Parse uploaded XML and pass the check report to the template."""
        xml_bytes = form.cleaned_data['meosfile'].read()
        gap_seconds = form.cleaned_data.get('gap_seconds') or 120
        enabled = set(form.cleaned_data.get('enabled_rules', []))
        try:
            report = check_meos_file(
                xml_bytes,
                gap_max_seconds=gap_seconds,
                enabled_rules=enabled,
            )
        except ValueError as exc:
            return self.form_invalid(form, parse_error=str(exc))
        return self.render_to_response(self.get_context_data(report=report, form=form))

    def form_invalid(self, form, parse_error=None):
        return self.render_to_response(self.get_context_data(form=form, parse_error=parse_error))


class VerifieMoiView(RenderShortcutMixin, FormView):
    """Vérifie-Moi tool — reads a MeOS XML and generates a CSV start list.

    Processes the uploaded XML, extracts runner info, and produces a CSV
    download with columns: name, club, category, start time, SI card, etc.
    """
    template_name = "results/verifie_moi.html"
    form_class = VerifieMoiFileForm

    def get_context_data(self, **kwargs):
        """Ensure all optional context keys default to None."""
        context = super().get_context_data(**kwargs)
        context.setdefault('parse_error', None)
        context.setdefault('result', None)
        context.setdefault('csv_content_json', None)
        context.setdefault('filename_json', None)
        return context

    def form_valid(self, form):
        """Parse the uploaded XML, generate CSV content, and pass it to the template."""
        xml_bytes = form.cleaned_data['meosfile'].read()
        try:
            result = generate_verifie_moi_csv(xml_bytes)
            csv_content_json = json.dumps(result.csv_content)
            safe_name = re.sub(r'[^\w\-\.\s]', '_', result.competition_name).strip() or 'verifie_moi'
            filename_json = json.dumps(safe_name + '.csv')
        except ValueError as exc:
            return self.form_invalid(form, parse_error=str(exc))
        return self.render_to_response(self.get_context_data(
            form=form, result=result,
            csv_content_json=csv_content_json,
            filename_json=filename_json
        ))

    def form_invalid(self, form, parse_error=None):
        return self.render_to_response(self.get_context_data(form=form, parse_error=parse_error))
