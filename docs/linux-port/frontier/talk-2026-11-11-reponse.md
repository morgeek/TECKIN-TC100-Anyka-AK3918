# Réponse du modèle frontier au dossier `talk` (2026-11-11)

Collée dans la conversation par le propriétaire ; texte complet conservé dans l'historique de la session. Résumé des
constats, dans l'ordre de la réponse :

- **C1** — sur refus (« speaker not available »), `owner = -1` : un second client prend le haut-parleur.
- **C2** — `talk_rtp` lance le lecteur sans regarder le verrou : sortie 3, puis 2 s de son perdu.
- **C3** — `talk_shutdown` envoie SIGTERM sans attendre le lecteur : le verrou survit au serveur.
- **C4** — après le SIGKILL de `talk_tick`, personne ne retire le verrou.
- **C5** — le trap de `speaker-play.sh` sur TERM retire le verrou mais le script continue et lance aplay.
- **C6** — `talk_init` peut retirer le verrou d'un clip push-to-talk en train de démarrer (fenêtre étroite).
- **C7 / H4** — si le script met plus de 1,5 s à atteindre `mkdir`, le refus n'est pas reconnu.
- **C8** — points mineurs : la reprise réelle se fait après 2 s de silence, pas 3.
- Proposition : vérifier le verrou avant de lancer, garder le propriétaire, attendre le lecteur à l'arrêt, nettoyer
  après SIGKILL, trap `exit 143` sur INT / TERM ; durcir l'aide de test.
