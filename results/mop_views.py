"""
mop_views.py — Vue Django pour le endpoint de réception MeOS (MOP).

MeOS est configuré pour pousser ses données vers :
    POST /mop/update/

Headers envoyés par MeOS :
    Competition: <cid>   (identifiant numérique de la compétition, optionnel)
    Pwd:         <clé API de la course ou mot de passe global>

Authentification (2 niveaux) :
    1. Clé API par course (CompetitionConfig.api_key) — identifie seule la
       compétition : le numéro de compétition peut rester vide dans MeOS.
    2. Repli : le mot de passe global MOP_PASSWORD (comportement historique,
       exige un CID valide).

La vue vérifie les identifiants, parse le XML et délègue à mop_receiver.
"""

import hmac
import logging

from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .mop_receiver import process_mop_xml, mop_response
from .services import find_race_by_key

logger = logging.getLogger(__name__)


def _mask(secret):
    """Masque un secret pour la journalisation (longueur seule, jamais le contenu)."""
    if not secret:
        return '(vide)'
    return f'(longueur {len(secret)})'


def _password_equals(given, expected):
    """Comparaison à temps constant, sûre pour les chaînes Unicode."""
    return hmac.compare_digest(
        given.encode('utf-8', 'replace'),
        expected.encode('utf-8', 'replace'),
    )


@csrf_exempt
@require_POST
def mop_update(request):
    """Endpoint de réception des mises à jour MeOS en temps réel."""

    # ── Authentification ──────────────────────────────────────────────────────
    # MeOS envoie les headers Competition et Pwd
    # Django les préfixe HTTP_ et les met en majuscules
    cid_str  = request.META.get('HTTP_COMPETITION', '')
    password = request.META.get('HTTP_PWD', '')

    # CID optionnel : valide s'il est un entier strictement positif
    try:
        cid = int(cid_str)
        if cid <= 0:
            raise ValueError
    except (ValueError, TypeError):
        cid = None

    # 1) Clé API d'une course (le numéro de compétition peut être vide)
    config = find_race_by_key(password)
    if config is not None:
        if cid is None:
            # MeOS configuré avec le numéro de compétition vide → dérivé de la clé
            cid = config.cid
        elif cid != config.cid:
            logger.warning(
                "mop_update: CID %s divergent de la course (cid=%s) associée à la clé",
                cid, config.cid,
            )
            return HttpResponse(
                mop_response('BADCMP'),
                content_type='text/xml',
                status=400,
            )
    else:
        # 2) Repli : mot de passe global (comportement historique)
        if cid is None:
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

        if not _password_equals(password, expected_password):
            logger.warning(
                "mop_update: identifiant incorrect pour cid=%s (reçu: %s)",
                cid, _mask(password),
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

    http_status_map = {'OK': 200, 'FROZEN': 423}
    http_status = http_status_map.get(status, 422)
    return HttpResponse(
        mop_response(status),
        content_type='text/xml',
        status=http_status,
    )
