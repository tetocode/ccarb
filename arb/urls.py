from django.conf.urls import url

from . import views

urlpatterns = [
    url(r'^get/(?P<currency>[A-Za-z]+)/$', views.get, name='get'),
    url(r'^$', views.main, name='main'),
    #    url(r'^(?P<currency>[A-Za-z]+)/$', views.main, name='main'),
    url(r'^config/(?P<currency>[A-Za-z]+)/$', views.config, name='config'),
]
