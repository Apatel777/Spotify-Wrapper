

import logging
import os
import random
import secrets
import requests
import json


import spotipy
import secrets


from django.conf import settings
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import make_password
from django.http import HttpResponseRedirect, HttpResponse, JsonResponse
from urllib.parse import urlencode
from .models import *

import spotipy
from spotipy.oauth2 import SpotifyOAuth
from datetime import datetime
from django.utils import timezone
from django.contrib import messages
from django.db import IntegrityError
from django.db import transaction  # Added for atomic transactions
from django.core.exceptions import ValidationError  # Added for validation errors
from django.core.cache import cache
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_protect
from django.views.decorators.http import require_http_methods

logger = logging.getLogger(__name__)

def home_view(request):
    return render(request, 'home/home.html', {})

def signup(request):
    """
    Handle user signup with Spotify OAuth verification.
    Flow:
    1. User fills out signup form
    2. Validate form data
    3. Store data in session
    4. Redirect to Spotify OAuth
    5. Verify Spotify auth in callback
    6. Create user account if authorized
    """
    theme = request.session.get('theme', 'light')
    if request.user.is_authenticated:
        logger.info("User already authenticated, redirecting to dashboard")
        return redirect('dashboard')

    if request.method == 'POST':
        logger.info("Processing signup form submission")

        # Basic form validation
        required_fields = ['username', 'email', 'password']
        if not all(field in request.POST for field in required_fields):
            logger.warning("Missing required signup fields")
            messages.error(request, "All fields are required")
            return render(request, 'home/signup.html', {'error': 'All fields are required'})

        # Store signup data securely in session
        signup_data = {
            'username': request.POST['username'],
            'email': request.POST['email'],
            'password': request.POST['password'],
        }

        # Validate unique constraints
        if User.objects.filter(username=signup_data['username']).exists():
            logger.warning(f"Username {signup_data['username']} already exists")
            messages.error(request, "Username already exists")
            return render(request, 'home/signup.html', {'error': 'Username already exists'})

        if User.objects.filter(email=signup_data['email']).exists():
            logger.warning(f"Email {signup_data['email']} already exists")
            messages.error(request, "Email already exists")
            return render(request, 'home/signup.html', {'error': 'Email already exists'})

        # Store data securely in session
        request.session['signup_data'] = signup_data

        # Generate and store OAuth state for CSRF protection
        state = secrets.token_urlsafe(32)
        request.session['oauth_state'] = state

        # Set session expiry for security
        request.session.set_expiry(300)  # 5 minutes

        logger.info(f"Redirecting user to Spotify OAuth. State: {state}")
        return HttpResponseRedirect(create_spotify_auth_url(state))

    return render(request, 'home/signup.html', {'theme': theme})


def login_view(request):
    """Handle login for predefined users"""
    theme = request.session.get('theme', 'light')
    print(f"Current theme: {theme}")

    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']
        print(f"Login attempt with username: {username}")

        user = authenticate(request, username=username, password=password)
        if user is not None and user.is_active:
            print(f"User {username} authenticated successfully")
            login(request, user)

            if not user.spotify_id:
                print("User has no Spotify account linked, redirecting to OAuth")
                state = secrets.token_urlsafe(32)
                request.session['oauth_state'] = state
                return HttpResponseRedirect(create_spotify_auth_url(state))

            print("User logged in and redirected to dashboard")
            return redirect('dashboard')
        else:
            print(f"Login failed for username: {username}")
            return render(request, 'home/login.html', {'theme': theme, 'error': 'Invalid credentials'})

    return render(request, 'home/login.html', {'theme': theme})


def create_spotify_auth_url(state=None):
    """Create Spotify authorization URL forcing login dialog"""
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

    return "https://accounts.spotify.com/authorize?" + urlencode(params)


