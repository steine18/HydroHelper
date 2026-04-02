from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    TIER_BASIC = 'basic'
    TIER_ADVANCED = 'advanced'
    TIER_CHOICES = [
        (TIER_BASIC, 'Basic'),
        (TIER_ADVANCED, 'Advanced'),
    ]

    tier = models.CharField(max_length=20, choices=TIER_CHOICES, default=TIER_BASIC)

    @property
    def is_advanced(self):
        return self.tier == self.TIER_ADVANCED or self.is_staff or self.is_superuser
