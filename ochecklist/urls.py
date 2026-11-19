from django.urls import path
from . import views

urlpatterns = [
    # L'application Android peut être configurée avec ou sans slash final.
    # APPEND_SLASH=False : sans cette seconde route, /ochecklist/update
    # renverrait 404 (et non une redirection qui perdrait le corps POST).
    path('update', views.ochecklist_update),
    path('update/', views.ochecklist_update, name='ochecklist_update'),
    path('', views.report_list, name='ochecklist_report_list'),
    path('clear/', views.clear_reports, name='ochecklist_clear_reports'),
    path('<int:report_id>/', views.report_detail, name='ochecklist_report_detail'),
    path('runner/<int:runner_id>/', views.runner_detail, name='ochecklist_runner_detail'),
]