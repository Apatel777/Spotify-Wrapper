import random
import spotipy
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.http import HttpResponseRedirect, HttpResponse
from urllib.parse import urlencode
from .models import User
from spotipy.oauth2 import SpotifyOAuth
import requests
from django.utils import timezone
from django.contrib import messages
from django.db import IntegrityError

def home_view(request):
    return render(request, 'home/home.html', {})


def signup(request):
    """Handle user signup and Spotify OAuth initiation"""
    if request.user.is_authenticated:
        return redirect('dashboard')

    theme = request.session.get('theme', 'light')

    if request.method == 'POST':
        print(f"Starting signup process for username: {request.POST.get('username')}")

        # Store new signup data
        request.session['signup_data'] = {
            'username': request.POST['username'],
            'email': request.POST['email'],
            'password': request.POST['password'],
        }

        # Validation checks with early return
        if User.objects.filter(username=request.POST['username']).exists():
            messages.error(request, 'Username already exists')
            return render(request, 'home/signup.html', {'error': 'Username already exists', 'theme': theme})
        if User.objects.filter(username=request.POST['email']).exists():
            messages.error(request, 'Email already exists')
            return render(request, 'home/signup.html', {'error': 'Email already exists', 'theme': theme})

        # Generate new state parameter
        import secrets
        state = secrets.token_urlsafe(32)
        request.session['oauth_state'] = state

        # Redirect to Spotify OAuth
        print("Redirecting to Spotify OAuth URL: ...")
        return HttpResponseRedirect(create_spotify_auth_url(state))

    return render(request, 'home/signup.html', {'theme': theme})


def login_view(request):
    theme = request.session.get('theme', 'light')

    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']

        # Authenticate the user
        user = authenticate(request, username=username, password=password)

        if user is not None:
            # Log the user in
            login(request, user)

            # Redirect to Spotify OAuth for linkage if not done yet
            if not user.email:  # Assuming email is set via Spotify OAuth
                return HttpResponseRedirect(create_spotify_auth_url())

            # Redirect to the dashboard after successful login
            return redirect('dashboard')
        else:
            return render(request, 'home/login.html', {'theme': theme, 'error': 'Invalid username or password'})

    return render(request, 'home/login.html', {'theme': theme})

def create_spotify_auth_url(state=None):
    """Create Spotify authorization URL with state parameter and force_dialog=true"""
    params = {
        "response_type": "code",
        "client_id": settings.SPOTIFY_CLIENT_ID,
        "redirect_uri": settings.SPOTIFY_REDIRECT_URI,
        "scope": "user-read-private user-read-email user-top-read user-read-recently-played",
        "show_dialog": 'true',  # Force showing the Spotify login dialog
        "force_dialog": 'true'  # Additional parameter to force new login
    }
    if state:
        params["state"] = state

    auth_url = "https://accounts.spotify.com/authorize?" + urlencode(params)
    print(f"Generated Spotify auth URL with parameters: {params}")
    return auth_url

def refresh_spotify_token(user):
    """Helper function to refresh expired Spotify token"""
    sp_oauth = SpotifyOAuth(
        client_id=settings.SPOTIFY_CLIENT_ID,
        client_secret=settings.SPOTIFY_CLIENT_SECRET,
        redirect_uri=settings.SPOTIFY_REDIRECT_URI,
        scope="user-read-private user-read-email user-top-read user-read-recently-played"
    )

    try:
        token_info = sp_oauth.refresh_access_token(user.spotify_refresh_token)
        user.spotify_access_token = token_info['access_token']
        user.spotify_refresh_token = token_info.get('refresh_token', user.spotify_refresh_token)
        user.spotify_token_expires = timezone.now() + timezone.timedelta(seconds=token_info['expires_in'])
        user.save(update_fields=['spotify_access_token', 'spotify_refresh_token', 'spotify_token_expires'])
        return token_info['access_token']
    except Exception as e:
        print(f"Error refreshing token: {e}")
        return None


