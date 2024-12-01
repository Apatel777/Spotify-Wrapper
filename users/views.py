import logging
import os
import random
import secrets
import requests
import json

from django.conf import settings
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import make_password
from django.http import HttpResponseRedirect, HttpResponse, JsonResponse
from urllib.parse import urlencode
from .models import *
from collections import Counter

from datetime import datetime
from django.utils import timezone
from django.contrib import messages
from django.db import IntegrityError
from django.db import transaction  # Added for atomic transactions
from django.core.exceptions import ValidationError  # Added for validation errors
from django.core.cache import cache
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_protect, csrf_exempt
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
        # Exchange authorization code for access token
        token_response = requests.post(
            'https://accounts.spotify.com/api/token',
            data={
                'grant_type': 'authorization_code',
                'code': code,
                'redirect_uri': settings.SPOTIFY_REDIRECT_URI,
                'client_id': settings.SPOTIFY_CLIENT_ID,
                'client_secret': settings.SPOTIFY_CLIENT_SECRET
            },
            headers={'Content-Type': 'application/x-www-form-urlencoded'}
        )

        if token_response.status_code != 200:
            logger.error("Failed to get Spotify access token")
            messages.error(request, "Failed to connect with Spotify. Please try again.")
            return redirect('signup')

        token_data = token_response.json()
        access_token = token_data['access_token']

        # Get Spotify user info
        user_response = requests.get(
            'https://api.spotify.com/v1/me',
            headers={'Authorization': f'Bearer {access_token}'}
        )

        if user_response.status_code != 200:
            logger.error(f"Failed to retrieve Spotify user info {user_response.status_code} - {user_response.text}")
            messages.error(request, "Failed to retrieve user information. Please try again.")
            return redirect('signup')

        spotify_user = user_response.json()
        spotify_id = spotify_user['id']

        # Optional: Get playlists for verification
        playlists_response = requests.get(
            'https://api.spotify.com/v1/me/playlists',
            headers={'Authorization': f'Bearer {access_token}'}
        )
        playlists = playlists_response.json() if playlists_response.status_code == 200 else []

        # Debugging/logging
        print("Full user object:")
        print(json.dumps(spotify_user, indent=2))
        print("\nPlaylists:")
        for playlist in playlists.get('items', []):
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
                    access_token,
                    token_data.get('refresh_token'),
                    token_data.get('expires_in', 3600)
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
        access_token = refresh_spotify_token(user)
        if not access_token:
            messages.error(request, "Error refreshing Spotify connection. Please log in again.")
            return redirect('logout')
    else:
        access_token = user.spotify_access_token

    try:
        headers = {'Authorization': f'Bearer {access_token}'}
        base_url = 'https://api.spotify.com/v1'
        # Fetch recently played tracks
        recent_tracks_response = requests.get(
            f'{base_url}/me/player/recently-played',
            headers=headers,
            params={'limit': 50}
        )
        recent_tracks = recent_tracks_response.json().get(
            'items', []
        ) if recent_tracks_response.status_code == 200 else []

        # Fetch the user's playlists
        playlist_response = requests.get(
            f'{base_url}/me/playlists',
            headers=headers,
        )
        top_playlists = playlist_response.json().get(
            'items', []
        ) if playlist_response.status_code == 200 else []

        # Add duration to each playlist and retain other information
        for playlist in top_playlists:
            playlist_id = playlist['id']
            # Fetch tracks for each playlist
            playlist_duration_response = requests.get(
                f'{base_url}/playlists/{playlist_id}/tracks',
                headers=headers,
            )

            tracks = playlist_duration_response.json().get(
                'items',[]
            ) if playlist_duration_response.status_code == 200 else []

            track_durations = []
            for item in tracks:
                track_durations.append(item['track']['duration_ms'])  # Duration in milliseconds

            total_duration_minutes = sum(track_durations) / 1000 / 60  # Convert from ms to minutes
            playlist['duration'] = total_duration_minutes  # Add the duration as a key in the playlist data

        # Sort the playlists by total duration in descending order
        ranked_playlists = sorted(top_playlists, key=lambda x: x['duration'], reverse=True)

        # Display ranked playlists
        for rank, playlist in enumerate(ranked_playlists, start=1):
            print(f"Rank {rank}: {playlist['name']} - {playlist['duration']:.2f} minutes")

        # Fetch top tracks and artists for different time ranges
        top_tracks, top_artists, all_genres = {}, {}, []
        for time_range in ['short_term', 'medium_term', 'long_term']:
            top_tracks_response = requests.get(
                f'{base_url}/me/top/tracks',
                headers=headers,
                params={'limit': 10, 'time_range': time_range}
            )
            top_artists_response = requests.get(
                f'{base_url}/me/top/artists',
                headers=headers,
                params={'limit': 10, 'time_range': time_range}
            )

            top_tracks[time_range] = top_tracks_response.json().get(
                'items', []
            ) if top_tracks_response.status_code == 200 else []

            top_artists[time_range] = top_artists_response.json().get(
                'items', []
            ) if top_artists_response.status_code == 200 else []

            for artist in top_artists[time_range]:
                all_genres.extend(artist.get('genres', []))

        genre_counts = Counter(all_genres)
        top_genres = genre_counts.most_common(10)

        # Combine all top tracks from different time ranges
        all_top_tracks = top_tracks['short_term'] + top_tracks['medium_term'] + top_tracks['long_term']
        album_counts = Counter(track['album']['name'] for track in all_top_tracks)
        most_listened_album = album_counts.most_common(1)

        request.session['recent_tracks'] = recent_tracks
        request.session['top_tracks'] = top_tracks
        request.session['top_artists'] = top_artists['short_term']
        request.session['top_genres'] = top_genres
        request.session['top_playlists'] = ranked_playlists

        context = {
            'lang': request.LANGUAGE_CODE,
            'user': user,
            'theme': request.session.get('theme', 'light'),
            'spotify_connected': True,
            'recent_tracks': recent_tracks,
            'top_tracks': top_tracks,
            'top_artists': top_artists['short_term'],
            'top_genres': top_genres,
            'top_playlists': ranked_playlists
        }

        if most_listened_album:
            # You can fetch the album details from Spotify using the album ID
            album_response = requests.get(
                'https://api.spotify.com/v1/search',
                headers={'Authorization': f'Bearer {access_token}'},
                params={'q': f'album:{most_listened_album[0][0]}', 'type': 'album', 'limit': 1}
            )

            if album_response.status_code == 200:
                album_items = album_response.json().get('albums', {}).get('items', [])
                if album_items:
                    album_info = album_items[0]
                    album_details = {
                        'name': album_info['name'],
                        'artist': album_info['artists'][0]['name'] if album_info['artists'] else None,
                        'image_url': album_info['images'][0]['url'] if album_info['images'] else None,
                    }
                    context['most_listened_album_details'] = album_details
                    request.session['top_albums'] = album_details

        return render(request, 'registered/dashboard.html', context)

    except Exception as e:
        messages.error(request, f"Error fetching Spotify data: {str(e)}")
        return render(request, 'registered/dashboard.html', {
            'user': user,
            'theme': request.session.get('theme', 'light'),
            'spotify_connected': False
        })

