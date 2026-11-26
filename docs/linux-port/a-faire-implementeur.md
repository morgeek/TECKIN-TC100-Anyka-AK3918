# Liste de l'implémenteur — état courant au 2026-11-26 (3.0.2-rc6)

Les sections datées qui suivent sont des notes historiques des RC précédentes ; leurs cases non cochées ne forment pas
à elles seules le backlog courant. L'état terrain ci-dessous et les entrées les plus récentes de `test-queue.md` font
foi. La liste d'origine date de rc25 ; les audits des 3, 4 et 6 novembre sont des instantanés, pas des listes de tâches
à jour.

## Audit du code C d'optimisation, 2026-11-24

Rapport : [audit-2026-11-24-optim.md](audit-2026-11-24-optim.md) (lecture seule, rien n'est encore corrigé). Ordre proposé :

« Après la 3.0.2 : retirer les gardes mémoire du noyau (`ak39_vi.guard`, garde du venc), chasse aux DMA errants close ; un changement noyau à lui seul, noyau SD d'abord (décision du propriétaire 25/11). »
- [x] **B1 `onvifd` ne relit pas `user.pwd` (fait 2026-11-24 `[b1-onvif]`, à tester : test-queue `B1-ONVIF`) :** l'ancien mot de
  passe restait valable en ONVIF après un changement ; `user.pwd` relu avant chaque authentification, écrit de façon atomique.
- [x] **B2 / B3 lecteurs de `boot.conf` trop courts (fait 2026-11-24 `[b2b3-conf]`, tampons 64 Ko, test-queue `B2B3-CONF`) :** `tc100-supervisord` (16 Ko, `REC_WHEN` à l'octet 16 461 : le son ne
  déclenche jamais l'enregistrement en mode « motion ») et `onvifd` (8 Ko, `RTSP_LITE_TALK` jamais lu) ; test CI sur le vrai
  `boot.conf.dist`.
- [x] **B4 teinte (HUE) perdue** après la première bascule jour / nuit (fait 2026-11-24 `[video-fix]`, test-queue
  `B4-HUE`) : réglage (`hue_cfg`) séparé de la table CPU (`p_hue`).
- [x] **R1** détection de mouvement par l'encodeur bloquée « en mouvement » après un changement de cadence (fait
  2026-11-24 `[video-fix]`, test-queue `R1-MDENC`) : la moyenne suit le budget par image de l'encodeur principal ;
  budget plus grand : moyenne remise à zéro, apprentissage d'au moins 6 images P et 1,5 s ; budget plus petit : moyenne
  mise à l'échelle en CBR (gardée en VBR), sans réapprendre la personne qui vient d'entrer.
- [x] **W1** mode confidentialité : chroma peinte octet par octet (fait 2026-11-24 `[video-fix]`, test-queue
  `W1-PRIVFILL`) : un `memset` par ligne.
- [x] **W3** double mise à zéro de 7,4 Mo à l'ouverture de l'encodeur (fait 2026-11-24 `[video-fix]`, test-queue
  `W3-ZERO`) : l'encodeur libre garde son `memset` et alloue par `akuio_alloc_pmem_nozero`.
- [x] **R2** le bouton reset bloqué pendant `nightmode.sh` / MQTT (fait 2026-11-24 `[r2-button]`, test-queue
  `R2-BUTTON`) : chaque attente d'un script interroge toutes les 50 ms et lit le bouton à l'heure ; `nightmode.sh`
  tué après 120 s (`DN_NIGHTMODE_TIMEOUT`), avec ce qu'il a lancé, et une ligne sur la console.
- [x] **R3** commande MQTT retenue exécutée à chaque connexion (fait 2026-11-24 `[r3-mqtt]`, test-queue `R3-MQTT`) :
  `tc100-mqttd` et le pont shell (écouteur persistant, abonnement par fenêtre) ignorent une commande reçue avec le
  drapeau RETAIN, une ligne de journal sans le contenu ; le mode flux curl hérité ne voit pas le drapeau.
- [x] **T1 + B5** test de parité des routes natives de `httpfront` (fait 2026-11-24 `[parity]`, test-queue
  `T1B5-PARITY`) : il tourne dans `local-ci.sh cross` et dans l'étape GitHub « httpfront under qemu-arm » (un saut
  = échec) ; `isp_tune` natif recopie `_isp_num` / `isp_tune_get` exactement ; la route native `fullconfig` (7) est
  retirée (le CGI répond, cache 5 s) ; `health.cgi` (5) gardée, sans écart.
