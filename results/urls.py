from django.urls import path
from .views import (IndexView, ShowCategories, DisplayCategory,
                    DisplayRunDetails, TutoView, MarkdownView, test1, test2,
                    test3, update_database)

app_name = 'results'
urlpatterns = [
    path('', IndexView.as_view(), name='home'),
    path('update/', update_database, name='update_database'),
    path('<int:comp_id>/', ShowCategories, name='category'),
    path('<int:comp_id>/<int:cls_id>/', DisplayCategory, name='catDet'),
    path('<int:comp_id>/<int:cls_id>/<int:run_id>/', DisplayRunDetails,
         name='run'),
    path('tuto/', TutoView.as_view(), name='tuto'),
    path('tuto/<int:article_id>/', MarkdownView, name='markdown'),

    path('test1/', test1, name='test1'),
    path('test2/', test2, name='test2'),
    path('test3/', test3, name='test3'),
]
