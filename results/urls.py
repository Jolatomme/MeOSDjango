from django.urls import path
from . import views
from .classViews import (
    HomeView, CompetitionDetailView, StartListView, StatisticsView,
    EtiquettesView, DriversView, MarkdownDetailView, TutoView,
    MeosCheckerView, VerifieMoiView,
)
from .mop_views import mop_update

app_name = 'results'

urlpatterns = [
    # ── Accueil ────────────────────────────────────────────────────────────
    path('', HomeView.as_view(), name='home'),

    # ── Compétition ────────────────────────────────────────────────────────
    path('competition/<int:cid>/', CompetitionDetailView.as_view(), name='competition_detail'),
    path('competition/<int:cid>/start-list/', StartListView.as_view(), name='start_list'),
    path('competition/<int:cid>/stats/', StatisticsView.as_view(), name='statistics'),

    # ── Catégories ─────────────────────────────────────────────────────────
    # class_id : nom de catégorie (ex. 'H21') ou identifiant entier
    path('competition/<int:cid>/class/<str:class_id>/',                     views.class_results,           name='class_results'),
    path('competition/<int:cid>/class/<str:class_id>/relay/',               views.relay_results,           name='relay_results'),
    path('competition/<int:cid>/class/<str:class_id>/superman/',            views.superman_analysis,       name='superman'),
    path('competition/<int:cid>/class/<str:class_id>/performance/',         views.performance_analysis,    name='performance'),
    path('competition/<int:cid>/class/<str:class_id>/regularity/',          views.regularity_analysis,     name='regularity'),
    path('competition/<int:cid>/class/<str:class_id>/grouping/',            views.grouping_analysis,       name='grouping'),
    path('competition/<int:cid>/class/<str:class_id>/grouping-index/',      views.grouping_index_analysis, name='grouping_index'),
    path('competition/<int:cid>/class/<str:class_id>/duel/',                views.duel_analysis,           name='duel'),
    path('competition/<int:cid>/class/<str:class_id>/recapitulatif/',       views.recapitulatif_analysis,  name='recapitulatif'),
    path('competition/<int:cid>/class/<str:class_id>/recapitulatif/csv/',   views.recapitulatif_csv,       name='recapitulatif_csv'),

    # ── Circuits ───────────────────────────────────────────────────────────
    # course_hash : hash MD5 tronqué 8 chars (ex. 'abc12345')
    # Les MÊMES vues que pour les catégories — _load_class_context détecte
    # automatiquement un hash et charge le circuit correspondant.
    path('competition/<int:cid>/course/<str:class_id>/',                    views.class_results,           name='course_results'),
    path('competition/<int:cid>/course/<str:class_id>/superman/',           views.superman_analysis,       name='course_superman'),
    path('competition/<int:cid>/course/<str:class_id>/performance/',        views.performance_analysis,    name='course_performance'),
    path('competition/<int:cid>/course/<str:class_id>/regularity/',         views.regularity_analysis,     name='course_regularity'),
    path('competition/<int:cid>/course/<str:class_id>/grouping/',           views.grouping_analysis,       name='course_grouping'),
    path('competition/<int:cid>/course/<str:class_id>/grouping-index/',     views.grouping_index_analysis, name='course_grouping_index'),
    path('competition/<int:cid>/course/<str:class_id>/duel/',               views.duel_analysis,           name='course_duel'),
    path('competition/<int:cid>/course/<str:class_id>/recapitulatif/',      views.recapitulatif_analysis,  name='course_recapitulatif'),
    path('competition/<int:cid>/course/<str:class_id>/recapitulatif/csv/',  views.recapitulatif_csv,       name='course_recapitulatif_csv'),

    # ── Concurrent / Organisation ──────────────────────────────────────────
    path('competition/<int:cid>/competitor/<int:competitor_id>/', views.competitor_detail, name='competitor_detail'),
    path('competition/<int:cid>/org/<int:org_id>/',               views.org_results,       name='org_results'),

    # ── API ────────────────────────────────────────────────────────────────
    path('api/<int:cid>/class/<str:class_id>/results/', views.api_class_results, name='api_class_results'),

    # ── GEC ───────────────────────────────────────────────────────────────
    path('gec/checker/',    MeosCheckerView.as_view(), name='meos_checker'),
    path('gec/verifie-moi/', VerifieMoiView.as_view(), name='verifie_moi'),

    # ── Tutoriels / Ressources ─────────────────────────────────────────────
    path('tuto/',               TutoView.as_view(), name='tuto'),
    path('tuto/<int:article_id>/', MarkdownDetailView.as_view(), name='markdown'),
    path('etiquettes/',         EtiquettesView.as_view(), name='etiquettes'),
    path('drivers/',            DriversView.as_view(), name='drivers'),

    # ── MOP ────────────────────────────────────────────────────────────────
    path('mop/update',  mop_update),
    path('mop/update/', mop_update, name='mop_update'),
]
