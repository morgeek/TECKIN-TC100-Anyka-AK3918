# Essai TC100 — 1.8.3-rc1

Version candidate issue de la base `5b0f4881de0fadd9a548cd62a302c59d625523b7` (1.8.2).
Les vérifications ont été exécutées sur ordinateur, avec fichiers et services simulés.
**Aucun déploiement ni essai sur la caméra n’a été effectué.** La compatibilité avec
l’ash/BusyBox ARM et les gains réels de CPU/RAM restent à mesurer sur l’appareil.

## Changements et budget de ressources

| Zone | Modification | Effet attendu / compromis |
|---|---|---|
| Tableau de bord | Réutilise la collecte `statusline` principale ; supprime la collecte supplémentaire toutes les 4 s | Moins de CGI, de forks et de requêtes Wi-Fi. Jauges mises à jour au rythme principal, généralement 20 à 30 s selon le profil |
| Santé | Respecte l’intervalle configuré, 60 s par défaut ; cache adapté à cet intervalle | Évite de refaire les sondes avant la prochaine collecte ; un changement peut apparaître plus tard |
| Mémoire | Soustrait `Shmem` de l’estimation de mémoire récupérable | Affichage plus prudent sur l’ancien noyau ; il s’agit d’une estimation, pas du `MemAvailable` d’un noyau récent |
| MQTT | Décode uniquement les octets non lus, par blocs de 16 Kio ; trames de commande limitées à 4 Kio, sujet inclus | Mémoire du décodeur bornée par bloc plutôt que par toute la session ; l’AWK consomme davantage que les seuls 16 Kio bruts |
| Capture MQTT | Deux captures au maximum, chacune limitée par `ulimit -f 128` | Jusqu’à 256 Kio de capture brute, suivant l’unité de `ulimit` ; reconnexion si le plafond est atteint |
| Reconnexions MQTT | Identifiant distinct par session, suivi des processus enfants, Will `offline` retenu et annonce `online` | Corrige les offsets réutilisés et ajoute le Will à l’abonnement. QoS 0 conservé : ce n’est pas une garantie de livraison |
| Configuration | Aucun `sync`/remplacement si la valeur est identique ; installation sans hachage/jeton temporaire | Moins de forks, de synchronisations et d’écritures SD ; correction de la récursion de `action.cgi` |
| Éditeur | Un seul lecteur du corps POST ; contrôle de longueur et de syntaxe shell ; remplacement par fichier temporaire ; une sauvegarde précédente par fichier dans `/tmp` | Évite une sauvegarde vide ou tronquée ; limite l’accumulation des sauvegardes. Le contrôle de syntaxe ne rend pas un contenu shell non fiable sûr |
| Import tar.gz | 1 Mio compressé, 2 Mio décompressés, 512 entrées ; liens refusés | Réduit les pics possibles dans `/tmp` ; archives plus grandes refusées |
| Commandes web | POST avec jeton CSRF sur les routes corrigées ; JavaScript actualisé et URLs versionnées | Les intégrations qui modifient ces routes par GET doivent être adaptées |
| Services | Suppression du watchdog FTP inconditionnel ; FTP/Telnet refusent un démarrage si `SECURITY_HARDENING_MODE=1` | Évite un service indésirable et sa surveillance en arrière-plan |
| Divers | Dates de sauvegarde/timelapse corrigées, manifeste de restauration des paquets, délai de vérification des mises à jour limité | Rétablit ces fonctions et borne l’attente réseau |

Le vidage du cache mémoire en fin de démarrage est supprimé. Le modèle
`boot.conf.dist` désactive aussi `MEM_GUARD_DROP_CACHES` pour les nouvelles installations.
**Un `boot.conf` existant n’est pas réécrit** : sa valeur conserve son effet.
Aucun nouveau service résident, aucune bibliothèque et aucun binaire ARM n’ont été ajoutés.
Les codecs, résolutions, débits vidéo, fréquences CPU, identifiants et paramètres réseau
existants restent ceux de la carte.

## Validation sur ordinateur

Depuis le dépôt modifié, avec Python 3, Bash et Node.js disponibles :

```sh
python3 -m unittest discover -s tests -v
```

La suite contrôle les scripts shell et JavaScript, les empreintes des 25 binaires et
bibliothèques verrouillés, l’éditeur, les gardes HTTP, les uploads, les archives, la
restauration des paquets, les dates, la mémoire, le JavaScript et MQTT.
Les fonctions embarquées sont exercées dans des fichiers temporaires ; les opérations
matérielles ne sont pas exécutées. Les tests de sockets utilisent un substitut de `nc`.
Le paquet d’essai ajoute un test indépendant d’application/retour arrière sur une fausse carte.

## Préparer la carte hors ligne

1. Conserver une copie complète de la carte actuelle sur l’ordinateur et noter la version,
   les flux RTSP utilisés, les services actifs et l’adresse IP. La sauvegarde automatique
   ci-dessous couvre seulement les fichiers remplacés, pas toute la carte.
2. Éteindre proprement la caméra et monter sa carte sur l’ordinateur. Ne pas appliquer
   ce lot par FTP pendant que les scripts s’exécutent. Une carte d’essai clonée permet
   de conserver la carte actuelle intacte.
3. Récupérer le [paquet d’essai disponible dans le dépôt](downloads/tc100-1.8.3-rc1-essai.zip)
   (sur GitHub, utiliser « Download raw file »), puis décompresser `tc100-1.8.3-rc1-essai.zip`. Dans ce dossier, vérifier la cible, par exemple
   sur macOS (adapter le nom du volume) :

