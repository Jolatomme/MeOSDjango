"""
race_views.py — Création et gestion publiques de courses (sans compte).

- ``GET/POST /creer-course/``           : formulaire de création ; génère une
  clé API MeOS unique (« Password » dans MeOS) et un lien privé de gestion.
- ``GET/POST /gestion-course/<token>/`` : lien privé — paramètres MeOS,
  régénération de la clé, édition des informations de course, suppression
  définitive de la course.

La course est identifiée dans MeOS par sa seule clé API : le numéro de
compétition peut rester vide. L'authentification côté MOP est traitée par
``services.find_race_by_key`` avec repli sur le mot de passe global
``MOP_PASSWORD`` (cf. mop_views).
"""

import logging
import time

from django.conf import settings
from django.contrib import messages
from django.core import signing
from django.db import IntegrityError
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext
from django.views import View

from .forms import IofImportForm, RaceCreateForm, RaceEditForm
from .iof_importer import (
    IofImportError, import_iof_result_list, inspect_iof_result_list,
)
from .models import CompetitionConfig, Mopcompetition
from .services import (
    create_race, delete_race, regenerate_api_key, regenerate_manage_token,
    save_org_logo, delete_org_logo,
)

logger = logging.getLogger(__name__)

_CREATION_SALT = 'results.race_create'
MIN_FILL_SECONDS = 2.0


def new_creation_token(age=0.0):
    """Jeton signé horodaté du formulaire de création.

    ``age`` décale l'horodatage dans le passé (utile dans les tests, pour
    simuler un remplissage déjà ancien).
    """
    return signing.dumps({'ts': time.time() - age}, salt=_CREATION_SALT)


def _token_too_fast(token):
    """True si le jeton est absent, falsifié ou trop récent (< 2 s)."""
    if not token:
        return True
    try:
        data = signing.loads(token, salt=_CREATION_SALT)
        ts = float(data.get('ts', 0))
    except (signing.BadSignature, ValueError, TypeError, AttributeError):
        return True
    return (time.time() - ts) < MIN_FILL_SECONDS


def _config_for_token(token):
    """Renvoie la CompetitionConfig du lien privé, ou 404."""
    if not token:
        raise Http404
    config = CompetitionConfig.objects.filter(manage_token=token).first()
    if config is None:
        raise Http404
    return config


def _competition_of(config):
    return Mopcompetition.objects.filter(cid=config.cid, id=1).first()


def _absolute_url(request, path):
    """URL absolue à afficher à l'organisateur.

    Si ``PUBLIC_SITE_URL`` est défini (settings/env), on l'utilise toujours :
    l'organisateur voit alors l'URL de production canonique, même quand la
    page est ouverte en local ou derrière un proxy qui réécrit le Host.
    Sinon, on déduit l'URL de la requête courante.
    """
    base = (getattr(settings, 'PUBLIC_SITE_URL', '') or '').rstrip('/')
    if base:
        return f"{base}{path}"
    return request.build_absolute_uri(path)


def _manage_context(request, config, form, competition=None):
    return {
        'config': config,
        'competition': competition,
        'form': form,
        'meos_url': _absolute_url(request, reverse('results:mop_update')),
        'manage_url': _absolute_url(
            request,
            reverse('results:race_manage', kwargs={'token': config.manage_token}),
        ),
    }


class RaceCreateView(View):
    """Page publique de création de course, sans compte."""

    template_name = 'results/race_create.html'

    def dispatch(self, request, *args, **kwargs):
        if not getattr(settings, 'ENABLE_RACE_CREATION', True):
            raise Http404
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        form = RaceCreateForm(initial={'token': new_creation_token()})
        return render(request, self.template_name, {'form': form})

    def post(self, request):
        form = RaceCreateForm(request.POST, request.FILES)
        if form.is_valid():
            cleaned = form.cleaned_data
            honeypot = bool(cleaned.get('website'))
            too_fast = _token_too_fast(cleaned.get('token'))
            if honeypot or too_fast:
                logger.info(
                    "race_create: soumission rejetée (honeypot=%s, trop_rapide=%s)",
                    honeypot, too_fast,
                )
                form.add_error(
                    None,
                    gettext("Formulaire invalide. Vérifiez les champs saisis."),
                )
            else:
                logo_file = cleaned.get('logo')
                logo = save_org_logo(logo_file) if logo_file else ''
                try:
                    config = create_race(
                        name=cleaned['name'],
                        date=cleaned['date'],
                        organizer=cleaned['organizer'],
                        homepage=cleaned.get('homepage') or '',
                        livelox=cleaned.get('livelox') or '',
                        logo=logo,
                    )
                except IntegrityError:
                    logger.warning("race_create: conflit de CID, nouvelle tentative requise")
                    delete_org_logo(logo)
                    form.add_error(
                        None,
                        gettext("Conflit à la création. Réessayez une nouvelle fois."),
                    )
                else:
                    return redirect(
                        'results:race_manage', token=config.manage_token
                    )
        return render(request, self.template_name, {'form': form})


