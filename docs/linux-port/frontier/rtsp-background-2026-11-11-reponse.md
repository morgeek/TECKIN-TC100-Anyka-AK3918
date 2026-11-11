# Réponse du modèle aux dossiers `rtsp` et `background` (2026-11-11, recopiée telle quelle)

A. tc100_rtsp : part fixe du fil principal et coût par paquet RTP
1. Réponse courte
La part fixe vient surtout du chemin micro : envoi RTP audio (50 paquets/s) et traitement par échantillon, qui tourne même quand personne n’écoute le son traité.
Les réveils de select, le travail par seconde et le tick de 5 s pèsent moins de 0,3 % au total d’après les extraits.
Les extraits n’expliquent qu’environ 2,5 à 4 % des 6,5 % ; le reste est dans du code non montré ou dans le biais de l’ajustement (deux caméras, une au crépuscule).
0,26 ms système par paquet est plausible sur ce cœur ; sendmmsg n’y gagnerait presque rien.
Les ~3 défauts de page par image correspondent au malloc / free d’une copie de 8 ko par image (H4).
2. Constats

C1. Classement des candidats à la part fixe (arithmétique supposée).

Hypothèse H0 : cœur à environ 400 MHz (non donné dans le dossier). Coût unitaire d’un envoi repris de la mesure vidéo (3,8 % / 147 paquets/s = 0,26 ms).

Rang	Candidat	Fréquence	Coût unitaire	Part d’un CPU
1	Traitement par échantillon (lvl_add, adsp_sample, alaw)	8000/s	400 cycles en ARM, ~1200 si les produits 64 bits passent par la bibliothèque (H2)	0,8 à 2,4 % utilisateur
2	RTP audio (aud_send tous les 160 échantillons)	50/s	0,26 ms	1,3 % système, si un client joue l’audio (H1)
3	snd_window : 2-3 logarithmes en flottant logiciel + écriture de fichier	4/s	~0,1 M cycles + ~0,15 ms	0,2 %
4	Tête de boucle : 6 lectures d’horloge, 2 parcours de MAXCLI, 2 verrous	par réveil	~40 µs	0,25 % à 60 réveils/s, quasi nul hors images
5	Bloc « une fois par seconde »	1/s	~6 appels système	0,02 %
6	Tick de 5 s	0,2/s	une ligne	< 0,01 %
7	lis_scan, live_scan, talk_tick	par réveil	non montré	inconnu

C2. Le traitement tourne sans consommateur (prouvé).

Dans aud_pump, if (dsp) s = adsp_sample(...) et le remplissage de pcm[] sont inconditionnels.
Quand seul le détecteur de son tient le micro ouvert (snd_on), le filtre, le gain et la copie ne servent à personne : le sonomètre est alimenté avant.
adsp_sample fait cinq produits 64 bits, plus une division 64 bits tous les 16 échantillons, sans division matérielle sur ARMv5.

C3. Les réveils « sans image » ne coûtent rien ici (prouvé).

aud_fd n’entre dans le select que si now_s() - t_frame > 0.25 (l. 3746). À 10 images/s l’écart est de 0,1 s : le micro ne réveille jamais la boucle.
Le micro est lu après chaque image, donc le nombre d’appels suit les images, mais le volume traité (8000 échantillons/s) est fixe.

C4. L’ajustement « fixe + par image » est fragile (supposé, H3).

Les deux points viennent de deux caméras, dont une à gain 26x.
À débit constant, tout ce qui dépend des octets (copie, paquets) est fixe dans le temps et non par image.
Le fil d’envoi suit pourtant les images (4,4 % puis 1,8 %), ce qui suggère un débit plus faible à 10 images/s ; la taille encodée à 10 images/s manque.

C5. Coût par paquet (prouvé pour les copies, supposé pour le reste).

Chemin par défaut : la charge est copiée deux fois, dans fu (send_nal) puis dans pk (rtp_out). Cela fait environ 2,8 ko par paquet, cohérent avec les 0,6 % utilisateur du fil.
Le chemin sg évite ces copies mais est désactivé par défaut.
Le temps système (0,26 ms) est dominé par la pile réseau et le pilote Wi-Fi USB, par paquet. Regrouper les appels n’économise que l’entrée/sortie du noyau, soit quelques pour cent.
Borne basse estimée : 0,15 à 0,2 ms par paquet de 1400 octets ; le vrai levier est le nombre de paquets.
H5 : si pacing_us > 0, chaque paquet ajoute un usleep, donc un réveil. Indice : 3 ms de temps mur par image contre 1,8 ms de CPU.
bcast_x garde cl_mu pendant send_frame : le fil principal peut attendre le verrou pendant un envoi (prouvé ; fréquence inconnue).