```sh
python3 essai_sd.py --sd /Volumes/TC100
```

Cette commande est en lecture seule. Elle vérifie chaque fichier contre la base auditée.
Si une version diffère ou si un script a été personnalisé, elle s’arrête : conserver le
message pour adapter le correctif à cette version, sans forcer l’écrasement.

4. Appliquer seulement après cette vérification, avec un **nouveau** dossier de sauvegarde
   hors de la carte. L’outil sauvegarde et vérifie tous les originaux avant la première
   écriture sur la carte ; les fichiers sont remplacés individuellement :

```sh
python3 essai_sd.py --sd /Volumes/TC100 --apply --backup "$HOME/tc100-avant-1.8.3-rc1"
```

5. Éjecter proprement la carte, la replacer puis démarrer la caméra. Le remplacement de
   tout le lot n’est pas une transaction atomique face à une déconnexion de la carte :
   garder la sauvegarde sur l’ordinateur jusqu’à validation complète.

## Essai matériel progressif

Faire une mesure de référence avant installation et reprendre le même scénario après :
**même profil, même nombre de clients RTSP, mêmes conditions Wi-Fi, même durée**.
Attendre deux minutes après démarrage avant de comparer.

| Étape | Vérification | Acceptation |
|---|---|---|
| Démarrage | Interface, adresse IP, flux RTSP principal et secondaire déjà utilisés | Accès retrouvé, image et débit conformes aux réglages existants |
| Charge | 15 minutes de vidéo, interface fermée, puis 15 minutes tableau de bord ouvert | Pas de redémarrage, pas de nouvelle coupure vidéo ; comparer CPU/RAM avec la référence |
| Interface | Rechargement forcé, navigation répétée dans les réglages, contrôle sans danger tel que la LED | Pas de commandes refusées à tort ; dans l’onglet Réseau, disparition de la collecte `statusline` supplémentaire toutes les 4 s |
| Santé | Lire `health.cgi` à plusieurs reprises | Cache réutilisé, intervalle conforme au `boot.conf`, champs mémoire numériques et plausibles |
| MQTT | Commande LED ; reconnecter le bridge/broker, puis refaire une commande | Commandes reçues après reconnexion, pas de multiplication des processus `nc` ni de croissance continue des captures |
| MQTT hors ligne | Si MQTT est utilisé, interrompre sa connexion dans un essai contrôlé | Will `offline` visible selon le délai keepalive du broker, retour `online` à la reconnexion |
| Éditeur | Enregistrer un fichier autorisé **sans le changer**, puis relire | Contenu conservé, réponse « Unchanged » ; pas de fichier vide |
| Sauvegardes | Télécharger une sauvegarde et examiner son contenu sur ordinateur | Archive valide, répertoires `config/` attendus. Réserver la restauration à la carte d’essai |
| Endurance | 2 h, puis idéalement 24 h dans l’usage habituel | Aucun OOM, aucun redémarrage imprévu, vidéo stable, captures MQTT toujours bornées |

Pour les relevés, utiliser l’accès de maintenance déjà configuré. Il n’est pas nécessaire
d’ouvrir FTP/Telnet pour ce test. Depuis cet accès, quelques commandes en lecture seule :

```sh
cat /proc/meminfo
cat /proc/loadavg
cat /proc/uptime
cat /tmp/health_snapshot.interval
ls -l /tmp/mqtt_stream.bin.*
ps
```

La charge (`loadavg`) n’est pas un pourcentage CPU. Employer la même méthode de mesure
CPU avant/après (interface ou outil déjà présent), et transmettre les deux relevés.
Ne pas effacer les caches mémoire avant une mesure : cela change la charge d’E/S.
Les captures MQTT peuvent contenir des commandes ; ne pas publier leur contenu brut.

## Retour arrière

Si la vidéo devient instable ou l’interface inaccessible, éteindre la caméra et remonter
la carte sur l’ordinateur. Depuis le dossier du paquet :

```sh
python3 essai_sd.py --sd /Volumes/TC100 --rollback "$HOME/tc100-avant-1.8.3-rc1"
```

L’outil vérifie les sauvegardes et refuse d’écraser un fichier ayant subi une troisième
modification depuis l’essai. En cas de carte illisible ou de contenu tronqué après une
coupure d’alimentation, utiliser la copie complète préparée avant l’essai. Éjecter la
carte puis redémarrer. Les réglages personnels n’ayant pas été modifiés par le paquet,
ils n’ont pas besoin d’être restaurés pour revenir au code précédent.

## Chantiers non inclus dans ce lot

Ce lot ne clôt pas tous les points de l’audit. Restent notamment la sérialisation sûre
et la validation sémantique de tous les fichiers de configuration sourcés, l’import JSON
`config_exchange.cgi`, la confidentialité persistante au démarrage, le dimensionnement
des journaux et enregistrements, la stratégie du CPU scaler/memory guard et la chaîne de
recompilation des binaires anciens. L’import d’archive n’est pas une transaction complète
avec rollback automatique sur erreur d’extraction. Les configurations importées doivent
provenir d’une sauvegarde de confiance.

Lors de fortes rafales MQTT, un recyclage de capture peut abandonner un reliquat de
commandes non traité ; le protocole utilisé reste QoS 0.

Ces changements plus larges nécessitent des essais ciblés ; cette version candidate
privilégie un premier lot mesurable sans modifier les paramètres de capture existants.
