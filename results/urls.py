from django.urls import path
from . import views
from .classViews import TutoView
from .mop_views import mop_update

app_name = 'results'

urlpatterns = [
    path('', views.home, name='home'),
    path('competition/<int:cid>/', views.competition_detail, name='competition_detail'),
    path('competition/<int:cid>/class/<int:class_id>/', views.class_results, name='class_results'),
    path('competition/<int:cid>/competitor/<int:competitor_id>/', views.competitor_detail, name='competitor_detail'),
    path('competition/<int:cid>/org/<int:org_id>/', views.org_results, name='org_results'),
    path('competition/<int:cid>/stats/', views.statistics, name='statistics'),
    path('api/<int:cid>/class/<int:class_id>/results/', views.api_class_results, name='api_class_results'),
    path('competition/<int:cid>/class/<int:class_id>/grouping/', views.grouping_analysis, name='grouping'),
    path('competition/<int:cid>/class/<int:class_id>/grouping-index/', views.grouping_index_analysis, name='grouping_index'),
    path('competition/<int:cid>/class/<int:class_id>/performance/', views.performance_analysis, name='performance'),
    path('competition/<int:cid>/class/<int:class_id>/regularity/', views.regularity_analysis, name='regularity'),
    path('competition/<int:cid>/class/<int:class_id>/superman/', views.superman_analysis, name='superman'),
    path('competition/<int:cid>/class/<int:class_id>/duel/', views.duel_analysis, name='duel'),
    path('competition/<int:cid>/class/<int:class_id>/relay/', views.relay_results, name='relay_results'),
    path('gec/checker/', views.meos_checker_view, name='meos_checker'),
    path('tuto/', TutoView.as_view(), name='tuto'),
    path('tuto/<int:article_id>/', views.MarkdownView, name='markdown'),
    path('etiquettes/', views.etiquettes, name='etiquettes'),
    path('drivers/', views.drivers, name='drivers'),
    path('mop/update/', mop_update, name='mop_update'),
]