C6. Défauts de page par image (H4, supposé).

emit_frame alloue une copie par image (sjob_new) et snd_main la libère (free(j)).
H4 : l’allocateur de musl rend ces blocs au noyau. Chaque image touche alors 2 pages neuves de données plus l’en-tête, soit ~3 défauts, comptés au fil principal qui fait la copie.
Les tampons de pile (pk, fu, raw, pcm) sont réutilisés et ne fautent plus après le premier passage.
Les ~20 défauts/s fixes ne sont pas identifiables ; candidat : l’écriture de fichier de snd_window (4/s).
3. Proposition

Pour C2 :

diff
--- src/tc100rtsp/tc100_rtsp.c (aud_pump)
-	int r, dsp = adsp_on(&aud_dsp), spk = 0;
+	int r, dsp = adsp_on(&aud_dsp), spk = 0, lis = lis_count();
@@
-	if (dsp && aud_dsp.duck) spk = talk_state() == 1 || !access("/tmp/speaker-play.lock", F_OK);
+	if (dsp && aud_dsp.duck && (aud_tx || lis || rec_audio_wanted()))
+		spk = talk_state() == 1 || !access("/tmp/speaker-play.lock", F_OK);
@@
 			else if (snd_on) { lvl_add(&snd_w, s); if (snd_w.n >= 2000) snd_window(); }
+			if (!(aud_tx || rec_a || lis)) continue;	/* only the meter listens: no filter, no copy */
 			if (dsp) s = adsp_sample(&aud_dsp, s, spk);

L’état du filtre est repris tel quel quand un auditeur arrive : prévoir un test du niveau des 100 premières ms.

Pour C6, sjob_new n’étant pas montré, en pseudo-code :

réserve de 4 tampons au plus, sous le verrou de la file ; chaque tampon garde sa capacité
sjob_new(n) : prendre un tampon de capacité >= n, sinon malloc(n arrondi à 16 ko)
sjob_put(j) : le garder si capacité <= 64 ko et réserve non pleine, sinon free
snd_main : free(j) -> sjob_put(j)

Coût mémoire : 64 à 256 ko au plus.

4. Contrôles, dans l’ordre
Chemin audio en bloc (H1). Même caméra, 10 min avec un client sans piste audio et détection de son coupée (micro fermé après 10 s), puis avec. L’écart d’utime + stime du fil principal donne la part audio ; s’il est inférieur à 1 %, C1 tombe.
PROF. RTSP_PROFILE=1 pendant 10 min : prof_ms[6] donne les réveils par seconde, [8] ceux dus au micro (attendu : 0, sinon C3 est faux).
H2. Désassembler adsp_sample : des appels à __aeabi_lmul confirment le haut de la fourchette. Sinon, couper RTSP_AUDIO_HPF/AGC/DUCK un par un et lire utime.
H0. BogoMIPS de /proc/cpuinfo.
H4. minflt par fil sur 60 s avant et après la réserve : attendu ~98/s vers ~25/s au fil principal. Sans changement, H4 est infirmée ; chercher alors du côté du tampon de sortie de l’encodeur.
H5. Valeur de pacing_us au démarrage ; à 0, l’écart mur/CPU vient du verrou ou de la préemption.
C5. RTSP_UDPSG=1 pendant 10 min : utime du fil d’envoi doit baisser, stime rester à ~0,26 ms par paquet.
H3. Forcer 10 images/s de jour sur la .11 et refaire la lecture par fil.
5. Ce qui manquait
aud_send, aud_get, alaw, rec_audio_wanted, wfile, send_pkt, send_frame, qsend, qflush, sjob_new, sndq_put (tc100_rtsp.c).
lis_scan, lis_count (alisten.c), live_scan, live_stream, rec_inputs, les boucles ISP et d’exposition.
L’attente de l’encodeur (bloquante ou par sondage), MAXCLI, RTP_PAYLOAD, pacing_us.
Les options de compilation (ARM ou Thumb, -O), la version de musl, le transport du client (TCP ou UDP), la taille encodée à 10 images/s.
B. Scripts d’arrière-plan : moins de forks
1. Réponse courte
Les extraits expliquent environ 45 forks par minute sur 78 à 100 ; wifi-quality.sh en fait ~25 à lui seul.
Les lignes les plus chères : les deux $(echo | cut) de wq_gateway (6), le tube printf | sed | head (4), wq_station (5-6).
wifi-roam.sh forke 4-5 fois par minute pour ne rien faire quand le signal est bon ; un seul suffit.
health-snapshot.sh et mqtt-bridge.sh forkent une fois par service à cause de $(fonction).
Gain visé : −20 à −25 forks/min. Le coût d’un fork n’est pas mesuré ; la méthode est au point 4.
2. Constats

