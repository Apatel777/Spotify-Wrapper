# models.py
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    email = models.EmailField(unique=True)  # Ensure the email is unique
    spotify_id = models.CharField(max_length=255, unique=True, null=True, blank=True)  # Unique Spotify ID for each user
    spotify_access_token = models.CharField(max_length=255, null=True, blank=True)
    spotify_refresh_token = models.CharField(max_length=255, null=True, blank=True)
    spotify_token_expires = models.DateTimeField(null=True, blank=True)
    #spotify_top_tracks = models.JSONField(blank=True, null=True)

    # REQUIRED_FIELDS is used for creating superusers
    REQUIRED_FIELDS = ['email']  # 'username' is included by default

    def __str__(self):
        return self.username

    def is_spotify_token_expired(self):
        """
        Check if the Spotify access token has expired.
        """
        if self.spotify_token_expires:
            return timezone.now() >= self.spotify_token_expires
        return True  # If there's no expiry date, treat it as expired

    def set_spotify_tokens(self, access_token, refresh_token, expires_in):
        """
        Store Spotify tokens and expiration time.
        """
        self.spotify_access_token = access_token
        self.spotify_refresh_token = refresh_token
        self.spotify_token_expires = timezone.now() + timezone.timedelta(seconds=expires_in)
        self.save()
