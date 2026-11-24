import logging
from authlib.integrations.django_client import OAuth
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.db import transaction
from django.shortcuts import redirect
from .models import Profile

logger = logging.getLogger(__name__)

def oidc_client():
    if not all([settings.KUBSU_OIDC_METADATA_URL, settings.KUBSU_CLIENT_ID, settings.KUBSU_CLIENT_SECRET]):
        return None
    oauth = OAuth()
    return oauth.register('kubsu', client_id=settings.KUBSU_CLIENT_ID, client_secret=settings.KUBSU_CLIENT_SECRET, server_metadata_url=settings.KUBSU_OIDC_METADATA_URL, client_kwargs={'scope': 'openid profile email', 'code_challenge_method': 'S256'})

def kubsu_login(request):
    client = oidc_client()
    if not client:
        messages.info(request, 'Вход через КубГУ будет доступен после подключения университетской системы авторизации.')
        return redirect('login')
    try:
        return client.authorize_redirect(request, request.build_absolute_uri('/auth/kubsu/callback/'))
    except Exception:
        logger.warning('KubSU authorization service unavailable')
        messages.error(request, 'Сервис входа КубГУ временно недоступен. Попробуйте позже.')
        return redirect('login')

def kubsu_callback(request):
    client = oidc_client()
    if not client:
        return redirect('login')
    try:
        token = client.authorize_access_token(request)
        claims = token.get('userinfo')
        if not token.get('id_token') or not claims or not claims.get('sub') or not claims.get('iss'):
            raise ValueError('Missing verified ID token claims')
        # Authlib validates signature, issuer, audience, nonce, expiry and OAuth state.
        # Never trust browser-submitted names, email or role for account binding.
        with transaction.atomic():
            profile = Profile.objects.select_for_update().filter(oidc_subject=claims['sub'], oidc_issuer=claims['iss']).first()
            if profile is None:
                username = claims.get(settings.KUBSU_LOGIN_CLAIM)
                if not isinstance(username, str) or not username:
                    raise ValueError('Missing university account identifier')
                profile = Profile.objects.select_for_update().get(user__username=username, oidc_subject__isnull=True)
                profile.oidc_subject = claims['sub']
                profile.oidc_issuer = claims['iss']
                profile.save(update_fields=['oidc_subject', 'oidc_issuer'])
            if not profile.user.is_active:
                raise ValueError('Inactive user')
            login(request, profile.user, backend='django.contrib.auth.backends.ModelBackend')
        return redirect('dashboard')
    except Exception:
        logger.warning('KubSU sign-in failed; no account was authenticated')
        messages.error(request, 'Не удалось выполнить вход. Аккаунт должен быть включён руководителем в список участников, а идентификатор — совпадать с университетским.')
        return redirect('login')
