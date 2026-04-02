from django.core.exceptions import PermissionDenied
from functools import wraps


def advanced_required(view_func):
    """Restrict a view to advanced (or staff/superuser) users."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_advanced:
            raise PermissionDenied
        return view_func(request, *args, **kwargs)
    return wrapper
