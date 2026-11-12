Relecture des CGI (func.cgi, action.cgi, config_exchange.cgi), TC100
1. Réponse courte
Seules des variables F_<nom> peuvent être créées (prouvé) ; l’eval tient tant que les quatre substitutions d’échappement sont exactes dans ce busybox (H1).
La boucle d’analyse n’a pas de set -f : une requête GET peut faire parcourir /proc au shell (prouvé).
csrf_guard accepte un jeton vide des deux côtés si la génération échoue (prouvé à la lecture ; déclencheur H2).
action.cgi n’appelle que csrf_guard, qui laisse passer tout GET : un GET qui modifie n’a aucune garde (H3, répartiteur absent).
Corps lent, décodage %XX à un fork par octet et borne 64 Ko contournable : déni de service avant toute garde.
2. Constats

C1. Expansion de chemins dans l’analyse (prouvé).

for _VAR in ${QUERY_STRING} (func.cgi l. 185-186) est sans set -f, alors que _ce_form_get le pose (config_exchange.cgi l. 458).
Un mot comme /proc/*/*/* est développé par le shell avant le contrôle du nom : processeur et mémoire consommés, en GET, avant limite de débit et CSRF.
Effet secondaire : un fichier au nom alphanumérique dans le répertoire courant crée F_<fichier>.

C2. Jeton CSRF vide accepté (prouvé ; déclencheur H2).

La comparaison "$_cg_header" != "$_cg_stored" (csrf_guard, dernière condition) ne vérifie pas que le jeton stocké est non vide.
H2 : si hexdump n’a pas de lien (même panne que tr, l. 51-56), le jeton généré est vide, et un POST sans en-tête passe.

C3. GET qui modifie (H3, supposé).

action.cgi l. 411 appelle csrf_guard, pas mutation_guard ; GET et HEAD ressortent sans contrôle.
La l. 402 limite reboot et shutdown pour toute méthode, ce qui suggère qu’ils sont acceptés en GET.
Conséquence : une simple balise image sur une page tierce suffit à déclencher la commande.

C4. Décodage coûteux avant les gardes (prouvé).

urldecode lance un $(printf) par %XX (l. 131) et recopie la chaîne à chaque caractère.
Un corps de 64 Ko en %41 donne environ 21 000 forks ; le dossier cite déjà 20-25 s pour 144 valeurs.
Le décodage a lieu au chargement de func.cgi, donc avant rate_limit_check et csrf_guard.

C5. Corps lent (prouvé).

head -c "$_cl" (l. 106, et import l. 501) bloque jusqu’à réception de la longueur annoncée, sans délai.
Chaque connexion muette retient un processus shell ; le délai du serveur web n’est pas montré.

C6. Borne 64 Ko contournable (H4, supposé).

[ "$_cl" -gt 65536 ] && _cl=65536 (l. 105) : si test échoue sur un nombre hors plage (code 2), la borne n’est pas appliquée.
Entre 2³¹ et 2³²−1, head -c peut accepter la valeur et tout charger en mémoire.
L’import est sûr sur ce point : ses tests échouent vers le refus (l. 491-492).

C7. sanitize_int_range laisse passer un nombre géant (H4, même cause).

Avec 99999999999999999999, les deux comparaisons échouent et la valeur ressort inchangée (action.cgi l. 442-447).
Une valeur comme 08 passe aussi, et casse un $(( )) ultérieur.

C8. Import : pas de défense locale sur chemin et valeur (H5, supposé).

_ce_rel sert de chemin sans contrôle de .. ni de / initial (_ce_prepare_file, mode single l. 542).
Une valeur décodée contenant un saut de ligne ou une tabulation ajouterait une ligne dans le fichier .edits, donc une clé hors table.
En modes flatd / flatq, un guillemet ferme la valeur. Tout repose sur _ce_build_rows et tc_normalize_and_validate, absents.

C9. Échappement de l’eval (prouvé correct en théorie, H1).

Le nom est limité à [A-Za-z0-9_] (l. 194-199) et les quatre caractères dangereux sont échappés, barre oblique inverse d’abord.
H1 : le rendu de ${v//\\/\\\\} varie selon les versions d’ash ; s’il ne double pas, \" sort de la chaîne.
Un %00 est supprimé en silence ; en doublon, le dernier gagne, donc l’URL l’emporte sur le corps.

C10. Limite de débit (prouvé, faible).

Lecture puis écriture sans verrou : des requêtes parallèles comptent moins que le réel.
Un lecteur qui tombe sur le fichier tronqué remet le compteur à zéro.
La limite et la purge des caches (l. 386-389) passent avant le CSRF : un POST forgé consomme le quota de l’utilisateur.
3. Proposition
diff
--- func.cgi (corps POST)
   case "$_cl" in ''|*[!0-9]*) _cl=0 ;; esac
+  case "$_cl" in ??????*) _cl=65536 ;; esac	# 6+ digits: skip the numeric test
   [ "$_cl" -gt 65536 ] && _cl=65536
