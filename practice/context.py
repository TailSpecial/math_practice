from django.conf import settings

def portal(request):
    profile = getattr(request.user, 'profile', None) if request.user.is_authenticated else None
    return {'portal_profile': profile, 'can_manage': bool(profile and profile.role == 'head'), 'can_oversee': bool(profile and profile.role in ('teacher', 'head')), 'sso_enabled': bool(settings.KUBSU_OIDC_METADATA_URL and settings.KUBSU_CLIENT_ID and settings.KUBSU_CLIENT_SECRET)}
