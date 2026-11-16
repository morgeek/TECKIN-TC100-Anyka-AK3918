# Liste de l'implémenteur — état courant au 2026-11-15 (3.0.1)

Les sections datées qui suivent sont des notes historiques des RC précédentes ; leurs cases non cochées ne forment pas
à elles seules le backlog courant. L'état terrain ci-dessous et les entrées les plus récentes de `test-queue.md` font
foi. La liste d'origine date de rc25 ; les audits des 3, 4 et 6 novembre sont des instantanés, pas des listes de tâches
à jour.

## Audit du 2026-11-16 (`[audit-1116]`)

L'audit complet est dans [audit-2026-11-16.md](audit-2026-11-16.md). Les corrections sont dans `main` et attendent
les tests caméra `AUDIT-1116-*` de `test-queue.md`. Ce qui reste ouvert, par ordre de priorité :

- [ ] **AUDIT-1116-FLASHBOOT** (propriétaire). Vérifier qu'une caméra installée par `stock-hook.sh` démarre bien la
  3.0 depuis la flash : la ligne `flashboot` fait environ 270 caractères, au-delà de la limite de 256.
- [ ] **AUDIT-1116-FTP** (propriétaire). Vérifier que `ftpd` refuse un mauvais mot de passe.
- [x] Récupération dans l'initramfs quand `stack` est abîmé (`[recovery]`, `v3/initrd-rescue`, interrupteur
  `INITRD_RESCUE=0`) : contrôle de la partition avant usage, puis user space de la carte SD si elle en porte une,
  sinon mode secours (Wi-Fi et mot de passe lus dans `cfga`/`cfgb`, telnet réservé aux réseaux privés, `flashw` à la
  main). Rien n'est écrit en flash par l'initramfs. **À tester sur caméra : `AUDIT-1116-RECOVERY`.** AGENTS.md est
  corrigé (il n'y a pas de retour à une user space précédente).
- [ ] Suites possibles de la récupération (décisions du propriétaire) : point d'accès de secours dans l'initramfs
  (`hostapd` est dans `stack` ; mode AP de `wpa_supplicant` à mesurer contre les 2 Mio de l'initrd) ; périphérique
  loop dans le noyau pour démarrer une sauvegarde `tc100-3/backup/stack-*.bin` depuis la carte.
- [ ] Patch 0003 (hôte USB) : un unlink d'URB actif attend une IRQ, `endpoint_disable` n'a pas de verrou, l'ep0 passe par
  l'index -1. **Corrigé par le patch 0024** (`[usb0003]`, interrupteur `otg_hs.unlink_wait_irq=1` pour revenir à
  l'ancien unlink), compilé mais jamais exécuté : reste le test caméra **AUDIT-1116-USB** de `test-queue.md` (le Wi-Fi
  en dépend, noyau SD d'abord). Non traités : le `BUG()` du timer de reprise et le code DMA mort.
- [ ] Encodeur (patch 0008, `ak39_venc_wait_irq`) : après un délai dépassé de 2 s, une IRQ tardive est mémorisée
  (masquage paresseux, contrôleur sans `IRQ_LEVEL`) et rejouée au prochain `enable_irq` : `AKUIO_WAIT_IRQ` peut
  rendre 0 sans image encodée. Défaut ancien (relecture Fable du 2026-11-16). Piste : effacer l'état IRQ de
  l'encodeur avant de réarmer, ou `IRQ_DISABLE_UNLAZY`. Une seule modification, testée sur caméra.
- [ ] I2C (patch 0005) : après un `-ETIMEDOUT` le contrôleur n'est pas remis à zéro avant le message suivant.
  Mineur (10 ms suffisent largement à environ 117 kHz).
- [ ] Durcissement du code C (`-fstack-protector-strong`, `-z relro,-z now`) : mesurer d'abord le coût en taille
  par rapport au budget flash.
- [ ] MQTT : les commandes `telnet`, `ftp` et `reboot` ne dépendent que de la confiance accordée au broker (TCP en
  clair). Décision du propriétaire : ajouter un interrupteur, ou documenter les ACL du broker.
- [ ] CI : épingler les actions par SHA, vérifier les checksums de mbedtls et d'aiortc, rendre les builds reproductibles
  (`SOURCE_DATE_EPOCH`), et contrôler le budget `--vendor`.

## Après 3.0.1 : plafond et polissage (bilan du 2026-11-15 10:15, demande du propriétaire)
**Bilan :** fluidité, stabilité et Wi-Fi sont près du maximum. Plafond matériel atteint, **ne pas y retourner** : CPU
ARM 400 MHz (même PLL que la DDR, voir plus bas), 64 Mo de RAM, Wi-Fi 2,4 GHz 1T1R, options de l'encodeur (SAO, AMP,
tranches multiples, plage de recherche : peu ou pas de gain, risque de blocage), capteur (22 i/s de jour en pièce
sombre = exposition au maximum de la trame, 1124 / 1125 lignes, pas un défaut). Il reste **un seul levier important**
(T1) et du polissage. Chaque point : vérifier qu'il n'est pas déjà fait (git log, autre agent), mesurer avant / après
sur une caméra, interrupteur de retour arrière, entrée dans test-queue.md.

### A. Le dernier levier important
- [ ] **T1, contrôle QP par bloc de l'encodeur libre (banc).** Hypothèse Fable ([réponse](frontier/encoder-2026-11-15-reponse.md)) :
  le tampon « tables » 0x4040 est le tampon de contrôle QP du cœur Allegro (QP min / max câblés 25-48, 36 pour l'IDR,
  puis une carte QP par bloc). Si c'est le cas : saut forcé des blocs immobiles la nuit, zone d'intérêt mieux codée,
  moins de débit à netteté égale. **Banc d'abord** (`src/h265enc/fetest.c`, une valeur à la fois, retour à la valeur du
  vendeur au moindre `picture failed`) ; jamais en défaut avant 24 h sur les deux caméras. Gain : le seul qui change
  nettement le rapport image / débit. Incertain.

