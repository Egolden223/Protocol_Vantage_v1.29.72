# CHANGELOG — Protocol Vantage

> **Règles du dépôt (à respecter à chaque version)**
> 1. **Un seul changelog : ce fichier.** Nouvelle version = nouvelle section en haut ; ne jamais créer `CHANGELOG_Vx.md`.
> 2. **Budget : 100 fichiers maximum** dans le dépôt (limite d'import GitHub). Contrôlé par `tests/test_regressions.py::test_repo_file_budget`.
> 3. Pas de rapports/notes séparés : les analyses vont dans la section de version correspondante.
> 4. Caches et données générées (`data/`, `__pycache__`) restent hors dépôt (`.gitignore`).

---

# v1.29.72 — FUSION des branches « leviers » (v1.29.69.1) et « Grok » (v1.29.71) — 18 novembre 2026
**Principe : rien n’est supprimé ni désactivé ; seules des erreurs de code sont corrigées**, plus un ajustement décidé par le propriétaire (tocard sur T3 et T4 seulement). Les deux branches partent de la v1.29.68 ; leurs historiques sont conservés ci-dessous.
- **Conservé de la branche Grok (tout reste actif)** : T2 en rangs relatifs au champ, plafond RAH-242 incluant GRU et tactique, pool GMO-V avec trace par numéro et correction du favori de marché réservé coupé par la limite de 14 chevaux, provenance des valeurs PMU, confiance transmise aux bonus B et malus M, atténuations SRI proxy et MPA, plafond d’outsiders A:2, B:2, minimum T1/T2/T3/T4 (T4a ∪ T4b) sur A, B **et C** sans bornes [3,5].
- **Conservé de la branche « leviers »** : bases par score propre figé hors trot (A, B, C), probabilités recalibrées, filtre de courses (cote du favori), garde T1 en repli, valeur PMU du trot ramenée à zéro en REJEU / chrono du jour présent (courses à venir traitées normalement), colonnes de mesure `captures_shadow_*`, `shadow_*` et `filtre_course`, test de bout en bout du pipeline complet.
- **Ajustement décidé** : le multiplicateur tocard (×0,75 par défaut) ne s’applique plus qu’aux tranches **T3 et T4** (`VANTAGE_TOCARD_MULT_T34`, alias `VANTAGE_TOCARD_MULT_T123` toujours lu ; plancher ×0,25, jamais nul). T1 et T2 sont inchangés : le score y est neutre (T1) ou inversé (T2, AUC intra-tranche 0,33).
- **Erreurs de code corrigées** : (1) `gmo_v.py` — le bloc `tocard_norm *= _tocard_mult(tr)` était recopié trois fois de suite (×0,75³ ≈ ×0,42 au lieu de ×0,75) ; test de non-régression ajouté ; (2) `tranches.py` — trois `import os` identiques ; (3) `ticket_quotas._liste_env` — une variable d’environnement vide retombe sur le défaut actif (comportement de la branche Grok) tout en conservant `none` / `off` pour désactiver explicitement ; (4) valeur invalide du multiplicateur tocard : retour au défaut actif ; (5) tests réalignés (version, groupes T4, minimum sur C, portée du tocard).
- **Résolution des chevauchements** : sélection finale = règle Grok (groupes T1/T2/T3/T4, sans bornes, A/B/C) — équivalente à celle de la branche « leviers » sur l’historique (A +0,31, B +0,21–0,22, C +0,01) ; version, flags (`fusion_v72_*`) et README alignés ; dépôt à 100 fichiers.
- **À surveiller en shadow** : le tocard empilé sur la sélection un-par-tranche a coûté −0,07 (A) et −0,09 (B) hors trot sur un modèle approché de l’ordre final ; la restriction à T3/T4 réduit mais ne supprime pas ce risque. Les atténuations SRI proxy et bonus B de la branche Grok n’ont pas de mesure chiffrée à ce jour.

---

# v1.29.71 — T2 RELATIF, RAH-242 COMPLET ET TRACES DE DIAGNOSTIC (18 novembre 2026) — branche « Grok »

**Base conservée** : tous les réglages actifs v1.29.70 restent en place, notamment min1 par tranche sur A/B/C, T4 fusionnée (T4a/T4b), sans bornes de répartition [3,5]/[5,3].
- **T2** : le score « force relative » utilise maintenant le rang PCH inversé du champ et l’edge compare le rang PCH au rang de cote. Calcul après la passe PCH complète; la formule T2 n’utilise aucun résultat futur. Comportement modifié, à mesurer en walk-forward.
- **RAH-242** : cap des contributions secondaires positives complété par `gru_pepite_piege_pch` et `tact_pch`; les totaux primaire positif, secondaire brut/autorisé et correction sont conservés dans `ModuleBreakdown`.
- **GMO-V** : ajout de `gmo_v_pool_trace` par numéro (motifs d’admission, rejet par capacité et admission finale); correction de l’application de la réservation favori marché lorsque le pool de 14 est déjà plein. Les choix greedy et mutations ultérieures restent dans le journal existant.
- **Provenance PMU** : traçage par cheval des champs valeur PMU et cotes, incluant source API/champ brut quand disponible, collecte locale UTC, valeur d’origine et valeur effectivement consommée après neutralisation trot. L’heure d’observation fournisseur reste `null` si elle n’est pas fournie; ne pas l’interpréter comme une date de course.
- **Tests ciblés** : T2 relatif, cap RAH-242 (GRU positif/négatif et tactique), survie GRU, provenance API, neutralisation valeur et réservation marché.
- Ces corrections statiques et ajouts de diagnostic ne constituent pas encore une validation de gain de capture sur les 162 courses. Aucun échec historique n’est attribué aux quotas/minima par tranche; il faudra comparer les prochaines courses à l’ancienne version et au marché.

---

# v1.29.70 — MINIMUM D’UN CHEVAL PAR TRANCHE ACTIVÉ SUR A/B/C (17 novembre 2026) — branche « Grok »

**Activation demandée** : `VANTAGE_SELECT_MIN1_TICKETS` vaut par défaut `A,B,C`; une variable absente ou vide conserve cette activation. Une valeur non vide, par exemple `B`, restreint les tickets concernés.
- **Tickets A, B et C** : au moins un cheval en T1, T2, T3 et T4 lorsque les tranches sont présentes. **T4 = T4a ∪ T4b** : une seule présence dans l’une des sous-tranches suffit; aucune présence simultanée T4a+T4b n’est imposée.
- Les bornes précédentes [3,5]/[5,3] entre T1+T2 et T3+T4 sont supprimées pour les tickets finaux. Après avoir réservé le meilleur score de chaque tranche requise, les places restantes sont attribuées par le mélange `z(ordre_final) + λ·z(−log cote)`; aucune réparation de bornes n’est faite.
- Le plafond outsiders A:2/B:2 de v1.29.69 est appliqué ensuite, sans casser les quatre minima.
- La modification est une règle de construction active pour les prochains tickets; elle **ne constitue pas une explication rétroactive des échecs observés** dans les audits antérieurs.
- Les seuils et valeurs d’incertitude de la v1.29.69 restent actifs. Version `v1.29.70-MIN1-T4-FUSION-SANS-BORNES-17112026`.

---

# v1.29.69 — RECALIBRAGE ACTIF SRI PROXY / B-M-CONFIANCE / MPA / TOCARD / OUTSIDERS (16 novembre 2026) — branche « Grok »

**Comportement actif pour les prochaines courses** (toutes les options restent surchargeables par variables d’environnement). Aucun changement de quota par tranche et aucune sélection « min1 tranche » activée.
- Version unifiée `v1.29.69`, build `v1.29.69-RECALIBRAGE-ACTIF-16112026`; le `VERSION.txt` obsolète est supprimé, la version de référence est `app/version.py`.
- **SRI** : SRI observé inchangé; proxys actifs gains ×0,65, cote ×0,40, plancher ×0,50 (`VANTAGE_SRI_PROXY_*_MULT`).
- **Catalogue B** : poids global ×0,90 et cumul répété dans une famille ×0,75 après la première occurrence (`VANTAGE_BONUS_B_MULT`, `VANTAGE_BONUS_B_REPEAT_MULT`).
- **Catalogue M** : confiance DEGRADE ×0,75, MINIMAL ×0,50; STRICT/inconnue inchangés. Le champ confiance est maintenant transmis à l’agrégateur.
- **MPA** : confiance de style inconnue — malus ×0,50; malus sans pénétromètre ×0,20. Les signaux positifs restent inchangés.
- **Tocard** : `VANTAGE_TOCARD_MULT_T123` par défaut ×0,75 (T1–T3; T4 inchangé; plancher ×0,25).
- **Outsiders** : au plus 2 chevaux de rang marché ≥9 dans A et B; C inchangé. `VANTAGE_CAP_OUTSIDERS` surcharge le réglage.
- **Intégrité trot** : neutralisation v1.29.68 conservée.
- **Diagnostic** : les signaux GRU pépite/piège ajoutés sont conservés dans `signaux_actifs` au lieu d’être écrasés.
- **Non activé** : sélection « un cheval par tranche + mélange » et toute modification des quotas par tranches.
- Les effets combinés de ces réglages ne sont pas validés historiquement; les scores doivent être comparés sur les prochaines courses à la version précédente et à la référence marché.

---
# v1.29.69.1 — LEVIERS ACTIVÉS PAR DÉFAUT sur les tickets A et B (et les bases/probabilités/filtre pour A, B, C) (15 novembre 2026) — branche « leviers »
Les corrections issues de l’analyse des échecs sont **actives par défaut** ; chacune se désactive par une variable d’environnement (`none`, `off` ou `0`). Là où la mesure montre qu’un levier est redondant ou nuisible une fois empilé sur les autres, il n’est volontairement pas activé (voir « Non activés »).
- **Sélection « au moins un cheval par tranche + z(ordre_final) + z(cote) »** : ACTIVE pour **A et B** (`VANTAGE_SELECT_MIN1_TICKETS`, défaut `A,B`). T4a est désormais exigé aussi pour B (mesure neutre : identique à T1–T3). Bornes [3,5] de B conservées. Mesure sur 160 courses sans paramètre ajusté : A +0,31 [+0,16 ; +0,46], B +0,22 [+0,08 ; +0,36] ; walk-forward 96 courses : A +0,33, B +0,42.
- **Plafond d’outsiders** ACTIF (`VANTAGE_CAP_OUTSIDERS`, défaut `A:2,B:2`) : au plus 2 chevaux de rang marché ≥ 9 ; filet de sécurité, neutre après la sélection (0,00).
- **Garde T1** (rang marché ≤ 3 jamais écarté) ACTIVE pour A **en repli** (`VANTAGE_GARDE_T1`, défaut `A`) : n’intervient que si la sélection est désactivée ; empilée sur la sélection elle coûte −0,02.
- **Bases par score propre figé, hors trot** ACTIVES pour **A, B et C** (`VANTAGE_BASES_SCORE_PROPRE`, défaut `1`) : les 3 bases du ticket sont choisies par le score propre (T1/T2 de préférence, B1 = plus petite cote) au lieu du maximum de P(désordre) Plackett-Luce ; part des bases dans le top 5 0,65–0,69 contre 0,53–0,59 (walk-forward). En trot le Plackett-Luce est conservé (comparaison propre impossible tant que la fuite n’est pas corrigée as-of). `structure_bases_complements.bases_source` indique l’origine.
- **Probabilités recalibrées** ACTIVES : `probabilites_recalibrees` publié dans chaque structure (A : désordre ×1,63, 5/5 ×1,57 ; B : ×1,12, ×0,81 ; C : ×0,86, ×0,83 ; appliqués à moitié) à côté des `probabilites_modele` brutes, qui restent inchangées.
- **Filtre de courses** ACTIF : `json_output["filtre_course"]` ; avertissement `FILTRE_COURSE_REDUIT` quand le favori est coté au-delà de 4 (`VANTAGE_FILTRE_FAVORI_MAX`) — 5/5 observé 8 % contre 21–22 % ; jamais bloquant.
- **Valeur PMU du trot** : mise à zéro en REJEU / chrono du jour présent, traitement normal des courses à venir (inchangé depuis v1.29.68).
- **Non activés par défaut, avec la mesure** : (1) *sélection pour le ticket C* : −0,07 [ns] contre sa sélection actuelle (qui bat déjà le marché de +0,13 à +0,18) → `VANTAGE_SELECT_MIN1_TICKETS=A,B,C` pour l’essayer ; (2) *baisse du poids tocard* : empilée sur la sélection elle coûte −0,09 [−0,16 ; −0,02] à B et −0,07 à A hors trot (effet de composition déjà capté) → `VANTAGE_TOCARD_MULT_T123` reste à 1,0, utile si la sélection est désactivée ; (3) *structure à 2 bases* : change la règle du ticket, à valider sur ≥ 100 courses PRE_COURSE ; (4) *mélange + score propre pour choisir les 8* : aucun gain (walk-forward).
- Reste hors de portée d’un réglage : l’aléa de course (6e–8e, incidents, scénarios), la forme du jour et la supériorité du lot (données absentes de l’export), les sources à 0 % de couverture, la remesure du trot sans fuite.
- Tests : les tests v68/v69 sont réécrits pour les nouveaux défauts ; ajouts : bases forcées, probabilités recalibrées et un test de bout en bout du pipeline complet (plat et trot, collecte et enrichissements neutralisés) ; 209 tests verts ; version, flags (`leviers_actives_v69_1`) et README alignés ; dépôt à 100 fichiers.

---

# v1.29.69 — SHADOW : bases par score propre figé, probabilités recalibrées, filtre de courses, garde T1 (15 novembre 2026) — branche « leviers »
**Aucun ticket réel modifié par défaut.** Tout est calculé et publié dans `json_output["shadow_v1_29_69"]` ; la seule application possible est la garde T1 du ticket A (`VANTAGE_GARDE_T1=A`, défaut inactif).
- **Bases par « score propre » figé** (`ticket_quotas.score_propre`, `bases_propres`) : régression logistique régularisée sur variables sans fuite (cote, forme linéaire, stabilité, tactique, IFF v2, musique 5 et 10 courses, gains moyens, taux de victoires, âge ; coefficients séparés trot / hors trot, ajustés sur les 160 courses du 11/11/2026, parité vérifiée avec l’analyse : Spearman 1,000 ; le coefficient « taux de D/A/T des 5 dernières » hors trot, positif (+0,41) sur 89 chevaux d’obstacle, est neutralisé : artefact sans effet sur les mesures). Bases publiées pour k = 2 et k = 3 : meilleurs scores en T1/T2 (les bases de T3 ne sortent que 34 % du temps), B1 = plus petite cote des bases. Mesure hors trot, walk-forward, 60 tickets-courses : part des bases dans le top 5 **0,65–0,69** contre 0,53–0,59 pour les bases actuelles (Plackett-Luce marché/PCH) et 0,56 pour la cote ; désordre à 3 bases 8,3 % contre 2,6 %. En trot les bases actuelles profitent de la fuite de la valeur PMU : comparaison non fiable avant correction as-of.
- **Probabilités recalibrées** (`probas_recalibrees`) : facteurs observé/prédit mesurés sur 106 audits — A : désordre ×1,63, 5/5 ×1,57 (sous-estimés) ; B : ×1,12 et ×0,81 ; C : ×0,86 et ×0,83 — appliqués à moitié (retrait vers 1) et publiés à côté des probabilités brutes.
- **Filtre de courses** (`signal_course`, `VANTAGE_FILTRE_FAVORI_MAX`, défaut 4,0) : « plein » si le favori est coté ≤ 4, sinon « réduit » ; 5/5 observé 21–22 % contre 8 % (76 contre 84 courses). Publié seulement, aucune décision automatique.
- **Garde T1** (`garder_t1`) : aucun cheval de rang marché ≤ 3 n’est écarté de A (échange contre le sélectionné de rang > 3 au plus faible score, « un par tranche » respecté) ; +0,10 [+0,01 ; +0,20] capture/course pour A, nul pour B. Shadow pour A, application par `VANTAGE_GARDE_T1=A`.
- **Mesure appariée** : l’audit calcule `baselines_contrefactuelles.shadow_v69` ; `courses.csv` et le CSV de lot gagnent `shadow_b3_top5_*`, `shadow_desordre_k2_*`, `shadow_desordre_k3_*`, `captures_shadow_garde_A`, `favori_cote` et `filtre_course`.
- Tests : 5 ajouts (`test_v69_*`). Version, flags (`recalibrage_v69_*`) et README alignés ; dépôt toujours à 100 fichiers.
- Réserve : les coefficients sont ajustés sur les mêmes 160 courses que l’analyse ; seuls le walk-forward et les prochains lots diront si le gain tient. Activer une structure à 2 bases n’est possible qu’une fois ces mesures confirmées (≥ 100 courses PRE_COURSE).

---

# v1.29.68 — RECALIBRAGE : un cheval par tranche + mélange ordre/cote (shadow), plafond d’outsiders, baisse du poids tocard, valeur PMU du trot (13 novembre 2026)
**Principe : recalibrage uniquement** (poids, plafonds, seuils, fenêtre as-of) — aucun module, signal, source ni parseur n’est supprimé ni débranché ; le tocard garde un plancher ×0,25. Tickets A, B et C **inchangés par défaut** : seule la valeur PMU du trot est ramenée à zéro, uniquement en REJEU / course déjà courue.
- **Sélection « au moins un cheval par tranche + z(ordre_final) + z(cote) »** (`ticket_quotas.appliquer_v68`) : au moins un cheval en T1, T2, T3 (et T4a pour A) puis les meilleurs scores restants ; B et C gardent leurs bornes [3,5] sur T1+T2 et T3+T4 ; aucun paramètre ajusté (λ = 1, `VANTAGE_MIN1_LAMBDA`). Calculée **en shadow** pour A, B et C et publiée dans `json_output["shadow_v1_29_68"]` ; appliquée pour de bon seulement aux tickets nommés dans `VANTAGE_SELECT_MIN1_TICKETS` (ex. `B` puis `A,B` ; **ne pas activer pour C**). Mesure walk-forward sur 96 courses : B +0,42 [+0,24 ; +0,60] (bornes comprises), A +0,33 [+0,15 ; +0,51] ; sur les 160 courses (sans entraînement) A +0,31 [+0,16 ; +0,46], B +0,22 [+0,08 ; +0,36] ; C −0,04 (non significatif).
- **Plafond d’outsiders** (`VANTAGE_CAP_OUTSIDERS="A:2,B:2"`, défaut inactif) : au plus N chevaux de rang marché ≥ 9, remplaçants de rang < 9, règle « un par tranche » et bornes respectées. Appliqué après la sélection ci-dessus il est redondant (−0,01 / 0,00) : utile seulement si la sélection n’est pas activée (A : +0,21 [+0,09 ; +0,33]).
- **Poids du score tocard** (`synthesis.compute_composite`, `VANTAGE_TOCARD_MULT_T123`, défaut 1,0 = inactif) : multiplicateur ×0,25 à 1,0 du poids tocard pour T1–T3 uniquement (T4a/T4b inchangés) ; paliers recommandés ×0,75 puis ×0,5 (hors trot ≈ +0,26 capture/course estimé sur un modèle linéaire de l’ordre final — à confirmer en shadow).
- **Valeur PMU du trot** (`common.attenuer_valeur_pmu_trot`) : la valeur PMU du trot suit l’ordre d’arrivée de la course du jour (ρ = −0,91 sur 56 courses ; prime de fuite ≈ +0,23 capture/course). **Dans une course déjà courue — mode REJEU, ou chrono du jour / réductions kilométriques présents — elle est ramenée à zéro (traitée comme absente)** : SRI et NRC reviennent à leur repli par les gains, M09 et M22 ne se déclenchent pas. **Les courses à venir sont traitées normalement** (aucune modification). Trot uniquement. `VANTAGE_TROT_VALEUR_MULT` : 0 (défaut) = zéro ; 0<m<1 = atténuation vers la moyenne ; 1 = désactivé. Le garde-fou « chrono du jour présent » couvre les analyses lancées après l’arrivée le jour même, que le mode (basé sur la date) classe PRE_COURSE : c’est ce qui a contaminé les 3 courses PRE_COURSE de trot de l’export du 11/11.
- **Mesure appariée** : l’audit calcule `baselines_contrefactuelles.shadow_captures` (et `shadow_captures_plafond2`) ; les exports `courses.csv` et le CSV de lot gagnent `captures_shadow_A/B/C`.
- Tests : 7 ajouts (`test_v68_*`). Version, flags (`recalibrage_v68_*`) et README alignés ; dépôt toujours à 100 fichiers.
- Déploiement recommandé : 1) livrer tel quel (seule la valeur PMU trot en REJEU change) ; 2) sur le lot suivant comparer `captures_shadow_*` aux `captures_*` ; 3) si l’écart tient (≥ +0,15, IC excluant 0), activer `VANTAGE_SELECT_MIN1_TICKETS=B` puis `A,B` ; 4) tocard ×0,75 puis ×0,5.

