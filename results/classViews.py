import json
import re
import markdown
from collections import defaultdict

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
    slugify_no_prefix,
)
from .meos_checker import check_meos_file
from .verifie_moi import generate_verifie_moi_csv
from .forms import MeosFileForm, VerifieMoiFileForm


class RenderShortcutMixin:
    """Mixin that uses Django's render() shortcut for CBV rendering.

    Allows tests to patch ``results.classViews.render`` instead of going through
    Django's TemplateResponse machinery.
    """

    def render_to_response(self, context, **response_kwargs):
        return render(self.request, self.template_name, context)


class HomeView(RenderShortcutMixin, ListView):
    """Landing page listing all competitions.

    For each competition, annotates ``has_individual_competitors`` to let the
    template know whether individual (non-relay) results are available.
    """
    template_name = "results/home.html"
    context_object_name = "competitions"

    def get_queryset(self):
        """Return all competitions, annotated with relay/individual flags."""
        qs = list(Mopcompetition.objects.all())
        for comp in qs:
            relay_class_ids = set(
                Mopteam.objects.filter(cid=comp.cid).values_list('cls', flat=True).distinct()
            )
            if relay_class_ids:
                comp.has_individual_competitors = Mopcompetitor.objects.filter(
                    cid=comp.cid, st__gt=0
                ).exclude(cls__in=relay_class_ids).exists()
            else:
                comp.has_individual_competitors = Mopcompetitor.objects.filter(
                    cid=comp.cid, st__gt=0
                ).exists()
        return qs


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
        return get_object_or_404(Mopcompetition, cid=self.kwargs['cid'])

    def get_context_data(self, **kwargs):
        """Build the full template context with class stats and courses."""
        context = super().get_context_data(**kwargs)
        cid = self.object.cid

        classes = Mopclass.objects.filter(cid=cid).order_by('ord', 'name')
        relay_class_ids = set(
            Mopteam.objects.filter(cid=cid).values_list('cls', flat=True).distinct()
        )

        if relay_class_ids:
            has_individual = Mopcompetitor.objects.filter(
                cid=cid, st__gt=0
            ).exclude(cls__in=relay_class_ids).exists()
        else:
            has_individual = Mopcompetitor.objects.filter(cid=cid, st__gt=0).exists()

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
        try:
            report = check_meos_file(xml_bytes)
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
