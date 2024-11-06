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




def create_spotify_auth_url():
    params = {
        "response_type": "code",
        "client_id": settings.SPOTIFY_CLIENT_ID,
        "redirect_uri": settings.SPOTIFY_REDIRECT_URI,
        "scope": "user-read-private user-read-email user-top-read",
    }
    auth_url = "https://accounts.spotify.com/authorize?" + urlencode(params)
    return auth_url

@login_required
def spotify_callback(request):
    # Check if the user is authenticated
    if not request.user.is_authenticated:
        print("Not authenticated")
        return redirect('login')  # Redirect to login page if the user is not authenticated

    code = request.GET.get('code')

    if code:
        try:
            # Initialize the Spotipy client with credentials and updated scope
            sp_oauth = SpotifyOAuth(
                client_id=settings.SPOTIFY_CLIENT_ID,
                client_secret=settings.SPOTIFY_CLIENT_SECRET,
                redirect_uri=settings.SPOTIFY_REDIRECT_URI,
                scope="user-read-private user-read-email user-top-read"  # Ensure user-top-read is included
            )
            token_info = sp_oauth.get_access_token(code)
            access_token = token_info['access_token']

            # Initialize Spotipy with the access token
            sp = spotipy.Spotify(auth=access_token)

            # Get the user's top tracks
            #top_tracks = sp.current_user_top_tracks(limit=10)  # Example call to fetch top tracks

            # Get the current logged-in user
            user = request.user

            # Update the user's profile with Spotify data
            user.spotify_access_token = access_token
            #user.spotify_top_tracks = top_tracks  # Assuming you have a field to store top tracks
            user.save()

            # Redirect the user to the dashboard once everything is set
            return redirect('dashboard')  # Make sure dashboard view is accessible and not redirecting to the callback again

        except Exception as e:
            # Handle errors like invalid authorization or data retrieval failure
            return HttpResponse(f"Error retrieving user data from Spotify: {str(e)}")

    # If there is no 'code' in the GET request, it indicates something went wrong with the Spotify callback
    return HttpResponse("No authorization code found.")

def home_view(request):
    return render(request, 'home/home.html', {})
def signup(request):
    # Get the theme from session, default to light mode
    theme = request.session.get('theme', 'light')

    if request.method == 'POST':
        username = request.POST['username']
        email = request.POST['email']
        password = request.POST['password']

        # Check if the email or username is already in use
        if User.objects.filter(email=email).exists():
            return render(request, 'home/signup.html', {'theme': theme, 'error': 'Email already in use'})
        if User.objects.filter(username=username).exists():
            return render(request, 'home/signup.html', {'theme': theme, 'error': 'Username already in use'})

        # Hash the password before saving
        hashed_password = make_password(password)

        # Create and save the user (without logging them in yet)
        user = User(username=username, email=email, password=hashed_password)
        user.save()

        # Log in the user after signup
        login(request, user)

        # Redirect to Spotify OAuth for linkage
        return HttpResponseRedirect(create_spotify_auth_url())

    # Render the signup form with the theme
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

@login_required
def dashboard(request):
    user = request.user

    # Assuming the access token is stored in the user's model
    access_token = user.spotify_access_token  # Adjust field name if necessary

    if not access_token:
        # Redirect to Spotify OAuth if access token is missing
        return HttpResponseRedirect(create_spotify_auth_url())

    # Use the access token to get the user's top tracks
    headers = {"Authorization": f"Bearer {access_token}"}

    #top_tracks_url = "https://api.spotify.com/v1/me/top/tracks"
    # response = requests.get(top_tracks_url, headers=headers)
    #
    # if response.status_code == 200:
    #     # Parse the top tracks data
    #     top_tracks_data = response.json()
    #     top_tracks = top_tracks_data.get('items', [])  # List of top tracks
    # else:
    #     top_tracks = []
    #     error_message = "Could not retrieve top tracks from Spotify."
    #     print(error_message)

    # Render the dashboard template with the top tracks
    context = {
        'user': user,
        #'top_tracks': top_tracks,
        'theme': request.session.get('theme', 'light'),  # Get theme from session
    }
    return render(request, 'registered/dashboard.html', context)


def profile_view(request):
    theme = request.session.get('theme', 'light')  # Default to light mode
    if request.method == 'POST':
        if 'delete_account' in request.POST:
            request.user.delete()
            return redirect('home')
        # add in whatever other stuff the profile view will have

    return render(request, 'users/profile.html', {'form': [], 'theme': theme})

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
    if theme in ['light', 'dark']:
        request.session['theme'] = theme
    return redirect(request.META.get('HTTP_REFERER', '/'))  # Redirect back to the page