def spotify_callback(request):
    """Handle Spotify OAuth callback and create user"""
    code = request.GET.get('code')
    state = request.GET.get('state')
    stored_state = request.session.get('oauth_state')
    signup_data = request.session.get('signup_data')

    # Verify state parameter to prevent CSRF
    if not state or state != stored_state:
        messages.error(request, 'Invalid OAuth state')
        return redirect('signup')

    if not code or not signup_data:
        messages.error(request, 'Missing required data')
        return redirect('signup')

    try:
        # Initialize Spotify OAuth
        sp_oauth = SpotifyOAuth(
            client_id=settings.SPOTIFY_CLIENT_ID,
            client_secret=settings.SPOTIFY_CLIENT_SECRET,
            redirect_uri=settings.SPOTIFY_REDIRECT_URI,
            scope="user-read-private user-read-email user-top-read user-read-recently-played"
        )

        # Get token info
        token_info = sp_oauth.get_access_token(code)

        # Get Spotify user info
        sp = spotipy.Spotify(auth=token_info['access_token'])
        spotify_user = sp.current_user()
        spotify_id = spotify_user['id']

        # Check if Spotify account is already linked
        if User.objects.filter(spotify_id=spotify_id).exists():
            messages.error(request, 'This Spotify account is already linked to another user')
            return redirect('signup')

        # Create new user
        user = User.objects.create_user(
            username=signup_data['username'],
            email=signup_data['email'],
            password=signup_data['password'],
            spotify_id=spotify_id
        )

        # Set Spotify tokens
        user.spotify_access_token = token_info['access_token']
        user.spotify_refresh_token = token_info['refresh_token']
        user.spotify_token_expires = timezone.now() + timezone.timedelta(seconds=token_info['expires_in'])
        user.save()

        # Clean up session data
        request.session.pop('signup_data', None)
        request.session.pop('oauth_state', None)

        # Log the user in
        login(request, user)
        messages.success(request, 'Successfully created account and connected to Spotify!')

        return redirect('dashboard')

    except Exception as e:
        messages.error(request, f'Error during signup: {str(e)}')
        return redirect('signup')

@login_required
def dashboard(request):
    user = request.user

    # Check if token needs refresh
    if user.spotify_token_expires and timezone.now() >= user.spotify_token_expires:
        new_token = refresh_spotify_token(user)
        if not new_token:
            messages.error(request, "Error refreshing Spotify connection. Please try logging in again.")
            return redirect('logout')
        access_token = new_token
    else:
        access_token = user.spotify_access_token

    try:
        sp = spotipy.Spotify(auth=access_token)
        recent_tracks = sp.current_user_recently_played(limit=50)['items']
        top_tracks = {
            'short_term': sp.current_user_top_tracks(limit=10, time_range='short_term')['items'],
            'medium_term': sp.current_user_top_tracks(limit=10, time_range='medium_term')['items'],
            'long_term': sp.current_user_top_tracks(limit=10, time_range='long_term')['items'],
        }
        top_artists = {
            'short_term': sp.current_user_top_artists(limit=10, time_range='short_term')['items'],
            'medium_term': sp.current_user_top_artists(limit=10, time_range='medium_term')['items'],
            'long_term': sp.current_user_top_artists(limit=10, time_range='long_term')['items'],
        }

        # Combine all top tracks from different time ranges
        all_top_tracks = top_tracks['short_term'] + top_tracks['medium_term'] + top_tracks['long_term']

        # Extract album names from top tracks
        top_albums = [track['album']['name'] for track in all_top_tracks]

        # Count the most frequent albums
        from collections import Counter
        album_counts = Counter(top_albums)

        # Get the most listened-to album
        most_listened_album = album_counts.most_common(1)

        request.session['top_tracks'] = top_tracks
        request.session['top_artists'] = top_artists

        context = {
            'user': user,
            'theme': request.session.get('theme', 'light'),
            'spotify_connected': True,
            'recent_tracks': recent_tracks,
            'top_tracks': top_tracks,
            'top_artists': top_artists,
            'most_listened_album': most_listened_album[0][0] if most_listened_album else None
            # Pass most listened album
        }
        # Optionally, if you want to pass album details (name, artist, cover image)
        if most_listened_album:
            # You can fetch the album details from Spotify using the album ID
            album_name = most_listened_album[0][0]
            album = sp.search(q='album:' + album_name, type='album', limit=1)
            if album['albums']['items']:
                album_info = album['albums']['items'][0]
                album_details = {
                    'name': album_info['name'],
                    'artist': album_info['artists'][0]['name'],
                    'image_url': album_info['images'][0]['url'] if album_info['images'] else None,
                }
                context['most_listened_album_details'] = album_details
                request.session['top_albums'] = album_details

        return render(request, 'registered/dashboard2.html', context)

    except Exception as e:
        messages.error(request, f"Error fetching Spotify data: {str(e)}")
        return render(request, 'registered/dashboard2.html', {
            'user': user,
            'theme': request.session.get('theme', 'light'),
            'spotify_connected': False
        })

