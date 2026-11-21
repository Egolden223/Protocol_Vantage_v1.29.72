# PROTOCOL VANTAGE v1.29.72

Application FastAPI de pronostic PMU (trot, plat, obstacle). Déploiement Render (`render.yaml`, Dockerfile).

- Version courante : `app/version.py` (source de vérité). Historique : `CHANGELOG.md` (seul changelog autorisé).
- Règles du dépôt : 100 fichiers maximum (`tests/test_regressions.py::test_repo_file_budget`), caches et `data/` hors dépôt.
- Archives locales : `{AAAA-MM-JJ}_R{n}C{m}_{discipline}_{hippodrome}_{distance}m` ; Hugging Face : `{JJ-MM-AA}-{discipline}-{hippodrome}-{distance}m`.


## Recalibrage actif v1.29.69

Les coefficients actifs par défaut sont : SRI proxy gains `0.65`, proxy cote `0.40`, plancher `0.50`; bonus catalogue B `0.90` et répétitions d’une famille `0.75`; malus M DEGRADE `0.75` et MINIMAL `0.50`; MPA style inconnu `0.50` et MPA négatif sans pénétromètre `0.20`; tocard T1–T3 `0.75`; plafond de rangs marché ≥9 `A:2,B:2`. Le SRI observé, les signaux stricts et les positifs MPA restent inchangés.

Les variables correspondantes sont `VANTAGE_SRI_PROXY_GAINS_MULT`, `VANTAGE_SRI_PROXY_COTE_MULT`, `VANTAGE_SRI_PROXY_FLOOR_MULT`, `VANTAGE_BONUS_B_MULT`, `VANTAGE_BONUS_B_REPEAT_MULT`, `VANTAGE_MALUS_M_DEGRADE_MULT`, `VANTAGE_MALUS_M_MINIMAL_MULT`, `VANTAGE_MPA_UNKNOWN_CONF_MULT`, `VANTAGE_MPA_NO_PENETRO_MULT`, `VANTAGE_TOCARD_MULT_T123` et `VANTAGE_CAP_OUTSIDERS`.

## Min1 par tranche actif v1.29.70

La sélection min1 est active par défaut pour A, B et C : au moins un cheval en T1, T2, T3 et T4, lorsque ces tranches sont présentes. **T4 regroupe T4a et T4b** : un cheval de l’une ou l’autre suffit; il n’est pas nécessaire de prendre les deux. Les anciennes bornes [3,5]/[5,3] entre T1+T2 et T3+T4 sont abandonnées pour les tickets finaux. `VANTAGE_SELECT_MIN1_TICKETS` peut restreindre explicitement le périmètre (par exemple `B`); si la variable est absente ou vide, A, B et C sont actifs.

## Corrections et audit v1.29.71

- **T2 relatif** : force = rang PCH inversé dans le champ; edge = rang PCH comparé au rang de cote, calculés après le PCH de tous les partants et avant la sélection. Le signal ne modifie pas `PCH_FINAL`; l’effet sur les prochaines arrivées reste à mesurer.
- **RAH-242** : le plafond inclut désormais les contributions positives GRU et tactiques; le breakdown expose primaire positif, secondaire brut, secondaire autorisé et correction appliquée.
- **GMO-V** : `json_output.gmo_v_pool_trace` fournit, par numéro, l’admission finale et les motifs. La réservation des favoris marché est appliquée après le cap de 14, conformément à la règle documentée. Le log greedy/post-sélection reste disponible dans `gmo_v_log`.
- **Valeur PMU trot** : l’audit rapporte valeur initiale/consommée, source champ lorsqu’elle est connue, valeur brute et heure UTC de collecte locale. Le champ fournisseur `observed_at_utc` reste explicitement `null` si l’API ne le fournit pas; une source préexistante non identifiable est marquée non attribuée.
- Ces ajouts améliorent la correction et l’observabilité des **prochaines** courses; ils ne prouvent pas que toutes les causes des 162 audits historiques sont corrigées. Les quotas/minima par tranche ne sont pas présentés comme explication des échecs passés.