---

# v1.29.67.1 — NETTOYAGE DU DÉPÔT : un seul changelog, 100 fichiers, version cohérente (10 novembre 2026)
**Aucun changement de logique** : tickets A, B et C identiques à la v1.29.67 (193 tests verts).
- **Version** : `app/version.py` passe à v1.29.67.1 ; les flags `turfbzh_html_p012` (v1.29.66.5) et `anti_doublon_prior_race` (v1.29.65.1) sont enfin déclarés (le code existait mais `VERSION.txt` annonçait 66.5 alors que `version.py` restait en 66).
- **v1.29.66.5 — Turf.bzh HTML gratuit P0/P1/P2** (section reprise de l'ancien `CHANGELOG_ENTRY.md`) : B65 avis entraîneur POSITIF (+4) / B66 NEGATIF (−8) ; B67 IMDC descente (+3) / montée (−1,5) ; B68 value / B69 surcote (cote BZH vs marché) ; B70 IA multi-places Top2–5 ; B71 synergie jockey-cheval ; B72 ex-favori ; B73 taux d'incident élevé ; B74 D4 / changement de ferrure ; flags (changement de driver, ELO, Turf Points 90 j, alloc_ratio, rank_prec, charge jockey) ; P2 : stats carrière, corde → `numero_autostart` si vide, record distance. Tous ces signaux sont de **famille C** (décote de famille 1 / 0,6 / 0,35 / 0,2 déjà appliquée par `tranches.appliquer_decote_famille`). B61–B64 conservés ; l'API payante reste un no-op (v1.29.66.4).
- **Budget de fichiers** (110 → 100, `test_repo_file_budget` redevient vert) : supprimés `CHANGELOG_ENTRY.md`, `CHANGELOG_v1_29_64.md`, `README_PATCH.md`, `VERSION.txt`, `VERSION_LINES.txt`, `docs/V1_29_64_VERSION_BUMP.txt` (restes de patchs) ; `app/engine/_v164_gru_boost.py` (code mort : aucune importation, les fonctions vivent dans `gru_signals.py`) ; `app/archive_names.py` (doublon exact de `hf_export.race_archive_basename` / `archive_basename_for_race`, imports redirigés) ; `app/scraping/turfbzh_api.py` (no-op, remplacé par la constante équivalente dans `equidia.py`) ; `app/scraping/validation.py` (fusionné dans `app/scraping/base.py`, imports redirigés).
- ⚠️ Le dépôt est **exactement à 100 fichiers** : toute nouvelle version devra supprimer ou fusionner un fichier. Rappel : `data/` et les caches restent hors dépôt (`.gitignore`).
- `README.md` mis à jour (n'indiquait plus la bonne version).

---

# v1.29.67 — TICKET B PAR FAMILLE (TROT / GALOP / OBSTACLE) + MÉCANISME DE RÉGLAGES PAR PORTÉE DANS LE CATALOGUE GRU (7 novembre 2026)
**Principe** (échange du 7/11) : un ajustement calé sur un constat local (ex. Deauville) ou global ne doit pas dégrader d'autres portées (ex. Vincennes). Constat du rejeu 55 courses : un même B (α = 0,75 + composantes + classement T3/T4 + entrée pépite) **gagne** au galop (+0,36) et à l'obstacle (+0,40) mais **perd** au trot (−0,30), où le PCH sépare mieux que le marché (AUC 0,84 contre 0,77). **A et C restent identiques à la v1.29.63** (contrôle d'équivalence).
- **Résolution par portée** (`gru_catalog.reglages_b_pour(race)`), du plus général au plus spécifique, chaque niveau ne redéfinissant que ses paramètres : `global → famille → famille × tranche de distance → hippodrome (toutes familles) → hippodrome × famille [× distance]`. Les réglages d'un hippodrome vivent dans **sa fiche du catalogue** : `entry["reglages_b"] = {"*": {...}, "TROT": {...}, "TROT|2000-2700": {...}}`. Une variable `VANTAGE_B_*` explicite l'emporte sur toutes les portées. Clés inconnues et valeurs invalides ignorées. Familles : `TROT` (attelé, monté), `GALOP` (plat), `OBSTACLE` (haies, steeple-chase, cross). Tranches de distance : `<=1400`, `1400-2000`, `2000-2700`, `>2700`.
- **Réglages par défaut** : GALOP = B complet (α 0,75, α_T3 0,8, composantes, classement T3/T4, 1 entrée pépite) ; **TROT = complément porté sur le PCH** : α = 0,30, sans α_T3 « marché », sans classement T3/T4, sans entrée pépite, composantes en rangs conservées ; **OBSTACLE** hérite de GALOP (10 courses : effectif insuffisant, `_herite`).
- **Rejeu 55 courses, chemin de production** : B par famille **4,09** (+0,18 contre C ; 13 courses meilleures / 6 pires) contre 4,00 pour le B uniforme. Trot : 4,35 contre 4,13 (uniforme) et 4,43 (C) — identique à C dans 39 % (contre 9 %), couverture C∪B 4,52 ; galop 3,95 et obstacle 3,80 inchangés. ⚠️ Le réglage du trot est issu d'une petite grille sur 23 courses (optimiste) ; trot, galop et obstacle n'atteignent pas l'effectif de 30 courses visé : à confirmer sur le lot.
- **Postcourse par portée** : `aggregate_audit_patterns()["par_portee"]` = captures A / B / C, écart B − C et IC 95 % par famille, famille × distance et hippodrome ; `effectif_suffisant` = au moins 30 courses (sinon la portée reste indicative).
- Export : `B_famille`, `B_portees` (niveaux appliqués) ; sortie : `quotas_info["reglages_b"]`.
- Tests : 194. Dépôt : 100 fichiers.

---

# v1.29.66 — ALTERNATIVES À SCRAPERAPI : chaîne de fournisseurs anti-bot (Firecrawl, …) avec bascule automatique (29 octobre 2026)
**Besoin** : le palier gratuit de ScraperAPI (≈ 5 000 requêtes / mois, ≈ 17-20 par course Geny) peut être épuisé en cours de mois ; Golden a ajouté les clés Firecrawl et d'un second service dans l'environnement Render.
- `app/scraping/base.py` : `fetch_html(..., via_scraperapi=True)` (appelants Geny **inchangés**) essaie désormais une **chaîne de fournisseurs** dans l'ordre `FETCH_PROVIDERS_ORDER` (défaut : `scraperapi, firecrawl, scrapingbee, scrapingant, scrapedo, zenrows, custom`), chacun n'étant tenté que si sa clé existe : ScraperAPI (`SCRAPERAPI_KEY`), **Firecrawl** (`FIRECRAWL_API_KEY` ou `FIRECRAWL_KEY`, POST `/v1/scrape`, format `rawHtml`, `FIRECRAWL_PROXY=basic|stealth`), ScrapingBee, ScrapingAnt, Scrape.do, ZenRows, et un fournisseur **générique** `custom` (`FETCH_CUSTOM_KEY` + `FETCH_CUSTOM_URL_TEMPLATE` avec `{key}` et `{url}`) pour tout autre service accessible par GET.
- **Bascule sur quota épuisé** : HTTP 401 / 402 / 403 → fournisseur mis de côté **6 h** ; 429 → **90 s** ; autre échec (5xx, timeout) ou **page de blocage / trop courte** renvoyée → fournisseur suivant sans mise de côté. Si tous échouent : **fetch direct habituel** (aucune régression). Sans aucune clé : comportement strictement identique à la v1.29.6.
- Diagnostic : `provider_stats()` (compteurs ok / échec / quota / bloqué, fournisseurs actifs, pauses en cours) repris dans `json_output["diagnostic_donnees"]["fetch_providers"]` ; lignes de log `FETCH fournisseur=… url=…`.
- `render.yaml` : secrets `FIRECRAWL_API_KEY`, `FETCH_CUSTOM_KEY`, `FETCH_CUSTOM_URL_TEMPLATE` (`sync: false`).
- ⚠️ Seuls ScraperAPI (déjà en production) et Firecrawl (selon sa documentation API) sont des intégrations vérifiées par le contenu des requêtes ; ScrapingBee, ScrapingAnt, Scrape.do et ZenRows sont codés d'après leurs documentations publiques et testés par simulation seulement. Firecrawl : 1 crédit par page en proxy `basic`, 5 en `stealth` ; son quota gratuit est à vérifier sur son tableau de bord.
- Tests : 189. Dépôt : 100 fichiers.

---

# v1.29.65 — TICKET B = LABORATOIRE COMPLET : tout ce qui restait est actif, A et C inchangés (29 octobre 2026)
**Garantie** : les tickets **A et C sont identiques à la v1.29.63**. Contrôle automatique (script d'équivalence) : sur 3 courses simulées de bout en bout, tickets A et C, `ordre_final`, PCH, pool élargi et signature sont **identiques** entre la v1.29.63 et cette version ; test de non-régression `test_ticket_b_lab_never_changes_tickets_A_and_C` (mêmes A et C avec le laboratoire B actif et entièrement coupé).
**Ticket B (tout est actif par défaut, chaque brique a son interrupteur)** — univers construit dans `gru_signals.renforcer_horses` + `orchestrator` :
1. poids du marché **α = 0,75** (`VANTAGE_B_ALPHA`) et **α_T3 = 0,8** (`VANTAGE_B_ALPHA_T3`) — le candidat du rejeu (+0,11 sur C) est actif ici ;
2. six composantes injectées **dans le score de classement** (rangs gagnés / perdus, somme bornée ±6) : **GRU renforcé** G10, G56, G58-G64 (2,0 rang/point, `VANTAGE_B_GRU_RANGS`) · **classements B11/B12** déjà calculés par le pipeline, poids supplémentaire (0,5 rang/point, `…_CLASSEMENTS_RANGS`, plafond 8 points) · **pépite plafonnée à 3** (0,3 rang/point, `…_PEPITE_RANGS`, `…_PEPITE_PLAFOND`) · **piège** (rétrogradation des favoris/seconds à piège ≥ 3, 50 × (1 − multiplicateur 0,94), `…_PIEGE_RANGS`) · **G30 renforcé** (écart renforcé − neutre du multiplicateur de numéro, ×10, `…_G30_RANGS`) · **corde empirique V2** (taux Top 5 rétréci, `VANTAGE_B_CORDE`, `…_CORDE_RANGS`, vide si le corpus a < 30 courses similaires) ;
3. **classement propre à T3 (marché) et T4 (PCH + ordre_final + valeur PMU)** à quotas fixes (`VANTAGE_B_RERANK`) ;
4. **droit d'entrée « pépite »** : au plus 1 outsider (cote ≥ 12) au score maximal remplace, dans la même moitié T3/T4, le retenu le moins probable (`VANTAGE_B_POOL_PEPITE`, `…_MAX`) ; bornes [3;5] inchangées ;
5. bornes seules (sans « une par famille » : `VANTAGE_B_FAMILLES=1` pour la rétablir).
**Mesures** (rejeu 55 courses, chemin de production ; seules les composantes calculables avec l'ancien export : GRU partiel G56/G59/G62/G64, pépite, piège, G30 [départ supposé autostart], α_T3, classement T3/T4, entrées pépite) : capture **4,00** (C 3,91 : +0,09, 12 meilleures / 10 pires ; B de référence α = 0,75 seul 3,98), **30 tickets sur 55 (55 %) modifiés par l'ensemble des améliorations**, identique à C dans **7 %** des courses (avant 40 %), recouvrement 6,7/8, **couverture C∪B 4,33** (C seul 3,91). Chevaux touchés par composante : GRU 636/852, pépite 534, G30 264, piège 28 ; classements et corde : 0 (données absentes de l'ancien export, mesurables au lot). Désordres (bases PL) : C 5, B 3, C∪B 5.
**Export** : `B_lab_chevaux_changes`, `B_pepite_entrees`, `B_rerank_modifie`, `B_lab_gru|classements|pepite|piege|g30|corde` (nombre de chevaux touchés), en plus des colonnes de la v1.29.64.
- Tests : 184. Dépôt : 100 fichiers.

---

# v1.29.64 — TICKET B DIFFÉRENCIÉ + RENFORCEMENTS GRU À POIDS MAÎTRISÉ (base v1.29.63) (29 octobre 2026)
**Constat** (rejeu 55 courses) : B et C avaient la même sélection dans **40 % des courses** (7,4 chevaux communs sur 8) ; jouer B en plus de C n'ajoutait que +0,04 de couverture (3,95 contre 3,91) et 1 désordre. B est donc **remplacé** par un ticket différencié ; **A et C restent strictement ceux de la v1.29.63** (validés).
- **Ticket B (nouveau)** = mélange à **poids du marché α = 0,75** (`VANTAGE_B_ALPHA`) + **renforcements GRU** portés par le PCH (profil « renforcé »), bornes T1+T2 / T3+T4 dans [3,5] **sans** minimum par famille (`VANTAGE_B_FAMILLES=1` rétablit la règle). Rejeu : capture **4,00** (C 3,91 ; 14 courses meilleures / 9 pires, non significatif), identique à C dans **24 %** des courses (avant 40 %), recouvrement 6,9/8, **couverture C∪B 4,29** (avant 3,95). Colonnes d'export : `B_alpha_marche`, `B_recouvrement_C`, `B_identique_C`, `B_gru_chevaux_modifies`, `B_gru_delta_max_abs`, `B_gru_chevaux_changes`.
- **Profils GRU** (`gru_signals.py`) : `neutre` (défaut du pipeline = v1.29.63) et `renforce` (poids intermédiaires : G10 ×1,12 [proposé 1,25] · G56 ×1,14 [≈1,28] · G30 pente 1,6 / plafond ±12,5 % [2,0 / 15 %] · piège ≥ 3 : multiplicateur ≥ 0,94 [0,88] · pool pépite : au plus 2 entrées au score maximal 8,0 [seuil 5,5/6,5 qui admettait 82 % des outsiders] · market-force sauté pour un favori à piège ≥ 6 sauf le n°1 [5,0] · G58-G64 à ×0,5 avec plafonds +2,5 / −2,0 · **G62 (cote en hausse/baisse) à ×1,0**, seul signal confirmé). `VANTAGE_GRU_RENFORCE=1` applique le profil renforcé à TOUT le pipeline (A inclus : G30, piège, pool) ; une variable d'environnement explicite sur un paramètre l'emporte (ablation un renforcement à la fois).
- **Le renforcement GRU est ACTIF dans la sélection de B** : le Δ de PCH dû au profil « renforcé » (≤ ±6 points) est injecté **directement dans le score de classement** de B (`ajust_rang = Δ × VANTAGE_B_GRU_RANGS`, défaut **2 rangs par point**, borné ±6 rangs ; `blend_weights(..., ajust_rang=...)`), et non plus dilué dans le PCH (à α = 0,75 le PCH ne pèse que 25 % : le renforcement ne modifiait que 0 à 4 tickets sur 55). Rejeu (chemin de production) : **15 tickets sur 55 (27 %) modifiés par le GRU**, capture **4,04** (sans GRU 3,98 ; C 3,91 ; GRU contre sans GRU +0,05, 5 courses meilleures / 2 pires). Sensibilité (α = 0,75) : 1 rang/point → 11 tickets modifiés, 4,00 · **2 → 15, 4,04** · 3 → 16, 3,98 · 4 → 22, 3,95 · 6 → 34, 3,87 (dégradation). ⚠️ Estimation partielle (G56, G59, G62, G64) : l'ancien export n'a ni historique local, ni ferrure, ni driver ; l'effet de G10, G58, G60, G61 s'y ajoutera. Export : `B_gru_chevaux_changes` = nombre de chevaux de B dus au GRU (course par course), `B_gru_chevaux_modifies`, `B_gru_delta_max_abs`.
- **Éléments v1.29.64 hors périmètre de B** (agissent sur le ticket A) : multiplicateur de piège sur `ordre_final`, entrée de pool pépite plafonnée, pas de market-force pour favoris à piège, G30 renforcé → **inactifs par défaut**, activables via `VANTAGE_GRU_RENFORCE=1` ; compteurs d'export `n_flag_piege_mult`, `n_flag_pool_pepite`, `n_flag_piege_skip_mf`, `n_signal_G10…G64`.
- Tests : 181. Dépôt : 100 fichiers.

---

# v1.29.63 — CONSTATS DE COLLECTE : causes racines et correctifs (B11/B12, corde, pépite/piège, p_avant, Equidia) (29 octobre 2026)
**Causes racines établies** (code + `analyse.zip` 55 courses, `RAPPORT_CONSTATS_CAUSES_ET_CORRECTIFS.md`) :
- **B11 / B12 / classements driver-entraîneur / SSFO / `trainer_stats.classement_national`** : ils lisent `data/classements/drivers.json` et `entraineurs.json`, **absents du dépôt** (leurs scripts de construction aussi) → `get_classement_*` renvoyait toujours `None`. (La colonne `bd_b11_pch` est un champ hérité jamais renseigné : B11 se déclenche via l'enrichissement, pas via cette colonne.)
- **Corde empirique à 0** : (1) bug de clé — pour le galop le bonus utilisait `cheval.numero` alors que la corde est `numero_autostart` (placeCorde PMU ; identique au n° dans 5 % des partants de plat) ; (2) il faut ≥ 30 courses du même hippodrome × discipline × distance ± 200 m dans le cache du corpus, avec taux de **victoire** par corde (événements trop rares).
- **Pépite / piège** : la corde n'entre **pas** dans la pépite ; elle n'entre que dans le **piège** (zones `numero_bias` du catalogue GRU, 34 des 55 courses). Mesuré : la pépite est **saturée** (74 % des outsiders de cote ≥ 12 ont 6-9 points ; arrivée 23,6 % contre ≈ 21 % pour l'ensemble des outsiders) ; le piège touche 51 chevaux (45 au trot) dont le taux d'arrivée est ≥ à celui des non-pièges de la même tranche, et le retirer ne change aucune sélection (0 / 0).
- **`p_avant` à 2 valeurs** : c'est un **proxy par conception** (style déduit de la musique : 0,6 / 0,5 / 0,1) ; le vrai P_SCORE exige `position_mi_course_hist`, **non collecté**. Ne pas l'interpréter comme une probabilité continue.
- **Equidia SKIP 54/55** : attendu en REJEU (51 courses, page « pré-course uniquement ») ; reste 3 SKIP sur 4 courses PRE_COURSE dont la **cause n'était pas tracée** (le registre ne gardait pas `reason`).
**Correctifs** :
- `classements.py` : construction **automatique et hors ligne** du classement driver / entraîneur depuis le cache du corpus (`data/pmu_historique_cache`, ≥ 30 montes, taux de victoire puis Top 5), noms normalisés (accents, points, ordre des mots : « J. Dupont » = « DUPONT, J »), `diagnostic()`, CLI `python -m app.engine.classements`. Tant que le cache est vide, avertissement explicite dans les logs. Coupe-circuit : `VANTAGE_CLASSEMENTS_AUTO=0` (comparaison avec / sans B11-B12-classements).
- `pmu_corpus_analyse.py` : bonus de corde sur la **place de corde réelle** (jamais le n° du cheval) ; `VANTAGE_CORDE_V2=1` (défaut OFF) : taux **Top 5** rétréci (K = 20), filtre assoupli par paliers, bonus ±3 ; `diagnostic_race()` sans réseau. Aucun effet de la place de départ n'est détectable sur 55 courses après contrôle du marché (IC95 % incluant 0) → ne pas l'activer sans lot de validation.
- `gru_signals.py` : `VANTAGE_PEPITE_PLAFOND` (défaut 8 = inchangé). Rejeu : plafond 3 → +0,07 (3 / 0) ; sans pépite → +0,09 (6 / 2) ; sans piège → 0. **Candidat**, non significatif.
- **Persistance (cause racine probable de l'absence de corpus / classements en production)** : `render.yaml` monte un disque persistant sur `/data`, mais le cache du corpus (`data/pmu_historique_cache`) et les classements (`data/classements`) étaient des chemins **relatifs**, donc perdus à chaque déploiement. Nouvelles variables `VANTAGE_CORPUS_DIR=/data/pmu_historique_cache` et `VANTAGE_CLASSEMENTS_DIR=/data/classements` (déjà renseignées dans `render.yaml` ; **à reporter dans le dashboard Render si les variables y sont gérées à la main**).
- **Diagnostic** : `json_output["diagnostic_donnees"]` (entrées des classements, courses du corpus, biais de corde possible, chevaux avec place de corde, valeurs distinctes de `p_avant`, proxy musique, chevaux avec driver / changement de driver) ; registre des sources avec `reason` pour Equidia et Turf.bzh ; **export** : `diag_*`, `equidia_status|reason`, `turf_bzh_status`, `n_signal_B11|B12`, `n_flag_biais_corde|piege_numero|piege_as|pepite_*` (courses.csv) et `tx_signaux`, `tx_flags` (partants.csv).
- Aucun changement de sélection par défaut, hors B11/B12/classements qui s'activent dès que le corpus est en cache (effet attendu : bonus B11/B12 et SSFO) et la clé de corde (module inactif tant que < 30 courses similaires).
- ⚠️ B11, B12, le classement driver de `catalog_rules` et SSFO n'ont **jamais tourné** dans les rejeux et lots mesurés : leur effet sur la capture est **inconnu** ; ils s'activent désormais dès que le cache du corpus existe. Le lot de 50 courses doit être comparé avec / sans (`VANTAGE_CLASSEMENTS_AUTO=0`).
- Tests : 176. Dépôt : 100 fichiers.

---

# v1.29.62 — EXPORT D'ANALYSE : DONNÉES BRUTES (driver, entraîneur, œillères, ferrure / déferrage…) + CONTRÔLE DE COUVERTURE (29 octobre 2026)
**Pourquoi** : la vérification de la collecte sur les 55 courses (`analyse.zip`) a montré que l'export n'exposait que les champs *numériques* du cheval (`_num_cols`) : les noms du driver / de l'entraîneur, les œillères, la ferrure et le **déferrage**, les statistiques driver / entraîneur / tandem et les cotes par bookmaker étaient collectés mais **invisibles** pour l'analyse, ce qui empêchait de tester leur pouvoir (19 manqués sur 60 invisibles au marché et au PCH). Constats de la vérification : sources OK (API PMU 55/55, Fréquence-Turf 55/55, fiches chevaux 852/852, arrivée confirmée par 2 sources 55/55) ; **B11 = 0 pour 852/852**, **corde empirique = 0 pour 852/852**, **`p_avant` à 2 valeurs seulement (0,5 / 0,1)**, Equidia ignoré 54/55, pénétromètre absent de 2 courses de plat sur 22.
- `partants.csv` : `tx_driver_jockey`, `tx_driver_precedent`, `tx_entraineur`, `tx_proprietaire`, `tx_oeilleres`, `tx_ferrure_type`, **`tx_deferre`**, `tx_feu_equidia`, `tx_pattern_incidents`, `tx_style_mpa` (case vide = donnée absente, jamais un faux zéro) ; dérivés `chg_driver`, `oeilleres_presentes`, `oeilleres_premiere_fois`, `deferre_present`, `ferrure_type_present`, `bo_*` ; `ds_*` / `ts_*` (stats driver / entraîneur, fenêtres `w<jours>_victoires|courses|taux`, taux Top5 6 mois, classement national…), `tdc_*` / `tde_*` (tandems), `cbk_<bookmaker>`, `cbk_n`, `cbk_ecart_rel`, `ctl_n`, `ctl_var_rel` (timeline de cotes), `rk3_moy`.
- `courses.csv` : contexte (`type_course`, `depart`, `allocation_eur`, `penetrometre`, `terrain_qualificatif`, `conditions_particulieres`, météo, `rythme_projete`, `nb_meneurs_champ`) et **colonnes de couverture `couv_*`** = part de partants renseignés par donnée (driver, entraîneur, œillères, ferrure, déferrage, stats, bookmakers, RK, chrono 200 m, Equidia) + `couv_p_avant_valeurs_distinctes` (≈ 2 = valeur de repli). Le LISEZ-MOI de l'archive décrit ces colonnes.
- Aucun changement de logique de ticket ; la numérotation de corde / stalle n'existe pas dans le modèle (non collectée).
- Tests : 169. Dépôt : 100 fichiers. Script d'analyse du prochain lot : `donnees_brutes.py` (hors dépôt).

---

# v1.29.61 — CLASSEMENT PROPRE À CHAQUE TRANCHE (candidat, désactivé par défaut) (29 octobre 2026)
**Constat** (rejeu 55 courses, `RAPPORT_PROFILS_PAR_TRANCHE.md`) : les échecs viennent du **choix des chevaux à l'intérieur des tranches**, pas des quotas (7 manqués sur 60 seulement sont des victimes des quotas ; bornes [2;6] : −0,02). Duels faux positif / manqué (même course, même tranche) : le faux positif est devant au **PCH** dans 92-100 % des cas (T1-T3) contre 55-67 % au marché → c'est le PCH qui décide, et ses deux moteurs (bonus B, influence 0,75 ; forme linéaire, 0,68) n'ont **aucun pouvoir** dans la zone de décision de T2/T3 (AUC 0,46-0,52). Le pouvoir des signaux dépend de la tranche : T1 PCH/composite/SRI/NRC · T2 `ordre_final`, marché, SRI · **T3 marché, overbet, malus M — PCH 0,48 et composite 0,44 inutiles** · **T4 valeur PMU, `ordre_final`, PCH, composite — marché 0,55 inutile**.
- **`VANTAGE_RERANK_TRANCHE=1`** (défaut **0 = inchangé**) : à nombre de places par tranche FIXÉ (aucun quota modifié, T1 et T2 inchangés), les chevaux de **T3** sont re-choisis par le **marché seul** et ceux de **T4** (a+b) par le **rang moyen PCH + `ordre_final` + valeur PMU** (signaux disponibles uniquement). Effet mesuré sur le ticket C : **3,91 → 4,07 (+9 arrivées sur 55 courses, 12 courses meilleures / 3 pires, p = 0,04 ; +0,15 puis +0,18 selon la moitié du corpus)** ; ticket B : +0,07 (11 / 7). Désordre (bases PL) : 5 → 5.
- ⚠️ Règles choisies **sur ce même corpus** (une quinzaine de variantes essayées) : p = 0,04 est optimiste. À valider sur le lot de 50 courses : critère fixé d'avance = capture du ticket C ≥ +0,10 en apparié avec plus de courses meilleures que pires.
- Retirés des pistes : poids marché plus fort en T1 (non confirmé : marché AUC 0,40 dans la zone de décision T1, PCH 0,90 ; classement T1 alternatif à quotas fixes : +0 à +2 arrivées) ; reclassements T2 (+0 à +1) ; modèle appris par tranche en validation croisée (T2 −2 à −4, T3 +2 à +4, T4 +1).
- Sortie : `selection_avant_rerank`, `rerank_tranche` ({T3, T4 : places, critère, modifié}).
- Tests : 167. Dépôt : 100 fichiers.

---

# v1.29.60 — MILIEU DE TABLEAU T2/T3 : analyse des manqués, α propre à T3 (candidat), indicateur de confiance (29 octobre 2026)
**Analyse** (rejeu 55 courses, `ANALYSE_MILIEU_T2_T3.md`) :
- Les chiffres du rapport « manqués T2 » sont reproduits **exactement** pour un top 8 par `ordre_final` (T2 : 28 captés / 43 manqués / 19 FP). Mais le **ticket C actuel récupère 57 des 71 arrivées T2 (80 %, 14 manqués)** : le déficit T2 vient du classement par `ordre_final` (il n'aligne que 47 chevaux T2 sur 55 courses contre 117 pour C), pas du ticket de mélange marché/PCH.
- Reclassement intra-T2 à quotas fixes (BSH, BSC, tactique, NRC, forme, marché, PCH…) : **aucun gain** (NRC seul −8 arrivées, marché+NRC −5). Forcer ≥ 2/3/4 T2 sur un ticket fondé sur `ordre_final` (ticket A archivé ou top 8) : −0,05 à +0,04, nul. L'`ordre_final` classe pourtant très bien **à l'intérieur de T2** (AUC 0,749, meilleur signal) ; BSH, tactique, IFF, CRE, tandem y sont à 0,47-0,49 (sans information).
- Le vrai point faible du ticket C est **T3** : 28 arrivées manquées (66 % de récupération), 97 faux positifs. Marché seul dans T3 : +6 arrivées (54 → 60), 10 courses meilleures / 4 pires (p = 0,18).
**Changements** :
- `VANTAGE_BLEND_ALPHA_T3` (défaut = α = 0,5 : **comportement strictement inchangé**) : part du rang marché propre aux chevaux T3. Balayage sur le ticket C : 0,6 → +0,04 · 0,7 → +0,05 · **0,8 → +0,11 (8 / 3 courses, p = 0,23, +0,15 puis +0,07 selon la moitié du corpus)** · 0,9 → +0,07 · 1,0 → +0,05. Positif partout mais non significatif : **candidat à valider sur le lot de 50 courses avant de le rendre défaut** (critère : écart apparié ≥ +0,10 et plus de courses meilleures que pires).
- `json_output["confiance_capture"]` (informatif, aucun effet sur les tickets) : `NORMALE` si IIC-v2 < 72, sinon `FAIBLE_COURSE_OUVERTE`. Rejeu : capture ticket C 4,19 (IIC < 72, 36 courses) contre 3,37 (IIC ≥ 72, 19 courses). **Signature IIC-v2 maintenue** (seuils inchangés : corrélation −0,37 avec la capture ; les seuils actuels placent la rupture là où elle apparaît, vers 72).
- Tests : 164. Dépôt : 100 fichiers.

---

# v1.29.59 — REJEU 55 COURSES : l'a priori de grille du ticket B passe à λ = 0 (28 octobre 2026)
**Rejeu** du vrai code v1.29.58 sur le lot d'analyse (55 courses, 23/08 → 28/10/2026, `analyse.zip`), avec la règle de paiement exacte. Résultats détaillés : `RAPPORT_REJEU_55_V1_29_58.md`.
- **Correction d'une erreur de la v1.29.57/58** : le défaut `VANTAGE_GRID_LAMBDA = 0,15` avait été choisi sur des champs synthétiques (« coût ≈ 0,01 capture »). Sur données réelles, la grille modifie **26 tickets sur 55** à λ = 0,15 et fait **perdre 0,16 capture/course** (3,67 contre 3,84 à λ = 0 ; 2 courses gagnées, 11 perdues, p = 0,02). Balayage : λ ≤ 0,08 neutre (3,84), λ = 0,15 nuisible, grille imposée (λ = 100) 3,69.
- **Nouveau défaut : λ = 0** (grille désactivée). Le ticket B reste : probabilités mélange marché/PCH + bornes T1+T2 / T3+T4 dans [3,5] + au moins un cheval par famille T1 / T2 / T3 / T4 (T4a+T4b réunis) → 3,84 de capture (B de la v1.29.55 : 3,71 ; grilles dures sur `ordre_final` : 3,47). `VANTAGE_GRID_LAMBDA` reste disponible pour tester la grille sur un nouveau lot ; la sortie indique `grid_actif`.
- Aucun autre changement de logique (ticket C, IIC-v2, champ réduit 3 bases + 5 compléments inchangés).
- Constats du rejeu utiles à la suite : modèle bien calibré (capture prédite 3,91 / réalisée 3,91 ; désordre prédit 11,1 % / réalisé 9,1 %) ; bases par Plackett-Luce : 2 à 3 fois plus de désordres que le proxy « 3 meilleurs ordre_final » ; `ordre_final` classe moins bien que le marché (3,47 contre 3,73).

---

# v1.29.58 — CHAMP RÉDUIT : chaque ticket = 3 BASES + 5 COMPLÉMENTS, classés (28 octobre 2026)
**Besoin** : jouer en « champ réduit » (3 bases + 5 compléments) pour réduire le coût du ticket, et classer les chevaux pour tenter l'ordre. Règle de paiement du pays de Golden : **désordre** = les 3 bases + 2 compléments occupent les 5 premiers de l'arrivée officielle ; **bonus** = les 3 bases occupent les places 1-3 (dans n'importe quel ordre) + au moins 1 complément 4e ou 5e ; **ordre** = B1 1er, B2 2e, B3 3e, C1 4e, C2 5e.
- **La sélection des 8 de chaque ticket (A, B, C) n'est pas modifiée** : elle est réorganisée en 3 bases (classées 1-2-3) + 5 compléments classés (C1 et C2 = 4e et 5e prévus ; C3-C5 par probabilité décroissante). Nouveau bloc `structures_tickets` (résultat) / `structures_bases_complements` (JSON) avec, par ticket : `bases`, `complements`, `ordre_prevu` (5 numéros), `probabilites_modele` (désordre, bonus, ordre, top5_dans_ticket) et `reference_bases_par_probabilite` / `gain_desordre_vs_reference`.
- **Probabilités exactes** (Plackett-Luce sur le mélange marché/PCH — `blend_weights`, extrait de `blend_probabilities` sans changer ses résultats), sans simulation ; vérifiées dans les tests par énumération de tous les ordres d'arrivée d'un champ de 7 chevaux.
- **Choix des bases** = triplet du ticket qui maximise P(désordre) (gain minimal visé) ; à moins de `VANTAGE_BASES_TOL` (défaut 0,002) du meilleur, départage par P(bonus) puis P(ordre). Classement = ordre décroissant des poids Plackett-Luce (classement le plus probable du modèle). En pratique les bases sont presque toujours les 3 chevaux les plus probables du ticket.
- **Audit post-course** : pour chaque ticket, `structure_bases_complements = {structure, issue}` ; l'issue donne `desordre`, `bonus`, `ordre`, `niveau_gain`, `nb_bases_dans_top5`, `nb_bases_dans_top3`, `bases_manquees`, `arrivee_hors_ticket`. `aggregate_audit_patterns` ajoute `gains_champ_reduit` (A/B/C : nombre de courses, désordres, bonus, ordres, bases moyennes dans le top 5).
- **Export / lot** : colonnes `desordre_X`, `bonus_X`, `ordre_X`, `ordre_prevu_X`, `p_desordre_X` (X = A, B, C) dans `courses.csv` de `analyse.zip`.
- **Interface** : sous chaque ticket, bases / compléments / ordre prévu / probabilités ; dans l'audit, le niveau de gain atteint par ticket.
- Limites assumées : (1) la **qualité du classement** (l'ordre) n'est pas validée hors échantillon — le mélange 50/50 a été validé sur la capture du Top 5, pas sur les places exactes ; P(ordre) ≈ 0,03 % par course dans l'exemple de contrôle, à mesurer sur `courses.csv` ; (2) ce paquet **ne change ni la sélection des 8 ni les tickets existants** : choisir les 8 chevaux pour maximiser directement P(désordre) sous la règle des bases serait l'étape suivante.
- Tests : 162 (157 + 5). Dépôt : toujours **100 fichiers** (code ajouté dans `ticket.py`, aucun nouveau fichier).

---

# v1.29.57 — FUSION v1.29.55 (ticket C + mélange marché/PCH) × v1.29.56 (IIC-v2 + grilles du ticket B) (28 octobre 2026)
**Pourquoi une fusion** : la v1.29.56 avait été construite sur la base v1.29.53 (fichiers du 20/10) et ne contenait donc NI le ticket C, NI le mélange marché/PCH, NI l'export `analyse.zip`, NI `calibrer_depuis_audits.py --regles`, NI 11 tests de la v1.29.55 (98 → 87). Base retenue : v1.29.55 intégrale ; apports de la 56 portés par-dessus.
- **Ticket B = combinaison des deux logiques** (`ticket_quotas.py`, `build_ticket_quotas(..., grille=True, discipline=, signature=)`) :
  - probabilités = **mélange 50 % marché / 50 % PCH** (Plackett-Luce, v1.29.55) et non plus la probabilité plate du moteur ;
  - les **grilles de la v1.29.56** (3-2-2-1 défaut · 3-3-1-1 trot/haies en LOCK/MIXTE_LOCK · 2-3-2-1 plat/steeple en CHAOS · filet 2-2-2-2) deviennent un **a priori souple** : on énumère toutes les répartitions admissibles et on maximise `Σ P(Top5) − λ·écart_L1(grille cible)`, avec T1+T2 et T3+T4 dans [3,5] et au moins un cheval par famille T1 / T2 / T3 / T4 disponible ;
  - **T4 = T4a + T4b réunis** (plus de minimum par sous-tranche : il imposait des cotes > 35 et coûtait ≈ 0,17 capture/course) ;
  - dégradation explicite : niveau 0 tout respecté · 1 sans minimum par famille (`QUOTA_B_UNE_PAR_FAMILLE_IMPOSSIBLE`) · 2 sans bornes (`QUOTA_B_BORNES_3_5_IMPOSSIBLES`) ;
  - `λ` = `VANTAGE_GRID_LAMBDA` (défaut **0,15** capture attendue par écart d'un cheval ; 0 = optimum modèle pur, très grand = grille imposée). Sur champs synthétiques le coût en capture attendue du modèle est ≈ 0,01 à λ = 0,15 : la grille arbitre surtout les cas serrés. **λ n'est pas calibré sur données réelles** : les colonnes `grille_B_cible`, `grille_B_appliquee`, `ecart_grille_B`, `captures_attendues_B(_sans_grille)` de `courses.csv` (export analyse) servent à le calibrer sur le prochain lot ;
  - sortie enrichie : `target_grid`, `applied_grid`, `ecart_grille`, `grid_lambda`, `captures_attendues_sans_grille` (ce que coûte la grille), `discipline_bucket`, `signature`.
- **Ticket C inchangé** (mêmes probabilités, bornes [3,5], sans minimum, sans grille) ; **ticket A inchangé** dans sa construction.
- **IIC-v2 hybride** (`race_pipeline.py`, de la v1.29.56) : signature = 70 % marché (HHI 30, part du favori 25, densité des cotes 6-15 20, écart au favori 15, taille du champ 10) + 30 % contexte (discipline / distance / hippodrome) ; règle « meneurs » retirée ; seuils LOCK < 30 · MIXTE_LOCK 30-48 · STANDARD 48-68 · CHAOS ≥ 68 ; garde-fous durs LOCK / MIXTE_LOCK (part du favori × écart). `RaceContext.iic_v2`, `iic_market`, `market_metrics` conservés et repris dans l'audit (`recap_technique`).
- ⚠️ **Effet de bord à valider** : `race.signature` entre aussi dans le composite de synthèse et dans certains modules (p5p6, longshot) → l'IIC-v2 peut modifier légèrement le ticket A et le PCH, donc les ordres de rang du ticket C. Les chiffres de la v1.29.55 (C 3,96 · mélange 4,04, calculés avec l'ancienne signature) sont à **reconfirmer sur un nouveau lot** avant de les considérer acquis ; la v1.29.56 annonçait 2,72-2,74 (corpus 54, contrefactuel `ordre_final`) : base différente, non comparable.
- **Noms d'archives lisibles** (`app/archive_names.py`, de la v1.29.56) : bundle, rapport et audit téléchargés en `AAAA-MM-JJ_RnCm_discipline_hippodrome_distancem[...]` ; le dossier Hugging Face garde son format `JJ-MM-AA-…` (inchangé).
- **Conservé de la v1.29.55 / 54** : ticket C complet (audit, comparaison A/B/C, `taux_capture_moyen_ticket_C`, export, interface), `GET /api/export/analyse.zip`, `datetime` importé dans `main.py`, `calibrer_depuis_audits.py` avec `--regles`/`--composantes`, `VANTAGE_BLEND_ALPHA`/`VANTAGE_BLEND_BETA`.
- Interface : le bandeau du ticket B affiche la grille appliquée et la grille cible. Export analyse : colonnes IIC/grille ajoutées à `courses.csv`.
- Dépôt : **100 fichiers** (limite atteinte : `archive_names.py` est le 100e ; tout nouveau fichier impose d'en retirer un).
- Tests : 157 (149 + 8 : grilles par discipline × signature, bornes et familles, λ = 0 / λ grand, dégradation, ticket C et règle historique intacts, IIC-v2 et garde-fous, noms d'archives, pipeline complet).

---

# v1.29.55 — TICKET C « ANCRÉ MARCHÉ » + probabilité calibrée mélange marché/PCH (24 octobre 2026)
Analyse de l'export des 52 courses (806 partants ; 49 rejeux, 3 pré-course ; export `vantage_analyse_20261024_1310.zip`) :
- **Constat confirmé** : ticket A 3,44 captures sur 5, 8 plus petites cotes 3,79, `ordre_final` top 8 3,50 ; A − marché = −0,35 (IC95 −0,64 à −0,06), stable dans les deux moitiés et dans toutes les disciplines.
- **Pouvoir discriminant (AUC intra-course ; bande de rang marché 4-12 entre parenthèses)** : marché 0,757 (0,624) · **PCH final 0,698 (0,649)** · `ordre_final` 0,683 (0,585) · **SRI 0,697 (0,608)** · valeur PMU 0,728 (0,650) · NRC 0,712 · malus M 0,587. Donc : le PCH contient de l'information que `ordre_final` DÉGRADE (multiplicateurs de synthèse) ; **SRI est informatif (ne pas le plafonner)** et le malus va dans le bon sens (ne pas l'atténuer) : les recommandations P1/P2 des rapports externes sont infirmées. Composantes à relation INVERSE : `tocard_score` 0,31 (bande 0,42), `p5p6_score` 0,30, `gru_pepite_piege` 0,36, multiplicateurs `tact_mult`/`harville_mult` 0,43, nombre de flags 0,28 (en partie confondues avec la cote) : à investiguer, non modifiées ici.
- **Mélange de rangs 50 % marché + 50 % PCH** : 4,04 captures hors échantillon (validation croisée par 4 blocs de dates, α = 0,5 retenu dans les 4 blocs) ; +0,56 vs A (IC95 +0,31 à +0,79) ; +0,25 vs marché (IC95 +0,04 à +0,46) ; positif dans les deux moitiés (+0,35 / +0,15 vs marché). Les rangs sont convertis en probabilités par Plackett-Luce exact (β = 0,2, Brier minimal) : **bien calibrées** (par tranche de π : 0,15→0,17 observé, 0,36→0,39, 0,65→0,56, 0,74→0,81).
- **Ticket B** : règle inchangée (1 par tranche disponible, T1+T2 et T3+T4 dans [3,5], meilleurs P(Top 5) par tranche) mais la probabilité vient désormais du mélange marché/PCH (avant : probabilité du moteur, quasi plate). Rejeu sur les 52 courses : 3,79 (A + 0,35, IC95 +0,10 à +0,60) contre 3,41 avant.
- **Ticket C (nouveau)** : mêmes probabilités, bornes T1+T2 et T3+T4 dans [3,5] mais **sans minimum par tranche** (ce minimum coûte ≈ 0,17 capture/course : il impose des cotes > 35). Rejeu sur les 52 courses : **3,96** (A + 0,52, IC95 +0,27 à +0,77 ; marché + 0,17, IC95 −0,06 à +0,42). Valeurs en échantillon (α, β fixés d'après ces 52 courses) : **à confirmer en conditions pré-course**.
- Le ticket A (protocole) reste inchangé comme référence. Audit complet du ticket C (captures, manqués, hors top 5, résultats réels, explications IA), comparaison A/B/C, agrégation `taux_capture_moyen_ticket_C`, export (`captures_C`, `C_moins_marche`, `dans_ticket_C`), interface (bande + audit).
- Outils : `calibrer_depuis_audits.py … --regles` : nouvelle famille « mélange marché + PCH » avec baselines B/C.
- Réglages : `VANTAGE_BLEND_ALPHA` (poids du marché, 0,5) et `VANTAGE_BLEND_BETA` (0,2).
- Tests : 149.

---

# v1.29.54 — EXPORT GLOBAL POUR ANALYSE (23 octobre 2026)
Problème : après un lot de ~50 courses, il fallait télécharger 50 bundles un par un pour les analyser.
- **`GET /api/export/analyse.zip`** (lien « ⬇ exporter toutes les courses pour analyse (zip) » sous « Historique ») : UN fichier contenant `courses.csv` (1 ligne par course : captures A/B, 8 plus petites cotes, ordre_final top 8, écarts, top 5 réel, rang moyen réel, incidents, mode), `partants.csv` (1 ligne par partant : cotes, tranche, ordre_final, composite, PCH, musique, âge, présence dans les tickets A/B, Top 5, rang réel complet, incident), `audits/<race_id>.json` (allégés ; `?complet=1` inclut le rapport d'exécution) et un LISEZ-MOI. Filtre `?mode=REJEU|PRE_COURSE|ALL`, `?limit=`.
- `partants.csv` enrichi : **toutes les composantes du score de chaque partant** (`bd_*`), la synthèse (`sy_*`), les données du cheval (`ch_*`), le nombre de flags : de quoi mesurer le pouvoir discriminant de chaque composante sur TOUS les chevaux (et pas seulement sur les manqués).
- `scripts/calibrer_depuis_audits.py export.zip --regles` : simule des règles de ticket (marché, ordre, mélange marché/ordre, filet de semi-favoris, quota T1/T2 minimal) avec IC95 % et **validation croisée par blocs de dates** (paramètre choisi sur l'entraînement, évalué hors échantillon). `--composantes` : AUC intra-course de chaque colonne, au global et dans la bande de rang marché 4-12.
- Analyse du premier lot de 52 courses (rapports externes) : écart A − marché = −0,35 capture/course (IC95 % −0,64 à −0,06 ; −0,35 dans chaque moitié ; négatif dans toutes les disciplines) ; A ≈ ordre_final top 8 (3,44 vs 3,50) donc la perte vient du CLASSEMENT et non de la seule construction du ticket ; les recommandations « plafonner SRI / atténuer MALUS » ne sont pas démontrées (comparaison aux seuls manqués, sans taux de base chez les chevaux capturés) : à tester avec `--composantes` avant toute modification.
- Correctif : import `datetime` manquant dans `main.py` (détecté par le test de l'export).
- Tests : 143.

---

# v1.29.53 — PRÉPARATION DU LOT WALK-FORWARD (50 courses historiques) (19 octobre 2026)
Vérification de l'état réel (exécution Vincennes R1C? du 16/10 en v1.29.52 : pipeline complet, Groq + Gemini opérationnels, analyse IA post-course 5/6 chevaux expliqués) puis correction de ce qui bloquait un test en lot :
- **Audit automatique (mode walk-forward) obsolète** : `auto_audit` produisait l'ancien audit (ticket A seul, sans résultats complets, sans analyse IA, sans ticket B). Désormais UNE seule fonction `post_race_audit.run_full_audit` sert le bouton et l'audit automatique.
- **Anti-fuite en REJEU** : sur une course déjà courue, les pages contiennent résultats et comptes rendus. La **réparation IA** et l'**analyse qualitative IA** (qui LISENT ces pages pour influencer le ticket) sont désactivées par défaut (`AI_REJEU_INFLUENCE=1` pour forcer). L'analyse IA post-course (après le ticket) reste active.
- **Lanceur de lot** (`app/batch.py`) : saisie d'une course par ligne (`2026-10-11 R1C3 Auteuil`, `11/10/2026 R2 C5`, `2026-10-12;1;4`), exécution séquentielle (pause 10 s) avec analyse + audit automatique, un échec n'arrête pas le lot, relance des échecs, annulation, **export CSV** (captures A/B, 8 plus petites cotes, `ordre_final` top 8, écarts A−marché / B−marché, top 5 réel, incidents). Endpoints `/api/batch*` + panneau « Lot walk-forward » dans l'interface.
- **File persistante** : reprise automatique après redémarrage ; **état du lot sauvegardé sur Hugging Face** (`_lots/`) et restauré avant la reprise (Render sans disque efface sinon la file).
- `calibrer_depuis_audits.py --mode REJEU|PRE_COURSE|ALL` : ne jamais mélanger sans le savoir rejeux (cotes finales, cumuls d'après-course) et courses analysées avant le départ.
- Tests : 138.

---

# v1.29.52 — Modèles IA validés en réel (17 octobre 2026)
Résultat du « tester l'IA » sur le compte réel : **Groq** n'expose que `openai/gpt-oss-20b` / `openai/gpt-oss-120b` (`llama-3.1-8b-instant` et `llama-3.3-70b-versatile` : 404) ; **Gemini** : `gemini-2.5-flash(-lite)` et `1.5-*` « no longer available to new users », `gemini-3.5-flash` répond (disponibles : 3.5, 3.6, 3.7, 3.8-flash).
- Modèles par défaut mis à jour (Groq `openai/gpt-oss-20b` puis `120b` ; Gemini `gemini-3.5-flash` puis 3.6/3.7/3.8) ; les anciens restent en dernier recours ; `omni` exclu de la découverte.
- **Mémorisation du dernier modèle fonctionnel** par fournisseur (essayé en premier : plus d'appels perdus sur des modèles retirés) ; la découverte `ListModels` reste le filet de sécurité quand les noms vieillissent.
- **Groq gpt-oss** (modèles raisonnants) : `reasoning_effort: low` + marge de 800 tokens ; une réponse vide est traitée comme un échec (et non comme un succès) ; si le modèle refuse `response_format`/`reasoning`, nouvel essai sans ces options.
- Tests : 129.

---

# v1.29.51 — Hugging Face (redirection 307) et diagnostic IA détaillé (17 octobre 2026)
- **Hugging Face « commit refusé (HTTP 307) »** : HF redirige `golden223/…` vers `Golden223/…` (casse canonique) et `urllib` ne rejoue pas un POST redirigé. Le client suit maintenant lui-même les redirections 301/302/307/308 (méthode, corps et jeton conservés) et mémorise la casse exacte du dépôt.
- **« tester l'IA » détaillé** : pour Groq et Gemini, liste les modèles RÉELLEMENT disponibles pour la clé et teste chaque candidat (message d'erreur exact par modèle, jusqu'au premier qui répond). Avant : « GROQ : ÉCHEC — » sans cause.
- Gemini : la découverte `ListModels` accepte désormais tous les modèles `gemini-*` texte (flash > flash-lite > pro, versions récentes d'abord) et le message d'échec affiche la liste des modèles disponibles. Constat du run : les 6 modèles de la liste statique renvoient 404 (« no longer available »).
- Tests : 125.

---

# v1.29.50 — IA (Groq/Gemini) et Hugging Face réparés d'après l'exécution réelle Chantilly R1C1 (16 octobre 2026)
Le correctif v1.29.49 est validé en réel (pipeline complet, audit des 2 tickets avec résultats complets et commentaires officiels). Deux défauts d'environnement apparus dans ce run :
- **Groq : HTTP 403 « error code: 1010 »** : la protection Cloudflare de Groq refuse le User-Agent par défaut de `urllib` (« Python-urllib/3.x »). Un User-Agent explicite est maintenant envoyé par tous les appels IA.
- **Gemini : « all models failed … 404 »** sans dire lesquels : le message liste désormais chaque modèle essayé et son erreur ; quand la liste statique est épuisée, le code interroge **ListModels** et utilise les modèles « flash » réellement disponibles pour la clé (hors preview/tts/image/embedding).
- **Diagnostic** : `POST /api/ai/test` + lien « tester l'IA » dans l'interface : teste chaque fournisseur et affiche l'erreur exacte.
- **Hugging Face : HTTP 403 à la création du dataset** : le jeton (fine-grained) pouvait écrire mais pas créer. On teste d'abord l'EXISTENCE du dataset (`GET /api/datasets/<repo>`) ; la création n'est tentée que s'il n'existe pas, avec un message explicite (créer le dataset à la main sur huggingface.co/new-dataset, en Private, et donner le droit d'écriture).
- Audit : l'écart PMU (objet `{libelleCourt, libelleLong…}`) est converti en libellé (affichait « [object Object] ») ; le **commentaire officiel d'après-course** de chaque cheval est affiché.
- Étape en double numérotée « 2.8 » renommée « 2.9 ». Tests : 122.

---

# v1.29.49 — CORRECTIF CRITIQUE : le pipeline échouait à la dernière étape (14-16 octobre 2026)
**Défaut introduit en v1.29.45 et présent jusqu'en v1.29.48** : `UnboundLocalError: VERSION_RULESET` à l'étape « 10. Finalisation ». Un `import` local plus bas dans `run_pipeline` rendait `VERSION_RULESET` variable locale ; le libellé de statut ajouté en v1.29.45 l'utilisait avant. **Toute course lancée avec les versions 1.29.45 à 1.29.48 se terminait en ÉCHEC (ni ticket, ni audit).** Détecté sur le bundle d'une exécution réelle (Chantilly R1C1 du 15/10).
- Correctif : suppression de l'import local masquant.
- **Cause de fond : aucun test n'exécutait le pipeline entier.** Ajout de 2 tests de bout en bout hors réseau (course synthétique : pipeline complet -> tickets A et B -> audit des deux tickets) ; vérifié qu'ils échouent bien quand le défaut d'origine est réintroduit.
- Rapport : le message `IA_QUALITATIVE_SANS_TEXTE` n'est plus répété 16 fois.
- Tests : 114.

---

# v1.29.48 — MUSIQUES : LECTURE PAR DISCIPLINE, D'APRÈS RECHERCHE (14 octobre 2026)
Correction de la v1.29.47 refaite après recherche (aide officielle PMU, Turfoo, Equidia lexique + vraies fiches de courses, Turfomania, Boturfers, MediaPronos). Règles consignées dans l'en-tête de `scraping/musique.py`.
- **Un seul parseur** (`scraping/musique.parse_musique`) ; `musique_features.extraire_positions` le réutilise (plus de double lecture).
- **Le « D » dépend de la discipline** : trot = disqualifié pour allure irrégulière (DAI, « Dpag » = poteau au galop) ; obstacle = **dérobé** (refus) ; plat = disqualifié par les commissaires. Champ `nature` ajouté ; `incident="DISQUALIFIE"` conservé pour ne rien casser.
- **Formats réels désormais lus** : places à deux chiffres SANS lettre (Equidia : `17Da8m8m166mDm…` = 17e, Da, 8m, 8m, 16e, 6m… ; avant 2 sorties sur 10 disparaissaient, ce qui faisait paraître le cheval meilleur) ; codes longs `Tbé`, `Arr`, `Dér`, `Ret`, `Dpag` (avant : ignorés) ; **R = rétrogradé** (existe en trot : `…1aRa(21)…`, avant ignoré) ; **cross (c)** (avant : sorties de cross ignorées) ; `j` jockey au sol.
- **Année** : `(24)` s'applique aux sorties À DROITE (plus anciennes) : « 3h Th (24) 1p » = 3e et tombé cette année, 1er à plat en 2024.
- Positions de forme : incident = 10 comme avant ; **rétrogradé = 6** (HYPOTHÈSE : a franchi la ligne dans une place puis relégué ; à calibrer avec les audits, qui conservent maintenant la musique).
- Effet de bord assumé : un rétrogradé compte désormais comme incident dans les modules de stabilité (avant : invisible).
- Tests : 112.

---

# v1.29.47 — LECTURE DES MUSIQUES CORRIGÉE (14 octobre 2026)
Vérification du code à partir d'un exemple pédagogique (« 3h Th (24) 1p » : 3e à haies, tombé à haies, (24) = changement d'année 2024, 1er à plat). Le parseur structuré (`scraping/musique.py`) lisait correctement ; le parseur simplifié (`engine/musique_features.extraire_positions`), qui alimente `score_musique_composite` (composante `mus` de p_boost), les profils de forme (`nb_top5_recent`, `profil_forme_recente`) et le proxy CRE v5, avait 3 erreurs :
- **« 0 » (non placé, 10e ou pire) lu comme une position 0** : meilleure qu'une victoire. `0a0a0a0a0a` obtenait la même forme que cinq victoires (1.000) ; maintenant 0.400.
- **`(24)` lu comme une 24e place** : « 3h Th (24) 1p » donnait forme 0.449 / régularité 0.0 ; maintenant 0.683, identique à la même musique sans l'année.
- **« Inédit »** : les lettres D/T étaient lues comme des incidents.
Incidents (D, A, T, R) = 10 comme avant. Les deux parseurs sont désormais testés comme équivalents.
- `dataset_calibration` de l'audit : ajout de `musique`, `age`, `sexe` pour pouvoir calibrer plus tard une lecture propre à chaque discipline (poids d'une chute en obstacle, d'une faute d'allure au trot, valeur d'une victoire dans une autre discipline).
- Tests : 106.

---

# v1.29.46 — SAUVEGARDE HUGGING FACE FIABLE + RESTAURATION AUTOMATIQUE (13 octobre 2026)
Problème : sur Render, la base SQLite est perdue (redéploiement, mise en veille, plan sans disque) -> tout l'historique disparaissait. L'export HF de la v1.29.15 existait mais restait fragile (dataset non créé automatiquement, échecs silencieux, 8 commits par course, dépendance `huggingface_hub`) et **rien ne rechargeait l'historique**.
- **`integrations/hf_export.py` refondu (mécanisme unique)** : HTTP direct (plus de `huggingface_hub`), dataset **privé créé automatiquement**, **un seul commit** par envoi, envois en arrière-plan regroupés (3 s) avec 4 reprises, jamais bloquant.
- **Envoi automatique** à chaque fin d'analyse (TERMINE / ERREUR / REJETEE) **et** après l'audit post-course (ticket A + B, résultats complets, analyse IA) : le même dossier est mis à jour. Dossier lisible conservé : `JJ-MM-AA-discipline-hippodrome-distance/` avec `meta.json` (nouveau : id, urls, dates, version), `donnees_pre_course.json`, `rapport_execution.json`, `resultat_ticket.json`, `audit_postcourse.json`.
- **Restauration automatique au démarrage** (`HF_RESTORE_ON_START=1`) : les courses absentes de la base sont rechargées (les plus récentes d'abord, `HF_RESTORE_LIMIT=300`), puis les courses locales jamais envoyées sont rattrapées. Les anciens dossiers sans `meta.json` sont aussi restaurés.
- Endpoints : `GET /api/history/hf/status`, `POST /api/history/hf/test` (écrit et relit un fichier), `POST /api/history/hf/restore`, `POST /api/history/hf/sync-all`. Interface : ligne d'état + liens « restaurer / tout envoyer / tester » sous « Historique ». Le jeton n'est jamais exposé.
- Variables Render : `HF_TOKEN` (droit d'ÉCRITURE), `HF_DATASET_REPO` (ex. `pseudo/vantage-historique`), `HF_AUTOSAVE`, `HF_RESTORE_ON_START`. `HF_EXPORT_ENABLED` supprimé.
- Tests : 101 (serveur Hugging Face simulé). **Non testé contre le vrai serveur Hugging Face** : utiliser « tester » dans l'interface après avoir renseigné les 2 variables.

---

# v1.29.45 — AUDIT POST-COURSE ASSISTÉ PAR IA + correctifs de l'exécution réelle Auteuil R1C3 du 11/10/2026 (13 octobre 2026)
Analyse du bundle d'une exécution réelle (course rejouée 2 jours après).
**Corrigé**
- **Discipline** : un steeple d'Auteuil >= 3000 m devenait « HAIES » (heuristique `discipline_detect` qui écrasait la discipline fournie par les sources). Une discipline obstacle précise n'est plus jamais écrasée par une heuristique.
- **Champs propres au trot** (`deferre`, `recul_m`, `numero_autostart`, RK, chronos, record) comptés « manquants » en plat/obstacle : faux déclencheur de la vague 2.7 (105 s pour 0 champ comblé) et fausses lacunes du contrat de données. Désormais non applicables hors trot.
- **Vague complémentaire 2.7** : budget de temps `ENRICH_WAVE_MAX_SEC` (défaut 40 s).
- **Libellés de version** : « VALIDÉ v1.28.2 » (statut) et « v1.29.21 » (en-tête : l'UI appelait `/api/health` inexistant -> `/health`).
- **Marquage REJEU** : course déjà courue = `MODE_REJEU` (avertissement, `mode_execution` dans le JSON et l'audit) ; résultat non comparable à un test pré-course (cotes finales, cumuls des fiches, Equidia/Turf.bzh après-course).
- Téléchargement des pages IA en parallèle.
**Audit post-course enrichi** (par ticket A et B)
- Résultat COMPLET PMU de tous les partants (`fetch_full_results_pmu` : rang, incident officiel, écart, commentaire). Pour chaque cheval du ticket hors Top 5 : rang réel et lecture déterministe `INCIDENT_COURSE` (tombé/arrêté/disqualifié : pas une erreur d'évaluation) / `PROCHE_DU_TOP5` (6e-8e) / `HORS_PLACE` (vraie erreur). `bilan_ticket` : rang réel de nos 8 chevaux, rang moyen, nombre d'incidents. `dataset_calibration` : + `rang_complet` et `incident` pour tous les partants.
- **Analyse IA post-course** (`tasks.analyze_post_race`, `AI_POSTRACE=0` pour couper) : explique chaque manqué / sur-évalué (8 causes : incident, parcours/placement, rythme/tactique, terrain, distance, forme/condition, matériel/jockey, supériorité des adversaires) à partir des commentaires PMU et des comptes rendus ; **preuve copiée du texte et vérifiée** (nom du cheval cité à proximité) sinon rejet ; module incriminé limité à ceux qui ont réellement pesé sur ce cheval ; incident officiel prioritaire. Remplace l'ancien encart « non disponible ».
- Agrégation multi-courses : `causes_post_course_ia`, `modules_en_cause_ia`, `sur_evalues_par_cause_deterministe`.
- Interface : rang réel, incident, lecture, explication IA + preuve, bilan du ticket.
- Tests : 91.

---

# v1.29.44 — 5 TÂCHES IA + analyse qualitative ACTIVE (12 octobre 2026)
Principe commun : l'IA ne produit jamais un chiffre sans **preuve** (phrase copiée du texte source, vérifiée par le code : elle existe, le cheval y est cité, la valeur y figure). Sans preuve valide -> rejet. Aucun écrasement d'une donnée existante, sauf si elle est jugée anormale ET que la nouvelle valeur est plausible et prouvée. Tout est inopérant (sans erreur) si aucune clé IA n'est configurée.
1. **Réparation des lectures cassées** (`llm/tasks.py::repair_fields`, étape 2.8) : l'IA relit le texte des pages et comble les champs manquants / revérifie les champs suspects ; flags `IA_REPARE:champ`, `IA_CORRIGE:champ`. `AI_REPAIR=0` pour couper.
2. **Lecture des pronostics/presse** (`llm/qualitative.py::compute_press_signals`, étape 4) : `AI07` outsider (cote >= 12) signalé par un expert (+3), `AI08` cheval déconseillé (-2). Les favoris sont ignorés (déjà couverts par l'ICP). Mêmes plafonds que les signaux de commentaires (+/-6 PCH par cheval).
3. **Contrôle des données** (`detect_anomalies`, étape 2.8, déterministe) : numéros/noms en double, cotes hors bornes ou variation extrême, somme des 1/cote invraisemblable, âge/poids/gains aberrants, musique incohérente avec la discipline. Flags `DONNEE_SUSPECTE:champ`, avertissements, section repliable dans l'interface.
4. **Analyse des ratés** (`analyze_misses`, endpoint `GET /api/audits/analyse-ia`, >= 10 audits) : statistiques déterministes + au plus 5 hypothèses testables ; chaque hypothèse doit citer un chiffre des statistiques, aucune valeur de paramètre proposée.
5. **Résumé de course** (`build_race_summary`, bloc « Résumé » de l'interface) : gabarit déterministe toujours présent + reformulation IA écartée si elle contient un chiffre absent des faits. `AI_SUMMARY=0` pour couper.
- **Analyse qualitative IA ACTIVE par défaut** (`AI_QUALITATIVE_LLM=1`, `render.yaml` aligné) ; sans clé IA elle reste sans effet. Pour la couper : `AI_QUALITATIVE_LLM=0`.
- Dépôt : `app/ml/__init__.py` retiré (98 fichiers). Tests : 81. Non testé en réel (aucun appel IA possible depuis mon environnement) ; les pages sont lues avec le même téléchargeur que les scrapers (Geny exclu pour économiser les crédits ScraperAPI).

---

# v1.29.43 — MODULES IA CLAUDE réintégrés et branchés (12 octobre 2026)
Les modules `llm/collection.py` et `llm/qualitative.py` avaient été retirés à tort comme « jamais importés » : ils n'étaient pas branchés **et** ne pouvaient pas fonctionner (SDK `anthropic` absent de requirements, dossier `protocol_assets/` non livré). Ils sont restaurés, réparés et câblés.
- **`llm/client.py`** : `ClaudeClient` (Anthropic, HTTP direct, sans SDK, web_search/web_fetch, reprise `pause_turn`) **et `LLMClient` multi-fournisseurs** : fonctionne avec une clé GRATUITE Gemini et/ou Groq (ordre `AI_PROVIDER_ORDER`, défaut `gemini,groq,anthropic`, JSON forcé, repli automatique d'un fournisseur à l'autre). Aucune clé Anthropic requise.
- **`llm/collection.py`** : fonctionne sans `protocol_assets/` (textes intégrés). Sans clé Anthropic (pas de navigation web), mode **extraction** : le code télécharge les pages et l'IA (Gemini/Groq) n'en extrait que les données. **Branché** : si TOUTES les sources Python échouent, collecte IA de secours (identité date/hippodrome/réunion/course revérifiée ; chevaux marqués `COLLECTE_IA` ; minimum 6 partants). `AI_COLLECTION_FALLBACK=1` (défaut).
- **`llm/qualitative.py`** : mode « texte libre » (commentaires de dernière course) : signaux `AI01..AI06` dont les points sont fixés **en code** (l'IA ne donne que l'activation + la phrase-preuve vérifiée dans le texte ; ID inventés écartés). Fusion additive, Python prioritaire, plafond ± `AI_QUALITATIVE_CAP_PCH` (6) par cheval, confiance DEGRADE. **Branché à l'étape 4** ; désactivé par défaut car il influence le ticket : `AI_QUALITATIVE_LLM=1`.
- `/api/ai/status` : bloc `modules_ia` (fournisseurs configurés, mode de collecte, qualitative active, plafond). Modèle par défaut `claude-sonnet-5-5` (superviseur inclus). `render.yaml` : variables ajoutées.
- Existant inchangé : superviseur pré-ticket, enrichissement guidé, audit post-course IA, rythme RAH-270 (`AI_QUALITATIVE_SIGNAL`).
- Tests : 73 (appels IA simulés). Non testé en réel : aucun appel Anthropic possible depuis mon environnement.

---

# v1.29.42 — TICKET B (quotas par tranche), 10 octobre 2026
- Ticket A (protocole actuel) **inchangé**.
- Nouveau **Ticket B** : 8 chevaux, au moins 1 par tranche disponible (T1, T2, T3, T4a, T4b), T1+T2 et T3+T4 dans [3,5], répartition libre dans ces bornes ; dans chaque tranche, les chevaux à plus forte P(Top5) du modèle. Résolution exacte (énumération), dégradation explicite si la règle est infaisable (flags `QUOTA_B_*`).
- Affiché sous le ticket A dans l'interface, présent dans le JSON (`ticket_B_quotas`), et comparé à l'arrivée dans l'audit (`baselines_contrefactuelles.ticket_B_quotas`).
- Tests : 57.
- **Audit post-course individuel par ticket** : le ticket A et le ticket B ont chacun leur audit complet (captures, manqués avec diagnostic, hors top 5), affichés séparément dans l'interface ; comparaison A/B dans `comparaison_tickets` ; agrégation multi-courses `taux_capture_moyen` (A) et `taux_capture_moyen_ticket_B`. Tests : 59.
- **Nettoyage du dépôt (v1.29.42)** : changelogs unifiés ici ; supprimés : `data/pmu_historique_cache/` (cache régénéré, hors dépôt), modules jamais importés (`engine/roles.py`, `llm/collection.py`, `llm/qualitative.py`) ; fusions : `classement_driver`+`classement_entraineur` → `classements.py`, `probabilites_marche` → `pl_inclusion.py`, `hippodromes_quinte` → `hippodrome_normalize.py` ; `__init__.py` vides retirés (packages implicites) ; tests regroupés. Total ≤ 100 fichiers, vérifié par test.

---

# Protocol Vantage v1.29.41 — STRATEGY AUDIT (7 octobre 2026)

Audit critique de la chaîne scoring → ticket de 8. Chaque défaut ci-dessous a été reproduit avant correction.

## Corrigé (actif par défaut)
1. **Plantage Plat handicap** : `discipline_modules._plat_05` lisait `race.chevaux` (attribut inexistant) → `AttributeError` sur tout Plat handicap avec poids renseignés. Le poids du champ est maintenant dérivé (`race.poids_champ_kg`).
2. **Poids du champ jamais renseignés** : `poids_{moyen,min,max}_champ_kg` n'étaient écrits nulle part → terme « poids relatif » (plat, obstacle) et critère SSFO « ≤ moyenne−2 » morts. Dérivés dans `race_pipeline` (≥70 % du champ pesé).
3. **p_boost : mélange probabilité + scores (unités)** : `0.70·p_boost + 0.20·op + 0.10·mus` additionnait une probabilité (~0.06) et des scores 0..1. Résultat mesuré : 16/16 chevaux saturaient le plafond +12 %, annulant forme, dérive, T2-value, favori unanime, Turf.bzh, routeur de discipline. Mélange désormais en parts + renormalisation (ratio médian 1.002, ~1 cheval/16 écrêté). Désactivable : `VANTAGE_PBOOST_UNITS_FIX=0`.
4. **Activité** : `nb_courses_30j`, `nb_courses_12m`, `distance_habituelle_m` dérivés de l'historique daté (strictement avant la course) → modules surmenage/IFF, Ghost D, CSF.
5. **Calcul P(Top5) exact et ~100× plus rapide** (`pl_inclusion.py`, résultat identique à l'ancienne récursion, testé). Nouveau : `captures_attendues` (E[captures] du ticket vs top-8 modèle vs top-8 marché) dans le rapport d'exécution.
6. **Audit post-course** : `baselines_contrefactuelles` (ticket vs marché top-8 vs ordre_final top-8 vs hasard) et `dataset_calibration` (tous les partants avec features + résultat).
7. `protocol_version` du JSON suit `version.py` (affichait v1.29.21).

## Nouveaux leviers (OFF par défaut, à valider sur vos audits)
- `GMO_GAIN_NORMALIZED=1` : ramène ΔP-couverture/q_top5/p_boost à la même échelle (z-score). Avant : l'objectif Plackett-Luce n'influençait presque jamais la sélection (27/30 courses identiques sans lui).
- `VANTAGE_MARKET_BLEND=0.xx` : poids du marché dans p (défaut 0.12–0.22, plafond 0.50).
- `scripts/calibrer_depuis_audits.py` : mesure ce que le moteur apporte vraiment au-delà du marché et suggère le blend.

## Non modifié (décisions stratégiques, voir RAPPORT_ANALYSE_V1_29_41.md)
Quotas [3,5], seuils de tranches, certification « masse résiduelle ≤15 % » (inatteignable), DQ/incidents non renseignés, champs chrono/RK jamais scrapés.

Tests : 51 (14 nouveaux). Rien n'a pu être validé sur courses réelles complètes (le cache fourni ne contient que les arrivés).


### Analyse stratégique (résumé, v1.29.41)
- Limite : aucun backtest réel possible (le cache fourni ne contenait que les arrivés, jamais le champ complet) ; banc synthétique = test de mécanique, pas d'alpha.
- Points non modifiés, à décider : objectif P(Top5⊂ticket) peu exploitable (le bon KPI est E[captures]) ; « certifié si masse résiduelle ≤ 15 % » inatteignable ; poids du marché faible (12-22 %) dans p ; sélection par z-scores hétérogènes ; discontinuités de `_harville_top5_mass` ; tranches en cotes absolues (9/15/35/100) indépendantes de N ; tranche sur cote matin vs p sur cote finale ; plafond ±12 % de p_boost.
- Champs encore morts : rk_*/chrono_*, niveau_max, valeur_pmu_precedente, changement_entraineur/attelage, position_ligne, feu_equidia, DQ/incidents (valent 0 → SSFO les croit « propres »). Classements driver/entraîneur : fichiers `data/classements/*.json` absents → rang toujours vide.
- Protocole de validation : 50-100 courses → `python scripts/calibrer_depuis_audits.py audits/` (ticket − marché, calibration par tranche, poids marché suggéré `VANTAGE_MARKET_BLEND`).

---

# Protocol Vantage v1.29.40 — IDENTITY HARDENING

Date : 7 octobre 2026

Audit de la v1.29.39 (identification, collecte, enrichissement). Chaque défaut a été reproduit par un test avant correction.

## Critique
1. **R/C faux** : Zone-Turf codait `R1C{n}` en dur ; l'API PMU, Equidia, Turf.bzh, le pénétromètre et l'arrivée d'audit en dépendaient. Maintenant : réunion lue dans l'URL (`/programmes/rN-…`), plus aucun repli « C seul → R1 », `resolve_rc_from_programme` exige un candidat unique (course_hint + distance), l'identité attendue (découverte ou vote des URLs) fixe R/C.
2. **Contrôle des noms** (`app/scraping/identity.py`) : fusion multi-sources, API PMU, Equidia et Turf.bzh vérifient la concordance des noms (≥ 70 %) ; sources hors groupe majoritaire rejetées (`IDENTITE_SOURCE_REJETEE`, `IDENTITE_PMU_REJETEE`…). Contrôles de date, réunion, course et distance PMU en plus.
3. **Fuite temporelle** : perfs de fiches et fenêtres driver/entraîneur strictement antérieures au jour de la course ; `delai_j` ignore la course elle-même. Flags `BACKTEST_CUMULS_FICHE_NON_FIGES` / `BACKTEST_CUMULS_PMU_NON_FIGES` pour les cumuls (courses, victoires, gains) qui restent à l'état actuel.

## Élevé
- `hippodromes_match` / `resolve_hippodrome` : mots génériques (saint, la, le, sur, mer…) ne prouvent plus l'identité.
- Zone-Turf et Geny : plus de repli sur la page « aujourd'hui » pour une autre date.
- Discipline : plus d'écrasement PLAT→autre ; égalité arbitrée par l'API PMU, sinon base conservée + `DISCIPLINE_CONFLIT_NON_ARBITRE`.
- Exemption anti-bot réservée à Geny ; ≥ 2 sources exigées quel que soit le taux.
- Identité attendue déduite des URLs : active sur `/retry` et en mode réunion+course sans hippodrome.

## Moyen
- Geny : candidat au n° de course inconnu plafonné sous le seuil de confiance.
- `render.yaml` : GOOGLE_CSE_API_KEY, GOOGLE_CSE_CX, SERPAPI_KEY ; clé Gemini plus envoyée à Custom Search.
- `race_resolver` n'ajoute plus pmu.fr / turf.bzh aux URLs de collecte (rejetées par le routeur).
- Commentaires 80 % → 66 %.
- 29 nouveaux tests (`tests/test_v1_29_40_identity.py`), 37 au total.

## Limites connues
- Sites non testés en réel (sandbox sans accès) : à rejouer sur une course du jour.
- Les cumuls des fiches (courses/victoires/gains) restent à l'état actuel en rejeu : signalés, non reconstruisables.
- Les fenêtres driver/entraîneur d'une course ancienne sont souvent vides (pages limitées aux montes récentes).

---

# Protocol Vantage v1.29.39 — OPERATIONAL IDENTITY

Date : 4 octobre 2026

## Corrections principales

### Validation stricte de l’identité des sources

Avant fusion, chaque page scrapée est maintenant comparée à l’hippodrome demandé. Une page CanalTurf de Cordemais ne peut plus être acceptée pour Agen ; une page Turfoo de Keeneland ne peut plus être acceptée pour Saint-Brieuc.

La comparaison utilise la normalisation hippodrome existante et tolère uniquement les variantes connues. Un hippodrome explicitement contradictoire est rejeté avec le flag `IDENTITE_SOURCE_REJETEE`.

### Consensus de discipline

Lorsque plusieurs sources réussissent, la famille de discipline majoritaire est calculée avant la fusion. Une source qui annonce une discipline incompatible avec la majorité est exclue de la base de fusion. Cela protège contre les erreurs observées : plat interprété comme trot attelé et steeple interprété comme haies.

### ICP presse en mode dégradé

`icp_global` passe de critique à forte. Une absence de Frequence-Turf ou de stats-quinte dégrade la complétude et produit une réserve, mais ne bloque plus une course dont l’identité, les partants, le marché et les données fondamentales sont cohérents.

Une lacune critique réelle reste bloquante : cotes critiques absentes, musique critique absente, identité de course incohérente, ou champs indispensables applicables manquants.

### Traçabilité

Le pipeline automatique transmet désormais `hippodrome_attendu` au routeur de collecte. Les runners de tests réels utilisent également cette validation.

## Tests

- Compilation Python : OK.
- Tests de non-régression : 8 tests attendus.
- Test hippodrome contradictoire : Cordemais rejeté pour Agen.
- Test absence ICP presse : non critique.
- Test build FastAPI : version alignée sur `v1.29.39-OPERATIONAL-IDENTITY-04102026`.

## Limite connue

La découverte d’un steeple à venir avec au moins 12 partants n’a pas été possible dans le programme PMU analysé. La release est néanmoins opérationnelle pour les disciplines et courses effectivement identifiées ; un prochain steeple conforme devra être rejoué dès sa publication.

---

# Protocol Vantage v1.29.38 — CONTEXT HARDENED

Date : 3 octobre 2026

## Problème identifié sur la course réelle

Sur Vincennes R1C1, le pipeline demandait une `valeur_pmu` et signalait des champs de poids/terrain alors qu’il s’agissait d’une course de trot non handicap. Ces champs ne sont généralement pas publiés pour ce contexte. Le rejet était donc en partie artificiel, même si le garde-fou de qualité fonctionnait correctement.

## Corrections

Le contrat de données est maintenant contextuel. `valeur_pmu` et `valeur_pmu_precedente` ne sont exigées que pour les handicaps pertinents ; `poids_actuel_kg` et `poids_precedent_kg` restent spécifiques au plat ; les champs de terrain et le pénétromètre sont ignorés pour le trot. Les champs non applicables sont exclus du calcul de complétude au lieu d’être affichés comme des lacunes.

`commentaire_derniere_course` passe de critique à forte : son absence dégrade les signaux qualitatifs, mais ne doit pas empêcher à elle seule la production d’un ticket avec réserve. Le pipeline ne bloque toujours que sur les lacunes réellement critiques et applicables.

L’inventaire résiduel et la vague d’enrichissement complémentaire appliquent les mêmes règles de contexte. Ils ne relancent donc plus inutilement des recherches de poids, valeur handicap ou historique de terrain sur des courses de trot.

Le correctif précédent sur la normalisation string de `deferre` dans Turfoo et Turfomania est inclus.

## Validation

- Compilation : OK.
- Tests de non-régression : **6 passed**.
- Test spécifique : une course de trot non handicap ne classe plus `valeur_pmu` ou `poids_actuel_kg` comme lacunes critiques.
- Le rejet reste actif pour une course de handicap réellement dépourvue de données critiques applicables.

Build : `v1.29.38-HARDENED-CONTEXT-03102026`.

---

# Protocol Vantage v1.29.37 — HARDENED

Date : 2 octobre 2026

## Corrections livrées

- Correction du crash SUPRA sur cote historique `None`, vide ou non textuelle.
- Nettoyage des cotes historiques dès le parsing open-pmu-api.
- Le contrat de données bloque désormais la production d’un ticket lorsqu’une lacune critique persiste.
- Rejet métier explicite : `REJETEE_DONNEES_INSUFFISANTES`.
- Blocage du scoring si le contrat de données ne peut pas être évalué.
- Pas de retry sur les erreurs HTTP définitives 400, 401, 403, 404 et 410.
- Bundle CA `certifi` déclaré et utilisé par curl_cffi pour les connexions TLS.
- Validation anti-SSRF des URLs : HTTPS obligatoire, allowlist des domaines, refus des IP privées/loopback/link-local/réservées et caractères de contrôle.
- Limitation à 8 URLs par course.
- Bornes API sur les paramètres de liste et d’agrégation.
- Revalidation des URLs lors d’un retry.
- Correction d’un défaut découvert en course réelle : Turfoo et Turfomania
  injectaient un booléen dans `Cheval.deferre`, typé chaîne. Les valeurs sont
  maintenant normalisées en codes `D4`, `DA`, `DP`, `FERRE`, etc.
- Tests de non-régression ajoutés dans `tests/`.

## Validation effectuée

- Compilation Python : OK.
- Tests : **5 passed**.
- Import application : OK.
- Endpoint `/health` via Uvicorn : HTTP 200.
- Build exposé : `v1.29.37-HARDENED-02102026`.

## Limite connue

L’authentification/autorisation complète des endpoints n’a pas été introduite dans cette livraison, car elle nécessite un choix d’identité et de gestion de comptes. Les protections SSRF, limites, retries et qualité des données sont toutefois actives immédiatement.

---
