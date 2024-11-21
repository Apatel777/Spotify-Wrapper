from django.contrib.auth.models import AbstractUser
from django.db import models, transaction
from django.utils import timezone
from django.db import IntegrityError
import logging

# Setting up a logger
logger = logging.getLogger(__name__)

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
            logger.error("Spotify ID cannot be null or empty")
            return False

        # If this user already has this Spotify ID, just return True
        if self.spotify_id == spotify_id:
            return True

        # Check if another user has this Spotify ID
        existing_user = User.objects.filter(spotify_id=spotify_id).first()
        if existing_user and existing_user.id != self.id:
            logger.error(f"Spotify ID {spotify_id} is already in use by another user.")
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
            logger.error(f"Error setting Spotify ID: {str(e)}")
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
            logger.error("Missing required token information")
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
            logger.error(f"Error setting Spotify tokens: {str(e)}")
            return False

    @transaction.atomic
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
            logger.error(f"Error clearing Spotify data: {str(e)}")
            return False

class SpotifyData(models.Model):
    """Base model for storing Spotify data snapshots"""
    WRAPPER_TYPES = [
        ('RECENTLY_PLAYED', 'Recently Played'),
        ('TOP_TRACKS_SHORT', 'Top Tracks Short Term'),
        ('TOP_TRACKS_MEDIUM', 'Top Tracks Medium Term'),
        ('TOP_TRACKS_LONG', 'Top Tracks Long Term'),
        ('TOP_ARTISTS', 'Top Artists'),
        ('TOP_ALBUM', 'Top Album'),
    ]

    WRAPPER_TYPE_MAP = {
        'Recently Played': 'RECENTLY_PLAYED',
        'Top Tracks Short Term': 'TOP_TRACKS_SHORT',
        'Top Tracks Medium Term': 'TOP_TRACKS_MEDIUM',
        'Top Tracks Long Term': 'TOP_TRACKS_LONG',
        'Top Artists': 'TOP_ARTISTS',
        'Top Album': 'TOP_ALBUM'
    }

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='spotify_data')
    wrapper_type = models.CharField(max_length=20, choices=WRAPPER_TYPES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    @classmethod
    def get_internal_wrapper_type(cls, human_readable_type):
        """Maps human-readable wrapper type to internal code."""
        return cls.WRAPPER_TYPE_MAP.get(human_readable_type)


class Track(models.Model):
    """Model for storing track information"""
    spotify_data = models.ForeignKey(SpotifyData, on_delete=models.CASCADE, related_name='tracks')
    track_id = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    artist = models.CharField(max_length=255)
    album = models.CharField(max_length=255)
    image_url = models.URLField(null=True, blank=True)
    played_at = models.DateTimeField(null=True, blank=True)  # For recently played tracks
    popularity = models.IntegerField(default=0)


class Artist(models.Model):
    """Model for storing artist information"""
    spotify_data = models.ForeignKey(SpotifyData, on_delete=models.CASCADE, related_name='artists')
    artist_id = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    image_url = models.URLField(null=True, blank=True)
    genres = models.JSONField(default=list)
    popularity = models.IntegerField(default=0)


class Album(models.Model):
    """Model for storing album information"""
    spotify_data = models.ForeignKey(SpotifyData, on_delete=models.CASCADE, related_name='albums')
    album_id = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    artist = models.CharField(max_length=255)
    image_url = models.URLField(null=True, blank=True)
    release_date = models.DateField(null=True, blank=True)
    total_tracks = models.IntegerField(default=0)
    play_count = models.IntegerField(default=1)  # For tracking most listened album


# Helper function to save Spotify data
def save_spotify_wrapper(user, sp, wrapper_type):
    """
    Save Spotify data based on wrapper type
    """
    spotify_data = SpotifyData.objects.create(
        user=user,
        wrapper_type=wrapper_type
    )

    if wrapper_type == 'RECENTLY_PLAYED':
        recent_tracks = sp.current_user_recently_played(limit=10)['items']
        for track in recent_tracks:
            Track.objects.create(
                spotify_data=spotify_data,
                track_id=track['track']['id'],
                name=track['track']['name'],
                artist=track['track']['artists'][0]['name'],
                album=track['track']['album']['name'],
                image_url=track['track']['album']['images'][0]['url'] if track['track']['album']['images'] else None,
                played_at=track['played_at'],
                popularity=track['track']['popularity']
            )

    elif wrapper_type.startswith('TOP_TRACKS'):
        time_range = {
            'TOP_TRACKS_SHORT': 'short_term',
            'TOP_TRACKS_MEDIUM': 'medium_term',
            'TOP_TRACKS_LONG': 'long_term'
        }[wrapper_type]

        top_tracks = sp.current_user_top_tracks(limit=10, time_range=time_range)['items']
        for track in top_tracks:
            Track.objects.create(
                spotify_data=spotify_data,
                track_id=track['id'],
                name=track['name'],
                artist=track['artists'][0]['name'],
                album=track['album']['name'],
                image_url=track['album']['images'][0]['url'] if track['album']['images'] else None,
                popularity=track['popularity']
            )

    elif wrapper_type == 'TOP_ARTISTS':
        for time_range in ['short_term', 'medium_term', 'long_term']:
            top_artists = sp.current_user_top_artists(limit=10, time_range=time_range)['items']
            for artist in top_artists:
                Artist.objects.create(
                    spotify_data=spotify_data,
                    artist_id=artist['id'],
                    name=artist['name'],
                    image_url=artist['images'][0]['url'] if artist['images'] else None,
                    genres=artist['genres'],
                    popularity=artist['popularity']
                )

    elif wrapper_type == 'TOP_ALBUM':
        # Get all top tracks to find the most listened album
        all_tracks = []
        for time_range in ['short_term', 'medium_term', 'long_term']:
            tracks = sp.current_user_top_tracks(limit=10, time_range=time_range)['items']
            all_tracks.extend(tracks)

        # Count albums
        from collections import Counter
        album_counts = Counter(track['album']['name'] for track in all_tracks)
        most_listened = album_counts.most_common(1)[0]

        # Search for the album to get full details
        album_search = sp.search(q='album:' + most_listened[0], type='album', limit=1)
        if album_search['albums']['items']:
            album_info = album_search['albums']['items'][0]
            Album.objects.create(
                spotify_data=spotify_data,
                album_id=album_info['id'],
                name=album_info['name'],
                artist=album_info['artists'][0]['name'],
                image_url=album_info['images'][0]['url'] if album_info['images'] else None,
                release_date=album_info.get('release_date'),
                total_tracks=album_info.get('total_tracks', 0),
                play_count=most_listened[1]
            )

    return spotify_data


# Helper function to delete specific Spotify data based on timestamp
def delete_spotify_wrapper(user, wrapper_type, created_at):
    """
    Delete specific Spotify data based on wrapper type and created_at timestamp.
    """
    try:
        # Map the human-readable wrapper_type to the internal code using the model's method
        wrapper_type_code = SpotifyData.get_internal_wrapper_type(wrapper_type)

        if not wrapper_type_code:
            return None  # Invalid wrapper_type provided

        # Find the SpotifyData instance for the given user, wrapper_type, and created_at
        spotify_data = SpotifyData.objects.filter(
            user=user,
            wrapper_type=wrapper_type_code,
            created_at=created_at
        ).first()

        if not spotify_data:
            return None  # No data found to delete

        # Delete related Track objects
        spotify_data.tracks.all().delete()

        # Delete related Artist objects
        spotify_data.artists.all().delete()

        # Delete related Album objects
        spotify_data.albums.all().delete()

        # Finally, delete the SpotifyData instance
        spotify_data.delete()

        return spotify_data

    except Exception as e:
        logger.error(f"Error deleting Spotify data: {str(e)}")
        return None