class RaceManageView(View):
    """Lien privé de gestion d'une course (par jeton secret)."""

    template_name = 'results/race_manage.html'

    def get(self, request, token):
        config = _config_for_token(token)
        competition = _competition_of(config)
        form = RaceEditForm(initial={
            'name': competition.name if competition else '',
            'date': competition.date if competition else None,
            'organizer': competition.organizer if competition else '',
            'homepage': competition.homepage if competition else '',
            'livelox': competition.livelox if competition else '',
        })
        return render(
            request, self.template_name,
            _manage_context(request, config, form, competition),
        )

    def post(self, request, token):
        config = _config_for_token(token)
        action = request.POST.get('action', '')

        if action == 'regenerate_key':
            regenerate_api_key(config)
            return redirect(f"{request.path}?ok=key")

        if action == 'regenerate_link':
            # L'ancien lien meurt immédiatement : on redirige vers le nouveau
            new_token = regenerate_manage_token(config)
            new_url = reverse(
                'results:race_manage', kwargs={'token': new_token}
            )
            return redirect(f"{new_url}?ok=link")

        if action == 'delete':
            # Suppression totale : le lien privé meurt avec la course →
            # on redirige vers l'accueil (message via le framework messages).
            competition = _competition_of(config)
            name = competition.name if competition else str(config.cid)
            delete_race(config)
            logger.info("race_manage: course cid=%s supprimée (%s)", config.cid, name)
            messages.success(
                request,
                gettext(
                    "Course « %(name)s » supprimée : résultats, clé API et "
                    "lien de gestion effacés."
                ) % {"name": name},
            )
            return redirect('results:home')

        if action == 'edit':
            form = RaceEditForm(request.POST)
            if form.is_valid():
                cleaned = form.cleaned_data
                Mopcompetition.objects.filter(cid=config.cid, id=1).update(
                    name=cleaned['name'],
                    date=cleaned['date'],
                    organizer=cleaned['organizer'],
                    homepage=cleaned.get('homepage') or '',
                    livelox=cleaned.get('livelox') or '',
                )
                logger.info("race_manage: course cid=%s mise à jour", config.cid)
                return redirect(f"{request.path}?ok=info")
            competition = _competition_of(config)
            return render(
                request, self.template_name,
                _manage_context(request, config, form, competition),
            )

        return redirect(request.path)


class RaceImportIofView(View):
    """Import privé d'un fichier IOF ResultList dans une course."""

    template_name = 'results/race_import_iof.html'

    @staticmethod
    def _context(config, competition, form, report=None):
        return {
            'config': config,
            'competition': competition,
            'form': form,
            'report': report,
        }

    def get(self, request, token):
        config = _config_for_token(token)
        competition = _competition_of(config)
        return render(
            request, self.template_name,
            self._context(config, competition, IofImportForm()),
        )

    def post(self, request, token):
        config = _config_for_token(token)
        competition = _competition_of(config)
        form = IofImportForm(request.POST, request.FILES)
        action = request.POST.get('action', 'import')
        if action not in ('inspect', 'import'):
            action = 'import'
        report = None

        if form.is_valid():
            xml_data = form.cleaned_data['ioffile'].read()
            race_number = form.cleaned_data.get('race_number')
            use_event_metadata = form.cleaned_data.get('use_event_metadata', False)

            if action == 'inspect':
                try:
                    report = inspect_iof_result_list(
                        xml_data,
                        cid=config.cid,
                        race_number=race_number,
                        use_event_metadata=use_event_metadata,
                    )
                except IofImportError as exc:
                    form.add_error(None, str(exc))
            elif not form.cleaned_data.get('confirm'):
                form.add_error(
                    'confirm',
                    gettext(
                        "Cochez la case de confirmation : l'import remplace "
                        "tous les résultats existants."
                    ),
                )
            else:
                try:
                    report = import_iof_result_list(
                        config.cid,
                        xml_data,
                        race_number=race_number,
                        use_event_metadata=use_event_metadata,
                    )
                except IofImportError as exc:
                    form.add_error(None, str(exc))
                else:
                    if report.status == 'FROZEN':
                        form.add_error(
                            None,
                            gettext(
                                "La course est gelée : aucun résultat n'a été "
                                "importé. Dégèle-la dans MeOS avant de réessayer."
                            ),
                        )
                    else:
                        logger.info(
                            "race_import_iof: cid=%s — import IOF réussi "
                            "(%d classes, %d concurrents, %d équipes)",
                            config.cid, report.classes,
                            report.competitors, report.teams,
                        )
                        messages.success(
                            request,
                            gettext(
                                "Résultats IOF importés : %(classes)d classe(s), "
                                "%(competitors)d concurrent(s), %(teams)d équipe(s)."
                            ) % {
                                'classes': report.classes,
                                'competitors': report.competitors,
                                'teams': report.teams,
                            },
                        )
                        manage_url = reverse(
                            'results:race_manage',
                            kwargs={'token': config.manage_token},
                        )
                        return redirect(f'{manage_url}?ok=iof')

        return render(
            request, self.template_name,
            self._context(config, competition, form, report),
        )

