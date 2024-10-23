# models.py
from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    email = models.EmailField(unique=True)  # Ensure the email is unique

    # You do not need to redefine password; it is inherited from AbstractUser

    # REQUIRED_FIELDS is used for creating superusers
    REQUIRED_FIELDS = ['email']  # 'username' is included by default

    def __str__(self):
        return self.username
