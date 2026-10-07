# DEPLOY.md — Déploiement (document temporaire)

> Guide destiné à déployer le site depuis un état **avant l'internationalisation**
> jusqu'à l'état actuel du dépôt. À supprimer une fois le déploiement généralisé.

## Rappels préalables

- Accès shell au dossier du site (celui qui contient `manage.py`), arbre git à jour du dépôt.
- `git`, Python et le venv / utilisateur habituel du site.
- **`msgfmt` requis** (paquet `gettext`) — indispensable à l'étape 5 :
  `which msgfmt` → sinon `apt install gettext` (ou équivalent de la distrib).

---

## Étape 1 — Sauvegardes et état de départ

```bash
cd <dossier du site>
git status --porcelain
git ls-files -v | grep '^S'          # fichiers masqués par skip-worktree

# Sauvegarde des valeurs réelles (credentials)
cp MeOSDjango/dev_settings.py dev_settings.backup

# S'il a édité settings.py à la main (DEBUG=False, etc.), sauver ses écarts
git diff MeOSDjango/settings.py > settings_local.patch   # (vide = rien à sauver)
```

## Étape 2 — Débloquer les fichiers masqués (indispensable)

```bash
git update-index --no-skip-worktree MeOSDjango/settings.py MeOSDjango/dev_settings.py || true
git diff MeOSDjango/settings.py      # REVOIR ses éditions locales :
                                     #   DEBUG / ALLOWED_HOSTS → le .env (étape 3) ;
                                     #   tout autre écart personnalisé → le ré-appliquer après
git restore MeOSDjango/settings.py MeOSDjango/dev_settings.py   # état git propre pour le merge
```

> ⚠️ **Étape clé** : sans elle, git conserve silencieusement l'ancien `settings.py`,
> sans le bloc i18n — le menu de langue resterait vide en production
> (bug déjà rencontré et corrigé de cette façon).

## Étape 3 — Le fichier `.env` (AVANT tout redémarrage)

Créer un fichier .env à mettre à la racine dans MeOSDjango.

```bash
DEBUG=False
ALLOWED_HOSTS=son-domaine.alwaysdata.net
PUBLIC_SITE_URL=https://son-domaine.alwaysdata.net
```

- Créé **une fois, à la main** : il est gitignoré et n'est jamais déployé par git.
- Si le site utilise d'autres variables (`MOP_PASSWORD`, `SITE_NAME`,
  `CLUB_COLOR_PRIMARY`…), elles peuvent toutes y figurer.
- Une variable réellement présente dans l'environnement du process reste
  prioritaire sur le `.env`.

## Étape 4 — Pull + restauration des credentials

```bash
git pull
# Le pull retire dev_settings.py du suivi (renommé en .example.py) :
# on remet le vrai fichier, désormais ignoré par git
cp dev_settings.backup MeOSDjango/dev_settings.py

# Vérifier la clé secrète — si elle vaut 'toto', la régénérer :
grep DJANGO_SECRET_KEY MeOSDjango/dev_settings.py
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

> La régénération invalide les sessions en cours (reconnexion admin nécessaire),
> sans autre impact.

## Étape 5 — Dépendances, migrations, traductions, statiques

```bash
pip install -r requirements.txt              # inchangé depuis l'état d'origine — inoffensif
python manage.py migrate                     # no-op de sécurité (aucune migration nouvelle)
python manage.py compilemessages             # ★ CRITIQUE : locale/{en,de,sv}/*.po → .mo
python manage.py collectstatic --noinput     # site.css, JS, drapeaux SVG
python manage.py check --deploy              # avertissements à lire
```

- `compilemessages` nécessite `msgfmt` ; **sans erreur à l'exécution** — sinon le
  site reste intégralement en français pour toutes les langues.
- Site plus vieux que les colonnes `livelox` / `logo` uniquement :
  `python manage.py setup_db --dry-run` puis sans `--dry-run` (idempotent).

## Étape 6 — Redémarrage

Redémarrer le daemon Django (AlwaysData : Site → daemon, ou `systemctl restart …`).
Les settings ne sont lus qu'au démarrage du process.

## Étape 7 — Sanité de la configuration

```bash
python -c "import os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','MeOSDjango.settings'); import django; django.setup(); from django.conf import settings; print(settings.DEBUG, settings.ALLOWED_HOSTS)"
# attendu :  False ['son-domaine.alwaysdata.net']
```

## Étape 8 — Vérifications

```bash
B=https://son-domaine.alwaysdata.net

curl -s $B/ | grep -c 'name="language"'                        # 4 = menu de langue peuplé
curl -s -b 'co_lang=de' $B/ | grep -o '<title>[^<]*</title>'   # traduit (Startseite…)
curl -s -o /dev/null -w '%{http_code}\n' $B/route-inexistante-xyz   # 404 page custom → DEBUG off
curl -s -o /dev/null -w '%{http_code}\n' $B/mop/update/             # 405 = endpoint MeOS vivant
curl -s -o /dev/null -w '%{http_code}\n' $B/admin/login/            # 200
curl -s -o /dev/null -w '%{http_code}\n' $B/static/results/img/flags/gb.svg   # 200
```

Au navigateur : bascule de langue au clic sur les drapeaux, persistance après
rechargement (cookie `co_lang`), et un envoi MeOS réel vers `/mop/update/`.

---

## Comportement attendu

- **Visiteur français** : rien ne change — le français est la langue source.
- **Visiteur navigateur en / de / sv** : le site s'affiche **dès la première
  visite** dans sa langue (choix persisté 1 an ; drapeaux en menu déroulant à
  côté du titre du site).
- **URLs inchangées** : liens MeOS, `/gestion-course/<token>/`, API et CSV —
  aucune reconfiguration.

## Pièges déjà rencontrés (ne pas sauter)

1. **`skip-worktree`** : s'il est présent, `git pull` ne met pas à jour le
   fichier concerné → i18n cassé en silence (étape 2 obligatoire).
2. **`dev_settings.py`** : le pull le retire du suivi — backup/restauration
   obligatoires, sinon `NameError: DJANGO_SECRET_KEY` au démarrage.
3. **`.env` avant redémarrage** : sinon `DEBUG=True` en production (pages
   d'erreur avec stack traces).
4. **`compilemessages`** : l'étape la plus souvent oubliée — le site entier
   resterait en français.
5. **Rollback** : `git log --oneline -3` → `git checkout <hash précédent>` puis
   redémarrage du daemon.
