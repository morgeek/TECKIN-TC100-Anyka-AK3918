Relecture DENOISE (NR1 / NR2), TC100
1. Réponse courte
La disposition des structures est correcte et prouvée ; la sûreté du GET/SET dépend du répartiteur ioctl, absent du document.
Le défaut principal est la base relue après un SET : le pilote garde les tables étirées, donc un redémarrage avec DENOISE ≠ 0 étire une seconde fois (supposé, à confirmer par le contrôle 4).
L’étirement est un levier plausible, mais au-dessus de 0 la courbe n’atteint plus sa queue : les contours forts sont lissés.
nr_stretch n’a ni débordement ni perte de monotonie ; l’échelle est asymétrique et −47 à −50 donnent le même résultat.
Rien ne montre que les registres NR1/NR2 sont écrits : les appels directs sont commentés.
2. Constats

C1. Base relue déjà étirée (H1, supposé, bloquant).

Preuve : ak_isp_vp_set_nr1_attr copie toute la structure dans isp->nr1_para (patch l. 2252). La base est relue par GET quand nr_base < 0 (tc100_rtsp.c l. 850), et la l. 1013 remet nr_base = -1; nr_asked = 0.
Supposé : GET renvoie isp->nr1_para (corps absent, l. 2266) et personne ne recharge le fichier de réglage avant la l. 850.
Conséquence : à chaque redémarrage du processus ou de la vidéo avec DENOISE ≠ 0, le facteur se compose (×2, ×4… à +50 ; extinction progressive en négatif).

C2. Bascule de style nuit ou reset ISP (H2, supposé).

Si un autre chemin réécrit les tables, nr_asked == p_dnr (l. 948) empêche de réappliquer : DENOISE est perdu sans message.
Un changement ultérieur de DENOISE repart de nr1_0 (jour) et écrase les tables de nuit, mode et en compris, puisque SET copie tout.
Le code de bascule (tune_hw) n’est pas montré.

C3. Le pilote ne modifie pas les jeux dans les lignes montrées (prouvé pour ces lignes seulement).

Il choisit un pointeur (isp->cur_env_nr1 = p_nr1, l. 7538-7539) et _isp_3dnr_work déclare des copies locales nr1, nr2 (l. 8165-8166).
La suite de _isp_3dnr_work est absente, donc l’absence d’écriture dans nr1_para reste supposée (H3).

C4. Disposition des structures (prouvé).

AK_ISP_NR1 : 1+51+1+17+16+3 = 89 mots de 16 bits ; l’attribut fait 1+10×89 = 891 mots, soit 1782 octets.
AK_ISP_NR2 : 24 mots ; l’attribut fait 241 mots, soit 482 octets.
Tout est en T_U16, donc sans remplissage en EABI ; l’ordre des champs (l. 757-760) suit les l. 16662-16696 du patch.
s[0] est le jeu manuel, s[1..9] sont linkage[0..8].

C5. Numéros et taille des ioctl (H4, supposé).

Les macros codent sizeof(int), pas 1782/482 (l. 761-764). C’est sûr seulement si le gestionnaire copie lui-même la taille de la structure.
NR1 a GET=11, SET=12 mais NR2 a GET=44, SET=43 : l’ordre inversé est à vérifier dans l’en-tête.
Si le pilote ne compare que le numéro et qu’ils sont inversés, le « GET » de nr_log (l. 886, tampon statique à zéro) écrirait des zéros dans NR2.

C6. Concurrence avec le travail de statistiques (supposé bénin, H5).

Le memcpy du SET se fait sans verrou visible (l. 2252), et le travail lit par pointeurs dans la même structure (l. 7538, 8176-8177).
Les pointeurs restent valides ; le pire cas est une courbe mi-ancienne mi-nouvelle pendant une image.
Entre SET_NR1 et SET_NR2, une image peut avoir NR1 nouveau et NR2 ancien.

C7. Application matérielle non démontrée (H6, supposé).

_set_nr1_attr et _set_nr2_attr sont commentés (l. 7535-7536) ; seul linkage_para_update_flag = 1 est posé (l. 2254).
L’écriture des registres se fait donc ailleurs, probablement dans la partie non montrée de _isp_3dnr_work, peut-être sous condition.
linkage_nr1[8] y sert de jeu « scène fixe » (l. 8176-8177) : étirer les 10 jeux est donc cohérent.

C8. Pertinence du levier (H7, supposé).

Si le poids est indexé par l’écart de pixel (filtre de type bilatéral), étirer l’axe revient à relever le seuil de bruit : c’est fidèle.
Le rôle de nr1_k / nr2_k (0 à 15) est inconnu. Si c’est une échelle de l’écart, l’étirement en est la version fine ; si c’est un dosage filtré/original, agir sur k serait plus fidèle et sans effet sur les contours.
lc_lut (modulation selon la luminance, supposé) et calc_*_k sont recopiés tels quels. C’est correct si calc_*_k ne sert qu’à l’outil de réglage.

Artefacts attendus :

Réglage	Effet sur la courbe	Effet visible probable
+50	d[16] = w[8] : la queue n’est jamais atteinte	Contours forts lissés, textures effacées, aspect cireux ; bavures de couleur en NR1 (domaine brut)
−50	d = {w[0], w[16], …} : filtre presque coupé	Grain et points colorés, bruit amplifié par la netteté inchangée, débit H.264 en hausse ou blocs à débit fixe

En −50, si w[16] ≠ 0, il reste un flou uniforme qui ne respecte plus les contours. Un effet sur la détection de mouvement du 3DNR (MD_stat, l. 8200) est possible mais non montré.

