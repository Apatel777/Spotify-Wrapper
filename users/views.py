from django.shortcuts import render, redirect
from django.contrib.auth import login, authenticate
from django.contrib.auth.hashers import make_password
from .models import User


def signup(request):
    if request.method == 'POST':
        username = request.POST['username']
        email = request.POST['email']
        password = request.POST['password']

        # Hash the password before saving
        hashed_password = make_password(password)

        # Create and save the user
        user = User(username=username, email=email, password=hashed_password)
        user.save()

        # Automatically log in the user after signing up
        login(request, user)

        return redirect('home')  # Redirect to home after signup

    return render(request, 'home/signup.html')  # Render the signup form

def login_view(request):
    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('home')  # Redirect to home after login
        else:
            # Handle invalid login
            return render(request, 'home/login.html', {'error': 'Invalid credentials'})

    return render(request, 'home/login.html')

def home_view(request):
    return render(request, 'home/home.html', {})

def dashboard(request):
    return render(request, 'registered/dashboard.html', {})
def profile_view(request):
    return render(request, 'users/profile.html', {'form': []})