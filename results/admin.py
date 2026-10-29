from django import forms
from django.contrib import admin, messages
from django.db import connection
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext, gettext_lazy

from .forms import validate_org_logo
from .models import CompetitionConfig, MeosTutorial, Mopcompetition
from .services import delete_org_logo, save_org_logo

MEOS_TABLES = [
    'mopRadio', 'mopClassControl', 'mopTeamMember',
    'mopCompetitor', 'mopTeam', 'mopOrganization',
    'mopClass', 'mopControl', 'mopCompetition',
]


# ─── CompetitionConfig ────────────────────────────────────────────────────────

class CompetitionConfigAdminForm(forms.ModelForm):
    """Formulaire admin de la configuration, enrichi des champs de course.

    ``livelox`` et ``logo`` appartiennent à ``mopCompetition`` (table MeOS non
    gérée par Django) : ils sont exposés ici pour pouvoir les modifier après
    la création de la course, sans passer par le lien privé de gestion.
    """

    livelox = forms.URLField(
        label="Livelox",
        max_length=128,
        required=False,
        assume_scheme='https',
    )
    logo = forms.FileField(
        label=gettext_lazy("Logo de l'organisateur"),
        required=False,
        validators=[validate_org_logo],
        help_text=gettext_lazy("SVG, PNG ou JPEG — 2 Mo maximum."),
    )

    class Meta:
        model = CompetitionConfig
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._competition = None
        cid = getattr(self.instance, 'cid', None)
        if cid is not None:
            self._competition = (
                Mopcompetition.objects.filter(cid=cid, id=1).first()
            )
        if self._competition is not None:
            self.initial.setdefault(
                'livelox', self._competition.livelox or '',
            )
            if self._competition.logo:
                self.fields['logo'].help_text = format_html(
                    '{} {} <a href="{}" target="_blank" rel="noopener">{}</a>',
                    self.fields['logo'].help_text,
                    gettext("Logo actuel :"),
                    reverse('results:org_logo', args=[self._competition.logo]),
                    self._competition.logo,
                )

    def save_competition_fields(self):
        """Reporte livelox/logo sur la ligne ``mopCompetition`` (cid, id=1)."""
        competition = self._competition
        cleaned = getattr(self, 'cleaned_data', None)
        if competition is None or not cleaned:
            return

        changes = {}

        livelox = cleaned.get('livelox') or ''
        if (competition.livelox or '') != livelox:
            changes['livelox'] = livelox

        old_logo = competition.logo or ''
        logo_file = cleaned.get('logo')
        if logo_file:
            new_logo = save_org_logo(logo_file)
            changes['logo'] = new_logo

        if not changes:
            return
        Mopcompetition.objects.filter(cid=self.instance.cid, id=1).update(
            **changes
        )
        if 'logo' in changes and old_logo:
            delete_org_logo(old_logo)


def _competition_name(cid):
    with connection.cursor() as cur:
        cur.execute("SELECT name FROM mopCompetition WHERE cid=%s", [cid])
        row = cur.fetchone()
    return row[0] if row else str(cid)


