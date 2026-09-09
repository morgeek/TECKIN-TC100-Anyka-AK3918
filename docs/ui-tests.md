# Validation UI rc2

Aucun test de ce lot ne commande une vraie caméra. Les 27 tests hôte comprennent
les vérifications précédentes, la réponse applicative des enregistrements, la
relecture des deux flux, les erreurs d’écriture vidéo/audio et les correspondances
avec les sections du vrai modèle de configuration INI. Les interactions
Chrome utilisent les vrais HTML/CSS/JavaScript du dépôt avec des réponses CGI simulées.

```sh
python3 -m unittest discover -s tests -v
```

Les 14 vérifications navigateur couvrent les sections avancées, la conservation
des valeurs, le double envoi, la désactivation pendant la sauvegarde, le choix du
flux secondaire, la relecture, la suppression différée du brouillon, les erreurs
applicatives HTTP 200, les brouillons conservés, les valeurs différentes à la
relecture, les champs invalides cachés, leur focus et l’échec du chargement initial.
Les captures ont été inspectées en 390 px et 1280 px, thèmes clair et sombre.

Pour reproduire avec Python 3, Node.js 24 et Chrome installé, créer un **dossier de
test vide** et générer la page (exemple macOS) :

```sh
python3 tests/ui-browser/make_fixture.py /tmp/tc100-ui-test
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless --disable-gpu --no-first-run --disable-background-networking \
  --no-default-browser-check --user-data-dir=/tmp/tc100-ui-test/chrome-profile \
  --remote-debugging-port=9339 about:blank
```

Dans un autre terminal, depuis le dépôt :

```sh
node tests/ui-browser/check.mjs /tmp/tc100-ui-test
```

Les captures et `results.json` sont écrits dans ce dossier. Fermer ensuite le
Chrome de test avec Ctrl+C dans le premier terminal. Le profil est isolé ; la page
simulée efface son stockage local au chargement pour repartir sans ancien brouillon.
Ces tests ne vérifient pas l’ash/BusyBox ARM ni la reprise vidéo sur le matériel.
