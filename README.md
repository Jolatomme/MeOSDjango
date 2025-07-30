# MeOSDjango
Django development for MeOS Orienteering results display.

a long way to go...

## première étape
- les compétitions s'affichent en liste
- les catégories de la compétition sélectionnée s'affichent,
	y compris les legs au sein de chaque catégorie s'il s'agit d'un relai
- les résultats d'une catégorie s'affichent en liste simple (sans les interpostes)
- les résultats individuels s'affichent en liste avec les interpostes
- ajout de vérification sur les paramètres des url avec renvoi d'erreur 404 si besoin
- ajout d'un titre personnalisé à chaque page renvoyée pour la navigation dans l'historique du navigateur

mais :
- pas de navigation possible entre les catégories ou les concurrents dans l'affichage en liste
- pas d'affichage avec interpostes par catégorie
- pas d'administration des courses proposées par défaut
 	(je voudrais pouvoir en mettre certaines en première page et d'autres en archives)
- pas encore de prise en compte des dixièmes de secondes

- le style global reste à revoir