Règle de compte : $(...) = 1, chaque étage d’un tube = 1, timeout = 1 de plus (son minuteur, vu avec init pour parent), un script lancé = 1. Le tableau des rafales montre rm comme processus : les applets forkent bien (prouvé).

C1. wifi-quality.sh hk, toutes les 60 s : ~25 forks (prouvé à la lecture).

Ligne	Forks
lancement du job	1
$(date +%s)	1
$(wq_station) : substitution, 2 étages, $(command -v iw), timeout + minuteur	5-6
mv -f du fichier de moyenne	1
$(wq_loss)	1
$(wq_gateway) + deux $(echo | cut) à 3 chacun	7
$(timeout 8 ping …) + minuteur	2
$(printf | sed | head)	4
$(wc -l)	1
awk + mv de wq_summary	2

C2. wifi-roam.sh once, toutes les 60 s : 4-5 forks sur le chemin normal (prouvé).

Le job (1), mkdir -p (1), $(now) avec cut (1-2), rm -f quand le signal est bon (1).

C3. health-snapshot.sh once, toutes les 300 s : ~20-25 forks (prouvé pour les lignes montrées).

_status="$(probe_service_fast …)" dans la boucle des services : 11 forks au moins, même quand la sonde interne est sans fork.
S’y ajoutent $(printf …) pour le JSON, mv, wc -l, mkdir -p, et les scripts de contrôle exécutés (onvif, ssh-server vus en rafale).

C4. collect_slow_health_metrics de mqtt-bridge.sh : au moins 27 forks par cycle (prouvé ; période non montrée).

4 ports à deux substitutions imbriquées (8), 5 $(service_script_running_int) (5).
Deux services passent par le chemin lent "$script" status (motion-detection, telnet-server vus en rafale).
ifconfig | awk (3), awk sur resolv.conf (1), df | awk (3), netstat (1).

C5. Forks en boucle (réponse à la question 3).

Oui : la boucle des services de C3, et les appels répétés de C4.
Non : wq_gateway ne forke que sur la ligne de la route par défaut ; les boucles sur /proc/meminfo, /proc/mounts et le while read de wq_station sont sans fork.
reboot-tracker.sh (3 grep + awk vus) n’est pas montré.

C6. Il reste 35 à 50 forks/min hors extraits (supposé, H1).

Moyenne des jobs montrés : 25 + 5 + 5 + 6, soit ~41, plus net-guard et divers.
Le reste vient de scripts non montrés : boucle principale de mqtt-bridge.sh, net-guard.sh, cfg-persist.
L’écart de la .24 (+22/min) peut venir de net-guard « chaque minute après un échec ».

C7. Coût d’un fork (supposé, H2).

Borne haute tirée des données : 2,8 à 4,1 % de CPU pour 78 à 100 processus/min, soit 17 à 25 ms par processus, travail utile compris.
Estimation : 5 à 15 ms pour fork + exec d’un applet, 2 à 4 ms pour un $(...) seul.
3. Proposition
diff
--- scripts/wifi-quality.sh
@@ wq_gateway
-    printf '%d.%d.%d.%d\n' "0x${_gw#??????}" "0x$(echo "$_gw" | cut -c5-6)" "0x$(echo "$_gw" | cut -c3-4)" "0x${_gw%??????}"
+    _g3=${_gw#????}; _g3=${_g3%??}; _g2=${_gw#??}; _g2=${_g2%????}
+    printf '%d.%d.%d.%d\n' "0x${_gw#??????}" "0x$_g3" "0x$_g2" "0x${_gw%??????}"
@@ wq_loss
-  _p=$(printf '%s\n' "$_out" | sed -n 's/.* \([0-9][0-9]*\)% packet loss.*/\1/p' | head -n 1)
+  _p=; case "$_out" in *"% packet loss"*) _p=${_out%%"% packet loss"*}; _p=${_p##*[!0-9]} ;; esac
--- scripts/wifi-roam.sh
-mkdir -p "$WR_STATE" 2>/dev/null
+[ -d "$WR_STATE" ] || mkdir -p "$WR_STATE" 2>/dev/null
@@
-t=$(now)
+if [ -n "$WRO_NOW" ]; then t=$WRO_NOW; else read -r t _ < /proc/uptime; t=${t%%.*}; fi
@@
-case "$WIFI_DBM" in ''|*[!0-9-]*) rm -f "$WR_STATE/weak"; exit 0 ;; esac
-if [ "$WIFI_DBM" -ge "$BELOW" ]; then rm -f "$WR_STATE/weak"; exit 0; fi
+case "$WIFI_DBM" in ''|*[!0-9-]*) [ -e "$WR_STATE/weak" ] && rm -f "$WR_STATE/weak"; exit 0 ;; esac
+if [ "$WIFI_DBM" -ge "$BELOW" ]; then [ -e "$WR_STATE/weak" ] && rm -f "$WR_STATE/weak"; exit 0; fi
wq_gateway : sortie identique (octets 5-6 et 3-4 extraits par expansion).
wq_loss : identique sur la sortie de ping. Deux cas diffèrent de sed (chiffres non précédés d’un espace ; première occurrence sans chiffre) : test propre à écrire avec le crochet WQ_PING.
Gain : wifi-quality 25 vers 15, wifi-roam 4-5 vers 1, soit environ −14 forks/min.

