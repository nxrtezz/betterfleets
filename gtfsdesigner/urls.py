from django.urls import path
from . import views

app_name = 'gtfsdesigner'

urlpatterns = [
    path('', views.index, name='index'),
    path('project/<int:project_id>/', views.project_detail, name='project_detail'),
    path('project/create/', views.create_project, name='create_project'),
    path('project/<int:project_id>/operator/create/', views.create_operator, name='create_operator'),
    path('project/<int:project_id>/route/create/', views.create_route, name='create_route'),
    path('project/<int:project_id>/stops/select/', views.select_stops, name='select_stops'),
    path('project/<int:project_id>/stops/save/', views.save_stops, name='save_stops'),
    path('project/<int:project_id>/calendar/create/', views.create_calendar, name='create_calendar'),
    path('project/<int:project_id>/timetable/', views.timetable_builder, name='timetable_builder'),
    path('project/<int:project_id>/timetable/save/', views.save_timetable, name='save_timetable'),
    path('project/<int:project_id>/export/', views.export_gtfs, name='export_gtfs'),
    path('api/stops/search/', views.search_stops, name='api_search_stops'),
    path('api/stops/create/', views.create_stop, name='api_create_stop'),
]
