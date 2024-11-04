from django.urls import path
from . import views
#urls for the page pathways
urlpatterns = [
    path('set_theme/<str:theme>/', views.set_theme, name='set_theme'),
    path('', views.home_view, name='home'),
    path('home/', views.home_view, name='home'),
    path('login/', views.login_view, name='login'),
    path('signup/', views.signup, name='signup'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('profile/', views.profile_view, name='profile'),
    path('logout/', views.logout_view, name='logout'),
    path('wraps/', views.wraps_view, name='wraps'),
    path('delete_account/', views.delete_account_view, name='delete_account'),
    path('profile/', views.profile_view, name='profile'),
]