Étapes suivantes, en pseudo-code (code appelé non montré, ou test dédié nécessaire) :

wq_station      : chercher iw dans $PATH par une boucle `for _d in $PATH` ; écrire la sortie d'iw dans un
                  fichier de /tmp et le lire par `while read … done < fichier` ; résultat en variables (−4)
health-snapshot : probe_service_fast pose une variable (PROBE_STATUS) au lieu d'écrire ; garder l'enveloppe
                  qui écrit pour les autres appelants (−11 par passage)
                  { printf '%s\n' "$_ts"; printf '{…}\n' …; } > "$_tmp" au lieu de _json="$(printf …)" (−1)
                  compter les lignes en attente par `while read` (12 lignes au plus) au lieu de wc (−1)
mqtt-bridge     : ports et état des services rendus en variables (−13) ;
                  serveurs DNS comptés par `while IFS= read -r l; case "$l" in nameserver[espace ou tab]*)` (−1) ;
                  `set -- $(df -k /mnt)` puis champs 9 à 12, à la place de df | awk (−2)

Laissés tels quels :

$(date +%s) : l’équivalent sans fork (btime + uptime) peut différer d’une seconde, donc le journal ne serait plus identique.
mv : nécessaire au renommage atomique.
wc -l du journal de 1440 lignes : le compter en shell coûterait plus qu’un fork.
La période d’une minute de wifi-quality : c’est son objet.
4. Contrôles, dans l’ordre
Coût d’un fork (H2). Sur la caméra, vidéo active : time sh -c 'i=0; while [ $i -lt 200 ]; do /bin/busybox true; i=$((i+1)); done', puis la même boucle avec x=$(:), puis avec : seul. Les écarts divisés par 200 donnent fork + exec et fork seul.
Compte par script. Lire processes dans /proc/stat avant et après sh wifi-quality.sh sample lancé à la main. Attendu ~25 avant, ~15 après ; un écart de plus de 3 infirme le compte de C1. Même mesure pour wifi-roam (5 vers 1) et health-snapshot.
Sorties identiques. Tests existants, plus cmp de /tmp/wifi-quality.log et /tmp/wifi-quality entre ancienne et nouvelle version sur les mêmes fichiers WQ_STATION, WQ_PING, WQ_NOW. Ajouter les deux cas limites de wq_loss.
H1. Retirer un job à la fois (housekeeper.sh job del) pendant 10 min et lire le rythme de processes : la baisse attribue les forks restants ; arrêter aussi le pont MQTT 10 min.
Gain global. Même capture de 2 h : processes par minute (attendu −14 avec le diff, −25 avec la suite) et part « non expliquée » du CPU (attendu −0,3 à −0,6 point si H2 vaut ~15 ms).
Housekeeper. Défauts mineurs de son processus sur 2 h : inchangés, le diff ne touchant pas sa boucle.
5. Ce qui manquait
hk_bgx, hk_wd, hk_alive (housekeeper.sh) ; scripts/health-probe.sh (probe_service_fast).
mqtt-bridge.sh : boucle principale, période du cycle santé, read_kv_config_value, sanitize_int_range, collect_port_states_from_netstat, l’usage de md5sum.
net-guard.sh, reboot-tracker.sh, cfg-persist, log-persist.sh, sdinfo-sd.sh, les scripts de contrôle appelés avec status ou health.
La configuration de busybox (applets sans fork) et le coût mesuré d’un fork.