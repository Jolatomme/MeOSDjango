"""
mop_views.py — Vue Django pour le endpoint de réception MeOS (MOP).

MeOS est configuré pour pousser ses données vers :
    POST /mop/update/

Headers envoyés par MeOS :
    Competition: <cid>   (identifiant numérique de la compétition)
    Pwd:         <mot de passe configuré dans MeOS>

La vue vérifie le mot de passe, parse le XML et délègue à mop_receiver.
"""

import logging

from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .mop_receiver import process_mop_xml, mop_response

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def mop_update(request):
    """Endpoint de réception des mises à jour MeOS en temps réel."""

    # ── Authentification ──────────────────────────────────────────────────────
    # MeOS envoie les headers Competition et Pwd
    # Django les préfixe HTTP_ et les met en majuscules
    cid_str  = request.META.get('HTTP_COMPETITION', '')
    password = request.META.get('HTTP_PWD', '')

    try:
        cid = int(cid_str)
        if cid <= 0:
            raise ValueError
    except (ValueError, TypeError):
        logger.warning("mop_update: HTTP_COMPETITION invalide: %r", cid_str)
        return HttpResponse(
            mop_response('BADCMP'),
            content_type='text/xml',
            status=400,
        )

    expected_password = getattr(settings, 'MOP_PASSWORD', '')
    if not expected_password:
        logger.error("mop_update: MOP_PASSWORD non configuré dans settings.py")
        return HttpResponse(
            mop_response('BADPWD'),
            content_type='text/xml',
            status=403,
        )

    if password != expected_password:
        logger.warning(
            "mop_update: mot de passe incorrect pour cid=%s (reçu: %r)",
            cid, password
        )
        return HttpResponse(
            mop_response('BADPWD'),
            content_type='text/xml',
            status=403,
        )

    # ── Lecture et validation du corps ────────────────────────────────────────
    xml_data = request.body
    if not xml_data:
        return HttpResponse(
            mop_response('NODATA'),
            content_type='text/xml',
            status=400,
        )

    # MeOS peut envoyer des archives ZIP dans des formats anciens
    if xml_data[:2] == b'PK':
        logger.warning("mop_update: ZIP non supporté pour cid=%s", cid)
        return HttpResponse(
            mop_response('NOZIP'),
            content_type='text/xml',
            status=415,
        )

    # ── Traitement ────────────────────────────────────────────────────────────
    status = process_mop_xml(cid, xml_data)

    http_status = 200 if status == 'OK' else 422
    return HttpResponse(
        mop_response(status),
        content_type='text/xml',
        status=http_status,
    )
