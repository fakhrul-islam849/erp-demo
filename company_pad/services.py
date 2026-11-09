import os
from io import BytesIO

from django.conf import settings
from django.contrib.staticfiles import finders
from django.core.files.base import ContentFile
from django.template.loader import render_to_string
from xhtml2pdf import pisa

from company.models import Company


def _link_callback(uri, rel):
    if uri.startswith(settings.MEDIA_URL):
        path = os.path.join(settings.MEDIA_ROOT, uri.replace(settings.MEDIA_URL, ''))
        if os.path.isfile(path):
            return path
    elif uri.startswith(settings.STATIC_URL):
        relative_path = uri.replace(settings.STATIC_URL, '')
        found = finders.find(relative_path)
        if found:
            return found
        path = os.path.join(settings.STATIC_ROOT, relative_path)
        if os.path.isfile(path):
            return path
    return uri


def generate_final_pdf(pad):
    """Renders the pad's letterhead PDF and attaches it to pad.final_pdf.
    Does NOT call pad.save() — the caller must save once, with status already set."""
    company = Company.load()
    html = render_to_string('company_pad/pad_pdf.html', {'pad': pad, 'company': company})
    buffer = BytesIO()
    pisa.CreatePDF(html, dest=buffer, link_callback=_link_callback)
    buffer.seek(0)
    pad.final_pdf.save(f'{pad.pk}.pdf', ContentFile(buffer.read()), save=False)