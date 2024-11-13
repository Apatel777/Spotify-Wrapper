import requests
from datetime import timedelta
from django.conf import settings

class SpotifyClient:
    def __init__(self, access_token, refresh_token=None):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.base_url = 'https://api.spotify.com/v1/'

    def _get(self, endpoint, params=None):
        headers = {
            'Authorization': f'Bearer {self.access_token}',
        }
        response = requests.get(self.base_url + endpoint, headers=headers, params=params)
        if response.status_code == 401:  # Token expired, refresh it
            self.refresh_access_token()
            return self._get(endpoint, params)
        return response.json() if response.status_code == 200 else None

    def refresh_access_token(self):
        token_url = 'https://accounts.spotify.com/api/token'
        data = {
            'grant_type': 'refresh_token',
            'refresh_token': self.refresh_token,
            'client_id': settings.SPOTIFY_CLIENT_ID,
            'client_secret': settings.SPOTIFY_CLIENT_SECRET,
        }
        response = requests.post(token_url, data=data)
        token_data = response.json()
        self.access_token = token_data['access_token']

    def get_user_profile(self):
        return self._get('me')

    def get_user_followers(self):
        profile = self.get_user_profile()
        if profile:
            return profile.get('followers', {}).get('total', 0)
        return 0
