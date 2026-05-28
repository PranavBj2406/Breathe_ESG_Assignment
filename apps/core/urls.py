from django.urls import path
from apps.core.views import quick_setup

urlpatterns = [
    path("", quick_setup, name="quick-setup"),
]