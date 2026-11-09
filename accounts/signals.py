from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

@receiver(user_logged_in)
def update_last_login_info(sender, request, user, **kwargs):
    ip = request.META.get('REMOTE_ADDR')
    device = request.META.get('HTTP_USER_AGENT')

    user.last_ip = ip
    user.last_device = device
    user.save(update_fields=['last_ip', 'last_device'])