- [x] Retirer les optimisations mortes (section 5 du rapport) en un seul nettoyage (fait 2026-11-24 `[cleanup]`,
  test-queue `CLEANUP-1124`) : `tc100_rtsp` sans `RTSP_UDPMMSG`, `RTSP_PACING_US` (règle aussi R4), `RTSP_SNDBUF`,
  `RTSP_POOLPAD`, `RTSP_ZEROCOPY`, les chemins `RTSP_FRAMECOPY=0` / `RTSP_LIVE_DIRECT=0` ni la recherche `/dev/mem` de la
  capture directe (`AK39_VI_G_PHYS` est dans le patch 0006 depuis le 2026-10-22) ; jour / nuit : plus de luminance
  tirée des octets du JPEG (50 sans `/tmp/cam_luma`, C et shell). `health.cgi` natif gardé.
- [x] Le reste des sections 2 et 4 du rapport : tout est fait (R1-R8, W1-W9 ; `[small]` SMALL-A-1124 et SMALL-B-1124,
  `[wifiq]` WIFIQ-FORKS, `[w5-audit]`). Les mesures de la section 5 sont celles des entrées `test-queue.md`, faites
  pendant les sessions de [readiness-3.0.2.md](readiness-3.0.2.md) (banc `tests/camera/`, entrée RECETTE-BENCH).

## Audit du 2026-11-16 (`[audit-1116]`)

L'audit complet est dans [audit-2026-11-16.md](audit-2026-11-16.md). Les corrections sont dans `main` et attendent
les tests caméra `AUDIT-1116-*` de `test-queue.md`. Ce qui reste ouvert, par ordre de priorité :

- [ ] **AUDIT-1116-FLASHBOOT** (propriétaire ; 25/11 : vérification en lecture seule sur les deux caméras). Vérifier qu'une caméra installée par `stock-hook.sh` démarre bien la
  3.0 depuis la flash : la ligne `flashboot` fait environ 270 caractères, au-delà de la limite de 256.
  *Décision du propriétaire 25/11 :* lecture seule de l'environnement U-Boot sur les deux caméras (rien n'est écrit) :
  `m=$(grep '"env"' /proc/mtd | cut -d: -f1); tr '\0' '\n' < /dev/${m}ro | grep -E '^(bootcmd|flashboot|flashargs)=' |
  awk '{ print length($0) - index($0,"=") ": " $0 }'`. Toute correction de `stock-hook.sh` reste à son accord explicite.
- [x] **AUDIT-1116-FTP** (propriétaire, décidé le 25/11 : FTP reste coupé par défaut, pas de test). Vérifier que `ftpd` refuse un mauvais mot de passe.
  *Décision du propriétaire 25/11 :* le `ftpd` de BusyBox n'est pas vérifié côté mot de passe ; il reste désactivé par
  défaut et c'est documenté ; l'activer est un choix de l'utilisateur sur un réseau de confiance.
