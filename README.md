# MeOS Results — Site de résultats Course d'Orientation

Site web Django pour afficher les résultats de courses d'orientation gérées avec **MeOS**, avec un rendu Bootstrap 5 moderne.

## Prérequis

- Python 3.10+
- MySQL 5.7+ (base de données MeOS existante)
- `libmysqlclient-dev` (Linux) ou MySQL Connector (Windows)

## Installation

```bash
# 1. Cloner / déposer le projet
cd meos_results

# 2. Environnement virtuel
python -m venv venv
source venv/bin/activate          # Linux/Mac
venv\Scripts\activate.bat         # Windows

# 3. Dépendances
pip install -r requirements.txt

# 4. Configuration (créer un fichier .env à la racine)
cp .env.example .env
nano .env
```

## Configuration `.env`

```ini
# Connexion base de données MeOS
MEOS_DB_NAME=meos
MEOS_DB_USER=root
MEOS_DB_PASSWORD=votre_mot_de_passe
MEOS_DB_HOST=127.0.0.1
MEOS_DB_PORT=3306

# Apparence du site
SITE_NAME=Résultats CO
SITE_SUBTITLE=Course d'Orientation
CLUB_NAME=Votre Club
CLUB_COLOR_PRIMARY=#1a6b3c
CLUB_COLOR_ACCENT=#f0a500
```

## Lancement

```bash
# Appliquer les migrations Django (auth, sessions…)
python manage.py migrate

# Créer un super-utilisateur pour l'admin (optionnel)
python manage.py createsuperuser

# Lancer le serveur de développement
python manage.py runserver
```

Ouvrir → http://127.0.0.1:8000

## Structure du projet

```
meos_results/
├── meos_results/          # Configuration Django
│   ├── settings.py        # Paramètres (DB, static…)
│   └── urls.py            # Routes principales
├── results/               # Application principale
│   ├── models.py          # Modèles MeOS (managed=False)
│   ├── views.py           # Vues (home, classement, splits…)
│   ├── urls.py            # Routes de l'app
│   ├── context_processors.py
│   ├── templatetags/
│   │   └── meos_tags.py   # Filtres personnalisés
│   └── templates/results/
│       ├── base.html      # Template de base Bootstrap 5
│       ├── home.html      # Liste des épreuves
│       ├── event_detail.html   # Catégories d'une épreuve
│       ├── class_results.html  # Classement par catégorie
│       ├── runner_detail.html  # Fiche + intermédiaires
│       ├── club_results.html   # Résultats par club
│       └── statistics.html    # Statistiques globales
└── requirements.txt
```

## Structure de la base MeOS

Le site lit les tables MeOS en lecture seule (`managed = False`).

| Table MeOS   | Modèle Django | Contenu                  |
|-------------|---------------|--------------------------|
| `oEvent`    | `Event`       | Épreuves                 |
| `oClass`    | `Class`       | Catégories (H21E, D20…)  |
| `oClub`     | `Club`        | Clubs                    |
| `oCourse`   | `Course`      | Circuits                 |
| `oRunner`   | `Runner`      | Concurrents + résultats  |
| `oFreePunch`| `SplitTime`   | Temps intermédiaires     |

## Pages disponibles

| URL | Description |
|-----|-------------|
| `/` | Liste des épreuves |
| `/event/<id>/` | Catégories d'une épreuve |
| `/event/<id>/class/<id>/` | Classement par catégorie |
| `/event/<id>/runner/<id>/` | Fiche concurrent + splits |
| `/event/<id>/club/<id>/` | Résultats d'un club |
| `/event/<id>/stats/` | Statistiques globales |
| `/api/class/<id>/results/` | JSON (refresh live) |

## Personnalisation

- **Couleurs / nom du club** → variables `CLUB_COLOR_*` et `CLUB_NAME` dans `.env`
- **Logo** → remplacer l'icône Bootstrap dans `base.html`
- **Langue** → changer `LANGUAGE_CODE` dans `settings.py`

## Rafraîchissement en direct

L'endpoint `/api/class/<id>/results/` retourne du JSON.
Pour un affichage live, appelez-le toutes les 30 secondes :

```js
setInterval(() => {
  fetch('/api/class/42/results/')
    .then(r => r.json())
    .then(data => updateTable(data.results));
}, 30000);
```

## Mise a jour de la course en direct

Configuration MeOS
Dans MeOS : Outils → Serveur Online → Configurer

Adresse : http://votre-serveur/mop/update/
Mot de passe : la valeur de MOP_PASSWORD dans settings.py (défaut : meos)

Pour changer le mot de passe en production, utiliser la variable d'environnement :
```bash
export MOP_PASSWORD="monMotDePasseSécurisé"
```

## Tests de non-régression
```bash
pytest results/tests/
```

