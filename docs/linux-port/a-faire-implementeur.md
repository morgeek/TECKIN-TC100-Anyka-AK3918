# À faire pour l'implémenteur — liste consolidée (testeur, 2026-11-04 19:50)

Une seule liste de ce qui reste ouvert après la rc25, par priorité. Les détails et les mesures sont dans
`test-queue.md` (entrées du 2026-11-03 et 2026-11-04), `audit-2026-11-03.md`, `audit-2026-11-04.md` et la checklist
`release-3.0.1.md`. État des caméras ce soir : **.11 en rc25** (pays FR, pont MQTT en C, `RTSP_QMAX=1024`, nuit de
mesure en cours), **.24 en rc23** (témoin). Cocher ici ou dans `release-3.0.1.md` quand c'est fait.

## P0 — rc26, avant le tag 3.0.1

1. [ ] **Publier une rc26** avec ce qui est sur `main` depuis la rc25, en particulier `04f2313` + `9853759` : arrêt du
   pont MQTT en C (`stop` laissait le démon tourner, un deuxième démon démarrait avec le même client id, `availability`
   basculait toutes les 2 s). Aujourd'hui le correctif n'existe sur la .11 qu'en RAM.
2. [ ] **Supprimer les sous-shells qui restent en mémoire** (~0,3 Mo, aucun C à écrire) :
   - `controlscripts/mqtt-bridge start` : `run_busybox nohup … &` garde un `sh mqtt-bridge start` vivant (217 Ko PSS)
     parent du démon. Proposition : `( exec "$BUSYBOX_BIN" nohup "$BIN" … ) &` (ou `nohup "$BIN" … &` direct) : `$!`
     devient alors le pid du démon lui-même, ce qui règle aussi la cause du point 1 ; idem pour le pont shell.
   - `/etc/init.d/S39tc100 start` reste vivant après le démarrage (90 Ko PSS) : `exec` sur la dernière commande ou
     ne pas attendre.
3. [ ] **Points ouverts de la checklist** : W4 (assistant sans jeton CSRF), B3 (`flashw -m` compare le fichier à
   lui-même, avec B1), D8 (passe de documentation : `api.md` cite encore HTTPS et `set_web_mode`, `wifi_set_country`
   non documenté…). B1 et W4 : décision du propriétaire reportée, à lui reposer avant le tag.
4. [x] **Retirer la mention « CVE-2026-98432 »** de l'entrée rc24 et de la checklist : mention retirée.
5. [x] **Petits restes de config** :
   - `boot.conf.dist` : `MEM_GUARD_SOFT_SERVICES=""` nettoyé ;
   - `config/autostart/memory-guard` retiré du dépôt (`MEM_GUARD_ENABLE=0` est le switch unique) ;
   - `mqtt.conf` : documenté la règle de dérivation du topic root basée sur le hostname (`_mb_slug`).
6. [ ] **Plans de test : mesurer la RAM en PSS** (`/proc/<pid>/smaps_rollup`), pas en RSS : le critère « RSS du
   démon bien en dessous des 5,7 Mo » comparait du code busybox partagé compté 7 fois (gain réel du pont C ≈ 0,9 Mo).
7. [ ] **Tests restants avant le tag** (testeur + propriétaire) : anti-masquage avec la main ; SD sur la .24 (plus de
   « not properly unmounted » après un redémarrage voulu) ; notification ntfy ou Telegram réelle ; RTSP en **UDP**
   (non testable depuis la VM du testeur, NAT : à faire par le propriétaire avec VLC ou Frigate) ; nuit en mode
   MQTT C (soak en cours sur la .11).

## P1 — 3.0.2 (fiabilité et image)

8. [ ] **Support natif d'une résolution intermédiaire 720p (1280×720)** :
   - Rendre la géométrie du flux principal configurable dans `tc100_rtsp` (`main_w`, `main_h`, options `-W`/`-H` ou `RTSP_WIDTH`/`RTSP_HEIGHT`).
   - Mettre à jour `rtsp-launch.sh` pour lire `[0] width` et `[0] height` dans `rtspserver.conf` et passer les arguments.
   - Adapter `scripts/action.d/video.sh` (`cmd=set_video_params`) pour accepter `video_size0=1280x720` (au lieu de forcer `1920x1080`).
   - Ajouter le sélecteur de résolution dans l'interface Web (`Settings → Main stream`, 1080p / 720p).
   - Gains : ~45 % de pixels en moins, soulage la bande passante bus DMA, l'encodeur matériel et libère ~1,7 Mo par trame NV12.

