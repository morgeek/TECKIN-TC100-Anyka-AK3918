# Audit de l'interface web — rc29, 2026-11-06 (testeur)

Fait sur la .24 et la .11 en rc29 (Chrome 157, interface en français) et dans le dépôt (`www/*.html`,
`src/webui/index/*.js`, `scripts/action.d/*.sh`). Aucun réglage modifié pendant l'audit (les clics ne visaient que
des boutons de lecture : mesures, actualisations, recherche Wi-Fi).

## Ce qui est bien câblé

- **Champs** : les 124 champs nommés des formulaires (`settings.html`, `backup.html`, `index.html`) sont tous lus par
  le serveur (`F_<nom>` dans `action.cgi` / `scripts/action.d`) ; aucun champ orphelin.
- **Commandes** : les 53 commandes `action.cgi?cmd=` appelées par l'interface ont un gestionnaire, sauf `logout`,
  traité dans le navigateur (`90-startup.js`, l'authentification Basic n'a pas de déconnexion côté serveur).
- **Identifiants** : aucun bouton ou lien avec `id` sans code ; les identifiants construits (`mv_cam<n>_url`,
  `<éditeur>_reload` / `_clear`) sont bien utilisés.
- **Essais réels** : « Mesurer de nouveau » (mémoire), « Actualiser la liste » (préréglages), « Vérifier la santé »
  (carte SD), « Actualiser l'image » (masques et zones), « Rechercher » (Wi-Fi, résultat en ~8 s) : chacun fait sa
  requête. Toutes les pages s'ouvrent sans erreur JavaScript (dans `index.html`).

## Doublons (même action à deux endroits ou plus)

| # | Quoi | Où | Proposition |
|---|---|---|---|
| D1 | Boutons Auto / Jour / Nuit / Éclairage IR / Filtre IR / Noir et blanc | Direct **et** Réglages → Jour/nuit | Garder ceux du Direct ; dans Jour/nuit, garder les seuils seulement (ou un lien « commandes dans Direct »). |
| D2 | LED bleue / rouge | Direct (boutons), Réglages → Système → LED (état au démarrage), Test du matériel | Expliciter dans Système « état au démarrage » (sinon on croit à un doublon) ; garder le reste. |
| D3 | Redémarrer | Menu Outils → Redémarrer **et** Système → Maintenance → « Redémarrage forcé » (même `cmd=reboot`) | En garder un ; « forcé » est faux (même redémarrage propre). |
| D4 | Sauvegarde / restauration de la configuration : **4 mécanismes** | Mise à jour et sauvegarde : « Instantané fiable » (enregistrer / restaurer), « Préréglages » (charger, enregistrer, exporter l'actuel, importer un fichier), « Échange JSON » (télécharger, envoyer à une autre caméra, importer), « Sauvegarde complète .tar.gz » | Fusionner « Exporter l'actuel / Importer un fichier » des préréglages avec l'échange JSON ; présenter : 1) sauvegarde complète, 2) export / import JSON (vers une autre caméra), 3) préréglages. L'instantané fiable fait doublon avec un préréglage nommé et avec cfga/cfgb. |
| D5 | Interrupteurs des services à clé de réglage (`recording` = `REC_LOCAL`, `syslog-forward` = `SYSLOG_ENABLE`, `memory-guard`, `whep`, `wifi-rescue`, `telegram-bot`) | Page Services (Démarrer / Arrêter / Démarrage) **et** leur onglet de Réglages | Normal qu'ils soient aux deux, mais la page Services doit dire que l'arrêt **éteint le réglage pour de bon** (cf. R15 / R19). |
| D6 | Telegram | Intégrations (jeton, chat) **et** Alertes (case « Telegram ») | Rassembler dans Alertes, ou un lien de l'un à l'autre. |

## Inutile ou trompeur en 3.0

| # | Quoi | Constat | Proposition |
|---|---|---|---|
| U1 | Menu Outils → **Éteindre** (`cmd=shutdown` → `/sbin/halt`) | Une caméra sans bouton marche/arrêt : elle reste éteinte jusqu'à ce qu'on la débranche ; à distance, c'est la perdre. | Retirer du menu (ou derrière une confirmation explicite « il faudra la débrancher »). |
| U2 | Système → **Vider le cache mémoire** (`drop_caches`) | Aucun gain : le cache est rendu dès qu'il faut ; `VM_TUNE` règle déjà la mémoire. | Retirer. |
| U3 | Système → Performance et sécurité : « durcissement » | En 3.0, `SECURITY_HARDENING_MODE` n'agit plus que sur ftp / telnet (`WEB_MODE` HTTPS n'existe plus : rien ne le lit) ; le texte promet encore HTTPS. Le bouton enregistre aussi `LIGHTWEIGHT_MODE=0` (champ absent de la page, `95-settings-page.js` l. 163 remplit un champ qui n'existe pas) ; sans effet car rien ne lit `LIGHTWEIGHT_MODE` en 3.0. | Revoir le texte (« coupe FTP et Telnet ») ; retirer `lightweight_mode` du JS et de `set_advanced_tuning`. |
| U4 | Clés de `boot.conf` sans lecteur en 3.0 (Éditeur de configuration) | `WEB_MODE`, `ULTRALITE_HTTP_PORT`, `UI_ULTRALITE_MODE`, `LIGHTWEIGHT_MODE`, `CPU_SCALER_*`, `RTSP_SERVER`, `RTSP_VENDOR_PORT`, `RTSP_LITE_*`, `RTSP_PROC_*`, `RTSP_FPS_LOCK`, `FIRMWARE_IMAGE`, `STORAGE_CLEANUP_*`, `TAMPER_DETECTION` (le sabotage passe par `tamper.conf`). L'entrée `autostart/cpu-scaler` existe sur les deux caméras mais l'autorun l'ignore. | Les retirer du `boot.conf.dist` de 3.0 (migration qui les commente), ou les marquer « 2.x seulement ». |
| U5 | Intégrations → MQTT : étiquette « 25+ Discovery Nodes » | Texte fixe ; la caméra en publie 49. | Afficher le nombre réel (ou retirer). |
| U6 | Réseau → Wi-Fi → Rechercher : colonne « Quality » | Elle affiche des dBm (-54.00). | Renommer « Signal (dBm) », sans décimales. |
| U7 | Services : `web-server` « En marche depuis 1s » | L'âge est celui du processus CGI qui répond, pas de `httpfront`. | Prendre le pid de `httpfront`. |
| U8 | Jour/nuit : seuils | Les champs de la méthode « luminance » et de la « méthode d'origine » sont affichés ensemble quel que soit le choix de « Mesure de la lumière ». | N'afficher que ceux de la méthode choisie. |
| U9 | Alerte « identifiants par défaut actifs » | Justifiée (mot de passe `pass`), mais sans lien vers le formulaire « Changer le mot de passe ». | Ajouter le lien. |

## Défaut trouvé pendant l'audit (corrigé)

- **Journal système et syslog distant morts** sur les deux caméras (`SYSLOG_ENABLE=1`) : `syslogd_start` lance
  `syslogd -D -f`, options absentes de la BusyBox de la base 3.0 ; `syslogd` s'arrête aussitôt, `/var/log/messages`
  s'arrête au démarrage du service et rien ne part vers 192.168.1.23. La page Services affichait bien
  `syslog-forward` « Arrêté ». Corrigé en `bf6d15c` (options activées dans `busybox.fragment` + repli sans ces options
  dans le script). Relancé en RAM sur les deux caméras (perdu au redémarrage jusqu'à la rc30).