- [x] Récupération dans l'initramfs quand `stack` est abîmé (`[recovery]`, `v3/initrd-rescue`, interrupteur
  `INITRD_RESCUE=0`) : contrôle de la partition avant usage, puis user space de la carte SD si elle en porte une,
  sinon mode secours (Wi-Fi et mot de passe lus dans `cfga`/`cfgb`, telnet réservé aux réseaux privés, `flashw` à la
  main). Rien n'est écrit en flash par l'initramfs. **À tester sur caméra : `AUDIT-1116-RECOVERY`.** AGENTS.md est
  corrigé (il n'y a pas de retour à une user space précédente).
- [x] Suites possibles de la récupération (décidé le 25/11 : telnet de secours tel quel, pas de point d'accès de secours, pas de loop) : point d'accès de secours dans l'initramfs
  (`hostapd` est dans `stack` ; mode AP de `wpa_supplicant` à mesurer contre les 2 Mio de l'initrd) ; périphérique
  loop dans le noyau pour démarrer une sauvegarde `tc100-3/backup/stack-*.bin` depuis la carte.
  *Décision du propriétaire 25/11 :* le telnet en clair réservé au réseau local reste la porte du mode secours ; pas de
  point d'accès de secours dans l'initramfs (un `wpa_supplicant.conf` sur la carte SD suffit) ; pas de périphérique
  loop dans le noyau (réécriture de `stack` à la main avec `flashw`).
- [ ] Patch 0003 (hôte USB) : un unlink d'URB actif attend une IRQ, `endpoint_disable` n'a pas de verrou, l'ep0 passe par
  l'index -1. **Corrigé par le patch 0024** (`[usb0003]`, interrupteur `otg_hs.unlink_wait_irq=1` pour revenir à
  l'ancien unlink), compilé mais jamais exécuté : reste le test caméra **AUDIT-1116-USB** de `test-queue.md` (le Wi-Fi
  en dépend, noyau SD d'abord). Non traités : le `BUG()` du timer de reprise et le code DMA mort.
  Reporté après le test caméra du 0024 : dans `done()`, vérifier RXPKTRDY / TXPKTRDY avant de traiter une IRQ (IRQ
  périmée d'un paquet arrêté), puis relancer l'URB suivant de l'endpoint après un unlink de l'URB actif.
- [ ] Encodeur (patch 0008, `ak39_venc_wait_irq`) : après un délai dépassé de 2 s, un signal pendant l'attente ou
  la dernière fermeture (`kill -TERM` de `tc100_rtsp` : le cas le plus fréquent), une IRQ tardive est mémorisée
  (masquage paresseux, contrôleur sans `IRQ_LEVEL`) et rejouée au prochain `enable_irq` : `AKUIO_WAIT_IRQ` peut
  rendre 0 sans image encodée, et libakuio rend alors le résultat 0 (état de fin vide), pris pour une réussite.
  Défaut ancien (relecture Fable du 2026-11-16). **Corrigé par le patch 0025** (`[venc-irq]`) : `IRQ_DISABLE_UNLAZY`
  sur la ligne (désarmée = masquée au contrôleur, rien n'est mémorisé ; la ligne est un niveau, aucune IRQ ne se
  perd), interrupteur `ak39_venc.irq_unlazy=0` (0644) pour revenir au masquage paresseux. Jamais exécuté : reste le
  test caméra **AUDIT-1116-VENCIRQ** de `test-queue.md` (noyau SD d'abord). Non traité, plus large : marquer
  `IRQ_LEVEL` toutes les lignes du contrôleur (patch 0001), qui change le comportement de tous les pilotes.
- [ ] I2C (patch 0005) : après un `-ETIMEDOUT` le contrôleur n'est pas remis à zéro avant le message suivant.
  Mineur (10 ms suffisent largement à environ 117 kHz).
- [x] Durcissement du code C (`-fstack-protector-strong`, `-z relro,-z now`) : mesurer d'abord le coût en taille
  par rapport au budget flash. **Fait le 2026-11-23 (`[harden]`)**, mesure dans `flash-budget.md` (« Hardening ») :
  +3,7 Ko dans le squashfs xz pour les dix programmes libres (+16 Ko bruts, surtout du remplissage de page), contre au
  moins 405 Ko libres dans `stack`. Activé par défaut : canari (`-fstack-protector-strong`) dans les programmes musl
  (`src/musl.mk`) et dans les trois programmes autonomes (`src/ssp-freestanding.h` : canari tiré de `AT_RANDOM`),
  RELRO complet (`-z now` met la GOT en lecture seule) pour les programmes musl. Pas de `_FORTIFY_SOURCE` (sans effet
  avec musl, binaires identiques) ni de PIE (+8 Ko xz, code plus lent sur l'ARM926). Interrupteur de build `HARDEN=0`
  (make, local-ci, entrée CI `harden`). Reste le test caméra **HARDEN** de `test-queue.md` (24 h, CPU identique).
- [x] MQTT (fait, `[mqtt-admin]`, test MQTT-ADMIN ; décidé le 25/11 : interrupteur `MQTT_ADMIN_CMDS`, actif par défaut) : les commandes `telnet`, `ftp` et `reboot` ne dépendent que de la confiance accordée au broker (TCP en
  clair). Décision du propriétaire : ajouter un interrupteur, ou documenter les ACL du broker.
  *Décision du propriétaire 25/11 :* un interrupteur dans `mqtt.conf`, actif par défaut (comportement actuel) ; 0 refuse
  ces trois commandes par MQTT.
- [x] CI : épingler les actions par SHA, vérifier les checksums de mbedtls et d'aiortc, rendre les builds reproductibles
  (`SOURCE_DATE_EPOCH`), et contrôler le budget `--vendor`. Fait (`[ci-pin]`) : actions épinglées par SHA (tag en
  commentaire) ; `.github/ci-pins.sh` = une seule place pour les commits (Linux v6.6, Buildroot 2024.02.9) et les
  SHA-256 (mbedTLS 2.28.9, firmware RTL8188FU), `npm ci` avec `package-lock.json`, pip avec `--require-hashes` ;
  `SOURCE_DATE_EPOCH` (heure du commit) pour mksquashfs, cpio, zip, tar, gzip, noyau (`KBUILD_BUILD_*`), Buildroot
  `BR2_REPRODUCIBLE` laissé coupé (relecture) ; étape CI « Flash budget gate » (pile, initramfs, partition `vendor` avec une image de pire cas
  de `tests/ci-vendor-budget.sh`, car l'image vendor est faite sur la caméra). Test : `tests/test_ci_pinning.py`.
  Reste le test GitHub CI-PIN de `test-queue.md` (deux runs du même commit, même `tc100-*-update.tar`).

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
  **16/11 : banc écrit** (`[t1-qp]`, rien d'activé, `tc100_rtsp` inchangé) : `src/h265enc/qpbench.c` + `qpctl.h`, procédure
  et expériences E0-E6 dans [frontier/t1-qp-bench.md](frontier/t1-qp-bench.md), entrée `T1-QP-BENCH` de `test-queue.md`.
  La forme du tampon colle au code public d'Allegro (`vcu-ctrl-sw` : contrôle QP 48 octets dont 20 utilisés, segments
  16 octets, puis un octet par bloc : QP 6 bits, intra forcé, saut forcé) ; reste à voir sur la caméra si le cœur lit la
  carte dans notre configuration. À faire par le propriétaire : E0 puis E1-E5, une expérience par lancement.

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

### B2. Trouvé dans les relevés du 18/11 (2 jours en 3.0.1) — à traiter avant la 3.0.2 finale
- [x] **DN-FLAP (remède 1 fait 2026-11-23 `[dn-flap]`, à tester sur la .11 deux soirs et sur la .24 : test-queue `DN-FLAP`, coupure `DN_FLAP_BACKOFF=0` dans `daynight.conf`), allers-retours jour / nuit en pièce faiblement éclairée (.11, 13 cycles sur 2 soirs).** Source
  `vendor` (`dn_step_vendor`, `src/supervisord/supervisord.c` ; même logique dans `auto-night-daemon.sh`). En nuit,
  la lumière IR fait baisser `lum` sous `VENDOR_DAY_LUM` (1536) avec de la lumière visible → jour ; en jour le capteur
  est au gain maximum mais les compteurs AWB (~200 000) retiennent le jour, puis redescendent → nuit. Pistes, une
  seule suffit, la 1re est la plus sûre :
  1. **Recul après un aller-retour :** un retour en nuit moins de 15 min après un passage en jour double le temps
     minimal avant le prochain passage en jour (15 → 30 → 60 → 120 min), remis à zéro par un vrai jour (`lum` bien
     sous `VENDOR_DAY_LUM`, par ex. < 600, pendant 5 min) ;
  2. seuil de jour compensé de l'IR : retenir `lum` juste après le passage en nuit (IR allumé) et n'accepter le jour
     que si `lum` baisse d'au moins 50 % par rapport à cette valeur ;
  3. en jour, ne pas laisser `AWB_DAY_CNT` retenir le jour quand le gain est au maximum (`idx` > 30 000).
  Test : les relevés `daynight.log` de la .11 entre 22 h et 2 h (journal de nuit `/tmp/log/nightmode.log`).
  Fait : la piste 1 (C `supervisord.c` et shell `auto-night-daemon.sh`, source `vendor`) ; les pistes 2 et 3 restent
  ouvertes si le recul ne suffit pas.
- [x] **AWB-NIGHT (fait 2026-11-23 `[awb-night]`, à tester sur les deux caméras : test-queue `AWB-NIGHT`, coupure `RTSP_AWB_NIGHT=0`), AWB-05 ne doit pas piloter les gains sous IR (.24 : 1618 kbit/s toute la nuit au lieu de ~650).**
  Au passage jour → nuit d'un serveur qui tourne, la boucle grey-world continue sur l'image IR (bleu ×4,8, `bex`
  1228 près du plafond 1536) : bruit de couleur amplifié, débit au plafond. Après un redémarrage de nuit : 650
  kbit/s. Corriger : au passage en nuit (jeu de paramètres de nuit de l'ISP), arrêter la boucle et rendre la main à
  l'ISP (ou figer des gains neutres), la reprendre au passage en jour depuis les gains de jour ; ne pas sauvegarder
  `awb.state` la nuit (aujourd'hui il garde le bleu ×4,8). Vérifier aussi la 3.0.2-rc1 (AWB-05-SAVED charge les gains
  du même mode : ne doit pas recharger un état de nuit pollué). Test : débit et gains MWB avant / après le passage du
  soir, sans redémarrage vidéo.
- [x] **Compteur d'échecs sur la journée (fait 2026-11-23 `[failcount]`, à lire après 24 h : test-queue `FAILCOUNT`) :**
  le journal vidéo plafonné ne garde que 2-4 h ; les totaux depuis le démarrage (`pic_fail`, `enc_reopen`, `cap_stall`,
  `starts`, ...) sont en fin de ligne `STAT`, dans `/tmp/tc100_rtsp.counters` (ils survivent à un redémarrage du
  serveur) et dans `memory-hourly.csv`, pour conclure sur 24 h et plus.
- [ ] **Mémoire :** journal en place (`scripts/memwatch.sh`, `memory.csv` toutes les 5 min et `memory-hourly.csv` toutes les
  heures, `MEMWATCH=1` ; `MEMWATCH_DROP_HOUR=` pour la paire drop_caches), entrée MEMWATCH du test-queue. Reste : 3 jours
  sur les deux caméras, lire avec le tableau de `internals.md` "Memory watch" ; noyau SD avec `CONFIG_SLUB_DEBUG`
  seulement si `SUnreclaim` monte (la baisse de ~0,4 Mo / jour n'est pas l'espace utilisateur).

### B3. Trouvé dans la première nuit en 3.0.2-rc2 (24/11)
- [ ] **NIGHT-CEIL, tranché le 26/11 : bruit de nuit à fort gain (relevé B : même débit avant et après un
  redémarrage vidéo au même gain ; nuit complète en rc6 : .24 à 1552 kbit/s de moyenne, .11 à 825).** Pas d'état de
  bascule. Décision du propriétaire du 26/11 : essai `RTSP_NIGHT_KBPS=900` sur la .24 seule (la .11 sert de témoin),
  protocole dans l'entrée NIGHT-CEIL-AUTO de `test-queue.md`. Reste : la lecture de cette nuit, puis la décision du
  propriétaire (900 par défaut, ou réglage par caméra). Les points ci-dessous sont l'historique de l'enquête.
- [x] **NIGHT-CEIL, analyse du code du 25/11 (lecture seule) : pas de bug de bascule trouvé, ne rien corriger avant
  les relevés A et B.** Un démarrage en nuit passe aussi par `style_switch(1)` (première image, `tc100_rtsp.c` ~:4610)
  et `isp_bases_reset()` remet toutes les bases à zéro ; le pilote recharge les 24 modules du jeu de nuit dans les deux
  cas ; côté encodeur une dette ne fait que baisser le débit et le VBR ne descend jamais sous le QP 33. Les deux nuits
  sont confondues par la lumière : la période « normale » (18:22-20:12) était une pièce éclairée faiblement, le
  plafond a commencé à 22:28 (lumières éteintes, gain plus fort), et le débit est redescendu à l'aube **sans
  redémarrage**. Cause la plus probable (~65-70 %) : le bruit de nuit à fort gain (~26x) remplit le budget R1 de nuit.
  - **Fait le 25/11 (`[night-ceil]`, entrée test-queue NIGHT-CEIL-AUTO) : les relevés A et B sont écrits par la caméra.**
    `tc100_rtsp` écrit `nightceil.csv` à côté de `stability.csv` (`/mnt/sd/logs` avec carte, sinon `/mnt/log`) : une
    ligne 5 s après le démarrage et après chaque bascule (`kind=switch`, `entered=start|switch`), une toutes les 10 min
    (`kind=sample` : débit moyen, gain total min / max), une à l'arrêt (`kind=stop`), avec gain, luma, exposition, NR,
    netteté, 3D-NR, budget, QP VBR. `RTSP_NIGHTCEIL_LOG=0` l'arrête. Reste : 2-3 nuits sur les deux caméras, et un
    `controlscripts/rtsp-h26x restart` en pleine nuit au plafond (relevé B), puis lire le fichier.
  - **Correctif candidat en place, éteint par défaut (`[night-ceil]`, même entrée) :** `RTSP_NIGHT_VBR_QP_ADD=N` (0-6,
    QP de qualité VBR + N la nuit) et `RTSP_NIGHT_KBPS=N` (plafond de nuit en kbit/s) dans `rtsp.env`, lus au
    démarrage et à chaque bascule, remis à la valeur configurée le jour, `md_enc_restart()` à chaque changement. Avec
    l'ABR : le débit en vigueur est le plus bas des deux. Les deux à 0 = comportement d'avant (test hôte). À essayer
    seulement si A/B confirment le bruit : `RTSP_NIGHT_VBR_QP_ADD=3` ou `RTSP_NIGHT_KBPS=900` sur la .24, une nuit.
  - **Relevé A (sans caméra) :** dans le `daynight.log` sauvé de la nuit du 24-25/11 (`tc100-fix/night-2411/`), gain
    total = (isp_d_gain x ((a_gain x d_gain) >> 8)) >> 16 et `lumi` aux trois périodes (18:22-20:12, 22:38-06:50,
    aube). Gain nettement plus bas avant 20:12 et qui baisse avec le débit à l'aube = cause 1 confirmée.
  - **Relevé B (prochaine nuit profonde, au plafond, même lumière) :** 3 fois `cat /tmp/cam_ae /tmp/cam_awb
    /var/run/isp_tune.status /sys/module/ak39_vi/parameters/nr3d /sys/module/ak39_vi/parameters/nr3d_overflow`, 5 min
    de `STAT ... bytes`, `grep -E "parameter set|noise reduction|sharpness|image tuning|3D-NR|AWB-05|exposure cap|anti-flicker|capture rate|free encoder: H.265" /tmp/logs/tc100_rtsp.log`,
    puis `controlscripts/rtsp-h26x restart` et la même chose. Toujours ~1600 au même gain = cause 1 ; ~900 au même
    gain = il existe un état de bascule (comparer les deux blocs, et seulement alors corriger).
  - **Si la cause 1 est confirmée :** un seul changement de nuit avec interrupteur, par ex. un QP de qualité VBR de
    nuit +2/+3 (`fe_set_vbr_qp` au passage noir et blanc, ~:4610, qui couvre démarrage et bascule) ou un plafond de
    nuit ; il doit appeler `md_enc_restart()` (une marche de QP change les tailles d'images sans mouvement). Risque :
    image de nuit un peu plus douce. Cause 2 (état de l'algorithme AWB du pilote gardé, ~15 %) : seulement si B le
    montre, et c'est un changement noyau (noyau SD d'abord).
- [x] **NIGHT-CEIL (hypothèse écartée le 26/11 par le relevé B : la façon d'entrer en nuit ne change pas le débit), confirmé la nuit du 24-25/11, et ce n'est pas AWB-05 (priorité haute pour la 3.0.2).** La .24 est
  restée au plafond, 1600 kbit/s, de 22:38 à 06:50 avec AWB-05 en pause (gains neutres). Ce qui décide : **la façon
  d'entrer en nuit.** Nuit commencée au démarrage du serveur vidéo → 870-960 kbit/s (24/11 18:22-20:12) ou 650
  kbit/s (17/11 02:10) ; nuit entrée par le passage du soir d'un serveur déjà lancé → plafond toute la nuit (17-18/11,
  24-25/11). À chercher dans `tc100_rtsp.c` : ce que le passage jour → nuit applique à chaud et que le démarrage en nuit
  applique autrement (jeu de paramètres de nuit de l'ISP : niveaux NR1 / NR2, 3D-NR, netteté ; état de l'encodeur gardé
  d'un mode à l'autre : QP, budget, smart). Test simple : à la prochaine nuit, comparer les paramètres ISP lus (NR,
  3D-NR, netteté) juste après le passage du soir puis après un redémarrage vidéo, au même endroit ; la correction est
  d'appliquer au passage exactement ce que fait le démarrage. Les lignes du passage de cette nuit sont perdues
  (rotation du journal de 1 Mo, 8 h gardées).
- [x] **SUBSTREAM-LOOP (clos côté caméra le 26/11 : les lignes de fermeture montrent un `TEARDOWN received` du
  client ; reste à lire les journaux Frigate / go2rtc côté propriétaire), le sous-flux H.264 est rouvert toutes les ~3 min toute la nuit sur les deux caméras**
  (`free encoder: H.264 closed after ~1800 pictures`, et sur la .24 `rtsp: 3 connections from one address, client 2
  closed for a new one`) : un client du sous-flux (Frigate / go2rtc ?) part et revient en boucle. Côté propriétaire :
  ses journaux. Côté caméra : fait (`[sub-loop]`, entrée test-queue SUBSTREAM-LOOP, `to test`) : une ligne
  `rtsp: client N (ip chemin transport) closed after S s, ...: <raison>` à chaque fermeture (TEARDOWN, pair fermé,
  erreur socket, envoi, délai de keepalive, remplacé par la limite par adresse, arrêt du flux, arrêt du serveur) ;
  à lire après une nuit : `grep 'rtsp: client .* closed' /tmp/logs/tc100_rtsp.log | sort | uniq -c`, à comparer
  aux journaux go2rtc / Frigate. Règle du serveur à garder en tête : `Session: ...;timeout=60` annoncé, seule une
  requête RTSP acceptée remet l'horloge à zéro (pas le RTCP) ; un client TCP en lecture n'expire jamais, un client
  UDP en lecture expire à 90 s sans requête, un client qui ne lit pas à 60 s.
- [x] **Ancienne entrée NIGHT-CEIL (gardée pour l'historique) : débit de nuit au plafond sur la .24 malgré AWB-NIGHT.** *Testeur, 24/11 18:20 : le
  `nightmode.log` de la .24 montre nuit 08:08 → jour 08:11 (heure locale) : les 3 min au plafond étaient une
  courte nuit juste après le démarrage, à l'aube, pas une nuit établie. Priorité plus basse ; la nuit du 24-25/11
  tranche (journal 1 Mo actif sur les deux caméras depuis 18:22, vidéo non redémarrée jusqu'au matin). Pour la
  RC3 : rien à corriger sur ce point avant cette lecture.* Au démarrage à l'aube, AWB-05 s'est bien mis
  en pause (`ISP auto`) mais le débit est resté à 1500-1870 kbit/s pendant 3 min (gain 26×, exposition qui bouge),
  alors que la .11 est restée à 650-890 kbit/s toute la nuit. Pas de correctif tant qu'on ne sait pas si c'est la
  lumière de l'aube sous l'IR, le bruit de nuit à fort gain, le 3D-NR ou le budget R1 (voulu : à 10 i/s une image
  bruitée peut prendre tout le plafond ; `RTSP_FE_FPS=0` le ramène à 640 kbit/s). Mesure de la nuit du 24-25/11 :
  `RTSP_LOGMAX=1048576` dans `rtsp.env` sur les deux caméras, pas de redémarrage vidéo avant le matin, relever les
  journaux avant tout redémarrage (test-queue, relevé du 24/11). Lecture : plafond toute la nuit profonde → réglages de
  bruit de nuit (NR 64-512 / 512-1024 à 26×), 3D-NR ou plafond de budget de nuit ; plafond seulement à l'aube et au
  crépuscule → lumière changeante, sans doute acceptable ; débit normal → cas particulier du démarrage à l'aube.
  Ensuite un seul correctif ciblé, avec son interrupteur.
- [ ] **WIFI-POWERON, `rtl8xxxu: Failed power on` ×2 au premier démarrage après la mise à jour web (.11, 23/11).**
  Rattrapé par les essais du pilote (+7 s), absent après un redémarrage et absent sur la .24 avec la même mise à jour.
  Piste : la puce restée alimentée par l'ancien firmware pendant le redémarrage de la mise à jour. Pas de correctif
  (il toucherait la chaîne de mise à jour pour un cas unique qui se corrige seul) ; à regarder à chaque mise à jour,
  et seulement s'il se répète : couper la puce ou réinitialiser le périphérique USB avant le redémarrage.

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
  une caméra, `test-queue.md` ENC-02 (interrupteurs `RTSP_FE_FPS=0`; tampon sous-flux 128 Ko en option `RTSP_FE_SUBBUF=1`, 57 Ko vendeur par défaut). Reste le 4 (T1, banc). **16/11 :** banc T1 écrit, à lancer : [frontier/t1-qp-bench.md](frontier/t1-qp-bench.md), `T1-QP-BENCH`.
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
