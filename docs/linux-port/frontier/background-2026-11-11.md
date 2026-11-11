# Dossier `background` — vérification de la réponse du 2026-11-11

Réponse du modèle : [rtsp-background-2026-11-11-reponse.md](rtsp-background-2026-11-11-reponse.md), partie B.
Mesures : [data/background-2026-11-11.md](data/background-2026-11-11.md). Tests : `tests/test_fork_cuts.py` (chaque
nouvelle ligne comparée à l'ancienne dans busybox ash ; deux mutations volontaires font échouer le test).

| Constat | Verdict | Preuve et suite |
|---|---|---|
| C1 — `wifi-quality.sh` : ~25 forks par minute | **Confirmé pour les lignes montrées, en partie corrigé** | `wq_gateway` : les deux `$(echo \| cut)` remplacés par des expansions (même adresse pour 6 passerelles testées). `wq_loss` : `printf \| sed \| head` remplacé par `case` + expansions (même résultat sur 7 sorties de ping, dont busybox, iputils, 100 % de perte, sortie vide, réseau injoignable, deux lignes qui correspondent). Environ **−10 forks par minute**. Laissés : `$(date +%s)`, les `mv` (renommage atomique), `wc -l` du journal, `wq_station` (demande un fichier temporaire : à faire avec son propre test). |
| C2 — `wifi-roam.sh` : 4-5 forks par minute pour ne rien faire | **Confirmé, corrigé** | L'heure vient de `/proc/uptime` lu par `read` (plus de `$(cut)`), `mkdir -p` seulement si le dossier manque, `rm -f` seulement si le fichier existe. Chemin « signal bon » : 1 fork (le lancement du job). Environ **−3 à −4 forks par minute** quand `WIFI_ROAM=1`. |
| C3 — `health-snapshot.sh` : un `$(probe_service_fast …)` par service | **Plausible, non corrigé** | `probe_service_fast` est dans `scripts/health-probe.sh`, non montré au modèle ; à reprendre en variable avec un test (−11 forks toutes les 5 min, soit ~2 par minute). |
| C4 — `collect_slow_health_metrics` (MQTT) : au moins 27 forks par cycle | **Plausible, non corrigé** | Période du cycle non montrée. Les rafales ont vu 12 à 19 processus du pont MQTT en 136 s. À reprendre avec un test de la charge utile MQTT. |
| C6 — 35 à 50 forks par minute hors extraits | **Accepté** | `net-guard.sh`, la boucle du pont MQTT, `cfg-persist`, `reboot-tracker.sh` n'étaient pas dans le dossier. La mesure H1 (retirer un job 10 min) les attribuera. |
| C7 — coût d'un fork | **Supposé, à mesurer** | La boucle `busybox true` × 200 proposée est lecture seule et sans effet ; à lancer sur la .11. |

Gain attendu de ce qui est corrigé : environ −13 à −14 forks par minute sur 78 à 100 (15 %), soit peut-être 0,3 à
0,6 point de CPU. À vérifier par la même capture de 2 h après installation (`processes` par minute).
