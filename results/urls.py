from django.urls import path
from . import views
from .classViews import TutoView
from .mop_views import mop_update

app_name = 'results'

urlpatterns = [
    # ── Accueil ────────────────────────────────────────────────────────────
    path('', views.home, name='home'),

    # ── Compétition ────────────────────────────────────────────────────────
    path('competition/<int:cid>/', views.competition_detail, name='competition_detail'),
    path('competition/<int:cid>/stats/', views.statistics, name='statistics'),

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

    # ── Concurrent / Organisation ──────────────────────────────────────────
    path('competition/<int:cid>/competitor/<int:competitor_id>/', views.competitor_detail, name='competitor_detail'),
    path('competition/<int:cid>/org/<int:org_id>/',               views.org_results,       name='org_results'),

    # ── API ────────────────────────────────────────────────────────────────
    path('api/<int:cid>/class/<str:class_id>/results/', views.api_class_results, name='api_class_results'),

    # ── GEC ───────────────────────────────────────────────────────────────
    path('gec/checker/',    views.meos_checker_view, name='meos_checker'),
    path('gec/verifie-moi/', views.verifie_moi_view, name='verifie_moi'),

    # ── Tutoriels / Ressources ─────────────────────────────────────────────
    path('tuto/',               TutoView.as_view(), name='tuto'),
    path('tuto/<int:article_id>/', views.MarkdownView, name='markdown'),
    path('etiquettes/',         views.etiquettes,   name='etiquettes'),
    path('drivers/',            views.drivers,      name='drivers'),

    # ── MOP ────────────────────────────────────────────────────────────────
    path('mop/update',  mop_update),
    path('mop/update/', mop_update, name='mop_update'),
]