def spotify_callback(request):
    """
    Handle Spotify OAuth callback and user account creation.
    Verifies OAuth state, creates user account, and links Spotify.
    """
    code = request.GET.get('code')
    state = request.GET.get('state')
    stored_state = request.session.get('oauth_state')
    signup_data = request.session.get('signup_data')

    logger.info("Processing Spotify OAuth callback")

    # Verify OAuth state for security
    if not state or state != stored_state:
        logger.error("Invalid OAuth state in callback")
        messages.error(request, "Invalid authentication state. Please try again.")
        return redirect('signup')

    if not code:
        logger.error("Missing authorization code in callback")
        messages.error(request, "Authentication failed. Please try again.")
        return redirect('signup')

    if not signup_data:
        logger.error("Missing signup data in session")
        messages.error(request, "Signup session expired. Please try again.")
        return redirect('signup')

    try:
        # Initialize Spotify OAuth
        sp_oauth = SpotifyOAuth(
            client_id=settings.SPOTIFY_CLIENT_ID,
            client_secret=settings.SPOTIFY_CLIENT_SECRET,
            redirect_uri=settings.SPOTIFY_REDIRECT_URI,
            scope="user-read-private user-read-email user-top-read user-read-recently-played",
            show_dialog = True
        )

        # Clear any cached tokens
        cache_path = sp_oauth.cache_handler.cache_path
        if os.path.exists(cache_path):
            os.remove(cache_path)

        # Get token info
        token_info = sp_oauth.get_access_token(code)
        if not token_info:
            logger.error("Failed to get Spotify access token")
            messages.error(request, "Failed to connect with Spotify. Please try again.")
            return redirect('signup')

        # Get Spotify user info
        sp = spotipy.Spotify(auth=token_info['access_token'])
        spotify_user = sp.current_user()
        spotify_id = spotify_user['id']

        print("Full user object:")
        import json
        print(json.dumps(spotify_user, indent=2))

        # Also try getting playlists to verify the account
        playlists = sp.current_user_playlists()
        print("\nPlaylists:")
        for playlist in playlists['items']:
            print(f"- {playlist['name']}")

        # Check if Spotify account is already linked
        if User.objects.filter(spotify_id=spotify_id).exists():
            logger.error(f"Spotify account {spotify_id} already linked to another user")
            messages.error(request, "This Spotify account is already linked to another user.")
            return redirect('signup')

        # Create new user account with transaction
        try:
            with transaction.atomic():
                # Create user account
                user = User.objects.create_user(
                    username=signup_data['username'],
                    email=signup_data['email'],
                    password=signup_data['password']
                )

                # Link Spotify account
                success = user.set_spotify_id(spotify_id)
                if not success:
                    raise ValidationError("Failed to link Spotify account")

                # Set Spotify tokens
                success = user.set_spotify_tokens(
                    token_info['access_token'],
                    token_info['refresh_token'],
                    token_info['expires_in']
                )
                if not success:
                    raise ValidationError("Failed to store Spotify tokens")

                # Clean up session
                request.session.pop('signup_data', None)
                request.session.pop('oauth_state', None)

                # Log user in
                login(request, user)

                logger.info(f"User account created successfully: {user.username}")
                messages.success(request, "Account created successfully!")
                return redirect('dashboard')

        except Exception as e:
            logger.error(f"Failed to create user account: {str(e)}")
            messages.error(request, "Failed to create account. Please try again.")
            return redirect('signup')

    except Exception as e:
        logger.error(f"Error during Spotify callback: {str(e)}")
        messages.error(request, "An error occurred. Please try again.")
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
            'lang': request.LANGUAGE_CODE,
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
    else:
        game_type = "Unknown Game"

    context = {
        'theme': theme,
        'top_tracks': request.session.get('top_tracks', {}),
        'top_artists': request.session.get('top_artists', {}),
        'top_albums': request.session.get('top_albums', {}),
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


@login_required
def wraps_view(request):
    theme = request.session.get('theme', 'light')
    user = request.user

    # Retrieve all SpotifyData entries for the user, sorted by creation date
    wraps = []
    data_entries = SpotifyData.objects.filter(
        user=user
    ).prefetch_related('tracks', 'artists', 'albums').order_by('-created_at')

    for entry in data_entries:
        wrap_data = {
            'type': dict(SpotifyData.WRAPPER_TYPES).get(entry.wrapper_type, entry.wrapper_type),
            'created_at': entry.created_at,  # Add creation date
        }

        if entry.wrapper_type.startswith('TOP_TRACKS') or entry.wrapper_type == 'RECENTLY_PLAYED':
            wrap_data['tracks'] = list(entry.tracks.all())

        if entry.wrapper_type == 'TOP_ARTISTS':
            wrap_data['artists'] = list(entry.artists.all())

        if entry.wrapper_type == 'TOP_ALBUM':
            wrap_data['albums'] = list(entry.albums.all())

        wraps.append(wrap_data)

    return render(request, 'users/wraps.html', {'wraps': wraps, 'theme': theme, 'lang': request.LANGUAGE_CODE})

@login_required
def delete_account_view(request):
    theme = request.session.get('theme', 'light')  # Default to light mode
    if request.method == 'POST':
        SpotifyData.objects.filter(user=request.user).delete()
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
        print(request.POST.get('language', settings.LANGUAGE_CODE))
        user_language = request.POST.get('language', settings.LANGUAGE_CODE)
        if user_language in dict(settings.LANGUAGES):
            print("Good language")
            translation.activate(user_language)
            request.session['django_language'] = user_language
            return HttpResponseRedirect(f'/{user_language}/profile/')
        else:
            print("Bad language")
    else:
        print("No POST")
    return HttpResponseRedirect(request.META.get('HTTP_REFERER', '/'))

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

def refresh_spotify_token(user):
    """
    Refresh the Spotify access token for a user.
    Returns the new access token if successful, None if failed.
    """
    try:
        sp_oauth = spotipy.SpotifyOAuth(
            client_id=settings.SPOTIFY_CLIENT_ID,
            client_secret=settings.SPOTIFY_CLIENT_SECRET,
            redirect_uri=settings.SPOTIFY_REDIRECT_URI,
            scope= "user-read-private user-read-email user-top-read user-read-recently-played"
        )

        token_info = sp_oauth.refresh_access_token(user.spotify_refresh_token)

        # Update user's token information
        success = user.set_spotify_tokens(
            access_token=token_info['access_token'],
            refresh_token=token_info.get('refresh_token', user.spotify_refresh_token),
            expires_in=token_info['expires_in']
        )

        return token_info['access_token'] if success else None

    except Exception as e:
        logger.error(f"Error refreshing token for user {user.id}: {str(e)}")
        return None

@login_required
@ensure_csrf_cookie
@require_http_methods(["POST"])
@csrf_protect
def handle_spotify_data(request):
    try:
        data = json.loads(request.body)
        wrapper_type = data.get('wrapper_type')
        action = data.get('action')
        logger.info(f"Received wrapper_type: {wrapper_type} with action {action}")
        print(wrapper_type)

        if not wrapper_type:
            return JsonResponse({'error': 'Wrapper type is required'}, status=400)

        user = request.user
        logger.info(f"Received user: {user}")

        # Check if token needs refresh, similar to dashboard view
        if user.spotify_token_expires and timezone.now() >= user.spotify_token_expires:
            access_token = refresh_spotify_token(user)
            if not access_token:
                return JsonResponse({'error': 'Failed to refresh Spotify token'}, status=401)
        else:
            access_token = user.spotify_access_token

        if not access_token:
            return JsonResponse({'error': 'No valid Spotify token found'}, status=401)

        sp = spotipy.Spotify(auth=access_token)

        if action == "saved":
            # Save the data using the helper function from models.py
            spotify_data = save_spotify_wrapper(
                user=user,
                sp=sp,
                wrapper_type=wrapper_type
            )
        else:
            created_at_str = data.get('created_at')
            try:
                created_at = datetime.fromisoformat(created_at_str)  # Convert the string to datetime
            except ValueError:
                return JsonResponse({'error': 'Invalid date format for created_at'}, status=400)

            spotify_data = delete_spotify_wrapper(
                user=user,
                wrapper_type=wrapper_type,
                created_at=created_at
            )

        logger.info(f"{action} Spotify data: {spotify_data.id}, Type: {wrapper_type}")

        return JsonResponse({
            'message': f'Successfully {action} {wrapper_type} data',
            'data_id': spotify_data.id
        })

    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON data'}, status=400)
    except Exception as e:
        logger.error(f"Error saving/deleting Spotify data: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)