9. [ ] **Build noyau pour le mode smart de l'encodeur** (essai sur la .11) : valeur par défaut compilée
   `ak39_venc.pool=12M` (patch 0015 ; le paramètre est `0444` et la ligne de commande vient du bootloader : pas de
   U-Boot). Puis `RTSP_VBR=1` + `RTSP_SMART=1` (mode 1 seulement). Critères : `smart mode 1 (long-term reference)`
   dans le log, pas de `alloc dma … failed`, serveur vivant 24 h, MemAvailable ~2,4 Mo plus bas, débit et qualité
   comparés à la .24.
9. [ ] **Pertes Wi-Fi** (7-11 % des mesures la nuit rc23, indépendantes d'une caméra à l'autre) : attendre le bilan
   de cette nuit (.11 : regdb + FR + `RTSP_QMAX=1024` ; .24 : rc23). Si la file plus grande réduit les images sautées
   sans gêner le direct, passer `QMAX_DEF` à 1 Mo par défaut ; ensuite essai `RTSP_PACING_US`, puis canal Wi-Fi de la
   box (décision du propriétaire).
10. [ ] **Mémoire de la .24** : 20,5 Mo disponibles hier soir, 18,6 Mo après 23 h 40 (enregistrement SD actif) :
    vérifier demain matin si c'est du cache ou une dérive.
