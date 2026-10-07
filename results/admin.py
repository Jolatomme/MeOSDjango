from django.contrib import admin, messages
from django.db import connection
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.translation import gettext, gettext_lazy

from .models import (
    Mopclass, Mopclasscontrol, Mopcompetition, Mopcompetitor,
    Mopcontrol, Moporganization, Mopradio, Mopteam, Mopteammember,
    MeosTutorial, CompetitionConfig,
)

MEOS_TABLES = [
    'mopRadio', 'mopClassControl', 'mopTeamMember',
    'mopCompetitor', 'mopTeam', 'mopOrganization',
    'mopClass', 'mopControl', 'mopCompetition',
]


# ─── CompetitionConfig ────────────────────────────────────────────────────────

def _competition_name(cid):
    with connection.cursor() as cur:
        cur.execute("SELECT name FROM mopCompetition WHERE cid=%s", [cid])
        row = cur.fetchone()
    return row[0] if row else str(cid)


@admin.register(CompetitionConfig)
class CompetitionConfigAdmin(admin.ModelAdmin):
    list_display  = ('_name', '_date', 'cid', 'frozen', 'visible', 'deleted')
    list_display_links = ('_name',)
    list_filter   = ('frozen', 'visible', 'deleted')
    list_editable = ('frozen', 'visible', 'deleted')
    search_fields = ('_name',)
    ordering      = ('-cid',)

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
                gettext("Données MOP supprimées pour cid=%(cid)s (%(name)s).")
                % {"cid": cid, "name": name},
                level=messages.WARNING,
            )
            return HttpResponseRedirect(
                reverse('admin:results_competitionconfig_changelist')
            )
        return super().changeform_view(request, object_id, form_url, extra_context)


# ─── Mopcompetition — colonnes utiles ────────────────────────────────────────

@admin.register(Mopcompetition)
class MopcompetitionAdmin(admin.ModelAdmin):
    list_display  = ('cid', 'name', 'date', 'organizer')
    list_filter   = ('date',)
    search_fields = ('name', 'organizer')
    ordering      = ['-date']


# ─── Inscriptions rapides pour les autres modèles ─────────────────────────────

@admin.register(Mopclass)
class MopclassAdmin(admin.ModelAdmin):
    list_display  = ('cid', 'id', 'name', 'ord')
    list_filter   = ('cid',)
    search_fields = ('name',)


@admin.register(Mopcompetitor)
class MopcompetitorAdmin(admin.ModelAdmin):
    list_display  = ('cid', 'id', 'name', 'org', 'cls', 'stat', 'rt')
    list_filter   = ('cid', 'stat')
    search_fields = ('name',)


@admin.register(Moporganization)
class MoporganizationAdmin(admin.ModelAdmin):
    list_display  = ('cid', 'id', 'name')
    list_filter   = ('cid',)
    search_fields = ('name',)


admin.site.register(Mopclasscontrol)
admin.site.register(Mopcontrol)
admin.site.register(Mopradio)
admin.site.register(Mopteam)
admin.site.register(Mopteammember)
admin.site.register(MeosTutorial)