@admin.register(CompetitionConfig)
class CompetitionConfigAdmin(admin.ModelAdmin):
    form = CompetitionConfigAdminForm
    list_display  = ('_name', '_date', 'cid', 'frozen', 'visible', 'deleted')
    list_display_links = ('_name',)
    list_filter   = ('frozen', 'visible', 'deleted')
    list_editable = ('frozen', 'visible', 'deleted')
    search_fields = ('_name',)
    ordering      = ('-cid',)
    readonly_fields = ('created_at',)
    fieldsets = (
        (None, {
            'fields': ('cid', 'frozen', 'visible', 'deleted'),
        }),
        (gettext_lazy("Informations de la course"), {
            'fields': ('livelox', 'logo'),
            'classes': ('co-race-info',),
        }),
        (gettext_lazy("Accès MeOS"), {
            'fields': ('api_key', 'manage_token', 'created_at'),
        }),
    )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # Le formulaire porte livelox/logo, absents du modèle CompetitionConfig.
        form.save_competition_fields()

    def get_queryset(self, request):
        existing = {c.cid for c in CompetitionConfig.objects.all()}
        with connection.cursor() as cur:
            cur.execute("SELECT cid FROM mopCompetition")
            all_cids = [row[0] for row in cur.fetchall()]
        for cid in all_cids:
            if cid not in existing:
                CompetitionConfig.objects.create(cid=cid)
        # Ne jamais supprimer une course dotée d'une clé API (course créée
        # depuis le site) : sa configuration porte un secret qui doit survivre
        # à la désynchronisation des tables.
        stale = existing - set(all_cids)
        if stale:
            CompetitionConfig.objects.filter(
                cid__in=stale, api_key__isnull=True,
            ).delete()
        return CompetitionConfig.objects.all()

    def _name(self, obj):
        return _competition_name(obj.cid)
    _name.short_description = gettext_lazy("Compétition")

    def _date(self, obj):
        with connection.cursor() as cur:
            cur.execute("SELECT date FROM mopCompetition WHERE cid=%s", [obj.cid])
            row = cur.fetchone()
        return row[0] if row else '—'
    _date.short_description = gettext_lazy("Date")
    _date.admin_order_field = 'cid'

    actions = ['revoke_manage_links']

    def revoke_manage_links(self, request, queryset):
        """Révoque les liens de gestion privés (jeton supprimé).

        La clé API MeOS (api_key) reste intacte : les envois MeOS continuent.
        Le lien privé /gestion-course/<jeton>/ devient invalide (404).
        """
        updated = queryset.filter(
            manage_token__isnull=False,
        ).update(manage_token=None)
        self.message_user(
            request,
            gettext(
                "%(n)s lien(s) de gestion révoqué(s) — les clés API MeOS "
                "restent actives."
            )
            % {"n": updated},
            level=messages.WARNING,
        )

    revoke_manage_links.short_description = gettext_lazy(
        "Révoquer les liens de gestion privés"
    )

    def has_delete_permission(self, request, obj=None):
        return False

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        obj = self.get_object(request, object_id) if object_id else None
        if request.method == 'POST' and '_delete_mop_data' in request.POST and obj:
            cid = obj.cid
            name = _competition_name(cid)
            with connection.cursor() as cur:
                for table in MEOS_TABLES:
                    cur.execute(f"DELETE FROM `{table}` WHERE cid = %s", [cid])
            CompetitionConfig.objects.filter(cid=cid).delete()
            self.message_user(
                request,
                gettext("Compétition supprimée pour cid=%(cid)s (%(name)s).")
                % {"cid": cid, "name": name},
                level=messages.WARNING,
            )
            return HttpResponseRedirect(
                reverse('admin:results_competitionconfig_changelist')
            )
        if request.method == 'POST' and '_delete_logo' in request.POST and obj:
            competition = Mopcompetition.objects.filter(
                cid=obj.cid, id=1,
            ).first()
            logo = (competition.logo or '') if competition else ''
            if logo:
                Mopcompetition.objects.filter(cid=obj.cid, id=1).update(
                    logo='',
                )
                delete_org_logo(logo)
                self.message_user(
                    request,
                    gettext("Logo de l'organisateur supprimé."),
                    level=messages.SUCCESS,
                )
            else:
                self.message_user(
                    request,
                    gettext("Aucun logo à supprimer."),
                    level=messages.WARNING,
                )
            return HttpResponseRedirect(
                reverse(
                    'admin:results_competitionconfig_change',
                    args=[obj.pk],
                )
            )
        if obj:
            competition = Mopcompetition.objects.filter(
                cid=obj.cid, id=1,
            ).first()
            extra_context = extra_context or {}
            extra_context['competition_logo'] = (
                (competition.logo or '') if competition else ''
            )
        return super().changeform_view(request, object_id, form_url, extra_context)


# ─── Modèles Mop* ────────────────────────────────────────────────────────────
# Non enregistrés dans l'admin Django : leurs tables ont une clé primaire
# composite (cid, id) — non supportée par l'admin Django 5.2–6.1. Les données
# MOP restent consultables via les pages publiques de résultats.

admin.site.register(MeosTutorial)