11. [ ] **Chantier audio natif ultra-léger (zéro surcoût / gain RAM & CPU)** :
    - **Capture ALSA directe dans `tc100_rtsp`** au lieu du sous-processus `arecord` : libère ~660 Ko PSS et supprime les pipes et changements de contexte noyau réguliers.
    - **Filtre passe-haut (High-Pass / Anti-Rumble)** : filtre biquad IIR léger à virgule fixe coupant à 150-200 Hz (suppression du ronflement 50 Hz d'alim et des bruits d'air sourds sans altérer la voix ; coût CPU < 0,2 % d'un cœur).
    - **Noise gate & AGC soft-clipping à virgule fixe** : atténue le souffle en pièce silencieuse et équilibre le volume des voix éloignées sans saturation.
    - **Coupure anti-larsen (half-duplex PTT)** : atténuation/coupure automatique du micro pendant la lecture haut-parleur (évite l'écho en retour).
    - *(Optionnel / P2)* Encodeur AAC compact pour la piste MP4 sur carte SD afin d'assurer une lecture HTML5 universelle dans le navigateur sans transcodage.
12. [ ] **Support ONVIF Profile T (Audio Backchannel standardisé)** :
    - La gestion du retour audio bidirectionnel (`Require: www.onvif.org/ver20/backchannel`, piste `track3` PCMA 8 kHz) est déjà implémentée dans `src/tc100rtsp/talk.c`.
    - Objectif : exposer l'AudioBackChannel dans la réponse ONVIF Device / Media2 service pour permettre le Two-Way Audio natif instantané dans Home Assistant (WebRTC / Go2RTC) et Frigate sans bidouille URL manuelle.
    - Coût CPU / RAM : 0 % (métadonnées XML / profil statique côté démon ONVIF + exploitation du code RTSP déjà présent dans `tc100_rtsp`).
13. [ ] **Régulation de trafic réseau / Pacing RTSP (`tc100_rtsp`)** :
    - Lissage temporel de l'envoi des paquets RTP lors des pics d'I-frames H.264/H.265 (pacing microsecondes `RTSP_PACING_US`).
    - Évite la saturation du tampon de transmission du pilote RTL8188FU lors des images clés, réduisant drastiquement les pertes de paquets Wi-Fi sans impacter la latence vidéo.
14. [ ] **Garde thermique dynamique (Thermal Guard)** :
    - Lecture périodique de `chip_temp` (`/sys/class/thermal/thermal_zone0/temp` ou capteur SoC).
    - En cas de surchauffe (> 75-80°C lors de canicules ou forte charge continue), réduction automatique et temporaire de la fréquence d'images (25 fps -> 15 fps).
    - Reprise automatique dès refroidissement sous le seuil d'hystérésis.
15. [ ] **Politique de rétention intelligente sur carte SD (FIFO hiérarchique)** :
    - Distinguer les enregistrements continus de fond des clips d'événements (détection de mouvement, bruit / VOX, falsification / tamper).
    - En cas d'espace disque saturé, supprimer d'abord les fichiers continus anciens et sanctuariser les vidéos d'alerte pour éviter toute perte critique.
16. [ ] **Anti-scintillement automatique (Auto Anti-Flicker 50/60 Hz)** :
    - Détection de la fréquence secteur (50 Hz en Europe, 60 Hz en Amérique) ou commutation fluide selon configuration dans l'ISP afin d'éliminer les bandes de défilement sous éclairage LED / fluorescent sans nécessiter de redémarrage.
17. [ ] **Watchdog Wi-Fi & Reconnexion douce (Auto-Healing)** :
    - Script/boucle légère vérifiant la joignabilité de la passerelle (toutes les 60 s).
    - Tentative de reconnexion douce via `wpa_cli reassociate` ou réveil de l'interface `wlan0`.
    - Si échec persistant, déchargement et rechargement propre du module USB `8188fu.ko` sans reboot complet de la caméra.
18. [ ] **Débit binaire adaptatif automatique (Auto-ABR dans `tc100_rtsp`)** :
    - Mesure du remplissage du buffer d'envoi RTSP / perte Wi-Fi.
    - Réduction dynamique temporaire du bitrate de l'encodeur matériel (ex: 2000 -> 1000 kbps) via `libakuio`, puis rétablissement à la normale une fois la liaison stabilisée.
19. [ ] **Détection de mouvement matérielle zéro CPU (VPU / P-frame stats)** :
    - L'encodeur matériel AK3918 calcule déjà les vecteurs de mouvement et les macroblocs inter/intra.
    - Exploitation de la taille des trames P ou des compteurs MB dans `tc100_rtsp` : une trame P passe de 2 Ko (immobile) à 20-30 Ko (mouvement).
    - Déclenchement instantané d'événements MQTT (`teckin/motion = ON`) et d'enregistrements SD sans consommer de CPU en décompression d'images.
20. [ ] **Snapshot JPEG direct sur événement MQTT (`teckin/snapshot`)** :
    - Capture d'une vignette JPEG légère depuis le sub-stream 640×360 lors d'un déclenchement (mouvement, bruit VOX, bouton).
    - Publication dans un topic MQTT pour affichage immédiat dans les notifications mobiles (Home Assistant Companion, Telegram, ntfy).
21. [ ] **Hystérésis temporelle et adoucissement Jour / Nuit** :
    - Verrouillage anti-rebond temporisé (au moins 60 s) après commutation du filtre IR-Cut pour éliminer le cliquetis en zone de pénombre crépusculaire.
    - Transition progressive de l'exposition/gain AWB lors de l'allumage des LED IR pour éviter le flash blanc.
22. [ ] **Sauvegarde / Restauration 1-clic de la configuration Web** :
    - Export/Import d'une archive `.tar.gz` de `/mnt/config/` depuis l'interface Web pour cloner ou restaurer rapidement des caméras (.11 <-> .24).
23. [ ] **Mode Point d'accès de secours (Failover AP Setup)** :
    - En cas d'échec de connexion Wi-Fi prolongé au boot (> 3 min), basculement du dongle `8188fu` en point d'accès Wi-Fi temporaire (SSID `Teckin-Setup`, IP `192.168.4.1`) avec interface Web minimale de configuration pour éviter d'avoir à brancher le câble série ou sortir la SD.
24. [ ] **Synchronisation horaire hybride (NTP + fallback HTTP Header `Date`)** :
    - En cas d'échec de synchronisation NTP (port UDP 123 bloqué ou filtré par pare-feu / box), requêter en HTTP `HEAD` un serveur fiable (`google.com`, `cloudflare.com` ou passerelle locale).
    - Extraction du header `Date: ...` et mise à l'heure système via `date -s` pour garantir des horodatages valides sur les enregistrements et certificats.
25. [ ] **Mode Confidentialité matériel / logiciel (Privacy Mode)** :
    - Commutateur Web et MQTT (`teckin/privacy/set = ON`).
    - Coupure logicielle immédiate du flux vidéo (trame noire avec mention "Privé / Inactif") et coupure de la capture micro ALSA (`amixer set Capture nocap`).
    - Optionnellement, extinction des LED d'état et mise en veille du capteur d'image JX-F23 (ou arrêt du flux ISP/RTSP) pour préserver l'intimité lors du désarmement d'alarme.
26. [ ] **Boutons d'action sirène et carillon sur l'interface Web** :
    - Les fichiers audio `sounds/siren.pcm`, `sounds/alert.pcm`, `sounds/chime.pcm` existent déjà dans le dépôt et sont câblés dans `scripts/mqtt-bridge.sh` (`play_sound`).
    - Ajouter les boutons d'action rapide dans l'interface Web (Dashboard / Actions rapides) pour déclencher la sirène ou le carillon en un clic sans passer par un script externe.
27. [ ] **Endpoint de métriques Prometheus minimaliste (`/metrics`)** :
    - Exposition texte brut ultra-légère par `httpfront` (format Prometheus / OpenMetrics standard, zéro parsing JSON).
    - Métriques clés : `tc100_chip_temp_celsius`, `tc100_memory_available_bytes`, `tc100_wifi_rssi_dbm`, `tc100_rtsp_clients_connected`, `tc100_rtsp_drops_total`, `tc100_sdcard_free_bytes`.
    - Permet l'intégration native et directe dans Grafana / Prometheus / VictoriaMetrics et Home Assistant sans surcoût CPU/RAM.
28. [ ] **Nettoyage et rotation circulaire des logs en RAM (`tmpfs`)** :
    - Écrêtage périodique automatique dans `housekeeper` des fichiers journaux (`/tmp/*.log`, dmesg) avec plafond strict (ex: 64 Ko max par log via `tail -n 100`).
    - Prévient toute érosion lente de la RAM disponible lors de fonctionnements ininterrompus sur plusieurs semaines.
29. [ ] **Accélération WebUI : Assets pré-compressés (gzip) & Cache HTTP agressif** :
    - Pré-compression statique des fichiers JS/CSS en `.gz` lors du build CI ; `httpfront` sert directement le flux compressé si `Accept-Encoding: gzip` est présent (0 cycle CPU de compression).
    - Ajout des en-têtes `Cache-Control: public, max-age=86400, immutable` et `ETag` pour rendre le chargement de l'interface Web quasi instantané depuis le cache navigateur.
30. [ ] **Pare-feu anti-brute-force ultra-léger en noyau (`iptables -m recent`)** :
    - Règle noyau bloquant temporairement (10 min) toute adresse IP source tentant plus de 5 connexions SSH / requêtes en échec consécutives en moins de 60 secondes (répond au point W3 de l'audit).
    - Coût RAM et CPU : quasi nul (100 % géré par la table d'états interne de Netfilter sans aucun démon en espace utilisateur).
31. [ ] **Profils dynamiques de performance (« Mode Veille / Nuit Éco »)** :
    - En absence de client RTSP connecté ou lors de la bascule en vision nocturne, ajustement automatique du framerate cible (25 fps -> 15 fps).
    - Rétablissement instantané à 25 fps dès la connexion d'un client RTSP ou la détection d'un événement (mouvement/son).
    - Gain : baisse de 3 à 5°C de la température SoC et réduction du bruit thermique sur le capteur JX-F23.
32. [ ] **Aide au positionnement Wi-Fi & Diagnostic passif** :
    - Affichage de la qualité du lien Wi-Fi en dBm avec code couleur sur le tableau de bord web.
    - Option de retour visuel sur la LED frontale (rythme de pulsation proportionnel au RSSI) pendant les 5 minutes suivant le démarrage pour orienter la caméra sans écran.
33. [ ] **Enregistrement avec « Pre-Roll » circulaire en RAM (Buffer continu 3 à 5 s)** :
    - Maintenir en mémoire vive un anneau circulaire (ring-buffer) des 3 à 5 dernières secondes de vidéo encodée H.264 (~600 à 900 Ko de RAM consommée).
    - Lors d'un déclenchement d'alarme (mouvement, son, tamper), le clip MP4 écrit sur la carte SD intègre ces secondes préalables, assurant de voir l'amorce de l'action plutôt que l'intrus déjà en train de sortir.
34. [ ] **Envoi de secours hors-site sur alerte critique (Cloud / Telegram / Webhook)** :
    - Sur détection de sabotage (tamper) ou intrusion confirmée, expédition immédiate d'une rafale de 3 snapshots HD ou d'un clip court vers un canal hors-site sécurisé (bot Telegram, webhook ntfy/Home Assistant ou stockage S3/WebDAV).
    - Protège les preuves d'intrusion même en cas de vol, d'arrachage de la caméra ou d'extraction de la carte SD par l'intrus.
35. [ ] **Passerelle WebRTC / WHEP directe ultra-légère dans `tc100_rtsp`** :
    - Protocole WHEP (WebRTC HTTP Egress Protocol) pour streaming direct vers les navigateurs sans serveur intermédiaire (Go2RTC/MediaMTX).
    - Exploitation directe des paquets RTP H.264/H.265 et audio PCMA déjà packagés en interne, avec latence inférieure à 150 ms dans le WebUI.
36. [ ] **Frise chronologique interactive dans le WebUI (Timeline & Replay scrubbing)** :
    - Interface temporelle fluide HTML5/Canvas pour naviguer dans les enregistrements sur carte SD sur 24 heures.
    - Représentation visuelle des blocs d'enregistrement continu et surlignage coloré des événements marquants (mouvements, bruits VOX, sabotages).
    - Clic ou scrub sur la frise pour charger instantanément le lecteur vidéo MP4 à la seconde exacte sans recharger la page.
    - Zéro charge CPU/RAM pour la caméra : rendu 100 % côté navigateur client à partir d'un fichier index compact.
37. [ ] **Réduction du bruit spatiale adaptative sans allocation CMA (2D-NR dynamique par gain ISP)** :
    - Le 3D-NR matériel étant désactivé par manque de mémoire tampon dans le pool CMA (18 Mo), exploiter dynamiquement le filtre spatial 2D-NR de l'ISP.
    - Asservir le niveau de lissage et le coring au gain capteur en temps réel (`ispx_ae_report`) : netteté maximale et piqué fin en plein jour, atténuation progressive du fourmillement sur les aplats sombres la nuit.
    - Gain : image nocturne nettement plus propre et économie de 20 à 30 % de bande passante / débit H.264 sans aucun octet de RAM supplémentaire.
38. [ ] **Audit du 2026-11-04, points ouverts** : B4, B5, B6, W2 (`NET_LAN_ONLY` sans effet sur le web, ssh et RTSP
    en 3.0 alors que la doc dit le contraire), W3 (mot de passe par défaut public, pas de limite d'essais), W6
    (secrets dans des GET), R1 (clients RTSP TCP sans expiration, `MAXCLI 4`), R2 (`httpfront` : un fork par
    connexion sans plafond), R3, D1-D7, D9.

## P2 — plus tard, seulement si un besoin apparaît

39. [ ] Un seul démon C pour `sound-detection`, `housekeeper`, `auto-night-daemon`, `cfg-persist`,
    `service-watchdog`, `button-watch` (~1 Mo PSS au total) : beaucoup de logique testée à réécrire ; la RAM n'est
    pas le goulot (20 Mo stables la nuit, aucune fuite).
40. [ ] Reconstruire `rwconf` / `getflag` / `getimage` depuis leurs sources en CI ; remplacer `monvifd` (binaire sans
    source ni licence) par un répondeur WS-Discovery libre.

## Hors implémenteur (propriétaire)

- Accord pour archiver ~50 notes anciennes du projet claude.ai et `_archive_v3-drafts/`.
- Décisions B1 et W4 (voir `audit-2026-11-04.md` §6).