def games_view(request):
    theme = request.session.get('theme', 'light')  # Default to light mode
    selected_game = request.GET.get('game')  # Retrieve the selected game

    if selected_game == "0":
        game_type = "Guess Top Track"
    elif selected_game == "1":
        game_type = "Guess Top Album"
    elif selected_game == "2":
        game_type = "Guess Artist"
    elif selected_game == "3":
        game_type = "Guess Clip"
    else:
        game_type = "Unknown Game"

    top_tracks_clip = []
    try:
        # Get top tracks from session with fallback to empty dict
        top_tracks = request.session.get('top_tracks', {})

        # Get short term tracks with fallback to empty list
        short_term_tracks = top_tracks.get('short_term', [])

        # List comprehension is more efficient than appending in a loop
        top_tracks_clip = [
            track for track in short_term_tracks
            if track and isinstance(track, dict) and track.get('preview_url')
        ]
    except Exception as e:
        top_tracks_clip = []

    top_tracks = random.choice(request.session.get('top_tracks', {})['short_term'])
    top_artists = random.choice(request.session.get('top_artists', {})['short_term'])
    top_tracks_clip = random.choice(top_tracks_clip)


    context = {
        'theme': theme,
        'top_tracks': top_tracks,
        'top_artists': top_artists,
        'top_albums': request.session.get('top_albums', {}),
        'top_tracks_clip': top_tracks_clip,
        'game_type': game_type,
    }
    return render(request, 'users/games.html', context)

def profile_view(request):
    theme = request.session.get('theme', 'light')  # Default to light mode
    if request.method == 'POST':
        if 'delete_account' in request.POST:
            request.user.delete()
            return redirect('home')
        # add in whatever other stuff the profile view will have

    return render(request, 'users/profile2.html', {'form': [], 'theme': theme})


def contact_view(request):
    theme = request.session.get('theme', 'light')  # Default to light mode
    if request.method == 'POST':
        # Extract data from the form
        name = request.POST.get('name')
        subject = request.POST.get('subject')
        message = request.POST.get('message')

        import urllib.parse

        name = urllib.parse.quote(name)  # Encode the name to handle special characters like spaces
        subject = urllib.parse.quote(subject)
        message = urllib.parse.quote(message)

        # Construct the pre-filled Google Form URL
        google_form_url = f'https://docs.google.com/forms/d/e/1FAIpQLSecVvMgS6_UKQNTcaEOZr55KLL5mHBa2sJfsk-A4skYfKRlxA/viewform?usp=pp_url&entry.1434750794={name}&entry.1846469222={subject}&entry.1381661191={message}'
        # You can either redirect to the google form or return the URL as context
        messages.success(request, 'Your message has been sent successfully!')

        return HttpResponseRedirect(google_form_url)

    return render(request, 'users/contact.html', {'form': [], 'theme': theme})


