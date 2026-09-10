# Essai TC100 — 1.8.3-rc2

Version candidate issue de la base `5b0f4881de0fadd9a548cd62a302c59d625523b7` (1.8.2).
Les vérifications sur ordinateur ont été complétées par un déploiement réel le
10 septembre 2026 sur une TC100 AK3918. La compatibilité avec l’ash/BusyBox ARM,
les pages HTTPS, la capture, RTSP et MQTT a été vérifiée. Le test d’endurance de
24 h reste à effectuer avant une version stable.

## Interface ajoutée dans rc2

Cette version comprend le lot d’optimisation rc1 et les nouvelles améliorations UI.
Le paquet s’applique à la base 1.8.2 auditée. Si rc1 a déjà été installé, revenir à
cette base avec sa sauvegarde avant d’appliquer rc2 ; l’outil refusera les fichiers
qui ne correspondent pas, sans forcer leur remplacement.

- Réglages vidéo essentiels visibles ; encodage avancé, format audio et seuils
  jour/nuit dans des sections repliables natives. Les ouvrir ne modifie rien.
- Enregistrement séparé du flux principal et du flux secondaire, avec préservation
  des paramètres avancés. Le profil « Quality » est correctement annoncé en 720p.
- Une seule soumission simultanée, brouillon conservé sur erreur, message durable
  au niveau du formulaire. Les champs invalides cachés sont révélés et ciblés.
- Lecture corrigée des sections INI et du mode CBR/VBR. Le réglage audio écrit
  le volume et le codec de la section audio, sans remplacer le codec vidéo.
- Les enregistrements vidéo/audio sont relus une fois pour comparer les valeurs.
  Un redémarrage demandé n’est pas annoncé comme un flux rétabli. Les profils rapides
  utilisent le résultat des contrôles RTSP et du rollback déjà présents côté caméra.
- Les anciennes routes qui ne renvoient pas encore de confirmation JSON affichent
  une réponse non confirmée, au lieu d’annoncer un succès sur la seule base HTTP 200.
  Relire les réglages avant de réessayer : une confirmation absente ne prouve pas
  que l’écriture a échoué.

Aperçus sur données simulées : [mobile, thème clair](ui/settings-mobile-rc2.png) ·
[bureau, thème sombre](ui/settings-dark-rc2.png).

Pour l’essai matériel UI : modifier un seul paramètre vidéo à la fois, vérifier sa
relecture puis la reprise du flux depuis le lecteur habituel. Tester aussi le flux
secondaire et vérifier que les valeurs avancées non modifiées restent identiques.
Ne pas provoquer une panne SD réelle pour tester les erreurs : ce cas est simulé
sur ordinateur. Les détails de validation sont dans [le guide de tests UI](ui-tests.md).

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

## Validation initiale sur matériel réel

Le 10 septembre 2026, la RC2 a été installée sur une TC100 en service. Le profil
observé confirme les contraintes retenues pendant l’optimisation : ARM926EJ-S
(ARMv5TEJ), noyau Linux 3.4.35, 33 384 Kio de RAM visible, aucun swap, racine
SquashFS en lecture seule et données sur VFAT. La ligne de démarrage réserve 64 Mio,
mais environ 33 Mio seulement sont exposés à Linux. La flash SPI fait 8 Mio.

La carte SD de test présente une première partition montée de 255 Mio et une seconde
partition non montée. Le projet ne doit ni monter, ni reformater automatiquement cette
seconde partition sans identification préalable de son rôle sur chaque variante.

Contrôles réussis après installation :

- version `1.8.3-rc2`, interface et réglages servis en HTTPS ;
- empreintes des fichiers `boot.conf`, `mqtt.conf` et `rtspserver.conf` inchangées ;
- capture JPEG réelle 1280×720 ;
- flux principal H.265 1280×720 à 25 i/s et secondaire H.265 640×360 à 30 i/s détectés ;
- publication MQTT et cycle arrêt/démarrage sans processus `nc` résiduel ;
- JSON `statusline`, `healthsnapshot` et `integrationtest` valide ;
- sauvegarde locale et sur carte vérifiée avant chaque remplacement.

Le relevé CPU ponctuel avant installation variait de 53 à 100 %, pour 56–57 % de RAM
utilisée. Après installation, les lectures ponctuelles observées ont varié de 36 à 67 %
et 57 % de RAM. Les conditions n’étant pas assez longues ni strictement identiques,
ces valeurs valident l’absence de régression immédiate mais ne constituent pas encore
une mesure de gain. ONVIF était arrêté sur l’appareil et est donc signalé comme service
désactivé. Le mot de passe par défaut était encore actif ; il doit être remplacé avant
une exposition sur un réseau non fiable.

Le test d’endurance de 2 h puis 24 h et une comparaison à charge RTSP identique restent
nécessaires avant de retirer le suffixe `rc2`.

## Préparer la carte hors ligne

1. Conserver une copie complète de la carte actuelle sur l’ordinateur et noter la version,
   les flux RTSP utilisés, les services actifs et l’adresse IP. La sauvegarde automatique
   ci-dessous couvre seulement les fichiers remplacés, pas toute la carte.
2. Éteindre proprement la caméra et monter sa carte sur l’ordinateur. Ne pas appliquer
   ce lot par FTP pendant que les scripts s’exécutent. Une carte d’essai clonée permet
   de conserver la carte actuelle intacte.
3. Récupérer le [paquet d’essai disponible dans le dépôt](downloads/tc100-1.8.3-rc2-essai.zip)
   (sur GitHub, utiliser « Download raw file »), puis décompresser `tc100-1.8.3-rc2-essai.zip`. Dans ce dossier, vérifier la cible, par exemple
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
python3 essai_sd.py --sd /Volumes/TC100 --apply --backup "$HOME/tc100-avant-1.8.3-rc2"
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
python3 essai_sd.py --sd /Volumes/TC100 --rollback "$HOME/tc100-avant-1.8.3-rc2"
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