-  POST_QUERY_STRING="$(head -c "$_cl" 2>/dev/null)"
+  POST_QUERY_STRING="$(timeout 10 head -c "$_cl" 2>/dev/null)"
--- func.cgi (boucle)
-_IFS=${IFS}; IFS='&'
+_IFS=${IFS}; IFS='&'; set -f
@@
-  esc_value="${value//\\/\\\\}"
-  esc_value="${esc_value//\"/\\\"}"
-  esc_value="${esc_value//\`/\\\`}"
-  esc_value="${esc_value//\$/\\\$}"
-  eval "F_${name}=\"${esc_value}\""
+  eval "F_${name}=\$value"	# name validated; value never parsed
 done
-IFS=${_IFS}
+set +f; IFS=${_IFS}
--- func.cgi (csrf_guard)
-    if [ -r /dev/urandom ]; then
+    if read -r _cg_u < /proc/sys/kernel/random/uuid 2>/dev/null; then
+      _cg_stored="${_cg_u//-/}"	# 32 hex, no fork, no applet
+    elif [ -r /dev/urandom ]; then
@@
-  if [ "$_cg_header" != "$_cg_stored" ]; then
+  if [ "${#_cg_stored}" -lt 32 ] || [ "$_cg_header" != "$_cg_stored" ]; then
--- action.cgi (sanitize_int_range)
-    ''|*[!0-9]*)
+    ''|*[!0-9]*|??????????*)
--- config_exchange.cgi (_ce_import)
     [ -n "$_ce_rel" ] || continue
+    case "$_ce_rel" in /*|*..*) _ce_fail "Invalid path" "VALIDATION_FAILED" ;; esac
@@
     _ce_value="$TC_NORMALIZED_VALUE"
+    case "$_ce_value" in *[[:cntrl:]]*) _ce_fail "Invalid value for ${_ce_rel}:${_ce_key}" "VALIDATION_FAILED" ;; esac

Pour C3, dans action.cgi à la place de csrf_guard (liste à compléter depuis le répartiteur) :

case "$F_cmd" in
  sd_card_info|wifi_get_ssid|local_rec_status|…) csrf_guard ;;   # lectures, GET admis
  *) mutation_guard ;;                                           # tout le reste : POST + jeton
esac

Pour C4 : refuser avant décodage une valeur brute de plus de 4096 caractères. Ce seuil est à valider contre configeditor.cgi, qui peut poster un fichier entier (non montré).

4. Contrôles, dans l’ordre

Avec CAM l’adresse de la caméra et T le jeton lu dans /tmp/csrf_token.

H1, H4 (shell de la caméra).
v='\'; printf '%s\n' "${v//\\/\\\\}" : deux barres attendues ; une seule confirme H1.
[ 4000000000 -gt 65536 ]; echo $? : 2 confirme H4.
sanitize_int_range 99999999999999999999 0 100 50 : toute sortie autre que 50 ou 100 confirme C7.
C1. time curl -g "http://$CAM/cgi-bin/action.cgi?/proc/*/*/*" comparé au même appel sans paramètre. Un écart net confirme ; après correctif, temps égaux.
C2 / H2. wc -c < /tmp/csrf_token doit donner 32. Puis curl -i -X POST -d 'cmd=sd_card_info' "http://$CAM/cgi-bin/action.cgi" : 403 attendu ; 200 confirme le jeton vide.
C3 / H3. curl -i "http://$CAM/cgi-bin/action.cgi?cmd=reboot" : si la caméra redémarre, H3 est confirmée ; 405 après correctif.
C4. curl -o /dev/null -w '%{time_total}\n' -d "x=$(printf '%%41%.0s' $(seq 20000))" "http://$CAM/cgi-bin/action.cgi" : plusieurs dizaines de secondes confirment.
C5. curl -m 300 -H 'Content-Length: 65536' -d 'a=1' "http://$CAM/cgi-bin/action.cgi", puis ps sur la caméra : un head bloqué confirme ; après correctif il disparaît en 10 s.
C10. seq 40 | xargs -P 40 -I{} curl -s -o /dev/null -w '%{http_code}\n' -X POST -H "X-CSRF-Token: $T" -d 'cmd=sd_card_info' "http://$CAM/cgi-bin/action.cgi" | sort | uniq -c : moins de vingt réponses 429 confirme la course.
C8 / H5. Test hors caméra : faire lire à la boucle un fichier de lignes forgé (../x|single|… et une valeur a%0Aflat%09%09AUTRE%09 1). Un fichier hors de la zone de préparation ou une clé AUTRE confirme. Pas de curl possible : le format JSON accepté n’est pas montré.
5. Ce qui manquait
config_exchange.cgi : _ce_build_rows, la table autorisée, _ce_fail, _ce_cleanup, l’origine de _ce_form, et l’appel à mutation_guard.
tc_normalize_and_validate, tc_apply_edits, tc_commit_config_files (fichier non nommé).
Le répartiteur de commandes d’action.cgi (après la l. 47) et wants_json_response.
state.cgi : remise du jeton et en-têtes inter-origines.
Le serveur web et sa configuration : authentification, délai de lecture du corps, nombre de CGI simultanés.
Les scripts qui lisent les fichiers de configuration : savoir s’ils sont chargés par . (une valeur flat serait alors exécutée).