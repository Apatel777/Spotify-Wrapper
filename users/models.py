from django.contrib.auth.models import AbstractUser
from django.db import models, transaction
from django.utils import timezone
from django.db import IntegrityError
from django.core.exceptions import ValidationError


class User(AbstractUser):
    email = models.EmailField(unique=True)
    spotify_id = models.CharField(max_length=255, unique=True, null=True, blank=True, db_index=True)
    spotify_access_token = models.CharField(max_length=255, null=True, blank=True)
    spotify_refresh_token = models.CharField(max_length=255, null=True, blank=True)
    spotify_token_expires = models.DateTimeField(null=True, blank=True)
    spotify_top_tracks_short = models.JSONField(null=True, blank=True)
    spotify_top_tracks_medium = models.JSONField(null=True, blank=True)
    spotify_top_tracks_long = models.JSONField(null=True, blank=True)
    spotify_last_updated = models.DateTimeField(null=True, blank=True)

    REQUIRED_FIELDS = ['email']

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['spotify_id'],
                name='unique_spotify_id',
                condition=models.Q(spotify_id__isnull=False)
            )
        ]

    def __str__(self):
        return self.username

    def clean(self):
        """Validate the model before saving"""
        super().clean()
        if self.spotify_id == '':
            self.spotify_id = None

    def save(self, *args, **kwargs):
        """Override save to ensure validation runs"""
        self.clean()
        super().save(*args, **kwargs)

    @transaction.atomic
    def set_spotify_id(self, spotify_id):
        """
        Safely set the Spotify ID for the user.
        Returns True if successful, False if the ID is already in use.
        Uses transaction.atomic to ensure database consistency.
        """
        if not spotify_id:
            return False

        # If this user already has this Spotify ID, just return True
        if self.spotify_id == spotify_id:
            return True

        # Check if another user has this Spotify ID
        existing_user = User.objects.filter(spotify_id=spotify_id).first()
        if existing_user and existing_user.id != self.id:
            return False

        try:
            # Lock the row for update to prevent race conditions
            user = User.objects.select_for_update().get(id=self.id)
            user.spotify_id = spotify_id
            user.save(update_fields=['spotify_id'])

            # Update the current instance to reflect the changes
            self.spotify_id = spotify_id
            return True
        except (User.DoesNotExist, IntegrityError) as e:
            print(f"Error setting Spotify ID: {str(e)}")
            return False

    @transaction.atomic
    def set_spotify_tokens(self, access_token, refresh_token, expires_in):
        """
        Store Spotify tokens and expiration time.
        Uses transaction.atomic to ensure database consistency.

        Args:
            access_token (str): Spotify access token
            refresh_token (str): Spotify refresh token
            expires_in (int): Token expiration time in seconds

        Returns:
            bool: True if successful, False otherwise
        """
        if not all([access_token, refresh_token, expires_in]):
            print("Missing required token information")
            return False

        try:
            # Lock the row for update to prevent race conditions
            user = User.objects.select_for_update().get(id=self.id)

            user.spotify_access_token = access_token
            user.spotify_refresh_token = refresh_token
            user.spotify_token_expires = timezone.now() + timezone.timedelta(seconds=expires_in)

            # Update all token-related fields at once
            user.save(update_fields=[
                'spotify_access_token',
                'spotify_refresh_token',
                'spotify_token_expires'
            ])

            # Update the current instance to reflect the changes
            self.spotify_access_token = access_token
            self.spotify_refresh_token = refresh_token
            self.spotify_token_expires = user.spotify_token_expires

            return True
        except Exception as e:
            print(f"Error setting Spotify tokens: {str(e)}")
            return False

    def clear_spotify_data(self):
        """
        Clear all Spotify-related data for the user.
        Useful for handling disconnection or errors.
        """
        try:
            self.spotify_id = None
            self.spotify_access_token = None
            self.spotify_refresh_token = None
            self.spotify_token_expires = None
            self.spotify_top_tracks_short = None
            self.spotify_top_tracks_medium = None
            self.spotify_top_tracks_long = None
            self.spotify_last_updated = None
            self.save(update_fields=[
                'spotify_id',
                'spotify_access_token',
                'spotify_refresh_token',
                'spotify_token_expires',
                'spotify_top_tracks_short',
                'spotify_top_tracks_medium',
                'spotify_top_tracks_long',
                'spotify_last_updated'
            ])
            return True
        except Exception as e:
            print(f"Error clearing Spotify data: {str(e)}")
            return False