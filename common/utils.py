import io
import os

from django.contrib import messages
from django.core.files.base import ContentFile
from django.db.models import ProtectedError
from PIL import Image

def compress_image(uploaded_file, max_dimension=1000, quality=80):
    image = Image.open(uploaded_file)

    if image.mode in ('RGBA', 'P', 'CMYK'):
        image = image.convert('RGB')

    image.thumbnail((max_dimension, max_dimension))

    buffer = io.BytesIO()
    image.save(buffer, format = 'JPEG', quality = quality, optimize = True)
    buffer.seek(0)

    original_name = os.path.splitext(uploaded_file.name)[0]
    return ContentFile(buffer.read(), name=f'{original_name}.jpg')


def delete_or_protect(request, obj, success_message):
    try:
        obj.delete()
        messages.success(request, success_message)
        return True
    except ProtectedError as e:
        protected = list(e.protected_objects)
        count = len(protected)
        label = protected[0]._meta.verbose_name_plural if count else 'related records'
        messages.error(request, f'Cannot delete — {count} {label} still reference this record.')
        return False
