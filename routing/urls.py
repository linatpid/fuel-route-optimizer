from django.urls import path

from routing import views

urlpatterns = [
    path("api/route", views.route_view, name="route"),
    path("map", views.map_view, name="map"),
    path("demo", views.demo_reset, name="demo"),
]