def logout_view(request):
    logout(request)
    return redirect('home')  # Redirect to home after logout

def wraps_view(request):
    theme = request.session.get('theme', 'light')  # Default to light mode
    # Fetch wraps associated with the user
    wraps = []  # Replace with actual query to fetch wraps
    return render(request, 'users/wraps.html', {'wraps': wraps, 'theme': theme})

@login_required
def delete_account_view(request):
    theme = request.session.get('theme', 'light')  # Default to light mode
    if request.method == 'POST':
        request.user.delete()
        return redirect('home')
    return render(request, 'users/delete_account.html', {'theme': theme})


def set_theme(request, theme):
    if theme in ['light', 'dark', 'color']:
        request.session['theme'] = theme
    return redirect(request.META.get('HTTP_REFERER', '/'))  # Redirect back to the page

from django.utils import translation
def set_language(request):
    if request.method == 'POST':
        print('Language Code:', request.POST.get('language', settings.LANGUAGE_CODE))
        user_language = request.POST.get('language', settings.LANGUAGE_CODE)
        if user_language in dict(settings.LANGUAGES):
            translation.activate(user_language)
            request.session['django_language'] = user_language
            return HttpResponseRedirect(f'/{user_language}/profile/')
    else:
        print("No POST")
    return HttpResponseRedirect(request.META.get('HTTP_REFERER', '/'))

from django.core.cache import cache
from django.conf import settings


def analyze_music_taste(request):
    theme = request.session.get('theme', 'light')

    # Safely get top_tracks from session
    all_top_tracks = request.session.get('top_tracks', {})
    if not all_top_tracks or 'short_term' not in all_top_tracks:
        return render(request, 'users/analysis.html', {
            'theme': theme,
            'error': 'No tracks found. Please connect to Spotify first.'
        })

    top_tracks = all_top_tracks['short_term'][:5]

    try:
        import google.generativeai as genai

        # Create cache key from track IDs
        cache_key = f"music_analysis_{'_'.join([t.get('id', '') for t in top_tracks])}"

        # Check cache first
        cached_analysis = cache.get(cache_key)
        if cached_analysis:
            return render(request, 'users/analysis.html', {
                'theme': theme,
                'top_tracks': top_tracks,
                'analysis': cached_analysis
            })

        # Format track data
        track_info = []
        for track in top_tracks:
            artists = ", ".join([artist['name'] for artist in track['artists']])
            track_info.append(f"{track['name']} by {artists}")

        tracks_text = "\n".join(track_info)

        # Configure Gemini
        genai.configure(api_key=settings.CLOUD_API_KEY)
        model = genai.GenerativeModel('gemini-pro')

        prompt = """Based on these songs:
{}

Generate a fun 3-paragraph personality analysis about someone who likes these songs.
Paragraph 1: Their likely personality traits and how they might think
Paragraph 2: Their potential style and fashion preferences
Paragraph 3: Their probable hobbies and interests

Keep it positive and playful, focusing on the overall vibe rather than specific songs.""".format(tracks_text)

        # Generate analysis
        response = model.generate_content(prompt)
        analysis = response.text

        # Cache successful analysis
        if analysis:
            cache.set(cache_key, analysis, 60 * 60 * 24)  # 24 hours

        return render(request, 'users/analysis.html', {
            'theme': theme,
            'top_tracks': top_tracks,
            'analysis': analysis
        })

    except Exception as e:
        print(f"Analysis generation error: {str(e)}")  # For debugging
        return render(request, 'users/analysis.html', {
            'theme': theme,
            'top_tracks': top_tracks,
            'error': 'Unable to generate analysis at this time. Please try again later.'
        })