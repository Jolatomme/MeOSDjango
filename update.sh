# Sur TA machine locale
git checkout nettoyage_drapeaux

# Applique les modifications une par une
git reset --hard origin/nettoyage_drapeaux  # Annule tes modifs actuelles

# Supprime les 4 drapeaux
rm -f results/static/results/img/flags/de.svg
rm -f results/static/results/img/flags/fr.svg
rm -f results/static/results/img/flags/gb.svg
rm -f results/static/results/img/flags/se.svg

# Modifie meos_tags.py (ligne 98-101)
sed -i "s/return {'en': 'gb', 'sv': 'se'}/return {'fr': 'fra', 'en': 'gbr', 'de': 'ger', 'sv': 'swe'}/" results/templatetags/meos_tags.py
sed -i "s/en → gb, sv → se/en → gbr, fr → fra, de → ger, sv → swe/" results/templatetags/meos_tags.py
sed -i "s|static/results/img/flags/<code>.svg|static/results/img/flags/nat/<code>.svg|" results/templatetags/meos_tags.py

# Modifie base.html
sed -i "s|'results/img/flags/'|'results/img/flags/nat/'|g" results/templates/results/base.html

# Modifie DEPLOY.md
sed -i "s|flags/gb.svg|flags/nat/gbr.svg|" DEPLOY.md

# Modifie test_i18n.py
sed -i "s/('fr', 'gb', 'de', 'se')/('fra', 'gbr', 'ger', 'swe')/" results/tests/test_i18n.py
sed -i "s|results/img/flags/{flag}.svg|results/img/flags/nat/{flag}.svg|g" results/tests/test_i18n.py
sed -i "s/fr \\/ Union Jack \\/ de \\/ sv/fra \\/ gbr \\/ ger \\/ swe/" results/tests/test_i18n.py
sed -i "s/('fr', 'fr'), ('en', 'gb'),/('fr', 'fra'), ('en', 'gbr'),/" results/tests/test_i18n.py
sed -i "s/('de', 'de'), ('sv', 'se')/('de', 'ger'), ('sv', 'swe')/" results/tests/test_i18n.py
sed -i "s|FLAGS_DIR / f'{flag}.svg'|FLAGS_DIR / 'nat' / f'{flag}.svg'|" results/tests/test_i18n.py

# Modifie test_views.py
sed -i "s|assert 'results/img/flags/nat/' not in html|# Vérifie qu'il n'y a pas de drapeau de nationalité (SWE, FRA, NOR, etc.)\\n        assert 'nat/SWE.svg' not in html\\n        assert 'nat/FRA.svg' not in html\\n        assert 'nat/NOR.svg' not in html|" results/tests/test_views.py

# Vérifie les modifications
git diff --stat

# Commit et push
git add -A
git commit -m "Nettoyage: pointe vers flags/nat/ avec codes ger/fra/gbr/swe"
git push origin nettoyage_drapeaux