def games_view(request):
    theme = request.session.get('theme', 'light')  # Default to light mode
    selected_game = int(request.GET.get('game', '0'))  # Retrieve the selected game
    game_type = ["Guess Top Track", "Guess Top Album", "Guess Artist"][selected_game]

    top_tracks = random.choice(request.session.get('top_tracks', {})['short_term'])
    top_artists = random.choice(request.session.get('top_artists', {}))
    language = request.session.get('django_language', settings.LANGUAGE_CODE)
    if language == "es":
        game_type = translate_to_spanish(game_type)
    elif language == "fr":
        game_type = translate_to_french(game_type)

    context = {
        'theme': theme,
        'language': language,
        'top_tracks': top_tracks,
        'top_artists': top_artists,
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

    return render(request, 'users/profile.html', {'form': [], 'theme': theme})


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


def fetch_wraps(request, data_entries):
    wraps = []
    for entry in data_entries:
        wrap_data = {
            'type': dict(SpotifyData.WRAPPER_TYPES).get(entry.wrapper_type, entry.wrapper_type),
            'created_at': entry.created_at,  # Add creation date
            'username': entry.user.username,
        }

        if entry.wrapper_type.startswith('TOP_TRACKS') or entry.wrapper_type == 'RECENTLY_PLAYED':
            wrap_data['tracks'] = list(entry.tracks.all())

        if entry.wrapper_type == 'TOP_ARTISTS':
            wrap_data['artists'] = list(entry.artists.all())

        if entry.wrapper_type == 'TOP_ALBUMS':
            wrap_data['albums'] = list(entry.albums.all())

        if entry.wrapper_type == 'TOP_GENRES':
            wrap_data['genres'] = list(entry.genres.all())

        if entry.wrapper_type == 'TOP_PLAYLISTS':
            wrap_data['playlists'] = list(entry.playlists.all())

        wraps.append(wrap_data)

    language = request.session.get('django_language', settings.LANGUAGE_CODE)
    if language == "es" or language == "fr":
        for wrap in wraps:
            if language == "es":
                wrap['type'] = translate_to_spanish(wrap['type'])
            elif language == "fr":
                wrap['type'] = translate_to_french(wrap['type'])

    return wraps

@login_required
def wraps_view(request):
    theme = request.session.get('theme', 'light')
    user = request.user

    # Retrieve all SpotifyData entries for the user, sorted by creation date
    data_entries = SpotifyData.objects.filter(
        user=user
    ).prefetch_related('tracks', 'artists', 'albums', 'genres', 'playlists').order_by('-created_at')

    wraps = fetch_wraps(request, data_entries)
    return render(request, 'users/wraps.html', {'wraps': wraps, 'theme': theme, 'lang': request.LANGUAGE_CODE})

@login_required
def public_wraps_view(request):
    theme = request.session.get('theme', 'light')

    # Retrieve all public SpotifyData entries, sorted by creation date
    data_entries = SpotifyData.objects.filter(
        is_public=True  # Only fetch public entries
    ).prefetch_related('tracks', 'artists', 'albums', 'genres', 'playlists').order_by('-created_at')

    wraps = fetch_wraps(request, data_entries)
    return render(request, 'users/public_wraps.html', {'wraps': wraps, 'theme': theme, 'lang': request.LANGUAGE_CODE})


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
        print('Language Code:', request.POST.get('language', settings.LANGUAGE_CODE))
        user_language = request.POST.get('language', settings.LANGUAGE_CODE)
        if user_language in dict(settings.LANGUAGES):
            translation.activate(user_language)
            request.session['django_language'] = user_language
            return HttpResponseRedirect(f'/{user_language}/profile/')
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
        language = request.session.get('django_language', settings.LANGUAGE_CODE)

        if cached_analysis:

            if language == "es":
                cached_analysis = translate_to_spanish(cached_analysis)
            elif language == "fr":
                cached_analysis = translate_to_french(cached_analysis)

            return render(request, 'users/analysis.html', {
                'theme': theme,
                'top_tracks': top_tracks,
                'analysis': cached_analysis,
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

Generate a fun roughly-50-word personality analysis
It should describe how someone who listens to this kind of music tends to act/think/dress.
Keep it positive and playful, focusing on the overall vibe rather than specific songs.""".format(tracks_text)

        # Generate analysis
        response = model.generate_content(prompt)
        analysis = response.text

        # Cache successful analysis
        if analysis:
            cache.set(cache_key, analysis, 60 * 60 * 24)

        if language == "es":
            analysis = translate_to_spanish(cached_analysis)
        elif language == "fr":
            analysis = translate_to_french(cached_analysis)

        return render(request, 'users/analysis.html', {
            'theme': theme,
            'top_tracks': top_tracks,
            'analysis': analysis,
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
        token_response = requests.post(
            'https://accounts.spotify.com/api/token',
            data={
                'grant_type': 'refresh_token',
                'refresh_token': user.spotify_refresh_token,
                'client_id': settings.SPOTIFY_CLIENT_ID,
                'client_secret': settings.SPOTIFY_CLIENT_SECRET
            },
            headers={'Content-Type': 'application/x-www-form-urlencoded'}
        )

        if token_response.status_code != 200:
            logger.error(f"Failed to refresh token for user {user.id}")
            return None

        token_data = token_response.json()

        # Update user's token information
        success = user.set_spotify_tokens(
            access_token=token_data['access_token'],
            refresh_token=token_data.get('refresh_token', user.spotify_refresh_token),
            expires_in=token_data['expires_in']
        )

        return token_data['access_token'] if success else None

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

        if action == "saved":
            # Save the data using the helper function from models.py
            spotify_data = save_spotify_wrapper(
                user=user,
                access_token=access_token,
                wrapper_type=wrapper_type
            )
        elif action == "deleted":
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
        else:
            # For protecting it and making it public
            created_at_str = data.get('created_at')
            try:
                created_at = datetime.fromisoformat(created_at_str)  # Convert the string to datetime
            except ValueError:
                return JsonResponse({'error': 'Invalid date format for created_at'}, status=400)

            spotify_data = make_spotify_data_public(
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

@csrf_exempt
def prepare_share_content(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            social_type = data.get('socialType')
            wrapper_type = data.get('wrapperType')
            print(social_type)
            print(wrapper_type)

            # Fetch user data or context (example shown)
            recent_tracks = request.session.get('recent_tracks', [])
            top_tracks = request.session.get('top_tracks', {})
            top_artists = request.session.get('top_artists', [])
            top_albums = request.session.get('top_albums', {})
            top_genres = request.session.get('top_genres', [])
            top_playlists = request.session.get('top_playlists', [])

            # Determine content based on wrapper type
            if wrapper_type == 'Recently Played':
                shared_content = ', '.join(track['track']['name'] for track in recent_tracks)
            elif wrapper_type in ['Short Term', 'Medium Term', 'Long Term']:
                term = wrapper_type.lower().replace(' ', '_')
                shared_content = ', '.join(track['name'] for track in top_tracks.get(term, []))
            elif wrapper_type == 'Top Artists':
                shared_content = ', '.join(artist['name'] for artist in top_artists)
            elif wrapper_type == 'Top Albums':
                shared_content = top_albums['name']
            elif wrapper_type == 'Top Genres':
                shared_content = ', '.join(f'{genre} ({count})' for genre, count in top_genres)
            elif wrapper_type == 'Top Playlists':
                shared_content = ', '.join(f'{playlist['name']} ({playlist['duration']} minutes)' for playlist in top_playlists)
            else:
                return JsonResponse({'error': 'Invalid wrapper type'}, status=400)

            # Limit the content length
            max_content_length = 500
            if len(shared_content) > max_content_length:
                shared_content = shared_content[:max_content_length - 3] + '...'

            print("Shared Content:\n", shared_content)
            # Return the prepared content
            return JsonResponse({
                'text': f'Check out my shared wrapper: {shared_content}',
                'url': request.build_absolute_uri(),
            })

        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    else:
        return JsonResponse({'error': 'Invalid request method'}, status=405)

@login_required
def accept_duo_invite(request, sender_email):
    try:
        user = request.user
        sender = User.objects.get(email=sender_email)
        invite = DuoInvite.objects.get(sender=sender, recipient = user, accepted=False)
        invite.data['partner2_tracks'] = request.session.get('top_tracks', {})['short_term'][:5]
        invite.accepted = True
        invite.save()

        messages.success(request, 'Invitation accepted! Create your Duo-Wrapped now.')
        return redirect('duo_wrapped')

    except DuoInvite.DoesNotExist:
        messages.error(request, 'Invalid invitation.')
        return redirect('duo_wrapped')


@login_required
def duo_wrapped_view(request):
    user = request.user
    open_invites = DuoInvite.objects.filter(recipient=user, accepted=False)
    accepted_invites = DuoInvite.objects.filter(recipient=user, accepted=True)

    context = {
        'open_invites': open_invites,
        'accepted_invites': accepted_invites,
        'user': user,
    }
    
    return render(request, 'users/duo_wrapped.html', context)

@login_required
def send_duo_invite(request):
    if request.method == 'POST':
        recipient_email = request.POST.get('friend_email')
        print(recipient_email)
        if recipient_email == request.user.email:
            print("Invite denied to oneself")
            return redirect('duo_wrapped')

        # Ensure the recipient exists
        try:
            recipient = User.objects.get(email=recipient_email)
        except User.DoesNotExist:
            return JsonResponse({"error": "User with this email does not exist."}, status=404)

        # Create a DuoInvite for this recipient
        duo_invite, created = DuoInvite.objects.get_or_create(
            sender=request.user,  # Assuming the sender is the currently logged-in user
            recipient=recipient,
            data={
                'partner_tracks': request.session.get('top_tracks', {})['short_term'][:5],
                'partner2_tracks': request.session.get('top_tracks', {})['short_term'][:5],
                'timestamp': datetime.now().isoformat()
            }
        )

        # Respond accordingly
        if created:
            print("Invite successfully sent. User: " + str(duo_invite.recipient.username))
            return redirect('duo_wrapped')
        else:
            return JsonResponse({"message": "An invite already exists for this recipient."})

    return JsonResponse({"error": "Invalid request method."}, status=400)

def translate_text(text, target_language):
    """
    Generic translation function using Google Translate API

    :param text: Text to translate
    :param target_language: Target language code (e.g., 'es', 'fr')
    :return: Translated text
    """
    try:
        url = f"https://translation.googleapis.com/language/translate/v2"
        params = {
            'key': settings.CLOUD_API_KEY,
            'q': text,
            'target': target_language,
            'format': 'text'  # or 'html' if you want to preserve HTML formatting
        }

        response = requests.post(url, params=params)
        response.raise_for_status()

        translated_text = response.json()['data']['translations'][0]['translatedText']
        return translated_text

    except Exception as e:
        # Log the error or handle it appropriately
        print(f"Translation error: {e}")
        return text  # Return original text if translation fails


def translate_to_spanish(text):
    """Translate text to Spanish"""
    return translate_text(text, 'es')


def translate_to_french(text):
    """Translate text to French"""
    return translate_text(text, 'fr')