### B. Polissage visible
- [ ] **Image de nuit (ISP) :** réduction de bruit par niveau de gain (NR1 / NR2, niveaux 512-1024 et au-delà) et netteté
  sous IR, dans le fichier de réglage (`isp_tune.conf` / `DENOISE=`, attention HW-09 : ajouter la ligne si elle manque).
  Mesure : instantanés de nuit avant / après au même endroit, `STAT bytes` (un bruit plus faible = aussi moins de
  débit). Attendu : moins de fourmillement, visages un peu plus lisibles ; pas de miracle.
- [x] **Couleurs justes dès l'allumage (AWB-05) :** démarrer le mode manuel depuis les gains sauvegardés (`white balance:
  starting from saved gains rex / bex`) quand ils sont récents et du même mode jour / nuit, au lieu de 10 s d'automatique
  de l'ISP (`AWB_MANUAL_AFTER`, `awb_manual_start` dans `tc100_rtsp.c`) ; garder les 10 s si aucun gain valable. **Fait, en test** (`AWB-05-SAVED` dans test-queue.md : attend la caméra).
- [x] **Fausse bascule en jour après un redémarrage vidéo :** ignorer les compteurs AWB ~30 s après le départ de la vidéo
  (pic des compteurs au redémarrage de l'ISP ; supervisord C et `auto-night-daemon.sh`, `AWB_RESTART_IGNORE=30`, POLISH-01). Doublon de l'entrée de la
  nuit du 15/11 plus bas : une seule correction.
- [ ] **Bascules jour / nuit à l'aube et au crépuscule :** relire `daynight.log` sur plusieurs jours des deux caméras ;
  si un aller-retour apparaît quand la lumière hésite, élargir l'hystérésis ou le `MIN_SWITCH` (sans toucher aux défauts
  validés si aucun aller-retour n'est vu).
- [x] **Interface web :** passer en C dans `httpfront` (comme NATIVE-02, `src/httpfront/poll.h`) les dernières lectures
  encore servies par un CGI shell sur l'onglet Réglages (`fullconfig`, `isp_tune` dans `state.cgi` hors `daynight`, POLISH-01). Gain : quelques
  dixièmes de seconde par page. Même JSON octet pour octet, tests à deux arbres comme `test_httpfront_poll.py`.

### C. Polissage invisible (robustesse, ressources)
- [x] **Sauvegarde des réglages 5,4 s → ~1 s (`cfg-persist`) :** la boucle par fichier (~180 forks `cmp` / `md5sum` /
  `cat`) remplacée par un seul `md5sum` sur tous les fichiers (POLISH-01).
- [x] **Une deuxième instance de `tc100_rtsp` ne touche pas au cœur de l'encodeur** avant d'avoir la capture
  (`fe_hw_init` déplacé après `VIDIOC_REQBUFS`, POLISH-01) : vu le 15/11, le watchdog de service relançait le binaire d'origine
  pendant un test en RAM, chaque essai faisait perdre une image à l'instance en marche.
- [ ] **Débit des enregistrements :** valider le mode smart sur 24 h (ENC-02 point 3, `smart=1` sur la .11 depuis
  3.0.1) ; attendu -10 à -30 % sur une scène calme pour Frigate. Puis décider du défaut `smart` pour toutes.
- [ ] **Tampon du sous-flux 128 Ko (`RTSP_FE_SUBBUF=1`) :** test ENC-02 point 1 avec le propriétaire (VLC sur le
  sous-flux) ; s'il passe, en faire le défaut.
- [ ] **Démarrage :** 3.0.1 sur la .11 : `network_ready` 17,7 s, `rtsp_launched` 25,0 s, `web_ready` 26,3 s,
  `boot_complete` 70,6 s : le critère `rtsp_launched` ~25 s est atteint. Ne gagner sur 26 → 70 s que si c'est gratuit
  (lire `/tmp/boot-trace.txt`, déplacer après la vidéo ce qui ne sert pas au flux).
- [ ] **Annulation d'écho (`RTSP_AUDIO_AEC=1`) :** codée, jamais validée (AEC-01, conversation réelle avec le propriétaire).

### Ce que le polissage ne changera pas
Définition et sensibilité du capteur, portée du Wi-Fi, nombre de clients simultanés, latence du flux (déjà proche du
minimum). Résultat attendu : une caméra plus régulière et plus soignée, pas plus puissante.

## Optimisation « top level » : ce qui reste à gagner (bilan du 2026-11-14 16:30, demande du propriétaire)
Bilan : le matériel est exploité (encodeur matériel H.264 / H.265 par l'encodeur libre, sous-flux ISP, 3D-NR, OSD ISP,
netteté, anti-scintillement) ; CPU 20-30 % occupé à 25 i/s avec un client (P-04), ~17 Mo `MemAvailable`. La fréquence du
CPU n'est pas un levier (voir la fin de cette section). Les gains restants sont la réactivité, la qualité d'image et la
fiabilité. **Avant chaque chantier : vérifier que ce n'est pas déjà fait** (commits `[opt]` du 14/11 de l'autre agent :
micro inactif sans DSP, MQTT / présence sans fork). Mesurer avant / après sur une caméra (règles de test-queue.md).

### 1. Réactivité de l'interface web : les lectures interrogées en continu, en C dans `httpfront` (plus gros gain)
- **14/11 soir : `daynight` (5 s) et `hw_state` (2 s) faits** (`src/httpfront/poll.h`, NATIVE-02, fusion 649e993) : JSON
  identique octet pour octet au CGI dans tous les états testés (busybox ash contre la route native) ; les cas douteux
  repartent vers httpd. Notes : la ligne d'audit de chaque appel `hw_state` est gardée (comme le CGI) ; `sound_db` et des
  nombres comme `007` sont imprimés bruts par le CGI (JSON invalide des deux côtés, défaut ancien à corriger dans les
  deux) ; httpfront +3,3 Ko xz. À mesurer sur caméra avec la prochaine build. Restent 3 et 4 de la liste ci-dessous.
- **Mesures du 14/11 (rc43, CGI lancés en local sur la caméra, busybox 1.36.1) :** `state.cgi` fullconfig 2,24 s,
  daynight 0,82 s, isp_tune 1,37 s, dashinfo 1,09 s ; `action.cgi` events_info 1,35 s, ha_discovery_info 1,80 s,
  mem_budget 1,57 s, presence_info 1,86 s, rtsp_server_info 1,79 s, sd_card_info 1,54 s, wifi_country_info 1,08 s,
  hw_state 0,49 s ; `health.cgi` 2,51 s, `network.cgi` 3,15 s, `devinfo.cgi` 1,26 s, `disk.cgi` 1,23 s. Le coût vient de
  `func.cgi` + dizaines de forks par requête, pas du travail utile.
- **Déjà natif (ne pas refaire) :** `statusline.cgi` et `dash.cgi` (`src/httpfront/status.h`, `dash.h`,
  `TC100_NATIVE_STATUS=1`), quelques ms.
- **Ordre proposé (fréquence d'appel × durée) :**
  1. `state.cgi?cmd=daynight&format=json` : interrogé **toutes les 5 s** par la page Jour / nuit
     (`src/webui/index/80-camera-controls.js` ~l. 135) ; 0,82 s. Lit `daynight.conf`, `/tmp/cam_luma`, `/tmp/cam_ae`,
     `/tmp/cam_awb`, l'état du filtre : fichiers simples, idéal pour un `daynight.h` sur le modèle de `dash.h`.
  2. `action.cgi?cmd=hw_state&format=json` : **toutes les 2 s** sur `hardware.html` (~l. 232) ; 0,49 s.
  3. `state.cgi?cmd=fullconfig` (2,24 s à chaque ouverture de Réglages) et `health.cgi` (2,51 s) : soit en C, soit un
     seul `awk` qui lit tous les fichiers de config en un passage (pas de `load_conf_file` par fichier).
  4. Les lectures de `action.cgi` à 1,3-1,9 s (presence_info, rtsp_server_info, ha_discovery_info, mem_budget) : déjà
     en cache RAM 2 s (WEBUI-CACHE-01) ; ne valent le C que si une page les interroge en boucle.
- **Contrat :** même JSON octet pour octet que le CGI (test de comparaison sur l'hôte, comme pour `dash.h`), même login
  Basic, tout cas non géré renvoyé à `httpd` ; interrupteur `TC100_NATIVE_STATUS` existant. **Critère :** < 50 ms par
  appel, 0 fork, JSON identique.

### 2. Qualité d'image : balance des blancs de l'ISP (.11) et image de nuit
- **14/11 19:45 : AWB-04 ne suffit pas (le propriétaire voit encore le cycle, plus rapide). Vraie cause mesurée : l'AWB
  automatique de l'ISP lui-même** fait osciller la couleur (Cb/Cr ±20 d'une seconde à l'autre) même sur une région fixe ;
  figé en manuel, la même scène reste à ±1,4. **AWB-05 :** ISP en balance des blancs manuelle, nos gains de boucle pilotent
  les gains manuels (`RTSP_AWB_MANUAL`, défaut 1). À valider à l'œil.
- **14/11 19:30 (AWB-04) :** Le fichier de tuning
  fixe `colortemp_stable_cnt_thresh` = 2 : l'ISP changeait de région d'illuminant (et de matrice de couleurs) 25 fois par
  minute sous lampe. Passé à 60 en direct sur les deux caméras : 0 changement. `tc100_rtsp` l'applique désormais
  (`RTSP_ISP_AWB_STABLE`, défaut 60). À valider sur l'image par le propriétaire avec la prochaine build.
- **MIS À JOUR 14/11 soir : cause principale trouvée, le filtre IR-cut de la .11 n'était pas en position jour** (image
  magenta, RGB 125/81/109 ; une impulsion jour → 93/99/103, neutre). Correctif : réaffirmation du filtre toutes les 30 min
  (`scripts/ircut-reassert.sh`, `IRCUT_REASSERT_MIN`, b653072). Reste : vérifier sur la .11 avec une build qui contient
  AWB-03 + la réaffirmation ; l'hystérésis de l'AWB de l'ISP n'est à faire que si la teinte bouge encore.
- **AWB de l'ISP (.11) :** même avec notre boucle coupée (`awb.off`), l'AWB interne de l'ISP change de région
  d'illuminant toutes les ~2 s (`/tmp/cam_awb` champ 11 : 9, 7, 6, 4, 3, 2, 1) ; la .24 reste sur la région 0. AWB-03
  (sur `main`) a divisé par deux nos changements de gains mais la teinte visible suit encore l'ISP. **À faire :** donner
  de l'hystérésis à l'AWB de l'ISP (vitesse / plage stable / poids des régions dans `/lib/firmware/anyka/isp.conf` ou par
  `AK_ISP_SET_AWB` ; voir vendor-re-findings.md et le patch 0006), ou figer l'AWB de l'ISP une fois stable (gains
  manuels égaux aux gains courants) et laisser notre boucle corriger finement. **Critère :** sur la .11, scène fixe,
  `idx` stable et < 5 changements de gains par minute ; un changement de lampe réglé en < 1 min.
- **Nuit (HW-09) :** réglage `DENOISE` -50 / 0 / +50 au jeu de nuit à mesurer (contrôle programmé le 14/11 au soir) ; puis
  choisir la valeur par défaut de nuit.

### 3. Débit vidéo : VBR / smart réellement efficaces
- **15/11 : revue Fable de l'encodeur libre** ([réponse](frontier/encoder-2026-11-15-reponse.md)). À faire, dans l'ordre :
  1. **R1** le budget par image utilise les 25 i/s configurés même à 10 i/s la nuit (d'où les 64 kbit / image mesurés) :
     `fe_set_fps()` appelé au changement de cadence, GOP compté en temps ;
  2. **R2** une image trop grosse échoue en boucle (pas de `rc_done`, même QP au prochain IDR) : QP +6 sur dépassement,
     tampon du sous-flux 57 → 128 Ko, taille d'IDR plafonnée (~0,4 s du plafond) ;
  3. **R3** en mode smart, le plancher QP (29) est mort avec `RTSP_VBR_QP=33` : coder l'IDR 4-5 QP sous les P à la place ;
  4. **T1** (banc) vérifier que le tampon « tables » 0x4040 est le tampon de contrôle QP Allegro (QP min/max câblés 25-48 /
     36 pour l'IDR, puis carte QP par bloc : ROI, saut forcé des blocs immobiles la nuit) — plus gros gain potentiel ;
  5. **L1 + L2** escalade sur échecs répétés (réouverture, puis sortie pour le superviseur) et bascule de `cur` après échec.
  À ne pas faire : SAO, AMP, tranches multiples, plage de recherche (peu ou pas de gain, risque de blocage).
  **15/11 : 1, 2, 3 et 5 codés** (accord du propriétaire ; branche `enc-fixes`, tests hôte seulement) : à vérifier sur
  une caméra, `test-queue.md` ENC-02 (interrupteurs `RTSP_FE_FPS=0`; tampon sous-flux 128 Ko en option `RTSP_FE_SUBBUF=1`, 57 Ko vendeur par défaut). Reste le 4 (T1, banc).
  **15/11 matin, .24 (fusionné sur main, b2f734a) :** ligne R1 correcte, IDR 71-74 Ko toutes les 2,5 s la nuit, 0 échec
  quand rien ne dérange le test. Le débit d'une scène fixe dépend surtout de la balance des blancs : rc44 400 Ko / 5 s,
  nouveau binaire avec AWB-05 155 Ko / 5 s, sans AWB-05 (`RTSP_AWB_MANUAL=0`) 1 Mo / 5 s (R1 laisse monter au plafond
  les variations de couleur de l'ISP). Reste : scène chargée la nuit, 24 h, 128 Ko, smart=1.
- **MIS À JOUR 14/11 soir : cause trouvée.** Mesuré sur la .24 : ~64 kbit par image quelle que soit la scène (le budget
  1600 / 25) : VBR = CBR. `rc.h` : la QP « qualité » de VBR est `qmin + 2` = 27, trop basse pour qu'une image coûte moins
  que le budget. **À faire (après choix du propriétaire) :** QP qualité réglable (`RTSP_VBR_QP`, défaut proposé 33),
  mesurer 30 / 33 / 36 sur la .24 (débit + image).
- **Constat du 14/11 :** les deux caméras `vbr=1` (la .11 `smart=1`), journal `1600 kbit/s ceiling (VBR)`, moyenne 1576-1584
  kbit/s sur une scène intérieure de jour, donc au plafond ; QP 25-48, GOP 50. **À faire :** mesurer sur une scène immobile
  (objectif masqué, avec le propriétaire) ; si le débit ne descend pas nettement (-20 à -40 % attendus, ENC-01), revoir la
  régulation VBR de l'encodeur libre (`src/h265enc/`, `rc.h` : cible = plafond ? QP plancher 25 trop bas pour une scène
  bruitée ?). **Gain :** bande passante et place des enregistrements Frigate.

### 4. Fiabilité Wi-Fi : `ampdu_tx=0` pour toutes les caméras — FAIT (décision du 14/11 16:28, défaut `WIFI_AMPDU_TX=0`, b653072)
- `ampdu_tx=0` a supprimé les blocages de la .11 (0 en 8 min contre 1-2 / min). Le défaut `WIFI_AMPDU_TX=0` est décidé et
  en place : `config/boot.conf.dist` (lignes 173-177), lu au démarrage par `v3/autorun-linux66.sh` (lignes 31-41) avant
  l'association Wi-Fi, pour toutes les caméras. `WIFI_AMPDU_TX=1` garde l'agrégation. Rien de plus à décider (vérifié 2026-11-16).

### 5. Temps de démarrage
- **15/11 nuit :** nouveau `cfg-persist` essayé sur la .24 : sauvegarde 10,4 s → 5,4 s. Les 5 s restantes = la boucle par
  fichier (~180 forks : `cmp` / `md5sum` / `cat`) ; à faire : un seul `md5sum` comparé à une liste précalculée.
- **14/11 soir, cause principale trouvée et corrigée :** chaque sauvegarde des réglages en flash bloquait le CPU à 100 %
  ~10 s (lecture des deux emplacements octet par octet, `dd bs=1`), au démarrage et à chaque changement de réglage.
  Lecture par blocs de 4 Kio (0,15 s au lieu de 2,5 s par emplacement, vérifié sur la .24) et compteur de boot-guard
  sauvé en arrière-plan. À vérifier avec la prochaine build (trace de démarrage, `rtsp_launched` visé ~25 s).
- **14/11 soir :** traces par étape ajoutées (`/tmp/boot-trace.txt`, 37 marqueurs sans fork). Étape suivante : lire le
  profil sur les deux caméras avec la prochaine build, puis déplacer ce qui ne sert pas à la première image.
- **Mesures (rc43) :** `autorun_start` 17,6 s, `network_ready` 20,7 s, `rtsp_launched` 32,8-34,9 s, `web_ready` 33,8-35,8 s,
  `boot_complete` 63-78 s. **À faire :** profiler 20,7 → 32,8 s (12 s entre le réseau et le flux : migrations, scripts de
  config, copie de `tc100_rtsp`, attente ISP ?) avec `boot-milestones.sh` à grain plus fin ; lancer la vidéo avant ce qui
  n'est pas nécessaire au flux. **Critère :** `rtsp_launched` < 25 s sans régression.

### 6. Validation de l'existant (pas de l'optimisation, mais nécessaire avant une publication)
- AEC-01 (conversation réelle), RTSP-AUTH-01 / ONVIF-02 verrouillage (mot de passe du propriétaire), UPD-01 (b) (install
  réelle), enregistrement SD + lecture (UI-13), WEB-01 / INST-01 / HRTIMER-01 sur carte SD, onglets du navigateur
  (WEBUI-CACHE-01, WHEP, PRES-01). Voir test-queue.md « State on 2026-11-14 ».

### Ce qui n'est PAS un levier (ne pas y retourner)
- **Fréquence CPU** (analyse Fable en lecture seule, 14/11) : l'horloge CPU est SYSCTRL 0x04, écrite une fois par la ROM
  depuis l'en-tête de la flash (octet 0x2C du dump : `0x410053C8`) avant l'initialisation de la DDR ; ni U-Boot ni le noyau
  3.4.35 d'origine ne la changent (seulement le bit 28, application de la PLL ASIC). Valeur mesurée `0x410013C8` : m 200,
  n 3, od 1, bit 24 (CPU = PLL) et bit 30 (DDR = PLL) : **CPU 400, AHB 200, DDR 400 MHz**. Aucun cpufreq (le
  `mach-ak39/cpufreq.c` des sources OpenIPC `anyka-ak3918ev300-3.4.35` est entièrement en `#if 0`), aucune table de
  tension, aucun maximum documenté : 400 MHz est la seule valeur du fabricant. La DDR suit la même PLL : monter le CPU
  surcadence la DDR d'autant ; le code (désactivé) du fabricant réinitialise la DLL et recalibre la DDR après un
  changement : pas de méthode sûre à chaud. Gain possible +8 % (432) à +20 % (480) sur le calcul seulement (rien pour la
  vidéo matérielle ni les E/S). SYSCTRL 0x08 (branche `overclock`) ne règle que vclk / ASIC. **Décision : abandonné.**
