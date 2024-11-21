from django.http import HttpResponse
from django.urls import path
from . import views

def favicon(request):
    return HttpResponse(status=204)
#urls for the page pathways
urlpatterns = [
    path('favicon.ico', favicon),
    path('set_theme/<str:theme>/', views.set_theme, name='set_theme'),
    path('set_language/', views.set_language, name='set_language'),

    path('', views.home_view, name='home'),
    path('home/', views.home_view, name='home'),
    path('login/', views.login_view, name='login'),
    path('signup/', views.signup, name='signup'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('spotify/callback/', views.spotify_callback, name='spotify_callback'),  # Add this line

    path('profile/', views.profile_view, name='profile'),
    path('logout/', views.logout_view, name='logout'),
    path('wraps/', views.wraps_view, name='wraps'),
    path('delete_account/', views.delete_account_view, name='delete_account'),
    path('profile/', views.profile_view, name='profile'),
    path('contact/', views.contact_view, name='contact'),
    path('games/', views.games_view, name='games'),
    path('analysis/', views.analyze_music_taste, name='analysis'),
    path('handle-spotify-data/', views.handle_spotify_data, name='handle-spotify-data'),
]