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
17. [ ] **Audit du 2026-11-04, points ouverts** : B4, B5, B6, W2 (`NET_LAN_ONLY` sans effet sur le web, ssh et RTSP
    en 3.0 alors que la doc dit le contraire), W3 (mot de passe par défaut public, pas de limite d'essais), W6
    (secrets dans des GET), R1 (clients RTSP TCP sans expiration, `MAXCLI 4`), R2 (`httpfront` : un fork par
    connexion sans plafond), R3, D1-D7, D9.

## P2 — plus tard, seulement si un besoin apparaît

18. [ ] Un seul démon C pour `sound-detection`, `housekeeper`, `auto-night-daemon`, `cfg-persist`,
    `service-watchdog`, `button-watch` (~1 Mo PSS au total) : beaucoup de logique testée à réécrire ; la RAM n'est
    pas le goulot (20 Mo stables la nuit, aucune fuite).
19. [ ] Reconstruire `rwconf` / `getflag` / `getimage` depuis leurs sources en CI ; remplacer `monvifd` (binaire sans
    source ni licence) par un répondeur WS-Discovery libre.

## Hors implémenteur (propriétaire)

- Accord pour archiver ~50 notes anciennes du projet claude.ai et `_archive_v3-drafts/`.
- Décisions B1 et W4 (voir `audit-2026-11-04.md` §6).
