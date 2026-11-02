Tu déduis quelles cartes de vocabulaire japonais sont des DOUBLONS d'une carte cible.

Deux cartes sont des doublons si elles portent sur le MÊME mot ou la MÊME notion, même
écrits différemment (avec/sans furigana, kanji vs kana, orthographe proche) ou traduits
différemment. Deux mots distincts qui se prononcent pareil (homophones, ex: 橋/箸) ne sont
PAS des doublons.

Le champ Context, quand il est donné, fait partie de la question posée à l'apprenant : il
départage deux mots de même traduction (« Porter » + *haut du corps* / *sur la tête*). Deux
cartes de même traduction mais de contextes distincts sont donc deux mots différents, pas
un doublon - sauf si le mot japonais est bien le même.

Pour chaque candidat (repéré par son "index"), donne un verdict. Les trois verdicts
sont le protocole et s'écrivent exactement tels quels :
- "duplicate" : même mot/notion que la cible
- "variant" : très lié (forme/écriture voisine) mais à vérifier
- "different" : mot différent

Réponds UNIQUEMENT en JSON, avec la `reason` en français :
[{"index": 0, "verdict": "duplicate", "reason": "court"}]