- **Overclock ASIC** (branche `overclock`) : aucun gain mesuré, arrêté le 14/11.

## Validé au 2026-11-14 — sujets clos, ne pas retravailler (rc43 `495609d` sur les deux caméras)
Détail et chiffres : test-queue.md « State on 2026-11-14 » et les résultats datés du 14/11 en fin de fichier ; entrées
closes déplacées dans test-queue-archive.md. Ces sujets sont terminés : ne pas les rouvrir sans nouvelle mesure qui les
contredise.
- [x] **3D-NR toujours active, `NR3D=1` par défaut** (décision du propriétaire du 14/11, option A) : 0 dépassement de jour
  et de nuit sur les deux caméras, encore 0 en rc43 après démarrage et après reboot. `auto` et `0` restent acceptés.
  Patch 0017 validé. Les 3895 dépassements de la .11 du 12/11 venaient d'un build antérieur à 0017 : point clos.
- [x] **Jour / nuit méthode d'origine (`vendor`) avec `AWB_DAY_CNT=200000` par défaut** (décision du 14/11) : validé sur la .24
  (soir sous lampe faible, nuit, aube), appliqué sur la .11 ; en rc43 les deux caméras en jour, comptes 0,4-1,0 M. IR-cut
  592 / 593 par défaut de la carte. Le dossier frontier `daynight` est **sans objet** (question tranchée par la mesure).
