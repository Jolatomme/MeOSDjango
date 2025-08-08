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
- pas d'affichage avec interpostes par catégorie (OK à l'étape 2)
- pas d'administration des courses proposées par défaut
 	(je voudrais pouvoir en mettre certaines en première page et d'autres en archives)
- pas encore de prise en compte des dixièmes de secondes

- le style global reste à revoir

## deuxième étape
- on peut à présent changer la présentation de simple à complète avec un switch sur la page (la page est rechargée)
- l'affichage complet est fonctionnel aussi bien pour les courses individuelles que les relais ou un leg au sein d'un relai

mais
- on pourrait passer de simple à complet sans recharger la page, avec du javascript
- l'affichage détaillée n'est pas adaptée au écrans mobiles

  
