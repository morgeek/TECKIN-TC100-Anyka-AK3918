# À faire pour l'implémenteur — liste consolidée (testeur, 2026-11-04 19:50 ; mise à jour implémenteur 2026-11-05 11:00)

Une seule liste de ce qui reste ouvert après la rc25, par priorité. Les détails et les mesures sont dans
`test-queue.md` (entrées du 2026-11-03 au 2026-11-05), `audit-2026-11-03.md`, `audit-2026-11-04.md` et la checklist
`release-3.0.1.md`. État des caméras le 2026-11-05 matin : **.11 en rc25** (pays FR, pont MQTT en C,
`RTSP_QMAX=1024` ; la rc26 est la prochaine étape), **.24 en rc25** depuis le 2026-11-04 au soir (plus de témoin).
Cocher ici ou dans `release-3.0.1.md` quand c'est fait.

## État au 2026-11-05 (résumé)

**Validé sur caméra** (testeur, .11 rc25, entrées du 2026-11-04 18:55 / 19:20 et bilan de nuit du 2026-11-05 09:50) :
`regulatory.db` et pays Wi-Fi FR (0 perte pendant l'application) ; correctifs de l'audit du 03/11 (valeurs MQTT
refusées, XSS de `viewrecords` / `camcontrols` / `showlog`, `frigateyaml` sans mot de passe, `integrationmanifest`
25 fps) ; TLS sortant avec le bundle de Buildroot (GitHub, ntfy) ; import JSON (13,6 s) ; RTSP TCP principal +
sous-flux + audio ; **pont MQTT en C** : une nuit stable (un seul démon, pas de reconnexion, PSS 209 Ko contre
1 129 Ko) → défaut depuis `d41ac72` ; RAM de la .11 sans fuite sur 15 h ; jour / nuit de la .11 correct.

**Échec / à reprendre** : pertes Wi-Fi inchangées (9,5 % des mesures, le pays FR n'y fait rien) ; carte SD de la .24
encore « not properly unmounted » après la mise à jour web ; aller-retour jour / nuit à l'aube sur la .24 (05:42 jour
→ 05:47 nuit → 06:28 jour).

**Fait, en attente d'essai sur caméra (rc27)** — chaque point a son entrée dans `test-queue.md`, désactivé par défaut
sauf mention : `[audit-fix]` (W2 LAN seul pour le web et le RTSP, R1, R2, B4-B6 ; actif), `[roadmap]` (20, 22, 26,
27, 29 ; actif), `[hwtest]`, `[720p]` (#8), `[smart-pool]` (#9), `[audio-native]` (#11), `[onvif]` (#12, #53),
`[retention]` (#15), `[flicker]` (#16), `[wifi-soft]` (#17), `[abr]` (#18), `[md-enc]` (#19), `[daynight-lock]` (#21,
actif), `[time-http]` (#24, actif), `[privacy]` (#25).

**Changé par un autre agent le 2026-11-05 matin, sans essai** (entrées ajoutées dans `test-queue.md` le même jour) :
pont MQTT en C par défaut dans `mqtt.conf.dist` (`d41ac72`, `[mqtt-c-default]`) ; `RTSP_PACING_US=100` par défaut
(`1a3a2eb`, `[pacing]`) ; `dosfsck -a` avant de remonter la carte (`96336d1`, `[sd-fsck]` : **sans effet aujourd'hui**,
voir #41) ; #33 coché (le pre-roll existait déjà dans `rec.c`).

## P0 — rc26, avant le tag 3.0.1

1. [x] **Publier une rc26** avec ce qui est sur `main` depuis la rc25, en particulier `04f2313` + `9853759` : arrêt du
   pont MQTT en C (`stop` laissait le démon tourner, un deuxième démon démarrait avec le même client id, `availability`
   basculait toutes les 2 s). Aujourd'hui le correctif n'existe sur la .11 qu'en RAM.
   *Fait : rc26 publiée (build `342b523`), relue et téléchargée par le testeur le 2026-11-04 20:15 ; installation sur
   la .11 prévue. Tout ce qui est sur `main` depuis le 2026-11-05 (voir le résumé ci-dessus) demande une **rc27**.*
2. [x] **Supprimer les sous-shells qui restent en mémoire** (~0,3 Mo, aucun C à écrire) :
   *Fait le 2026-11-05 pour le pont MQTT (`( exec "$BB" nohup … ) &`, `$!` = le démon, shell et C). La boucle getty
   de `S39tc100` reste : elle relance la console série.*
   - `controlscripts/mqtt-bridge start` : `run_busybox nohup … &` garde un `sh mqtt-bridge start` vivant (217 Ko PSS)
     parent du démon. Proposition : `( exec "$BUSYBOX_BIN" nohup "$BIN" … ) &` (ou `nohup "$BIN" … &` direct) : `$!`
     devient alors le pid du démon lui-même, ce qui règle aussi la cause du point 1 ; idem pour le pont shell.
   - `/etc/init.d/S39tc100 start` reste vivant après le démarrage (90 Ko PSS) : `exec` sur la dernière commande ou
     ne pas attendre.
     *Vérification (implémenteur, 2026-11-04 nuit)* : ce processus est la boucle `( while :; do /sbin/getty …; done ) &`
     de `S39tc100` (même ligne de commande que le script), qui relance la console série : elle est nécessaire. La
     redirection ajoutée en rc26 (`</dev/null >/dev/null 2>&1` sur l'autorun) ne la supprime pas, et le CHANGELOG rc26
     qui annonçait ~0,3 Mo gagnés est corrigé. Pour la supprimer : une ligne `respawn` de getty dans `/etc/inittab`
     (que `build-rootfs66.sh` retire aujourd'hui pour laisser S39 choisir entre login et `consoleshell`). Côté MQTT,
     la proposition `( exec … nohup "$BIN" … ) &` reste valable : `run_busybox` est une fonction, le sous-shell
     lancé par `&` attend le démon.
3. [ ] **Points ouverts de la checklist** (*D8 fait le 2026-11-05, voir `audit-2026-11-04.md` §7*) : W4 (assistant sans jeton CSRF), B3 (`flashw -m` compare le fichier à
   lui-même, avec B1), D8 (passe de documentation : `api.md` cite encore HTTPS et `set_web_mode`, `wifi_set_country`
   non documenté…). B1 et W4 : décision du propriétaire reportée, à lui reposer avant le tag.
4. [x] **Retirer la mention « CVE-2026-98432 »** de l'entrée rc24 et de la checklist : mention retirée.
5. [x] **Petits restes de config** :
   - `boot.conf.dist` : `MEM_GUARD_SOFT_SERVICES=""` nettoyé ;
   - `config/autostart/memory-guard` retiré du dépôt (`MEM_GUARD_ENABLE=0` est le switch unique) ;
   - `mqtt.conf` : documenté la règle de dérivation du topic root basée sur le hostname (`_mb_slug`).
     *Coché à tort le 2026-11-04 (relecture du testeur, 20:15) ; fait réellement le 2026-11-05 : commentaire au-dessus de
     `MQTT_CLIENT_ID` / `MQTT_TOPIC_ROOT` dans `config/mqtt.conf.dist`.*
6. [x] **Plans de test : mesurer la RAM en PSS** (*règle ajoutée en tête de `test-queue.md` le 2026-11-05*) (`/proc/<pid>/smaps_rollup`), pas en RSS : le critère « RSS du
   démon bien en dessous des 5,7 Mo » comparait du code busybox partagé compté 7 fois (gain réel du pont C ≈ 0,9 Mo).
7. [ ] **Tests restants avant le tag** (testeur + propriétaire) : anti-masquage avec la main ; SD sur la .24 (plus de
   « not properly unmounted » après un redémarrage voulu) ; notification ntfy ou Telegram réelle ; RTSP en **UDP**
   (non testable depuis la VM du testeur, NAT : à faire par le propriétaire avec VLC ou Frigate) ; nuit en mode
   MQTT C (soak en cours sur la .11).
   *2026-11-05 : nuit MQTT C **validée** (une nuit ; une deuxième sur la rc26 était conseillée, le défaut a déjà changé) ;
   SD de la .24 **échec** (encore sale après la mise à jour web : voir #41) ; anti-masquage, ntfy / Telegram et RTSP UDP
   restent à faire.*

## P1 — 3.0.2 (fiabilité et image)

8. [x] **Support natif d'une résolution intermédiaire 720p (1280×720)** :
   *Fait le 2026-11-05 : il fallait aussi le noyau (patch 0016 : le pilote recadrait à la taille demandée, donc un
   coin de l'image ; il recadre maintenant la fenêtre 1080p entière et l'ISP met à l'échelle). Clé `[0] mainres`
   (720 / 1080) et non `width` / `height`, que des profils de compatibilité remplissaient déjà de 1280x720.
   Test : entrée `[720p]` de `test-queue.md`.*
   - Rendre la géométrie du flux principal configurable dans `tc100_rtsp` (`main_w`, `main_h`, options `-W`/`-H` ou `RTSP_WIDTH`/`RTSP_HEIGHT`).
   - Mettre à jour `rtsp-launch.sh` pour lire `[0] width` et `[0] height` dans `rtspserver.conf` et passer les arguments.
   - Adapter `scripts/action.d/video.sh` (`cmd=set_video_params`) pour accepter `video_size0=1280x720` (au lieu de forcer `1920x1080`).
   - Ajouter le sélecteur de résolution dans l'interface Web (`Settings → Main stream`, 1080p / 720p).
   - Gains : ~45 % de pixels en moins, soulage la bande passante bus DMA, l'encodeur matériel et libère ~1,7 Mo par trame NV12.

9. [ ] **Build noyau pour le mode smart de l'encodeur** (essai sur la .11) *(2026-11-05 : la CI construit ce noyau
   de test à la demande, entrée `[smart-pool]` de `test-queue.md` ; reste l'essai)* : valeur par défaut compilée
   `ak39_venc.pool=12M` (patch 0015 ; le paramètre est `0444` et la ligne de commande vient du bootloader : pas de
   U-Boot). Puis `RTSP_VBR=1` + `RTSP_SMART=1` (mode 1 seulement). Critères : `smart mode 1 (long-term reference)`
   dans le log, pas de `alloc dma … failed`, serveur vivant 24 h, MemAvailable ~2,4 Mo plus bas, débit et qualité
   comparés à la .24.
9. [ ] **Pertes Wi-Fi** (7-11 % des mesures la nuit rc23, indépendantes d'une caméra à l'autre) : attendre le bilan
   de cette nuit (.11 : regdb + FR + `RTSP_QMAX=1024` ; .24 : rc23). Si la file plus grande réduit les images sautées
   sans gêner le direct, passer `QMAX_DEF` à 1 Mo par défaut ; ensuite essai `RTSP_PACING_US`, puis canal Wi-Fi de la
   box (décision du propriétaire).
   *Bilan de la nuit du 2026-11-05 : 9,5 % des mesures avec perte totale (rc23 : 11 %) malgré FR + regdb, signal fort
   (-19 dBm, MCS 7, 0 retry au compteur iw) : pas le domaine réglementaire, plutôt la réception ou un blocage du pilote.
   `RTSP_QMAX=1024` : 5 courts épisodes d'images sautées en début de nuit, rien de négatif, mais pas de témoin pour
   chiffrer. `RTSP_PACING_US=100` est le défaut depuis `1a3a2eb` (sans essai, entrée `[pacing]`). Suite : mesurer le
   pacing, canal Wi-Fi de la box (propriétaire), puis le pilote `rtl8xxxu`.*
10. [ ] **Mémoire de la .24** : 20,5 Mo disponibles hier soir, 18,6 Mo après 23 h 40 (enregistrement SD actif) :
    vérifier demain matin si c'est du cache ou une dérive.
    *2026-11-05 : la .11 n'a pas de fuite (22,1 → 21,8 Mo sur 15 h) ; la .24 était à 18,8 Mo après 22,8 h (rc23) puis a
    été mise à jour en rc25 : à remesurer sur une nuit avec l'enregistrement SD actif.*
11. [ ] **Chantier audio natif ultra-léger (zéro surcoût / gain RAM & CPU)** :
    *2026-11-05 : capture ALSA directe (`RTSP_ALSA_DIRECT=1`, `src/tc100rtsp/acap.c`), passe-haut 150 Hz, noise gate +
    AGC + écrêtage doux, micro coupé pendant le haut-parleur (`RTSP_AUDIO_HPF/AGC/DUCK=1`, `adsp.c`) : faits, désactivés
    par défaut jusqu'à l'essai (entrée `[audio-native]`). Reste l'encodeur AAC (optionnel, P2).*
    - **Capture ALSA directe dans `tc100_rtsp`** au lieu du sous-processus `arecord` : libère ~660 Ko PSS et supprime les pipes et changements de contexte noyau réguliers.
    - **Filtre passe-haut (High-Pass / Anti-Rumble)** : filtre biquad IIR léger à virgule fixe coupant à 150-200 Hz (suppression du ronflement 50 Hz d'alim et des bruits d'air sourds sans altérer la voix ; coût CPU < 0,2 % d'un cœur).
    - **Noise gate & AGC soft-clipping à virgule fixe** : atténue le souffle en pièce silencieuse et équilibre le volume des voix éloignées sans saturation.
    - **Coupure anti-larsen (half-duplex PTT)** : atténuation/coupure automatique du micro pendant la lecture haut-parleur (évite l'écho en retour).
    - *(Optionnel / P2)* Encodeur AAC compact pour la piste MP4 sur carte SD afin d'assurer une lecture HTML5 universelle dans le navigateur sans transcodage.
12. [ ] **Support ONVIF Profile T (Audio Backchannel standardisé)** :
    *2026-11-05 : `tc100-onvifd` (libre, remplace `monvifd`, `ONVIF_IMPL=c`) annonce le retour audio (sortie et
    décodeur audio dans le profil Media2), plus les événements de mouvement (PullPoint) pour Home Assistant. Reste
    l'essai sur caméra, entrée `[onvif]`.*
    *Propriétaire, 2026-11-05 : ONVIF est utilisé. Passe par le remplacement de `monvifd` (#53) : un démon ONVIF libre
    (WS-Discovery, Device, Media / Media2 avec le profil audio de retour).*
    - La gestion du retour audio bidirectionnel (`Require: www.onvif.org/ver20/backchannel`, piste `track3` PCMA 8 kHz) est déjà implémentée dans `src/tc100rtsp/talk.c`.
    - Objectif : exposer l'AudioBackChannel dans la réponse ONVIF Device / Media2 service pour permettre le Two-Way Audio natif instantané dans Home Assistant (WebRTC / Go2RTC) et Frigate sans bidouille URL manuelle.
    - Coût CPU / RAM : 0 % (métadonnées XML / profil statique côté démon ONVIF + exploitation du code RTSP déjà présent dans `tc100_rtsp`).
13. [ ] **Régulation de trafic réseau / Pacing RTSP (`tc100_rtsp`)** :
    *2026-11-05 : `RTSP_PACING_US=100` mis par défaut dans `rtsp-launch.sh` par un autre agent (`1a3a2eb`), sans
    mesure ; `rtsp.env` peut le remettre à 0. Entrée `[pacing]` : à mesurer contre les pertes de #9.*
    - Lissage temporel de l'envoi des paquets RTP lors des pics d'I-frames H.264/H.265 (pacing microsecondes `RTSP_PACING_US`).
    - Évite la saturation du tampon de transmission du pilote RTL8188FU lors des images clés, réduisant drastiquement les pertes de paquets Wi-Fi sans impacter la latence vidéo.
14. [ ] **Garde thermique dynamique (Thermal Guard)** :
    *Bloqué (2026-11-05) : pas de capteur de température exploitable (`CONFIG_THERMAL` et `CONFIG_HWMON` absents, rien
    dans le device tree). Piste : la température du SoC sur le SAR ADC ou un registre de température du capteur
    JX-F23, à chercher dans le firmware d'origine (Ghidra), puis un petit pilote.*
    - Lecture périodique de `chip_temp` (`/sys/class/thermal/thermal_zone0/temp` ou capteur SoC).
    - En cas de surchauffe (> 75-80°C lors de canicules ou forte charge continue), réduction automatique et temporaire de la fréquence d'images (25 fps -> 15 fps).
    - Reprise automatique dès refroidissement sous le seuil d'hystérésis.
15. [x] **Politique de rétention intelligente sur carte SD (FIFO hiérarchique)** :
    *Fait le 2026-11-05 : marqueur `.evt` sur chaque fichier où il y a eu mouvement ou son ; `REC_KEEP_EVENTS=1`
    (désactivé par défaut) supprime d'abord les enregistrements sans événement. Le sabotage n'y entre pas encore
    (`tamper-detect.sh` ne parle pas à `tc100_rtsp`). Entrée `[retention]`.*
    - Distinguer les enregistrements continus de fond des clips d'événements (détection de mouvement, bruit / VOX, falsification / tamper).
    - En cas d'espace disque saturé, supprimer d'abord les fichiers continus anciens et sanctuariser les vidéos d'alerte pour éviter toute perte critique.
16. [x] **Anti-scintillement automatique (Auto Anti-Flicker 50/60 Hz)** :
    *Fait le 2026-11-05 : le réglage 50 / 60 Hz sans redémarrage existait (`POWER_HZ`, R9-03) ; ajouté `auto` = la
    fréquence du pays Wi-Fi (Japon et pays non réglé : inchangé). Une vraie détection de la fréquence demanderait
    d'analyser les bandes dans l'image : pas fait. Entrée `[flicker]`.*
    - Détection de la fréquence secteur (50 Hz en Europe, 60 Hz en Amérique) ou commutation fluide selon configuration dans l'ISP afin d'éliminer les bandes de défilement sous éclairage LED / fluorescent sans nécessiter de redémarrage.
17. [x] **Watchdog Wi-Fi & Reconnexion douce (Auto-Healing)** :
    *Fait le 2026-11-05 : `net-guard.sh` (passerelle pingée chaque minute, redémarrage après 15 min) et
    `wifi-recover.sh` (sans `wlan0` : nouveau sondage USB, coupure GPIO 11) existaient ; ajouté les réparations douces
    quand `wlan0` existe (`NET_GUARD_SOFT=1`) : réassociation à 2 min, `wifi-apply` à 5 min, nouveau sondage USB à
    8 min. Le pilote `rtl8xxxu` est dans le noyau (pas de module à recharger) : le sondage USB en tient lieu.
    Entrée `[wifi-soft]`.*
    - Script/boucle légère vérifiant la joignabilité de la passerelle (toutes les 60 s).
    - Tentative de reconnexion douce via `wpa_cli reassociate` ou réveil de l'interface `wlan0`.
    - Si échec persistant, déchargement et rechargement propre du module USB `8188fu.ko` sans reboot complet de la caméra.
18. [ ] **Débit binaire adaptatif automatique (Auto-ABR dans `tc100_rtsp`)** :
    *2026-11-05 : régulation écrite (`RTSP_ABR=1`, désactivée par défaut) : -30 % quand des clients TCP sautent des
    images, +10 % du réglage après 30 s calmes, borne `RTSP_ABR_MIN`. Elle passe par `ak_venc_set_br(handle, kbit/s)`
    de la bibliothèque du fabricant, dont la signature n'est pas vérifiée (la bibliothèque est sur la caméra, pas
    dans le dépôt) : à confirmer par l'essai `[abr]` (ou en désassemblant `/mnt/lib/libmpi_venc_ex.so`). Pas de signal
    pour les clients UDP.*
    - Mesure du remplissage du buffer d'envoi RTSP / perte Wi-Fi.
    - Réduction dynamique temporaire du bitrate de l'encodeur matériel (ex: 2000 -> 1000 kbps) via `libakuio`, puis rétablissement à la normale une fois la liaison stabilisée.
19. [ ] **Détection de mouvement matérielle zéro CPU (VPU / P-frame stats)** :
    *2026-11-05 : écrit (`RTSP_MD_ENC=1`, désactivé par défaut), en plus de la grille de luminance (qui ne décode rien
    non plus : 64x36 points lus 4 fois par seconde) : taille des trames P comparée à leur moyenne glissante, seuil x2 à
    x6 selon la sensibilité. Ne voit presque rien en CBR (VBR nécessaire) ; les zones ne s'y appliquent pas. Les
    vecteurs de mouvement de l'encodeur ne sont pas accessibles par la bibliothèque. Entrée `[md-enc]`.*
    - L'encodeur matériel AK3918 calcule déjà les vecteurs de mouvement et les macroblocs inter/intra.
    - Exploitation de la taille des trames P ou des compteurs MB dans `tc100_rtsp` : une trame P passe de 2 Ko (immobile) à 20-30 Ko (mouvement).
    - Déclenchement instantané d'événements MQTT (`teckin/motion = ON`) et d'enregistrements SD sans consommer de CPU en décompression d'images.
20. [x] **Snapshot JPEG direct sur événement MQTT (`teckin/snapshot`)** :
    *Fait le 2026-11-05 : existait déjà sur la commande MQTT `snapshot` ; ajouté sur mouvement, son et sabotage
    (`mqtt-bridge.sh snapshot-event`, `MQTT_SNAPSHOT_ON_EVENT=1`, désactivé par défaut, 10 s entre deux images), image sur
    `<racine>/snapshot/image` (entité caméra HA enregistrée alors). Le bouton reset n'en envoie pas : ses appuis
    servent au Wi-Fi de secours et au redémarrage.*
    - Capture d'une vignette JPEG légère depuis le sub-stream 640×360 lors d'un déclenchement (mouvement, bruit VOX, bouton).
    - Publication dans un topic MQTT pour affichage immédiat dans les notifications mobiles (Home Assistant Companion, Telegram, ntfy).
21. [ ] **Hystérésis temporelle et adoucissement Jour / Nuit** :
    *Constat du testeur (2026-11-05, .24 rc25) : 05:42 jour → 05:47 nuit → 06:28 jour à l'aube. Les 60 s minimum
    (`MIN_SWITCH`) ne couvrent pas un retour 5 min après : regarder les seuils de la source utilisée sur la .24
    (`DAYNIGHT_SOURCE`, journal de calibration `auto-night`).*
    *2026-11-05 : seuils séparés et temps de maintien (`NIGHT_HOLD`, `DAY_HOLD`) existaient ; ajouté 60 s minimum entre
    deux bascules quelle que soit la source (`MIN_SWITCH`, entrée `[daynight-lock]`). Reste la transition progressive
    de l'exposition à l'allumage des LED IR (dans l'ISP, à étudier avec le jeu de paramètres de nuit).*
    - Verrouillage anti-rebond temporisé (au moins 60 s) après commutation du filtre IR-Cut pour éliminer le cliquetis en zone de pénombre crépusculaire.
    - Transition progressive de l'exposition/gain AWB lors de l'allumage des LED IR pour éviter le flash blanc.
22. [x] **Sauvegarde / Restauration 1-clic de la configuration Web** :
    *Fait le 2026-11-05 : l'export / import JSON et l'envoi vers une autre caméra existaient ; ajouté la sauvegarde
    complète `.tar.gz` de cette caméra (page Sauvegarde, `config_exchange.cgi?cmd=archive|restore`, mêmes fichiers que les
    emplacements flash, restauration validée et transactionnelle). Pour cloner .11 vers .24 : l'envoi JSON (il laisse
    l'identité de côté) ; l'archive, elle, ramène aussi le nom, l'adresse et les clés ssh.*
    - Export/Import d'une archive `.tar.gz` de `/mnt/config/` depuis l'interface Web pour cloner ou restaurer rapidement des caméras (.11 <-> .24).
23. [x] **Mode Point d'accès de secours (Failover AP Setup)** :
    *Existait (constaté le 2026-11-05) : `wifi-rescue` ouvre un point d'accès WPA2 après 10 min sans Wi-Fi (ou avec le
    bouton reset 3-7 s), interface web complète sur http://10.42.0.1. Amélioration possible : un portail captif (petit
    DNS qui répond 10.42.0.1 à tout) pour que les téléphones ouvrent la page tout seuls.*
    - En cas d'échec de connexion Wi-Fi prolongé au boot (> 3 min), basculement du dongle `8188fu` en point d'accès Wi-Fi temporaire (SSID `Teckin-Setup`, IP `192.168.4.1`) avec interface Web minimale de configuration pour éviter d'avoir à brancher le câble série ou sortir la SD.
24. [x] **Synchronisation horaire hybride (NTP + fallback HTTP Header `Date`)** :
    *Fait le 2026-11-05 : `scripts/time-fallback.sh` (en-tête `Date:` de la page du routeur par défaut, adresses
    Internet seulement si on les ajoute dans `TIME_HTTP_URLS`). Entrée `[time-http]`.*
    - En cas d'échec de synchronisation NTP (port UDP 123 bloqué ou filtré par pare-feu / box), requêter en HTTP `HEAD` un serveur fiable (`google.com`, `cloudflare.com` ou passerelle locale).
    - Extraction du header `Date: ...` et mise à l'heure système via `date -s` pour garantir des horodatages valides sur les enregistrements et certificats.
25. [x] **Mode Confidentialité matériel / logiciel (Privacy Mode)** :
    *Fait le 2026-11-05 : `controlscripts/privacy` (page Services, interrupteur MQTT « Privacy Mode », `PRIVACY_SCREEN`
    gardé au redémarrage) ; `tc100_rtsp` noircit les deux images avant l'encodeur, l'instantané et l'enregistrement,
    coupe le son et la détection de mouvement. Pas de texte « Privé » (la police de l'horloge n'a que des chiffres) ni
    de mise en veille du capteur (l'ISP reste réglé). Entrée `[privacy]`.*
    - Commutateur Web et MQTT (`teckin/privacy/set = ON`).
    - Coupure logicielle immédiate du flux vidéo (trame noire avec mention "Privé / Inactif") et coupure de la capture micro ALSA (`amixer set Capture nocap`).
    - Optionnellement, extinction des LED d'état et mise en veille du capteur d'image JX-F23 (ou arrêt du flux ISP/RTSP) pour préserver l'intimité lors du désarmement d'alarme.
26. [x] **Boutons d'action sirène et carillon sur l'interface Web** :
    *Fait le 2026-11-05 : Carillon, Alerte, Sirène sur le tableau de bord (à côté d'Écouter / Parler), au volume du
    curseur du haut-parleur, confirmation pour la sirène.*
    - Les fichiers audio `sounds/siren.pcm`, `sounds/alert.pcm`, `sounds/chime.pcm` existent déjà dans le dépôt et sont câblés dans `scripts/mqtt-bridge.sh` (`play_sound`).
    - Ajouter les boutons d'action rapide dans l'interface Web (Dashboard / Actions rapides) pour déclencher la sirène ou le carillon en un clic sans passer par un script externe.
27. [x] **Endpoint de métriques Prometheus minimaliste (`/metrics`)** :
    *Fait le 2026-11-05 : `metrics.cgi` existait (mémoire, Wi-Fi, charge, réseau, détections) ; ajouté `/metrics`
    (redirection par `httpfront`), images capturées par seconde, débits, clients en lecture et images sautées
    (`/var/run/tc100_rtsp.stat`), carte SD (présence, taille, libre), `tc100_info{version}`. Pas de température : aucun
    pilote de capteur dans le noyau.*
    - Exposition texte brut ultra-légère par `httpfront` (format Prometheus / OpenMetrics standard, zéro parsing JSON).
    - Métriques clés : `tc100_chip_temp_celsius`, `tc100_memory_available_bytes`, `tc100_wifi_rssi_dbm`, `tc100_rtsp_clients_connected`, `tc100_rtsp_drops_total`, `tc100_sdcard_free_bytes`.
    - Permet l'intégration native et directe dans Grafana / Prometheus / VictoriaMetrics et Home Assistant sans surcoût CPU/RAM.
28. [ ] **Nettoyage et rotation circulaire des logs en RAM (`tmpfs`)** :
    - Écrêtage périodique automatique dans `housekeeper` des fichiers journaux (`/tmp/*.log`, dmesg) avec plafond strict (ex: 64 Ko max par log via `tail -n 100`).
    - Prévient toute érosion lente de la RAM disponible lors de fonctionnements ininterrompus sur plusieurs semaines.
29. [x] **Accélération WebUI : Assets pré-compressés (gzip) & Cache HTTP agressif** :
    *Fait le 2026-11-05 : `.gz` pré-compressés, ETag et Last-Modified existaient (busybox httpd). Pas de
    `Cache-Control` possible avec busybox httpd ; à la place, chaque script et feuille de style est chargé en
    `?v=<md5>` (`src/webui/stamp-assets.sh`) : nouvelle URL à chaque changement, donc jamais de vieille copie après une
    mise à jour (le dictionnaire français et le script principal avaient des versions figées).*
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
33. [x] **Enregistrement avec « Pre-Roll » circulaire en RAM (Buffer continu 3 à 5 s)** :
    *(Vérifié aussi par l'implémenteur : vrai pour `REC_WHEN=motion` et `offline` ; ~1 Mo de file ≈ 3-5 s selon le débit.)*
    *Fait (vérifié le 2026-11-05) : le buffer d'anneau `q_buf` dans `src/tc100rtsp/rec.c` (`REC_RING_KB`, 1024 Ko par défaut)
    maintient en permanence les trames en veille (`q_trim(q_size * 6 / 10)` en mode `standby`). Dès qu'un événement motion/offline
    survient (`update_want`), les trames antérieures déjà bufferisées sont dépilées et intégrées au début du conteneur fMP4.*
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
38. [ ] **Annonce mDNS / Zero-Conf enrichie (IP, version, état de santé)** :
    - Enrichir les enregistrements TXT du démon `tc100-mdnsd` pour diffuser non seulement le service web/rtsp mais aussi la version firmware exacte, l'adresse IP et les indicateurs vitaux (température SoC, charge, Wi-Fi RSSI).
    - Facilite l'identification immédiate et le repérage multi-caméras sur le réseau local depuis les navigateurs/outils réseau sans scanner les baux DHCP.
39. [ ] **Structure de trames indépendante multi-profils NVR (GOP différencié ch0 / ch1)** :
    - Permettre de configurer des intervalles de trames clés (GOP / I-frame interval) distincts entre le flux principal ch0 et le sous-flux ch1 dans `tc100_rtsp` (`rtspserver.conf`).
    - Cas d'usage optimisé pour NVR / Frigate : flux principal ch0 à GOP long (2 à 4 s) pour minimiser l'espace disque d'enregistrement, et sous-flux ch1 à GOP court (1 s) pour une détection d'objets IA instantanée et ultra-réactive.
40. [ ] **Roaming Wi-Fi multi-bornes / Mesh (Fast BSS Transition & anti-client collant)** :
    - Dans les installations disposant de répéteurs Wi-Fi ou réseau Mesh (même SSID sur plusieurs BSSID), éviter que la caméra ne reste connectée à une borne affaiblie (« sticky client »).
    - Si le RSSI chute sous -75 dBm pendant plus de 2 minutes alors qu'une borne alternative avec le même SSID propose un signal nettement supérieur (> 15 dB d'écart), forcer une réassociation douce (`wpa_cli reassociate`) sur le meilleur BSSID.
41. [x] **Contrôle et réparation douce FAT32 sur carte SD (`mount-sd.sh` / `dosfsck`)** :
    *Fait le 2026-11-05 (implémenteur) : la cause de la carte sale de la .24 est trouvée : à l'arrêt, init appelle
    `S39tc100 stop` avant `umount -a -r`, et S39 sortait sans rien faire : l'enregistreur écrivait encore, le remontage
    en lecture seule échouait. `stop` arrête maintenant l'enregistreur, `sync`, remonte la carte en lecture seule
    (sinon `tc100-3/shutdown.log` dit qui la tient). `fsck.fat` (dosfstools) dans `ext/` : le bouton Réparer de la page
    Carte SD marche ; `SD_AUTO_REPAIR=1` répare une carte laissée sale par une coupure, une minute après le démarrage
    (mode flash). Le `dosfsck -a` de `96336d1` est retiré. Entrée `[sd-clean]`.*
    *2026-11-05 : `96336d1` (autre agent) lance `dosfsck -a` dans `rec-storage.sh _mount_card`, mais (1) `dosfsck` n'est
    pas dans l'image (ni dosfstools dans Buildroot, ni applet busybox : la ligne ne fait rien), (2) au démarrage la carte
    est montée par `v3/S39tc100-linux66`, pas par `_mount_card` (qui ne sert qu'après une éjection en mode flash), (3)
    `-a` répare tout seul (peut tronquer) et vérifierait toute la carte à chaque montage (RAM, minutes). Reste à faire :
    `fsck.fat` dans l'image (dosfstools), dans S39 lire le bit « sale » avant de monter et ne réparer que s'il est posé,
    avec une entrée de test. `scripts/sd-diag.sh` (page Carte SD) sait déjà vérifier / réparer quand `fsck.fat` existe.*
    - Détection automatique et non-destructive du dirty bit (« not properly unmounted ») lors du montage au boot via `dosfsck -n`.
    - Si une incohérence mineure est décelée, exécution automatique de `dosfsck -a` avant montage en lecture-écriture pour prévenir toute corruption silencieuse des enregistrements consécutive à une coupure électrique.
42. [ ] **Mode Démarrage Discret / Silencieux (`BOOT_STEALTH=1`)** :
    - Option dans `boot.conf` et l'interface Web désactivant les jingles sonores au haut-parleur (`sounds/startup*.pcm`) et maintenant les LED éteintes pendant toute la phase de boot.
    - Idéal pour les caméras placées en chambre de bébé ou pièces de vie nocturne lors des redémarrages automatiques de maintenance.
43. [ ] **Test de latence et gigue vers le NVR / Frigate dans Diagnostics** :
    - Bouton d'action dans l'interface Web envoyant une salve de requêtes ICMP/ping vers l'hôte NVR/Frigate configuré.
    - Affichage du RTT moyen, du jitter et du taux de perte pour lever immédiatement le doute entre instabilité caméra et congestion du réseau Wi-Fi local.
44. [ ] **Infobulles explicatives pour chaque réglage dans l'interface Web (Tooltips)** :
    - Ajouter une icône d'aide ou un tooltip interactif sur chaque commutateur, curseur et champ de saisie dans l'interface Web.
    - Rôle : expliquer en langage clair la fonction exacte du réglage, son mode d'action technique et son impact recommandé.
45. [ ] **Simulateur d'occupation mémoire dynamique dans les réglages (Memory Budgeter)** :
    - Jauge d'estimation en temps réel dans l'interface Web calculant l'impact RAM prévisionnel selon les options cochées :
      - Résolution (1080p vs 720p : gain/coût ~1,7 Mo),
      - Débit binaire et taille du tampon RTSP (`RTSP_QMAX`),
      - Activation du pre-roll en RAM (ex: +800 Ko),
      - Démons optionnels (pont MQTT, détection sonore VOX, etc.).
    - Alerte visuelle / Warning dynamique (passage en orange puis rouge) dès que la configuration choisie s'approche de la zone critique (< 10 Mo de RAM libre restante) afin de guider l'utilisateur vers une configuration pérenne et stable.
46. [ ] **Refonte ergonomique et visuelle de la page Services (`scripts.cgi`)** :
    - Remplacer le tableau linéaire étroit peu efficace par une mise en page moderne en cartes / grille responsive (grid multi-colonnes exploitant toute la largeur de l'écran).
    - Regroupement thématique clair des services : Core/Système (RTSP, Web, Housekeeper), Réseau/Accès (SSH, mDNS), Intégrations (MQTT, Telegram, Syslog).
    - Affichage compact des interrupteurs d'état (démarré/arrêté), commutateurs de boot, indicateurs d'impact RAM/CPU et boutons d'action rapide.
47. [ ] **Passe de cohérence et actualisation des textes dans toute l'interface Web** :
    - Nettoyer les mentions historiques devenues obsolètes (anciennes références à lighttpd, 2.x, v4l2rtspserver, etc.).
    - Harmoniser le vocabulaire, les infobulles, les traductions françaises (`www/i18n/fr.js`) et la documentation intégrée pour refléter l'architecture 3.0 moderne (noyau 6.6, `httpfront`, `tc100_rtsp`, pont MQTT en C).
48. [ ] **Gestionnaire de sons personnalisés (Démarrage, Alertes, Upload audio)** :
    - Interface de sélection du son au démarrage (jingle par défaut, son alternatif ou silencieux) et des sons d'alertes / carillons.
    - Outil d'upload audio dans l'interface Web permettant d'importer de nouveaux sons personnalisés (ex: voix d'accueil, aboiement dissuasif, mélodie personnalisée) avec conversion automatique en PCM 8 kHz / 16 kHz léger sur la carte SD.
49. [x] **Banc d'essai matériel interactif avec jumeau visuel (Hardware Visual Twin / Interactive Testbed)** :
    *Fait le 2026-11-04 (première version, dessin d'après la photo du propriétaire) : `www/hardware.html`, Outils →
    Test du matériel, commande de lecture `hw_state`. Pas de banc de débit de la carte SD (écrire sur la carte des
    enregistrements pour mesurer n'est pas anodin) : la carte montre taille, espace libre, montage et santé. Dos
    redessiné d'après la photo du propriétaire ; la LED rouge est supposée être la 2e couleur de la LED d'état en façade
    (le dos n'en a pas), à confirmer sur caméra.*
    - Nouvelle page ou vue dédiée dans le WebUI représentant un schéma vectoriel interactif SVG stylisé de la TECKIN TC100 (vue de face et vue arrière) permettant de tester et diagnostiquer chaque composant physique en un clic :
      - **Vue de face** :
        - *Objectif / Capteur* : clic pour snapshot instantané et affichage de la luminance / exposition en direct.
        - *LED frontale bleue* : clic pour allumer / éteindre ou faire pulser la LED avec animation lumineuse synchrone sur le schéma SVG.
        - *Couronne IR & filtre IR-Cut* : clic pour commuter le solénoïde mécanique de l'IR-Cut et allumer les projecteurs infrarouges de test.
        - *Trou microphone* : vumètre sonore réactif en temps réel affichant le niveau dBFS capté par ALSA.
      - **Vue arrière** :
        - *Grille haut-parleur* : clic pour jouer immédiatement un bip de test ou un carillon et valider la sortie audio.
        - *Fente carte MicroSD* : clic pour afficher la santé du support, l'espace disponible et lancer un benchmark de débit rapide.
        - *LED arrière rouge* : interrupteur on/off instantané.
        - *Bouton physique arrière* : voyant d'état GPIO dynamique indiquant en temps réel si le bouton est pressé ou relâché.
    - Zéro charge CPU/RAM pour la caméra : rendu 100 % SVG/CSS dans le navigateur client, réutilisant directement les endpoints CGI existants (`action.cgi`).
50. [ ] **Modernisation UI : Exploration des pistes Pico CSS & Shoelace (look haut de gamme, rapide et léger)** :
    *Propriétaire, 2026-11-05 : moteurs d'interface chargés à la volée (choix dans les réglages), Bulma reste intégré ;
    Pico / Shoelace se chargent depuis la carte SD si elle les a, sinon depuis un CDN (rien de plus dans la flash).*
    - Évaluer le remplacement ou l'évolution de Bulma vers des solutions modernes adaptées à l'embarqué :
      - **Piste 1 : Pico CSS** (champion de la légèreté, ~10 Ko gzippé) : CSS sémantique pur stylisant directement les balises HTML sans surcharger le code de classes, Dark Mode natif automatique sans JS, divise par 2 à 3 le poids des pages et la bande passante requise.
      - **Piste 2 : Shoelace (Web Components natifs)** : composants riches standardisés (`<sl-switch>`, `<sl-tooltip>`, `<sl-progress-ring>`, `<sl-dialog>`) offrant un rendu haut de gamme de type "UniFi / Synology", sans framework JS lourd (exécuté nativement par le moteur du navigateur).
      - Objectif : interface d'administration ultra-rapide, moderne, épurée et réactive avec un budget de transfert minimal.
51. [ ] **Audit du 2026-11-04, points ouverts** (*2026-11-05 : B4, B5, B6, W2 (web et RTSP ; pas ssh), R1, R2, R3,
    D2, D8 faits, voir `audit-2026-11-04.md` §7 ; restent W3, W6, M1, D1, D3-D7, D9*) : B4, B5, B6, W2 (`NET_LAN_ONLY` sans effet sur le web, ssh et RTSP
    en 3.0 alors que la doc dit le contraire), W3 (mot de passe par défaut public, pas de limite d'essais), W6
    (secrets dans des GET), R1 (clients RTSP TCP sans expiration, `MAXCLI 4`), R2 (`httpfront` : un fork par
    connexion sans plafond), R3, D1-D7, D9.

## P2 — plus tard, seulement si un besoin apparaît

52. [ ] Un seul démon C pour `sound-detection`, `housekeeper`, `auto-night-daemon`, `cfg-persist`,
    `service-watchdog`, `button-watch` (~1 Mo PSS au total) : beaucoup de logique testée à réécrire ; la RAM n'est
    pas le goulot (20 Mo stables la nuit, aucune fuite).
53. [ ] *(2026-11-05 : `monvifd` remplacé par `tc100-onvifd`, désactivé par défaut jusqu'à l'essai `[onvif]` ; restent
    `rwconf` / `getflag` / `getimage`)* Reconstruire `rwconf` / `getflag` / `getimage` depuis leurs sources en CI ; remplacer `monvifd` (binaire sans
    source ni licence) par un répondeur WS-Discovery libre.
    *Propriétaire, 2026-11-05 : ONVIF est utilisé → le remplacement de `monvifd` passe en P1, avec #12. #35 (WebRTC) :
    sans alourdir le CPU.*

## Hors implémenteur (propriétaire)

- Accord pour archiver ~50 notes anciennes du projet claude.ai et `_archive_v3-drafts/`.
- LED rouge : 2e couleur de la LED d'état en façade ? À vérifier sur caméra (réponse du 2026-11-05 : à vérifier).
- *Fait : D3, accord du 2026-11-05 : `src/libakuio/libakuio.so`, `src/httpfront/httpfront`, `src/jpegenc/jpegenc` retirés
  de git (la CI les construit).*
- Décisions B1 et W4 (voir `audit-2026-11-04.md` §6).
