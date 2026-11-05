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

## POINT DE SITUATION — 2026-11-05 au soir (implémenteur, pour le propriétaire et le testeur)

Tout ce qui a été dit au propriétaire ce soir, consigné ici. Les détails de chaque changement (quoi, interrupteur, test,
critères) sont dans `test-queue.md` sous l'étiquette indiquée.

### Décisions du propriétaire (2026-11-05)
- W3 clos : on garde le bandeau rouge « identifiants par défaut » et la limite d'essais `WEB_LOCKOUT` ; pas de mot de
  passe aléatoire, pas d'assistant obligatoire.
- #50 (Pico / Shoelace) : **d'abord** des références précises de l'UI actuelle par l'autre agent (`[ui-baseline]`),
  #50 ensuite seulement.
- B1 + B3 et W4 dans la RC ; #35 (WebRTC) en entier ; #52 / #55 (démon C) dans la RC.
- « Il faut tout faire » et « active tous les items codés que nous incluront dans la prochaine RC » : tout le code
  restant écrit, et toutes les nouveautés activées par défaut (`[rc28-defaults]`).
- Règle de sortie : tout faire sauf #50, qualifier, puis lancer la RC.

### Fait le 2026-11-05 (code, CI locale et GitHub)
| Sujet | Étiquette |
|---|---|
| Place en flash : filtre xz ARM, tonalités de test et CSS sources hors de l'image (−65 Ko mesurés) | `[flash-space]` |
| Frise des enregistrements (canvas, événements, clic → seconde) | `[rec-timeline]` |
| Sons personnalisés (conversion dans le navigateur, carte SD) | `[sounds]` |
| Prévision mémoire dans Réglages | `[mem-budget]` |
| Audit : points dépôt D1-D9 | `[audit-d]` |
| Infobulles (71 réglages) et textes à jour | `[ui-text]` |
| Page Services en cartes | `[services-ui]` |
| Mise à jour web : 3 essais, plus de redémarrage après un échec, MD5SUMS vérifié (B1, B3) | `[b1-update]` |
| Assistant : jeton CSRF obligatoire (W4) | `[w4-wizard]` |
| Console série 5 min, réglages `vm` (#56) | `[opt-56]` |
| Démon C unique : jour/nuit, bouton, détection de son (#52) | `[supervisord]`, `[supervisord-2]` |
| Découverte Home Assistant en C (#55) | `[mqtt-disco]` |
| WebRTC / WHEP complet (#35) | `[whep-srtp]`, `[whep]` |
| `statusline` et `dash.cgi` répondus par httpfront (#55) | `[httpfront-native]`, `[httpfront-native-2]` |
| Audit câblage front/back, code mort (#57) | `[wiring-57]` |
| Corrections rc27 : pacing retiré, `restart` dans 15 scripts, WebRTC sans image, fps ONVIF, import plus rapide, contrôle des variables libc (R2-R7) | `[rc28-fixes]` |
| `rwconf` libre compilé en CI, `getflag` / `getimage` retirés (#53) | `[rwconf-53]` |
| `tc100-logfwd` et `libnetacl` compilés en CI (#51) | `[ci-uclibc]` |
| Son AAC dans les enregistrements (#11) | `[rec-aac]` |
| Toutes les nouveautés activées par défaut + migration unique des caméras installées | `[rc28-defaults]` |

### Activé par défaut pour la rc28 (`[rc28-defaults]`, chaque fonction garde son interrupteur)
- `boot.conf` : `SUPERVISOR_IMPL=c`, `WHEP=1`, `HTTPFRONT_NATIVE=1`, `NET_GUARD_SOFT=1`, `WEB_LOCKOUT=1`,
  `MDNS_SERVICES=1`, `MDNS_INFO=1`, `REC_KEEP_EVENTS=1`, `SD_AUTO_REPAIR=1`, `WIFI_QUALITY=1`, `WIFI_ROAM=1` ;
  `mqtt.conf` : `MQTT_BRIDGE_IMPL=c`, `MQTT_DISCOVERY_IMPL=c` ; `onvif.conf` : `ONVIF_IMPL=c`.
- `tc100_rtsp` (défauts de `rtsp-launch.sh`, `rtsp.env` peut dire 0) : `RTSP_ALSA_DIRECT`, `RTSP_AUDIO_HPF`,
  `RTSP_AUDIO_AGC`, `RTSP_AUDIO_DUCK`, `RTSP_ABR`, `RTSP_MD_ENC`, `RTSP_REC_AAC`.
- Caméras déjà installées : `scripts/migrate-rc28-defaults.sh`, une fois (clé absente ou encore à l'ancien défaut →
  nouvelle valeur ; un choix fait par quelqu'un reste ; marqueur `config/.migrated-rc28-defaults`).
- **Laissés désactivés (préférences, pas des remplacements)** : `PRIVACY_SCREEN` (image noire), `BOOT_STEALTH`,
  `WIFI_AIM`, `IDLE_FPS`, `ISP_TUNE`, `NOTIFY_BURST` (images envoyées hors de la maison), détections anti-masquage et
  alarme, `MEM_GUARD_ENABLE` ; le mode smart attend le noyau de #9 (sans lui il ne fait rien).

### Risques connus, à surveiller en premier sur la rc28
- `RTSP_ABR=1` appelle `ak_venc_set_br` du fabricant, signature jamais vérifiée : flux figé ou plantage de
  `tc100_rtsp` → `RTSP_ABR=0` dans `rtsp.env`.
- Son AAC (`RTSP_REC_AAC=1`) et traitement audio : jamais écoutés sur une vraie voix ; coût CPU de l'AAC estimé sous
  qemu (~2 %), pas mesuré.
- `libnetacl` / `tc100-logfwd` : testés sous qemu avec une glibc présentée sous les noms uClibc, pas contre la vraie
  uClibc (telnet / FTP / syslog distant à vérifier).
- `RTSP_MD_ENC=1` voit peu en CBR (il s'ajoute à la grille de luminance).
- CI locale : le test de parité `sd_used_kb` de `test_httpfront_native` échoue parfois quand d'autres conteneurs Docker
  écrivent en même temps (dérive du disque entre deux lectures) ; il passe seul. À rendre robuste.

### Gains annoncés et gains mesurés (honnêteté des chiffres)
- Minification de `fr.js` : 0,36 Ko de xz, pas 15-25 Ko → non retenue.
- Découverte HA en C : pas de gain de flash (+16 Ko de binaire ; ≈ 5 Ko compressés quand le code shell sera retiré) ;
  le vrai gain est ~120 sous-shells de moins par connexion.
- Démon C : 0,3 à 0,5 Mo de PSS estimés pour jour/nuit + bouton (mesuré sur la .11 : 145 Ko contre 354 Ko pour les deux
  boucles), + 140 à 190 Ko avec la détection de son ; pas 1 à 1,5 Mo (housekeeper et cfg-persist restent en shell).
- httpfront natif : +6,5 Ko compressés (statusline) et +1,8 Ko (dash) ; gain de flash seulement quand les CGI seront
  retirés ; réponse ~13x plus rapide sous qemu.
- `rwconf` libre : 4,9 Ko au lieu de 31 Ko.

### Leçons de CI du jour (ce qui a cassé et le garde-fou ajouté)
- awk : `gsub` avec antislash diffère selon busybox / mawk / gawk → `jsonflat.awk` sans `gsub` pour les échappements ;
  test avec tous les awk ; annotations GitHub pour lire les échecs sans accès aux journaux.
- musl : `struct timeval` sans `<sys/time.h>` (glibc l'apporte, pas musl) → contrôle `tests/docker/whep-musl.sh`.
- gcc 15 (runner Ubuntu 26.04) : boucle de multiplication transformée en appel libgcc en Thumb → `httpfront` cassé ;
  corrigé, et la CI GitHub compile les programmes autonomes avec le compilateur du runner.
- Variable libc via la libc de substitution (`stderr`) : `tc100-onvifd` plantait → `tests/check-libc-data-imports.sh`.

### Ce qui reste
- **Sur caméra (testeur / propriétaire)** : publier la rc28 (R1) puis le plan de test T1-T13 / P1-P10 ; `srtp-bench`,
  latence WebRTC dans le navigateur, VLC en UDP, import JSON, PSS des démons C ; #9 (noyau smart), #10 (mémoire de la
  .24), #37 (2D-NR à régler sur la caméra).
- **#58** : retirer `monvifd`, les boucles shell remplacées, la partie découverte de `mqtt-bridge.sh`, `arecord` — sur
  consigne « dès confirmation », donc après les essais de la rc28.
- **#50** : après `[ui-baseline]`.
- **Bloqués / à décider** : #14 garde thermique (aucun capteur de température exploitable ; à chercher dans le firmware
  d'origine) ; #13 vrai lissage du débit (demanderait `CONFIG_HIGH_RES_TIMERS` dans le noyau) ; #21 transition
  progressive de l'exposition au passage en nuit (à étudier sur caméra).

## À FAIRE EN PREMIER — constats du testeur sur la rc27 (.11, 2026-11-05 soir) → rc28

Détails et mesures : `test-queue.md`, entrées du 2026-11-05 19:35 et 20:40. La .11 tourne en rc27 avec des binaires
corrigés **superposés en RAM** (perdus au prochain redémarrage) : la rc28 est urgente.

R1. [ ] **Publier la rc28** avec, au minimum : `ee969e9` (onvifd/supervisord sans variable libc), `d8ff063` (whep :
    paquets RTP de 1412 octets), le point R2, et un `tc100-whep` reconstruit (image de base, `build-base-rootfs` lancé à
    la main le 2026-11-05 ~20:35 : vérifier qu'il est vert et que le build de la rc28 prend bien cette image).
R2. [x] *(fait, `[rc28-fixes]`)* **Annuler `RTSP_PACING_US=100` par défaut** (`1a3a2eb`, `v3/linux66-sd/rtsp-launch.sh`) : noyau `CONFIG_HZ=100`
    sans minuterie haute résolution (`/proc/timer_list` : résolution 10 ms) → `usleep(100)` dort ≥ 10 ms ; le pacing
    ne touche que les clients **UDP** et dort dans la boucle principale (un seul fil) après chaque paquet : un client
    UDP plafonne vers 100 paquets/s (< 1,6 Mbit/s) et retarde la capture pour tous. Un vrai lissage demanderait
    `CONFIG_HIGH_RES_TIMERS=y` ou un envoi par lots sans `usleep`, mesuré sur caméra.
R3. [x] *(contrôle CI ajouté : `tests/check-libc-data-imports.sh` sur les `imports.txt`, `[rc28-fixes]`)* **`tc100-onvifd` plantait au démarrage** (corrigé par le testeur, `ee969e9`) : la libc factice de ces Makefiles
    déclare tout import comme une fonction, donc **aucune variable libc** (`stderr`, `stdout`, `optarg`, `environ`,
    `timezone`…) dans `src/tc100rtsp`, `src/mqttd`, `src/onvifd`, `src/supervisord` : le test
    `tests/test_audit_fixes.NoLibcDataImports` le vérifie désormais. Contrôle à ajouter en CI : `readelf --dyn-syms` des
    binaires ARM contre une liste des symboles OBJECT de la uClibc (aucun import de donnée).
R4. [~] **WHEP sans vidéo** (corrigé par le testeur, `d8ff063` ; image de base reconstruite (run 42089030516) et binaire validé sur la .11 le 2026-11-05 21:30 : 18 img/s reçues par aiortc, voir test-queue) : `on_video()` jetait tout paquet > 1400 ; le test
    d'interop découpe maintenant comme `tc100_rtsp` (échoue avec l'ancien code). Sur caméra : retester avec la rc28
    (aiortc : images reçues, page web : direct WebRTC, retour MP4 si échec). Point d'UI à vérifier : si le WebRTC
    s'établit mais **sans image**, la page doit aussi retomber sur le MP4 (sinon direct noir avec le son). *(2026-11-05 soir : corrigé, la page exige `videoWidth > 0` et compte les images décodées, `[rc28-fixes]`)*
R5. [x] *(fait pour les 15 scripts sans `restart`, test pour tous, `[rc28-fixes]`)* **`controlscripts/auto-night-detection` n'a pas de `restart`** (seulement start/stop/status/health) : un
    `restart` (Services, passage `SUPERVISOR_IMPL`) ne fait rien. Ajouter `restart` (stop puis start), vérifier les
    autres scripts de service.
R6. [x] *(fait, plus la taille 720p, `[rc28-fixes]`)* **`controlscripts/onvif` plafonne les fps annoncés à 15** (`FPS0=15` « unless the file says less ») alors que
    les flux tournent à 25 : même défaut que `frigateyaml` corrigé en `9cf38e1`. Annoncer la valeur réelle.
R7. [~] *(un sous-shell de moins par valeur sans caractère encodé, `[rc28-fixes]` ; à mesurer sur caméra)* **Import JSON plus lent** : 20-25 s pour 144 valeurs en rc27 (12-15 s pour 123 en rc25) et la capture tombe à
    11-17 img/s pendant l'import ; voir où partent les secondes (nouveaux validateurs ?).
R8. [x] *(2026-11-05 soir, consigne du propriétaire « active tous les items codés » : tout activé par défaut, migration unique pour les caméras installées, entrée `[rc28-defaults]` ; risque principal : `RTSP_ABR`)* **Garder sur la .11 et en faire les défauts si la nuit est bonne** (propriétaire : « si tout est concluant on
    garde ») : `SUPERVISOR_IMPL=c`, `MQTT_DISCOVERY_IMPL=c`, `RTSP_ALSA_DIRECT=1` (validés le 2026-11-05 : découverte
    identique octet pour octet, plus d'`arecord`, son réel), `ONVIF_IMPL=c` (validé avec le binaire corrigé). WHEP
    après R4. Bilan de nuit du testeur le 2026-11-06 au matin.

## PLAN DE TEST jusqu'au tag 3.0.1 — ce qui n'a jamais été testé sur caméra (testeur, 2026-11-05 20:00)

Validé par le propriétaire. À exécuter sur la rc28 (après R1-R4), sur la .11 puis la .24 passée elle aussi en rc28.
T = testeur seul, à distance ; P = demande le propriétaire (action physique ou appareil à lui). Pour chaque point :
l'implémenteur vérifie que la fonction est prête (interrupteur, doc, critère), le testeur mesure et consigne dans
`test-queue.md`, la case est cochée ici.

**Stabilité et charge (T)**
T1. [ ] Endurance **7 jours** sur les deux caméras, toutes les nouvelles implémentations actives : pas de redémarrage
    non voulu, MemAvailable stable (PSS par processus au début et à la fin), CMA, écritures flash via `cfg-persist`
    (nombre par jour), pertes Wi-Fi, images sautées.
T2. [ ] Charge : 2, 3 puis 4 clients RTSP en même temps (chute de fps connue), multiview ouvert dans plusieurs
    navigateurs, Frigate + ONVIF + WebRTC simultanés sur un seul cœur (fps de capture, charge, latence du direct).
T3. [ ] `.24` en rc28 avec les mêmes réglages que la .11 (seules l'IP et l'identité matérielle diffèrent).

**Mises à jour et reprise (T)**
T4. [ ] Mise à jour web qui échoue (fichier corrompu, écriture flash refusée) : réessais sans redémarrage (B1/B3),
    caméra intacte et joignable.
T5. [ ] Mode sans échec : 3 démarrages ratés → boot-guard, interface accessible avec mot de passe, retour normal.
T6. [ ] Retour à la configuration précédente (cfga/cfgb) après une config cassée.

**Sécurité (T)**
T7. [ ] Limite d'essais de mot de passe du web (`WEB_LOCKOUT`) : blocage, déblocage, sans gêner Frigate/HA.
T8. [ ] `httpfront` face à une avalanche de connexions muettes (R2 de l'audit) : la caméra reste joignable.
T9. [ ] Expiration des clients RTSP inactifs (`9e2089e`) : **Frigate en TCP n'est jamais déconnecté** (une nuit),
    un client muet après SETUP l'est.

**Fonctions rc27 jamais activées (T, une à la fois, avec retour arrière noté)**
T10. [ ] Flux principal **720p** (patch noyau 0016) : image, fps, débit, Frigate.
T11. [ ] **Mode smart** de l'encodeur avec le noyau `venc_pool` 12M (#9) : critères de #9.
T12. [ ] `RTSP_ABR=1` (débit adaptatif), `RTSP_MD_ENC=1` (mouvement par l'encodeur), `PRIVACY_SCREEN`,
     `IDLE_WHEN` (fps réduits sans spectateur / la nuit), `TIME_HTTP_FALLBACK` (NTP bloqué), `POWER_HZ=auto`,
     `RTSP_AUDIO_HPF/AGC/DUCK`, `MIN_SWITCH` jour/nuit, `BOOT_SOUND`, `WIFI_AIM`, `NET_GUARD_SOFT`.
T13. [ ] Événements de mouvement **ONVIF** (PullPoint) vus par Home Assistant (avec P5).

**Matériel (P)**
P1. [ ] Anti-masquage avec la main (correctif `25fecef` jamais retesté) : `tamper_active=1` après ≥ 6 s, retour à 0.
P2. [ ] Bouton reset avec `tc100-supervisord` (appui court / long : actions attendues).
P3. [ ] LED (avant, rouge, IR), IR coupé derrière une vitre (`IR_LED_MODE=off`), page `hardware.html` complète.
P4. [ ] Haut-parleur : push-to-talk du navigateur, audio bidirectionnel depuis HA / Frigate / go2rtc (ONVIF backchannel).

**Réseau (P)**
P5. [ ] RTSP en **UDP** dans VLC (confirme R2 / pacing), intégration ONVIF de Home Assistant, un NVR tiers (Synology
    Surveillance Station ou Blue Iris).
P6. [ ] Point d'accès Wi-Fi de secours (bouton reset 3-7 s) et Wi-Fi par `wifi.txt` sur la carte.
P7. [ ] Direct **WebRTC** dans le navigateur du propriétaire (après R4), retour MP4 si échec.

**Carte SD, sur la .24 (P pour poser / retirer la carte, T pour le reste)**
P8. [ ] Enregistrement, frise (`view_records.html`), pré-enregistrement, `REC_KEEP_EVENTS`, réparation automatique
    (`SD_AUTO_REPAIR`), plus de « not properly unmounted » après un redémarrage voulu, sons personnalisés,
    sauvegarde / restauration complète, retrait de la carte à chaud.

**Notifications (P : compte ntfy / Telegram du propriétaire)**
P9. [ ] ntfy ou webhook, Telegram, image envoyée sur alerte (`NOTIFY_BURST`), `MQTT_SNAPSHOT_ON_EVENT`.

**Risqué (P, en dernier, sur une caméra récupérable par la carte SD)**
P10. [ ] Coupure de courant pendant une mise à jour web : la caméra redémarre sur l'ancienne version ou se récupère.

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
   non documenté…). B1 et W4 : *décision du propriétaire le 2026-11-05 soir : les deux dans la prochaine RC* (B1 + B3 : jusqu'à 3 essais par partition, plus de redémarrage automatique après un échec ; W4 : jeton CSRF exigé par l'assistant). Faits le 2026-11-05 soir, entrées `[b1-update]`, `[w4-wizard]` (à essayer sur caméra).
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
    par défaut jusqu'à l'essai (entrée `[audio-native]`). Encodeur AAC fait le 2026-11-05 soir (`[rec-aac]`, activé par défaut pour la rc28).*
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
28. [x] **Nettoyage et rotation circulaire des logs en RAM (`tmpfs`)** :
    *Fait le 2026-11-05 : presque tous les journaux se plafonnaient déjà eux-mêmes (tc100_rtsp 128 Ko, audit / MQTT /
    nuit / son / mouvement 32-64 Ko, wifi-quality 1440 lignes, daynight 2 x 400, syslog -s 200) ; ajouté le filet
    `scripts/log-cap.sh` (housekeeper, 10 min, `LOG_CAP_KB=64`, réécriture sur place). Entrée `[log-cap]`.*
    - Écrêtage périodique automatique dans `housekeeper` des fichiers journaux (`/tmp/*.log`, dmesg) avec plafond strict (ex: 64 Ko max par log via `tail -n 100`).
    - Prévient toute érosion lente de la RAM disponible lors de fonctionnements ininterrompus sur plusieurs semaines.
29. [x] **Accélération WebUI : Assets pré-compressés (gzip) & Cache HTTP agressif** :
    *Fait le 2026-11-05 : `.gz` pré-compressés, ETag et Last-Modified existaient (busybox httpd). Pas de
    `Cache-Control` possible avec busybox httpd ; à la place, chaque script et feuille de style est chargé en
    `?v=<md5>` (`src/webui/stamp-assets.sh`) : nouvelle URL à chaque changement, donc jamais de vieille copie après une
    mise à jour (le dictionnaire français et le script principal avaient des versions figées).*
    - Pré-compression statique des fichiers JS/CSS en `.gz` lors du build CI ; `httpfront` sert directement le flux compressé si `Accept-Encoding: gzip` est présent (0 cycle CPU de compression).
    - Ajout des en-têtes `Cache-Control: public, max-age=86400, immutable` et `ETag` pour rendre le chargement de l'interface Web quasi instantané depuis le cache navigateur.
30. [x] **Pare-feu anti-brute-force ultra-léger en noyau (`iptables -m recent`)** :
    *Fait le 2026-11-05 autrement : le noyau n'a pas de netfilter, donc dans `httpfront` (`WEB_LOCKOUT=1`, désactivé
    par défaut) : 10 mauvais identifiants web en 5 min depuis une adresse ferment ses connexions 5 min ; MD5 crypt sans
    libc (`src/httpfront/md5crypt.h`) vérifié contre la glibc et OpenSSL. Le RTSP compte déjà ses refus (R1) et ONVIF
    a son propre verrou ; ssh (dropbear) reste sans limite. Entrée `[web-lockout]`. Couvre aussi la partie « limite
    d'essais » de W3.*
    - Règle noyau bloquant temporairement (10 min) toute adresse IP source tentant plus de 5 connexions SSH / requêtes en échec consécutives en moins de 60 secondes (répond au point W3 de l'audit).
    - Coût RAM et CPU : quasi nul (100 % géré par la table d'états interne de Netfilter sans aucun démon en espace utilisateur).
31. [x] **Profils dynamiques de performance (« Mode Veille / Nuit Éco »)** :
    *Fait le 2026-11-05 : la cadence réduite existait (`IDLE_FPS`, « rien ne bouge ») ; ajouté `IDLE_WHEN=unwatched`
    (personne ne regarde : pleine cadence dès qu'un client lit) et `IDLE_WHEN=night` (en mode nuit). Le gain de
    température n'est pas mesurable (pas de capteur, #14). Entrée `[eco-fps]`.*
    - En absence de client RTSP connecté ou lors de la bascule en vision nocturne, ajustement automatique du framerate cible (25 fps -> 15 fps).
    - Rétablissement instantané à 25 fps dès la connexion d'un client RTSP ou la détection d'un événement (mouvement/son).
    - Gain : baisse de 3 à 5°C de la température SoC et réduction du bruit thermique sur le capteur JX-F23.
32. [x] **Aide au positionnement Wi-Fi & Diagnostic passif** :
    *Fait le 2026-11-05 : le tableau de bord avait déjà le signal (% , dBm, courbe) ; ajouté la couleur (vert / orange /
    rouge) et `WIFI_AIM=1` (LED bleue qui clignote plus vite quand le signal est meilleur, 5 min après le démarrage,
    `scripts/wifi-aim.sh`). Entrée `[wifi-aim]`.*
    - Affichage de la qualité du lien Wi-Fi en dBm avec code couleur sur le tableau de bord web.
    - Option de retour visuel sur la LED frontale (rythme de pulsation proportionnel au RSSI) pendant les 5 minutes suivant le démarrage pour orienter la caméra sans écran.
33. [x] **Enregistrement avec « Pre-Roll » circulaire en RAM (Buffer continu 3 à 5 s)** :
    *(Vérifié aussi par l'implémenteur : vrai pour `REC_WHEN=motion` et `offline` ; ~1 Mo de file ≈ 3-5 s selon le débit.)*
    *Fait (vérifié le 2026-11-05) : le buffer d'anneau `q_buf` dans `src/tc100rtsp/rec.c` (`REC_RING_KB`, 1024 Ko par défaut)
    maintient en permanence les trames en veille (`q_trim(q_size * 6 / 10)` en mode `standby`). Dès qu'un événement motion/offline
    survient (`update_want`), les trames antérieures déjà bufferisées sont dépilées et intégrées au début du conteneur fMP4.*
    - Maintenir en mémoire vive un anneau circulaire (ring-buffer) des 3 à 5 dernières secondes de vidéo encodée H.264 (~600 à 900 Ko de RAM consommée).
    - Lors d'un déclenchement d'alarme (mouvement, son, tamper), le clip MP4 écrit sur la carte SD intègre ces secondes préalables, assurant de voir l'amorce de l'action plutôt que l'intrus déjà en train de sortir.
34. [x] **Envoi de secours hors-site sur alerte critique (Cloud / Telegram / Webhook)** :
    *Fait le 2026-11-05 : les notifications Ntfy / Telegram / webhook existaient (une image par mouvement, **aucune pour
    le sabotage**) ; ajouté une image fraîche quand l'événement n'en a pas, la rafale `NOTIFY_BURST` (1 image/s) et la
    copie hors site `NOTIFY_UPLOAD_URL` (PUT WebDAV / adresse d'envoi). L'appel Ntfy ne passe plus par `eval`. Pas
    d'interface pour les nouvelles clés (fichier `notify.conf`). Entrée `[notify-burst]`.*
    - Sur détection de sabotage (tamper) ou intrusion confirmée, expédition immédiate d'une rafale de 3 snapshots HD ou d'un clip court vers un canal hors-site sécurisé (bot Telegram, webhook ntfy/Home Assistant ou stockage S3/WebDAV).
    - Protège les preuves d'intrusion même en cas de vol, d'arrachage de la caméra ou d'extraction de la carte SD par l'intrus.
35. [ ] *(2026-11-05 soir : feu vert du propriétaire ; étape 1 faite, entrée `[whep-srtp]` : `src/whep/srtp.h` (SRTP testé avec les vecteurs RFC 3711) et `srtp-bench` dans le pack de test, à mesurer sur la caméra ; conception dans `docs/linux-port/whep-design.md` ; étapes 2 à 5 faites, `WHEP=0` par défaut, entrée `[whep]` : restent la construction Buildroot musl confirmée par la CI et les essais sur caméra)* **Passerelle WebRTC / WHEP directe ultra-légère dans `tc100_rtsp`** :
    - Protocole WHEP (WebRTC HTTP Egress Protocol) pour streaming direct vers les navigateurs sans serveur intermédiaire (Go2RTC/MediaMTX).
    - Exploitation directe des paquets RTP H.264/H.265 et audio PCMA déjà packagés en interne, avec latence inférieure à 150 ms dans le WebUI.
36. [x] *(2026-11-05 : fait, entrée `[rec-timeline]` ; un seul type d'événement (mouvement ou son, l'entrée du recorder est combinée), pas de vignettes au survol)* **Frise chronologique interactive dans le WebUI (Timeline & Replay scrubbing)** :
    - Interface temporelle fluide HTML5/Canvas pour naviguer dans les enregistrements sur carte SD sur 24 heures.
    - Représentation visuelle des blocs d'enregistrement continu et surlignage coloré des événements marquants (mouvements, bruits VOX, sabotages).
    - Clic ou scrub sur la frise pour charger instantanément le lecteur vidéo MP4 à la seconde exacte sans recharger la page.
    - Zéro charge CPU/RAM pour la caméra : rendu 100 % côté navigateur client à partir d'un fichier index compact.
37. [ ] **Réduction du bruit spatiale adaptative sans allocation CMA (2D-NR dynamique par gain ISP)** :
    - Le 3D-NR matériel étant désactivé par manque de mémoire tampon dans le pool CMA (18 Mo), exploiter dynamiquement le filtre spatial 2D-NR de l'ISP.
    - Asservir le niveau de lissage et le coring au gain capteur en temps réel (`ispx_ae_report`) : netteté maximale et piqué fin en plein jour, atténuation progressive du fourmillement sur les aplats sombres la nuit.
    - Gain : image nocturne nettement plus propre et économie de 20 à 30 % de bande passante / débit H.264 sans aucun octet de RAM supplémentaire.
38. [x] **Annonce mDNS / Zero-Conf enrichie (IP, version, état de santé)** :
    *Fait le 2026-11-05, désactivé par défaut (le démon avait été écrit volontairement sans version ni service :
    n'importe qui sur le réseau les lit) : `MDNS_SERVICES=1` (DNS-SD `_http._tcp` / `_rtsp._tcp`), `MDNS_INFO=1`
    (version, charge, Wi-Fi dans les TXT). Pas de température (#14). Corrigé au passage une lecture hors limites du nom
    (ASan). Entrée `[mdns-sd]`.*
    - Enrichir les enregistrements TXT du démon `tc100-mdnsd` pour diffuser non seulement le service web/rtsp mais aussi la version firmware exacte, l'adresse IP et les indicateurs vitaux (température SoC, charge, Wi-Fi RSSI).
    - Facilite l'identification immédiate et le repérage multi-caméras sur le réseau local depuis les navigateurs/outils réseau sans scanner les baux DHCP.
39. [x] **Structure de trames indépendante multi-profils NVR (GOP différencié ch0 / ch1)** :
    *Existait (constaté le 2026-11-05) : Réglages → Flux principal / Sous-flux → « Intervalle des images clés »
    (`[0] goplen` / `[1] goplen`), passés à `tc100_rtsp` en `-g` / `-G` par `rtsp-launch.sh`.*
    - Permettre de configurer des intervalles de trames clés (GOP / I-frame interval) distincts entre le flux principal ch0 et le sous-flux ch1 dans `tc100_rtsp` (`rtspserver.conf`).
    - Cas d'usage optimisé pour NVR / Frigate : flux principal ch0 à GOP long (2 à 4 s) pour minimiser l'espace disque d'enregistrement, et sous-flux ch1 à GOP court (1 s) pour une détection d'objets IA instantanée et ultra-réactive.
40. [x] **Roaming Wi-Fi multi-bornes / Mesh (Fast BSS Transition & anti-client collant)** :
    *Fait le 2026-11-05 (sans 802.11r : `rtl8xxxu` ne fait pas de FT) : `scripts/wifi-roam.sh`, tâche du housekeeper
    (`WIFI_ROAM=1`, désactivé par défaut) : sous -75 dBm deux minutes, scan, `wpa_cli roam` vers une borne du même SSID
    au moins 15 dB meilleure, puis 10 min de pause. Entrée `[wifi-roam]`.*
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
42. [x] **Mode Démarrage Discret / Silencieux (`BOOT_STEALTH=1`)** :
    *Fait le 2026-11-05 : `BOOT_STEALTH=1` coupe le carillon et le clignotement `WIFI_AIM`, éteint les LED dès S39
    (le noyau allume la bleue quelques secondes avant : device tree `default-state = "on"`, laissé pour tout le monde) ;
    `BOOT_SOUND` ajouté à `boot.conf.dist` (D5). Entrée `[boot-stealth]`.*
    - Option dans `boot.conf` et l'interface Web désactivant les jingles sonores au haut-parleur (`sounds/startup*.pcm`) et maintenant les LED éteintes pendant toute la phase de boot.
    - Idéal pour les caméras placées en chambre de bébé ou pièces de vie nocturne lors des redémarrages automatiques de maintenance.
43. [x] **Test de latence et gigue vers le NVR / Frigate dans Diagnostics** :
    *Fait le 2026-11-05 : Diagnostics → « Lien vers l'enregistreur » (`cmd=nvr_latency`) : 10 pings vers l'adresse
    Frigate, sinon `REC_CLIENT`, sinon la box ; pertes, délai min / moy / max, gigue. Entrée `[nvr-latency]`.*
    - Bouton d'action dans l'interface Web envoyant une salve de requêtes ICMP/ping vers l'hôte NVR/Frigate configuré.
    - Affichage du RTT moyen, du jitter et du taux de perte pour lever immédiatement le doute entre instabilité caméra et congestion du réseau Wi-Fi local.
44. [x] *(2026-11-05 : fait, entrée `[ui-text]` ; 71 réglages de Réglages ; les autres pages ont déjà leurs textes d'aide)* **Infobulles explicatives pour chaque réglage dans l'interface Web (Tooltips)** :
    - Ajouter une icône d'aide ou un tooltip interactif sur chaque commutateur, curseur et champ de saisie dans l'interface Web.
    - Rôle : expliquer en langage clair la fonction exacte du réglage, son mode d'action technique et son impact recommandé.
45. [x] *(2026-11-05 : fait, entrée `[mem-budget]` ; PSS mesurée par programme, estimations seulement pour les services arrêtés ; `RTSP_QMAX` et le débit ne sont pas modélisés, faute de mesure)* **Simulateur d'occupation mémoire dynamique dans les réglages (Memory Budgeter)** :
    - Jauge d'estimation en temps réel dans l'interface Web calculant l'impact RAM prévisionnel selon les options cochées :
      - Résolution (1080p vs 720p : gain/coût ~1,7 Mo),
      - Débit binaire et taille du tampon RTSP (`RTSP_QMAX`),
      - Activation du pre-roll en RAM (ex: +800 Ko),
      - Démons optionnels (pont MQTT, détection sonore VOX, etc.).
    - Alerte visuelle / Warning dynamique (passage en orange puis rouge) dès que la configuration choisie s'approche de la zone critique (< 10 Mo de RAM libre restante) afin de guider l'utilisateur vers une configuration pérenne et stable.
46. [x] *(2026-11-05 : fait, entrée `[services-ui]` ; captures bureau, sombre et téléphone vérifiées avec les données de `src/webui/screenshots/mock`)* **Refonte ergonomique et visuelle de la page Services (`scripts.cgi`)** :
    - Remplacer le tableau linéaire étroit peu efficace par une mise en page moderne en cartes / grille responsive (grid multi-colonnes exploitant toute la largeur de l'écran).
    - Regroupement thématique clair des services : Core/Système (RTSP, Web, Housekeeper), Réseau/Accès (SSH, mDNS), Intégrations (MQTT, Telegram, Syslog).
    - Affichage compact des interrupteurs d'état (démarré/arrêté), commutateurs de boot, indicateurs d'impact RAM/CPU et boutons d'action rapide.
47. [x] *(2026-11-05 : fait, entrée `[ui-text]` ; les chaînes visibles ne citaient plus que lighttpd et le « firmware constructeur » de Infos ; le reste était dans des commentaires)* **Passe de cohérence et actualisation des textes dans toute l'interface Web** :
    - Nettoyer les mentions historiques devenues obsolètes (anciennes références à lighttpd, 2.x, v4l2rtspserver, etc.).
    - Harmoniser le vocabulaire, les infobulles, les traductions françaises (`www/i18n/fr.js`) et la documentation intégrée pour refléter l'architecture 3.0 moderne (noyau 6.6, `httpfront`, `tc100_rtsp`, pont MQTT en C).
48. [x] *(2026-11-05 : fait, entrée `[sounds]` ; conversion dans le navigateur (Web Audio) en PCM 8 kHz, la caméra ne fait que stocker ; pas de son joué sur événement, seulement les noms existants chime / alert / siren)* **Gestionnaire de sons personnalisés (Démarrage, Alertes, Upload audio)** :
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
    **Consignes du propriétaire (2026-11-05 soir) :**
    - **Dictionnaire / Shim d'adaptation sémantique Bulma -> Pico / Shoelace** : prévoir un fichier dictionnaire CSS/JS léger (~2-3 Ko) traduisant les classes Bulma existantes (`.card`, `.button.is-primary`, `.columns`, `.field.is-grouped`) vers les sélecteurs natifs de Pico ou les custom elements de Shoelace. Les pages HTML et scripts JS restent 100 % intacts sans rien casser.
    - **Stockage Flash vs SD/CDN** : Pico CSS minifié/gzippé (~10 Ko brut, ~3 Ko dans squashfs xz) peut intégrer la flash si souhaité. En revanche, Shoelace (> 350 Ko) reste obligatoirement chargé depuis la carte SD (`/mnt/sd/ext/www/`) ou CDN distant.
    - **Préalable** : avant tout travail sur #50, des tests précis de l'UI actuelle (captures de référence de chaque page, bureau / téléphone / sombre, et vérifications du comportement), faits par l'autre agent ; #50 ne commence qu'ensuite, en comparant à ces références. Voir l'entrée `[ui-baseline]` de `test-queue.md`.
    - Évaluer le remplacement ou l'évolution de Bulma vers des solutions modernes adaptées à l'embarqué :
      - **Piste 1 : Pico CSS** (champion de la légèreté, ~10 Ko gzippé) : CSS sémantique pur stylisant directement les balises HTML sans surcharger le code de classes, Dark Mode natif automatique sans JS, divise par 2 à 3 le poids des pages et la bande passante requise.
      - **Piste 2 : Shoelace (Web Components natifs)** : composants riches standardisés (`<sl-switch>`, `<sl-tooltip>`, `<sl-progress-ring>`, `<sl-dialog>`) offrant un rendu haut de gamme de type "UniFi / Synology", sans framework JS lourd (exécuté nativement par le moteur du navigateur).
      - Objectif : interface d'administration ultra-rapide, moderne, épurée et réactive avec un budget de transfert minimal.
51. [ ] *(2026-11-05 soir : W6 et M1 faits, entrées `[secrets-get]`, `[mqtt-m1]` ; D1, D3 (`tc100-logfwd` / `libnetacl` compilés par la CI depuis le 2026-11-05 soir, `[ci-uclibc]`), D4, D5, D6, D7, D9 (sauf branches `/tmp/linux66` et archivage de `test-queue.md`) faits, entrée `[audit-d]` ; W3 : décision du propriétaire le 2026-11-05, on garde le bandeau rouge « identifiants par défaut » (`default_password_active`) et la limite d'essais `WEB_LOCKOUT`, pas de mot de passe aléatoire ni d'assistant obligatoire)* **Audit du 2026-11-04, points ouverts** (*2026-11-05 : B4, B5, B6, W2 (web et RTSP ; pas ssh), R1, R2, R3,
    D2, D8 faits, voir `audit-2026-11-04.md` §7 ; restent W3, W6, M1, D1, D3-D7, D9*) : B4, B5, B6, W2 (`NET_LAN_ONLY` sans effet sur le web, ssh et RTSP
    en 3.0 alors que la doc dit le contraire), W3 (mot de passe par défaut public, pas de limite d'essais), W6
    (secrets dans des GET), R1 (clients RTSP TCP sans expiration, `MAXCLI 4`), R2 (`httpfront` : un fork par
    connexion sans plafond), R3, D1-D7, D9.

## P2 — plus tard, seulement si un besoin apparaît

52. [ ] *(2026-11-05 soir : jour/nuit et bouton reset faits dans `tc100-supervisord`, `SUPERVISOR_IMPL=c`, désactivé par défaut, entrée `[supervisord]` ; sound-detection ajouté le 2026-11-05 soir, `[supervisord-2]` ; housekeeper et cfg-persist restent en shell, volontairement : redémarreur et écriture flash)* Un seul démon C pour `sound-detection`, `housekeeper`, `auto-night-daemon`, `cfg-persist`,
    `service-watchdog`, `button-watch` (~1 Mo PSS au total) : beaucoup de logique testée à réécrire ; la RAM n'est
    pas le goulot (20 Mo stables la nuit, aucune fuite).
53. [x] *(2026-11-05 soir : `rwconf` libre compilé en CI, `getflag` / `getimage` retirés, `[rwconf-53]` ; `monvifd` reste dans l'image jusqu'à #58)* *(2026-11-05 : `monvifd` remplacé par `tc100-onvifd`, désactivé par défaut jusqu'à l'essai `[onvif]` ; restent
    `rwconf` / `getflag` / `getimage`)* Reconstruire `rwconf` / `getflag` / `getimage` depuis leurs sources en CI ; remplacer `monvifd` (binaire sans
    source ni licence) par un répondeur WS-Discovery libre.
    *Propriétaire, 2026-11-05 : ONVIF est utilisé → le remplacement de `monvifd` passe en P1, avec #12. #35 (WebRTC) :
    sans alourdir le CPU.*
    - **Cible Flash immédiate (suppression de `bin/monvifd`)** : Dès que `tc100-onvifd` est validé sur caméra, supprimer définitivement l'ancien binaire opaque `bin/monvifd` (gain direct de **228 Ko brut**, soit ~70-80 Ko de flash SquashFS).
    - **Remplacement des résidus 2.x (`rwconf`, `getflag`, `getimage`)** : Remplacer ces 3 anciens binaires uClibc (45 Ko au total) par un unique helper C minimaliste ou des fonctions intégrées directement dans `httpfront`/`tc100_rtsp`.

54. [x] *(2026-11-05 : fait, entrée `[flash-space]` ; mesuré : exclusions -65 Ko, BCJ -4 Ko sur nos binaires, le reste dépend de `ext/` ; le wizard ne charge plus Bulma au lieu du bundle)* **Gisements d'optimisation espace Flash SPI (gain net estimé : 150 à 250 Ko dans `stack.sqfs`, sans perte fonctionnelle)** :
    - *Filtre ARM pour SquashFS (`build-stack.sh`)* : ajouter l'option `-Xbcj arm` à la commande `mksquashfs` pour améliorer la compression XZ des binaires ELF ARM (`tc100_rtsp`, `httpfront`, `tc100-mqttd`, `tc100-onvifd`) de 5 à 8 % sans aucun surcoût en RAM lors de la décompression noyau (gain ~60 à 100 Ko flash).
    - *Tonalités audio de test (`sounds/`)* : exclure `sounds/test-1k-*.pcm` (141 Ko brut) de l'image flash via `-e` dans `build-stack.sh`. Ces fichiers ne servent qu'au banc d'essai usine/étalonnage et restent disponibles sur la carte SD ou via `generate_sounds.py` (gain ~40 à 50 Ko flash).
    - *Déduplication CSS WebUI (`www/css/`)* : `ui.bundle.min.css` intègre déjà Bulma + ui-modern + ui.css. Faire pointer `wizard.cgi` vers le bundle minifié et exclure les sources non groupées `bulma.1.0.2.purged.min.css` (121 Ko) et `ui.css` (41 Ko) de la flash (gain ~40 Ko flash).

55. [ ] **Chantiers de réécriture C ciblés pour gains RAM & Flash (feuille de route propriétaire 2026-11-05)** :
    - **Capture audio ALSA directe dans `tc100_rtsp` (#11)** : Éliminer le sous-processus `arecord` et le pipe Unix associé au profit d'un `snd_pcm_read` direct dans le serveur RTSP. Gain : **~660 Ko PSS** économisés, zéro fork, élimination des sauts de contexte noyau.
    - **Micro-démon superviseur unifié C (`tc100-supervisord`) (#52)** : Remplacer les boucles shell résidentes (`button-watch.sh`, `auto-night-daemon.sh`, surveillance `housekeeper`) par un seul processus C compact avec `poll()`. Gain : **~1 à 1,5 Mo de RAM PSS** récupérée et fin des forks cycliques (`read`, `cat /proc/uptime`).
    - *(2026-11-05 soir : fait, `MQTT_DISCOVERY_IMPL=c`, désactivé par défaut, entrée `[mqtt-disco]` ; mesuré : binaire +16 Ko bruts, gain de flash ≈ 5 Ko compressés seulement quand le code shell sera retiré, le gain réel est ~120 sous-shells de moins par connexion)* - **Découverte Home Assistant C dans `tc100-mqttd` (remplacement de `scripts/mqtt-bridge.sh`)** : Le script shell actuel pèse 121 Ko (2 981 lignes de shell générant du JSON statique pour Home Assistant). Intégrer la publication des topics d'autodiscovery HA directement dans le démon C `tc100-mqttd` ou un helper C dédié. Gain : **~35 à 45 Ko de flash SquashFS** libérés et fin des forks de parsing texte cycliques (`sed`/`awk`/`cat`).
    - *(2026-11-05 soir : première route faite, `statusline.cgi` natif, `HTTPFRONT_NATIVE=1`, désactivé par défaut, entrée `[httpfront-native]` ; binaire +6,5 Ko compressé, pas de gain de flash tant que les CGI restent en repli)* - **Handlers HTTP natifs en C dans `httpfront` (remplacement progressif de `state.cgi` / `action.cgi`)** : `state.cgi` (67 Ko, 1 534 lignes) et `action.cgi` (40 Ko, 1 193 lignes) forcent des forks lourds pour chaque commande web. Migrer les endpoints les plus sollicités en routes natives dans `httpfront`. Gain : **~40 à 60 Ko de flash** et latence d'action divisée par 20 (< 5 ms au lieu de 200 ms).
    - *(2026-11-05 soir, mesuré : retirer l'indentation de `fr.js` fait passer sa taille xz de 36 092 à 35 732 octets, soit 0,36 Ko : la squashfs xz compresse déjà les blancs ; non retenu. Le vrai poids est la copie `fr.js.gz` (40,7 Ko, incompressible) que `build-stack.sh` ajoute pour busybox httpd.)* - **Minification du dictionnaire français (`www/i18n/fr.js`)** : Le fichier pèse 121 Ko non minifié. Nettoyage et minification des chaînes avant SquashFS. Gain : **~15 à 25 Ko de flash**.

56. [ ] *(2026-11-05 soir : 3 (console 5 min, `SERIAL_CONSOLE`), 4 (`VM_TUNE`) faits, 5 déjà câblé (R11-01) et validé, attend le noyau de #9 ; entrées `[opt-56]` ; 1 et 2 attendent leurs essais #11 / #19)* **Optimisations avancées RAM/CPU & comportement de secours (avis propriétaire 2026-11-05)** :
    - **1. Capture ALSA directe dans `tc100_rtsp`** : *Accord propriétaire*. Déjà pré-câblé dans `src/tc100rtsp/acap.c` (`RTSP_ALSA_DIRECT=1`, voir #11) ; à valider et passer par défaut une fois testé sans régression sonore.
    - **2. Détection de mouvement matérielle VPU / P-frame stats** : *Rapprochement avec l'existant*. Le propriétaire note à juste titre que c'était déjà proposé (#19 `[md-enc]`, `RTSP_MD_ENC=1`) : l'implémentation existante analyse les écarts de taille de trames P encodées (VPU) plutôt que du CPU pixel diff. À coordonner avec l'évaluation d'un seuil adaptatif VBR et l'essai `[md-enc]`.
    - **3. Gestion getty / console série avec extinction auto 5 min & réveil safe-mode** :
      - *Mise en garde et consigne du propriétaire* : la console UART physique reste allumée à chaque redémarrage pendant 5 minutes. Si aucune session n'est ouverte ou active après ces 5 min, la boucle `getty` est désactivée automatiquement (libérant ainsi la mémoire et le sous-shell).
      - *Filet de sécurité anti-crash (Safe-Mode)* : en cas de plantage, boucle de redémarrage ou problème matériel/logiciel (levée du flag `/tmp/safemode` par `boot-guard` après 3 reboots courts, ou alerte watchdog), le délai d'extinction est annulé et **la console série / `getty` est maintenue active en permanence** pour garantir le diagnostic et le dépannage direct par le port série sous toutes circonstances.
    - **4. Réglages noyau de pression cache VFS (`vfs_cache_pressure` / `dirty_ratio`)** : *Accord propriétaire car sans risque*.
      - Configuration dans `autorun-linux66.sh` : `sysctl -w vm.vfs_cache_pressure=150` (recycle agressivement les dentries/inodes en RAM basse) et `sysctl -w vm.dirty_background_ratio=5` / `sysctl -w vm.dirty_ratio=10`.
      - Zéro risque de perte de données : les écritures sur SD sont flushées plus tôt en arrière-plan sans bloquer les allocations vidéo.
    - **5. Smart Bitrate / Smart GOP sur VPU AK3918** : *Accord propriétaire*. Activer via `libmpi_venc_ex.so` / `libakuio` (`ak_venc_set_smart_config`) pour diviser le débit par 2 à 3 sur scènes nocturnes ou immobiles sans impact CPU.

57. [x] *(2026-11-05 soir : fait, `tests/test_wiring_e2e.py`, entrée `[wiring-57]`)* **Audit final exhaustif front/back & élimination du code mort (Consigne propriétaire 2026-11-05 soir, en toute fin de projet)** :
    - **Risque identifié** : suite au très grand nombre de modifications et d'ajouts réalisés aujourd'hui (W6, secrets, exclusions flash, bundle CSS, refontes de scripts, services-ui, endpoints CGI, migration WHEP/ONVIF), il existe un risque majeur de rupture de câblage silencieuse entre le front (JS/HTML/CGI) et le back (scripts shell, daemons C, variables d'environnement).
    - **Contrôle d'intégrité de bout en bout (End-to-End wiring check)** :
      - Pour chaque bouton, formulaire, slider, toggle et appel AJAX (`fetch` / `XMLHttpRequest`) de toutes les pages web (`index.html`, `settings.html`, `view_records.html`, `hardware.html`, `backup.html`, `logs.html`, `diagnostics.html`, etc.) : vérifier que l'endpoint CGI correspondant (`state.cgi`, `action.cgi`, `config_exchange.cgi`, etc.) existe, traite bien le paramètre exact, et produit la réponse attendue sans erreur 404 ni 500.
      - Vérifier que chaque paramètre sauvé dans `/mnt/config/*.conf` est correctement relu et honoré par les daemons et scripts de démarrage (`autorun-linux66.sh`, `tc100_rtsp`, `httpfront`, `tc100-mqttd`).
    - **Chasse au code mort (Deadcode hunt)** :
      - Détecter et supprimer les fonctions JS orphelines, variables shell non référencées, fichiers temporaires ou dépendances résiduelles non appelées.
      - Consolider la suite de tests automatisés (`tests/test_*.py`) pour sanctuariser ce câblage avant le tag 3.0.1 final.

58. [ ] **Nettoyage et élimination définitive des anciens composants remplacés (Consigne propriétaire 2026-11-05 soir, dès confirmation)** :
    - **Principe impératif du propriétaire** : une fois les nouveaux composants C validés sur caméra (rc28), supprimer systématiquement et définitivement les anciens fichiers et binaires obsolètes pour récupérer un maximum de place dans la Flash SPI (ne pas laisser cohabiter les deux implémentations indéfiniment).
    - **Cibles de suppression identifiées** :
      1. **Suppression de `bin/monvifd`** : Ancien binaire opaque 2.x de 228 Ko (remplacé par `tc100-onvifd`). Gain net : **~75 à 85 Ko de Flash SquashFS**.
      2. **Suppression des scripts de supervision shell** : `scripts/auto-night-daemon.sh` et `scripts/button-watch.sh` (remplacés par `tc100-supervisord`).
      3. **Suppression ou dégraissage massif de `scripts/mqtt-bridge.sh`** : 121 Ko / 2 981 lignes de shell (remplacé par la découverte C `tc100-mqttd`). Gain net : **~35 à 45 Ko de Flash**.
      4. **Élimination de la dépendance à `arecord` dans la stack** : Une fois `RTSP_ALSA_DIRECT=1` figé par défaut, évaluer le retrait d'`arecord` de `ext/bin/` dans `build-stack.sh`.
      5. **Nettoyage des résidus 2.x (`bin/rwconf`, `bin/getflag`, `bin/getimage`)** : Remplacement ou suppression définitive.

## Prochaine RC (propriétaire, 2026-11-05 soir)

Tout faire sauf #50, qualifier, puis lancer une nouvelle RC. Décisions : B1 + B3 et W4 dans la RC ; #35 en entier
(étapes 2 à 5), désactivé par défaut (`WHEP=0`), la mesure `srtp-bench` décidant ensuite flux principal ou
secondaire ; #52 / #55 (démon C unifié) dans la RC avec un interrupteur désactivé par défaut, l'ancien chemin shell
gardé ; #56 (console série 5 min, réglages `vm`, smart bitrate) ; #50 après les références UI (`[ui-baseline]`).

## Hors implémenteur (propriétaire)

- Accord pour archiver ~50 notes anciennes du projet claude.ai et `_archive_v3-drafts/`.
- LED rouge : 2e couleur de la LED d'état en façade ? À vérifier sur caméra (réponse du 2026-11-05 : à vérifier).
- *Fait : D3, accord du 2026-11-05 : `src/libakuio/libakuio.so`, `src/httpfront/httpfront`, `src/jpegenc/jpegenc` retirés
  de git (la CI les construit).*
- Décisions B1 et W4 (voir `audit-2026-11-04.md` §6).