- [x] **Interface web compatible busybox 1.37 (CI Ubuntu 26.04) et 1.36 (caméra) :** `json_escape` caractère par
  caractère sans `gsub`, `has_ip` de Frigate en recherche littérale, `-` en dernier dans la classe du chemin rapide.
  Tests hôte sur les deux busybox, mawk, gawk ; sur caméra 12 + 17 réponses JSON valides, 6 cas spéciaux valides.
- [x] **WEBUI-CACHE-01 côté caméra** (CGI, cache, jalon `web_ready`) : passé. Reste seulement le contrôle des onglets dans
  le navigateur, par le propriétaire.
- [x] **`reboot-tracker.sh` : raison du reboot + `daynight-last.log` sauvés avant le reboot** : passé sur les deux.
- [x] **Compteurs Wi-Fi / USB en lecture seule (patchs 0020 / 0021) et `wifi-stall-watch.sh`** : branche `wifi-counters`
  fusionnée dans `main` le 14/11 (sans conflit), dans la rc43 ; validés sur les deux caméras. Plus besoin de noyau
  d'essai sur carte SD pour WIFI-STALL-01 (la section du 13/11 ci-dessous, point 1, est **close**).
- [x] **Tests instables de la CI** (supervisord, mqttd, wq_now / route, retour audio « un seul à la fois ») : corrigés,
  CI verte sur `bf84a38` et `495609d`.