C9. nr_stretch et nr_apply (prouvé à la lecture).

Pas de débordement d’indice : j+1 ≤ 16 car j ≥ 16 est traité à part.
Pas de dépassement arithmétique : 1023×100 et 16×10000 tiennent dans un int.
f = 100 donne l’identité exacte ; d[0] = w[0] toujours.
La monotonie est conservée et les valeurs restent dans la plage d’origine (interpolation linéaire).
L’arrondi est par troncature : biais d’au plus 1 pas sur 10 bits, négligeable.
f = 0 est géré, mais tout f ≤ 6 donne le même résultat : −47 à −50 sont identiques.
L’échelle est asymétrique : −50 éteint, +50 double seulement. Une loi f = 100·2^(p/50) serait symétrique ; à décider avant la première diffusion, sinon il faudra une migration.
Dans nr_apply, errno est lu avant l’ioctl de restauration : correct.
Le libellé « iso16 » pour s[6] (l. 110 de l’extrait) dépend de l’énumération envi_flag, absente.
3. Proposition

Pour C1 dans le même processus : ne pas prendre pour base ce qu’on vient d’écrire. Le coût est de 2,2 Ko de BSS, évitable en réutilisant les tampons de nr_log.

diff
@@ static int nr_base = -1, nr_now, nr_asked;
+static int nr_wrote;	/* nr1_1/nr2_1 = last tables accepted by the ISP */
@@ nr_apply
-	if (nr_base < 0) nr_base = ioctl(fd, ISP_GET_NR1, &nr1_0) == 0 && ioctl(fd, ISP_GET_NR2, &nr2_0) == 0;
+	if (nr_base < 0) {
+		static struct isp_nr1 g1;
+		static struct isp_nr2 g2;
+
+		nr_base = ioctl(fd, ISP_GET_NR1, &g1) == 0 && ioctl(fd, ISP_GET_NR2, &g2) == 0;
+		/* our own output read back: keep the base we already have */
+		if (nr_base == 1 && !(nr_wrote && !memcmp(&g1, &nr1_1, sizeof g1) && !memcmp(&g2, &nr2_1, sizeof g2))) {
+			nr1_0 = g1; nr2_0 = g2;
+		}
+	}
@@
 		nr_now = p_dnr;
+		nr_wrote = 1;
 	} else {
@@
 		nr_base = 0; nr_now = 0;
+		nr_wrote = 0;

Le memcmp est fiable parce que les structures n’ont pas de remplissage (C4). Il suppose que GET rend exactement ce que SET a écrit (contrôle 3).

Pour le redémarrage du processus, même principe avec un fichier en tmpfs :

après un SET réussi : écrire {nr1_0, nr2_0, nr1_1, nr2_1} dans /tmp/tc100_nr (4,5 Ko), écriture + rename
à la première lecture : si le fichier existe et GET == {nr1_1, nr2_1} du fichier → base = {nr1_0, nr2_0} du fichier
                        sinon → base = GET (réglage neuf), supprimer le fichier

Pour C2 : après chaque chargement de réglage (jour/nuit), poser nr_base = -1; nr_asked = 0;. L’endroit exact est dans du code non montré.

4. Contrôles, dans l’ordre
Test hôte de nr_stretch (avec ASan), pour f de 0 à 200 sur des courbes décroissantes : identité à f=100, d[0] == w[0], monotonie, bornes. Un échec infirme C9.
nr_log au démarrage, DENOISE=0. en à 0/1, k ≤ 15, niveaux cohérents : C4 et H4 confirmés. NR2 tout à zéro ou k aberrant : numéros 43/44 inversés ou taille mal copiée.
Aller-retour SET puis GET avec memcmp. Égal : GET rend nr_para, le diff est valide. Différent : le pilote retouche les tables (H3 infirmée), il faut alors comparer uniquement les courbes.
DENOISE=25, puis tuer et relancer tc100_rtsp. Lire la ligne w[4] a -> b : si le nouveau a vaut l’ancien b, H1 est confirmée ; s’il vaut l’ancien a, le réglage est rechargé au démarrage et H1 tombe.
Bascule jour/nuit avec DENOISE ≠ 0, puis nr_log avec w[4] ajouté. Valeur non étirée : H2 confirmée.
Effet réel : scène fixe peu éclairée, débit H.264 à −50, 0 et +50. Débit qui monte à −50 et baisse à +50 : registres écrits (H6 levée). Aucun écart : chemin d’écriture conditionnel ou jeu actif différent.
Levier du constructeur : journaliser temporairement w[4], w[8], w[16] et k des 9 niveaux. Courbes qui s’élargissent avec le gain à k constant : l’étirement est fidèle. Courbes identiques et k variable : k est le levier (H7). w[16] ≠ 0 : revoir le cas −50.
Endurance : alterner DENOISE ±50 chaque seconde pendant 10 minutes en diffusion. Ni message noyau ni image corrompue : H5 confirmée.
5. Ce qui manquait
Le répartiteur ioctl du pilote ISP et l’en-tête des numéros AK_ISP_GET/SET_NR1/NR2 (patch 0006) : taille copiée, comparaison de la commande.
Le corps de ak_isp_vp_get_nr1_attr et les fonctions NR2 équivalentes.
_set_nr1_attr, _set_nr2_attr et la suite de _isp_3dnr_work : usage matériel des poids, de k, de lc_lut, et mélange des jeux.
L’énumération envi_flag et le début de la fonction de sélection (l. < 7488), avec la condition liée à linkage_para_update_flag.
Dans tc100_rtsp.c : le contexte des l. 940-948 et 1013, le chargement du fichier de réglage et la bascule jour/nuit (tune_hw).