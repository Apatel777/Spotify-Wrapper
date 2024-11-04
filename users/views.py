from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required

from django.contrib.auth.hashers import make_password
from .models import User


def signup(request):
    if request.method == 'POST':
        username = request.POST['username']
        email = request.POST['email']
        password = request.POST['password']

        if User.objects.filter(email=email).exists():
            return JsonResponse({'error': 'Email already in use'}, status=400)

        # Hash the password before saving
        hashed_password = make_password(password)

        # Create and save the user
        user = User(username=username, email=email, password=hashed_password)
        user.save()

        # Automatically log in the user after signing up
        login(request, user)

        return redirect('dashboard')  # Redirect to home after signup

    return render(request, 'home/signup.html')  # Render the signup form

def login_view(request):
    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']

        # Try to authenticate the user
        user = authenticate(request, username=username, password=password)

        if user is not None:
            # User exists and credentials are correct
            login(request, user)
            return redirect('dashboard')
        else:
            # Invalid credentials
            return render(request, 'home/login.html', {'error': 'Invalid username or password'})

    return render(request, 'home/login.html')

def home_view(request):
    return render(request, 'home/home.html', {})

@login_required
def dashboard(request):
    return render(request, 'registered/dashboard.html')

def profile_view(request):
    if request.method == 'POST':
        if 'delete_account' in request.POST:
            request.user.delete()
            return redirect('home')
        # add in whatever other stuff the profile view will have

    return render(request, 'users/profile.html', {'form': []})

def logout_view(request):
    logout(request)
    return redirect('home')  # Redirect to home after logout

def wraps_view(request):
    # Fetch wraps associated with the user
    wraps = []  # Replace with actual query to fetch wraps
    return render(request, 'users/wraps.html', {'wraps': wraps})

@login_required
def delete_account_view(request):
    if request.method == 'POST':
        request.user.delete()
        return redirect('home')
    return render(request, 'users/delete_account.html')