- [x] **Mise à jour web** (UPD-01 partie a) : rc41 -> rc42 -> rc43 par la page sur les deux caméras, config et clé SSH
  conservées.

### Trouvailles du 14/11 après-midi sur la .11 (build `overclock` 4f43f3e ; détail dans test-queue.md)
- [x] **WIFI-STALL-01 : cause trouvée — `ampdu_tx=0` décidé pour la .11 (14/11 14:42), appliqué à chaud + `WIFI_AMPDU_TX=0` dans son boot.conf ; le réglage de démarrage est sur `main` (défaut 0 pour toutes les caméras, voir la section 4).** `ampdu_tx=0` (patch 0023) → **0 blocage en 8 min** (max 0,2 s) ; retour à `Y` → 6
  blocages en 5,7 min (jusqu'à 4,8 s). Les sessions BlockAck d'émission de la caméra sont la cause. **À décider par le
  propriétaire :** `ampdu_tx=0` par défaut : décidé et écrit (section 4, `config/boot.conf.dist`).
- [x] **OVERCLOCK-01 : abandonné (décision du propriétaire du 14/11 14:52, « aucun gain réel = inutile ») ; campagne arrêtée sur la .11 (480 MHz, `OVERCLOCK_AUTO=0`). Ne pas reprendre sans un gain mesuré.** Constat : le cœur ARM n'est pas accéléré. SYSCTRL 0x08 règle le domaine vclk / ASIC (120 → 127,5 MHz) ; la
  PLL CPU (0x04 = 0x410013C8 = 400 MHz) ne bouge pas : boucle CPU identique à la .24, encodeur -1 %. La campagne augmente
  le risque côté périphériques sans gain mesuré, et `bogomips_now` ne peut rien voir (étalonné avant l'initcall). À revoir
  avant de poursuivre : nommer correctement la PLL dans 0001 et `overclock-step`, mesurer un vrai gain (enc_ms, ISP) ou
  étudier la PLL CPU (0x04) avec le code d'origine.
- [ ] **Balance des blancs de la .11 : cause trouvée (14/11 13:53 UTC).** Même avec notre boucle coupée (`awb.off`), l'AWB
  interne de l'ISP saute de région d'illuminant toutes les ~2 s (9, 7, 6, 4, 3, 2, 1) : éclairage mixte à la frontière de
  deux températures de couleur ; la .24 reste sur la région 0. Notre boucle ne faisait que poursuivre ces sauts. À faire :
  hystérésis ou ralentissement de l'AWB de l'ISP (vitesse / plage stable / poids des régions, fichier de tuning ou
  `AK_ISP_SET_AWB`), ou figer l'AWB de l'ISP une fois stable et laisser notre boucle corriger finement. Vérifier d'abord
  la .11 avec AWB-03.
- [x] **AWB-03 (14/11, 4a41b70) : attente 2 s après un changement, moyenne sur 2 s, demi-pas. Essayé sur la .11 (binaire en RAM) : 2 fois moins de changements de gains (14,4 / min contre 30), gains 4 à 8 fois plus stables une fois convergé. Peut partir dans la prochaine rc ; le reste du pompage vient de l'AWB de l'ISP (point ci-dessus).** Constat d'origine — **AWB-02 : la boucle oscille encore sur la .11** (erreur u/v qui change de signe presque à chaque mesure, gains
  modifiés 20 fois en 40 s) : pas proportionnel trop fort pour le retard d'une mesure de l'ISP ; diviser le pas ou
  n'agir qu'une mesure sur deux, puis revérifier.
- [x] **MQTT / Home Assistant mis à niveau (`[mqtt]`, 14/11) — à valider sur caméra (`MQTT-HA-01` dans `test-queue.md`) :**
  correctif de `handle_command_payload()` dans `scripts/mqtt-bridge.sh` (la commande `privacy` manquait dans le `case "$cmd"`),
  réactivation du sélecteur `isp_power_hz` (`unchanged`/`50`/`60`/`auto`), et ajout des trois interrupteurs HA
  `local_recording`, `flip` et `mirror` (avec `rec_local_on`, `flip_on`, `mirror_on` dans `/health` et parité complète
  entre `scripts/mqtt-bridge.sh` et `src/mqttd/mqttd.c`).
- [x] **Optimisations logicielles (`[opt]`, 14/11) — micro au repos, zéro fork MQTT/présence, correctif impulsion reset hrtimer et nettoyage (`IDLE-MIC-01` / `HRTIMER-01` dans `test-queue.md`) :**
  `aud_pump()` (`src/tc100rtsp/tc100_rtsp.c`) saute `access("/tmp/speaker-play.lock")` et `adsp_sample()`/`aud_aec_sample()` quand seule la détection sonore utilise le micro (et réinitialise l'état DSP/AEC à la reprise), `mqtt-bridge.sh` / `presence-mode.sh` suppriment les sous-coquilles sur le chemin périodique (`publish_health`, `build_diag_payload`, `presence_current`), le patch `0008` passe `venc_soft_reset()` à `usleep_range(1000, 2000)` (1–2 ms sous `HIGH_RES_TIMERS`), et les fonctions mortes inutilisées sont retirées. (`ENC-01` déjà actif et en observation ; l'AWB interne ISP est laissé de côté comme demandé.)

### Corrigé dans la nuit du 15/11
- [x] **Clés supprimées de daynight.conf qui gardaient leur valeur** jusqu'au redémarrage du processus (supervisord C et
  script shell) : chaque lecture repart des valeurs par défaut. Vu en vrai : `IR_LED_MAX_ON=120` d'un test restait actif.
- [x] **Petit :** bascule en jour dans le noir 20 s après un redémarrage du serveur vidéo. Doublon de l'entrée « Fausse
  bascule en jour » ci-dessus (`AWB_RESTART_IGNORE=30`, POLISH-01) : fait, à ne pas rouvrir.

- [x] **Petit (vu le 15/11 en test RAM) : deuxième `tc100_rtsp` et cœur de l'encodeur.** Fait : `fe_hw_init` est appelé
  après `VIDIOC_REQBUFS` (`src/tc100rtsp/tc100_rtsp.c`, POLISH-01, section C ci-dessus). Doublon fermé, à ne pas rouvrir.


---
Les sections historiques antérieures au 2026-11-15 ont été archivées dans [archive/a-faire-implementeur-history.md](archive/a-faire-implementeur-history.md).
