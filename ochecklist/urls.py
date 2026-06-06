from django.urls import path
from . import views

urlpatterns = [
    path('update/', views.ochecklist_update, name='ochecklist_update'),
    path('', views.report_list, name='ochecklist_report_list'),
    path('clear/', views.clear_reports, name='ochecklist_clear_reports'),
    path('<int:report_id>/', views.report_detail, name='ochecklist_report_detail'),
    path('runner/<int:runner_id>/', views.runner_detail, name='ochecklist_runner_detail'),
]