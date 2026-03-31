from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Custom user model. Extends AbstractUser so fields can be added later
    (e.g. USGS office, preferences) without a painful migration.
    """
    pass
