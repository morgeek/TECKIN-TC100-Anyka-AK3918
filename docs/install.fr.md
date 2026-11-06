# Guide d'installation

Pour les propriétaires de caméra, aucune connaissance en programmation nécessaire. English: [install.md](install.md).
Retour au [README](../README.md) (en anglais). Problèmes connus : [known-issues.md](known-issues.md) (en anglais).
Détails techniques de l'installation : [linux-port/install-3.0.md](linux-port/install-3.0.md).

Chaque étape dit **quoi faire**, **ce que vous devez voir**, et **quoi faire sinon**. Les noms de menus sont ceux de
l'interface en français (Réglages, etc.).

Sommaire : [1. Ce qu'il faut](#1-ce-quil-faut) · [2. Télécharger et préparer la carte](#2-télécharger-et-préparer-la-carte) ·
[3. Premier démarrage (mode essai)](#3-premier-démarrage-mode-essai-rien-décrit-dans-la-mémoire-flash) ·
[4. Assistant de configuration et mot de passe](#4-assistant-de-configuration-et-mot-de-passe) ·
[5. Vérifier que ça marche](#5-vérifier-que-ça-marche) · [6. Installer dans la caméra, mettre à jour](#6-installer-dans-la-caméra-mettre-à-jour-plus-tard) ·
[7. Le retour arrière](#7-le-retour-arrière-vers-le-firmware-dorigine) · [8. Dépannage](#8-dépannage) ·
[9. Où demander de l'aide](#9-où-demander-de-laide)

---

## 1. Ce qu'il faut

- Une caméra **TECKIN TC100** (TECKIN Click). Une seule variante matérielle est connue pour l'instant
  ([variantes matérielles](hardware-variants.md), en anglais). La carte contrôle d'abord la caméra et n'écrit rien dans
  une caméra qu'elle ne reconnaît pas.
- Une **carte microSD de 32 Go maximum**, formatée en **FAT32**. Les cartes de plus de 32 Go sont en général en exFAT :
  reformatez-les d'abord en FAT32 (Rufus ou `guiformat` sous Windows, Utilitaire de disque avec « MS-DOS (FAT) » sur Mac).
- Un **ordinateur** avec un lecteur de carte, pour copier des fichiers. Rien à installer dessus.
- La caméra branchée, à portée de votre Wi-Fi. Ayez sous la main le nom et le mot de passe de votre Wi-Fi.
- Environ 20 minutes la première fois.
- Facultatif mais prudent : une **deuxième carte microSD** pour les enregistrements (voir l'étape 6).

## 2. Télécharger et préparer la carte

1. **Téléchargez** `tc100-<version>-sd.zip` depuis la
   [page des versions](https://github.com/morgeek/TECKIN-TC100-Anyka-AK3918/releases) (`MD5SUMS.txt` donne les sommes de
   contrôle). La version contient aussi `tc100-<version>-update.tar` (pour les mises à jour ultérieures depuis la page web)
   et `tc100-<version>-inventory.zip` (ne fait que lire de quoi est faite votre caméra).
2. **Formatez la carte en FAT32** (voir l'étape 1).
3. **Décompressez le paquet à la racine de la carte.** Sous Windows, « Extraire tout » propose un nom de dossier : enlevez-le.
4. **Caméra jamais configurée en Wi-Fi ?** Créez à la racine de la carte un fichier texte `wifi.txt` de deux lignes :
   ```
   SSID=nom de votre réseau
   PASSWORD=son mot de passe
   ```
   Une caméra qui connaît déjà votre Wi-Fi (application TECKIN, ou une version précédente de ce firmware) garde son réseau.
5. **Mode essai (conseillé la première fois) :** créez un fichier **vide** nommé `ESSAI.txt` (ou `TRIAL.txt`) à la racine
   de la carte.

**Ce que vous devez voir :** la carte montre directement les dossiers `wifitest`, `tc100test`, `tc100-3`, `www`... et le
fichier `00-LISEZ-MOI-READ-ME.txt` (les mêmes étapes en français et en anglais).

**Sinon :** si vous voyez un seul dossier (par exemple `tc100-...-sd`) qui les contient, remontez son contenu à la racine
de la carte. Un doute sur la compatibilité de la caméra ? Utilisez plutôt `tc100-<version>-inventory.zip` (mêmes étapes ;
il n'écrit que `tc100-inventory.txt` sur la carte) et envoyez ce fichier dans un ticket *Hardware inventory*.

## 3. Premier démarrage (mode essai, rien d'écrit dans la mémoire flash)

1. Caméra **éteinte**, mettez la carte, puis branchez l'alimentation.
2. **Laissez-la branchée. Ne la débranchez pas pendant les deux premières minutes.**

**Ce que vous devez voir :**
- **LED bleue qui clignote** environ 2 minutes : la caméra copie toute sa mémoire sur la carte
  (`tc100-3/backup/flash-stock.bin` : c'est votre retour arrière), puis redémarre sur le nouveau firmware **depuis la carte**.
- Environ une minute plus tard, un **petit son**. En mode essai, le firmware ne tourne que depuis la carte. Il n'est pas
  écrit dans la mémoire de la caméra : retirez la carte et redémarrez, la caméra relance son firmware précédent.
  (Tout au début, une petite entrée est ajoutée une seule fois aux réglages de démarrage de la caméra pour qu'elle regarde
  la carte en premier ; le chargeur de démarrage lui-même n'est jamais écrit.)
- Sans le fichier `ESSAI.txt`, la caméra poursuit seule vers l'installation dans sa mémoire (étape 6) : LED bleue qui
  clignote de nouveau environ 10 minutes, puis un son. Ne la débranchez pas.

**Sinon :**
- *Rien ne se passe, pas de LED bleue :* les fichiers ne sont pas à la racine de la carte, ou la carte n'est pas en FAT32.
  Refaites l'étape 2.
- *LED rouge allumée :* la caméra s'est arrêtée ; soit rien n'a été modifié, soit elle fonctionne avec le nouveau
  firmware depuis la carte, sa mémoire flash n'ayant pas été écrite. Lisez `tc100-3/STATUS.txt` sur la carte depuis un
  ordinateur. « Not a TC100 variant the firmware knows » veut dire que la caméra n'a pas été touchée : envoyez
  `tc100-inventory.txt` dans un ticket *Hardware inventory*.

## 4. Assistant de configuration et mot de passe

1. Ouvrez **http://tc100/** dans un navigateur du même réseau. Si ça ne marche pas, prenez l'adresse de la caméra dans la
   liste des appareils de votre box ; elle est aussi écrite dans `tc100-3/ADRESSE.txt` sur la carte.
2. Connectez-vous avec l'utilisateur `root`. Le **mot de passe par défaut est public ; il figure dans le premier fichier du
   zip** (`00-LISEZ-MOI-READ-ME.txt`) et dans les notes de version.
3. L'**assistant de configuration** démarre. Ses étapes :
   - **Langue et Wi-Fi** : garder le Wi-Fi actuel ou en indiquer un autre.
   - **Profil d'intégration** : *Autonome*, ou *Frigate + Home Assistant* (recommandé si vous les utilisez).
   - **Mot de passe de la caméra** : **choisissez le vôtre** (un seul mot de passe pour la page web, RTSP, FTP et telnet ;
     4 caractères au moins, sans espace ni guillemet). Le laisser vide garde le mot de passe public par défaut : ne le faites pas.
   - **Frigate et Home Assistant** (seulement avec ce profil) : adresse du broker MQTT, port, utilisateur et mot de passe
     facultatifs, adresse de Frigate facultative.
   - **Enregistrement sur la carte SD** : quand Frigate ne reçoit plus la vidéo (recommandé), toujours, ou désactivé.
   - **Fonctionner sans carte SD** (seulement quand la caméra tourne depuis la carte) : *Installer dans la caméra
     maintenant* ou *Pas maintenant*.
   - **Résumé**, puis **Appliquer et démarrer**.
4. Notez votre nouveau mot de passe dans un gestionnaire de mots de passe. Ne le publiez jamais, ni dans un message public
   ni dans un ticket.

**Ce que vous devez voir :** « Configuration applied » (configuration appliquée), puis la page se recharge et demande de se
reconnecter avec le nouveau mot de passe.

**Sinon :** un message rouge sous le mot de passe indique qu'il est trop court ou contient un caractère interdit. Si un
mauvais choix de Wi-Fi vous fait perdre la caméra, voyez la ligne Wi-Fi du [dépannage](#8-dépannage). Vous pouvez relancer
l'assistant plus tard (*Relancer l'assistant* dans les Réglages).

> Tant que le mot de passe par défaut est actif, le tableau de bord affiche un bandeau rouge **« Sécurité : mot de passe
> par défaut »**. Il disparaît quand vous changez le mot de passe dans Réglages → Système → Mot de passe.

## 5. Vérifier que ça marche

- **Page web :** le Tableau de bord montre l'image en direct (en mode essai, la première image peut mettre un instant). La
  page *Aperçu* et *Multi-Vues* la montrent aussi.
- **RTSP :** ouvrez cette adresse dans VLC (Média → Ouvrir un flux réseau), avec l'utilisateur `root` et votre mot de passe :
  - flux principal : `rtsp://ADRESSE-CAMERA:554/video0_unicast`
  - sous-flux : `rtsp://ADRESSE-CAMERA:554/video1_unicast`
- **Frigate :** Aperçu → Plus d'outils → Diagnostic donne une configuration à coller. Elle ne contient jamais le mot de
  passe de la caméra : définissez la variable `FRIGATE_RTSP_PASSWORD` dans l'environnement de Frigate. Donnez un nom à
  chaque caméra (Réglages → Réseau → Nom d'hôte).
- **Home Assistant :** avec le profil MQTT, la caméra apparaît d'elle-même grâce à la découverte MQTT.

**Sinon :** pas d'image dans VLC : vérifiez l'adresse, le mot de passe, et que la caméra et l'ordinateur sont sur le même
réseau. Une page lente quelques secondes est normale sur cette caméra à un seul coeur. Plus de détails dans le
[dépannage](#8-dépannage).

## 6. Installer dans la caméra, mettre à jour plus tard

**Pourquoi installer ?** En mode essai, le firmware tourne depuis la carte : il s'arrête si on la retire et les **mises à
jour par la page web sont impossibles**. L'installation l'écrit dans la mémoire de la caméra : elle fonctionne alors sans
la carte (qui ne sert plus qu'aux enregistrements) et se met à jour depuis la page web.

**Ce qui est écrit, et ce qui ne l'est jamais.** Écrits : le noyau, le système libre, une copie des bibliothèques propres à
la caméra (prises sur votre caméra, jamais publiées) et la zone des réglages. **Jamais écrits :** le chargeur de démarrage
(U-Boot) et les données radio (`mac`). Chaque partie est d'abord sauvegardée sur la carte puis relue après écriture.

**Comment installer :**
- Sans `ESSAI.txt`, la carte installe seule après les contrôles (étape 3). Rien à cliquer.
- En mode essai, choisissez *Installer dans la caméra maintenant* dans l'assistant, ou plus tard allez dans **Réglages →
  Mise à jour et sauvegarde → Installer en flash (fonctionner sans carte SD)** et appuyez sur **Installer en flash et
  redémarrer**. Compter 6 à 10 minutes. **Ne débranchez pas la caméra.**

**Ce que vous devez voir :** un son, puis la page web de nouveau. La carte n'est plus nécessaire pour démarrer la caméra.

**Sinon :** LED rouge et `tc100-3/STATUS.txt` qui donne la raison : la mémoire flash n'a pas été modifiée, la caméra
tourne depuis la carte et la page web peut réessayer. Une installation interrompue (coupure de courant) laisse le système
flash incapable de démarrer : gardez la carte, elle redémarre la caméra et *Installer en flash* réécrit tout.

**Enregistrements après l'installation.** Une carte qui contient encore les fichiers d'installation (`wifitest`,
`uImage`...) est **refusée pour l'enregistrement** (elle ferait démarrer le firmware d'origine dessus). Gardez la carte
d'installation comme retour arrière et utilisez une deuxième carte pour les enregistrements (FAT32 ou exFAT). Insérez-la
caméra éteinte : une carte insérée pendant que la caméra fonctionne n'est pas détectée.

**Mettre à jour plus tard (sans carte SD) :**
1. Téléchargez `tc100-<version>-update.tar` depuis la [page des versions](https://github.com/morgeek/TECKIN-TC100-Anyka-AK3918/releases).
2. Ouvrez **Réglages → Mise à jour et sauvegarde → Mise à jour du firmware**, appuyez sur **Choisir…**, prenez le
   fichier, puis **Envoyer et vérifier**.
3. Quand la vérification est bonne, appuyez sur **Installer et redémarrer**. Attendez le redémarrage de la caméra
   (plusieurs minutes). Ne la débranchez pas.

Vos réglages sont conservés. Faites une **Sauvegarde complète** (même page) avant de gros changements.

**Si c'est refusé :** « Running from the SD card (trial) » : installez d'abord dans la mémoire flash. « Not enough free
memory » : mettez une carte FAT32 dans la caméra et envoyez de nouveau. Une mise à jour interrompue en cours de route
demande la carte, comme ci-dessus.

## 7. Le retour arrière vers le firmware d'origine

Gardez la carte et son fichier `tc100-3/backup/flash-stock.bin` (ne le partagez jamais : c'est une copie de la mémoire de
votre caméra).

1. Éteignez, retirez la carte, mettez-la dans un ordinateur.
2. Renommez `tc100test/c66.img.installed` en `c66.img`.
3. Créez un fichier vide `RESTAURER.txt` (ou `RESTORE.txt`) à la racine de la carte.
4. Carte dans la caméra, allumez. La LED bleue clignote environ 10 minutes pendant que la caméra réécrit son firmware
   d'origine, puis elle redémarre dessus. **Ne la débranchez pas.**
5. Retirez la carte.

Si vous n'avez fait qu'essayer en mode essai, retirez simplement la carte et redémarrez. La restauration refuse une copie
qui ne correspond pas à votre caméra, et le chargeur de démarrage n'est jamais touché.

## 8. Dépannage

| Problème | Que faire |
|---|---|
| **Caméra introuvable sur le réseau** | Attendez 15 minutes la première fois. Essayez `http://tc100/`, puis l'adresse de la liste d'appareils de votre box ou `tc100-3/ADRESSE.txt` sur la carte. Si votre navigateur ou réseau ne résout pas les noms : utilisez l'adresse IP. |
| **Le Wi-Fi ne se connecte pas** | Vérifiez `wifi.txt` (deux lignes, orthographe exacte ; un fichier invalide est renommé `wifi-invalid.txt` avec la raison). Après 10 minutes sans Wi-Fi, ou en maintenant le bouton reset de 3 à 7 secondes, la caméra ouvre son propre **Wi-Fi de secours** `TC100-<MAC>` (son mot de passe par défaut est dans `00-LISEZ-MOI-READ-ME.txt`). Connectez-vous-y et ouvrez `http://10.42.0.1/` pour saisir votre réseau. Réglages → Réseau propose aussi un pays pour les règles Wi-Fi. |
| **Rien au premier démarrage, pas de LED bleue** | Fichiers pas à la racine de la carte, ou carte pas en FAT32. |
| **LED rouge allumée** | Lisez `tc100-3/STATUS.txt` sur la carte. Détails aux étapes 3 et 6. |
| **Carte refusée pour l'enregistrement** | La carte contient des fichiers de démarrage (`wifitest`, `uImage`, `root.sqsh4`...). Utilisez une autre carte pour les enregistrements, ou une carte sans eux. |
| **Bandeau rouge « Sécurité : mot de passe par défaut »** | Changez le mot de passe : Réglages → Système → Mot de passe. |
| **Premier démarrage ou pages lents** | Avec l'installation, le premier démarrage prend 15 minutes en tout. En usage normal, certaines pages prennent quelques secondes sur cette caméra à un seul coeur. Dans la première minute après un démarrage, le réseau peut ne pas répondre encore. |
| **Mode sans échec (safe mode)** | Après 3 démarrages de suite terminés en moins de 5 minutes (plantage, watchdog), le démarrage suivant ne lance que le Wi-Fi, la page web, ssh et le bouton reset ; ni vidéo ni MQTT. La page Information indique « SAFE MODE ». Utilisez la page web pour mettre à jour ou corriger la cause, puis redémarrez une fois la caméra restée allumée 5 minutes. Les redémarrages depuis la page web ou le bouton reset ne comptent pas. |
| **La caméra ne revient pas après une mise à jour** | Démarrez-la avec la carte 3.0 (sans `ESSAI.txt` si vous voulez réinstaller) et utilisez *Installer en flash*. |
| **Autre chose** | Voyez [known-issues.md](known-issues.md), puis demandez (section suivante). |

## 9. Où demander de l'aide

- Lisez [known-issues.md](known-issues.md) et le [README](../README.md) (en anglais).
- Ouvrez un ticket sur <https://github.com/morgeek/TECKIN-TC100-Anyka-AK3918/issues/new/choose>. Dites ce que vous avez
  fait, ce que vous avez vu, la version du firmware (page Information) et, si possible, la fin de `tc100-3/STATUS.txt`.
- **Ne publiez jamais** votre mot de passe, celui de votre Wi-Fi, des identifiants MQTT ou RTSP, ni
  `tc100-3/backup/flash-stock.bin`.
