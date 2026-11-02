Tu retravailles une carte de vocabulaire japonais qui est un LEECH : l'apprenant francophone
échoue dessus de façon répétée. Réécris-la pour qu'elle soit PLUS FACILE à mémoriser la
prochaine fois, SANS changer le mot ni son sens central.

## Champs (clé "fields")
- Expression : le mot en furigana `漢字[かな]`. NE PAS le changer (corrige seulement un furigana faux).
- Translation : français. Garde UN seul sens, le plus fréquent, en 1 à 2 mots. Retire les sens
  secondaires : c'est souvent la source de confusion qui fait échouer.
- Context : à renseigner si le mot se confond avec un autre de même traduction - c'est
  souvent ça, le leech. Voir les règles plus bas.
- Notes : ajoute un indice mémoriel COURT si utile (nuance distinctive, piège fréquent) : sur
  un leech, c'est une raison d'écrire une Note. Sinon vide.
  NE mets PAS ici l'aide sur les kanji (elle va dans "kanji_help").
- Example + ExampleTranslation : une phrase TRÈS courte, concrète et quotidienne qui ancre le mot.
  Remplace un exemple trop long ou abstrait. Les deux ensemble, ou les deux vides.

## Context, Notes, registre

{{include:vocab_fields}}

Les noms de champs sont le schéma du type de notes : reprends-les exactement tels
quels, sans jamais les renommer ni les traduire. Ce que tu écris dessous est en
français.

## Aide kanji (clé "kanji_help") - le SENS des kanji, rien d'autre
Si l'Expression s'écrit avec PLUSIEURS kanji, donne le sens de chacun, dans l'ordre du mot.
Pas de phrase, pas d'« histoire » - quelques mots : `学 étudier + 生 vie`.
- NE décompose JAMAIS un kanji en composants ni en clés : la forme d'un kanji est l'affaire
  de sa carte dans le deck kanji, pas de celle du mot.
- Le sens du KANJI, en un mot, pas celui du mot entier : `生 vie`, pas « étudiant ».
- UN seul kanji (`橋`, `食[た]べる`) : `kanji_help` = "". Son sens est la traduction, déjà sur
  la carte.
- Kanji choisis pour leur son (ateji : `寿司`, `珈琲`) : `kanji_help` = "". Leur sens
  égarerait.
- NE répète PAS le mot lui-même au début (il est déjà dans l'Expression) : commence
  directement par le premier kanji, sans préfixe « 漢字 = ».
- NE répète PAS le sens/la traduction du mot (déjà sur la carte) : pas de conclusion « → … ».
- PAS de ligne de confusion ni de « ≠ … » : uniquement le sens des kanji.
**1 ligne courte** (~50 caractères). Sinon `kanji_help` = "".

## Convention furigana
`漢字[かな]` avec un espace ASCII avant chaque groupe de kanji (`今日[きょう]は 暑[あつ]い`).

## Carte hors catégorie (clé "category", facultative)
Ce deck ne contient que du **vocabulaire**, et une carte qui n'en est pas explique souvent
l'échec répété. Si l'Expression n'est pas du vocabulaire, ajoute la clé `category` :

- `grammar` : règle, particule seule (は, が, を…), suffixe ou tournure (〜ている, 〜たら, 〜ながら).
- `sentence` : phrase entière ou proposition, là où on attend un mot.
- `fragment` : morceau qui ne s'emploie jamais seul (élément de mot composé, okurigana orphelin).

Les trois valeurs sont le protocole et se reprennent exactement telles quelles ; la
`reason` qui les accompagne s'écrit en français, et reste très courte.

Dans le DOUTE, **omets cette clé** : une expression figée, un mot composé, une onomatopée,
un compteur, un nom propre courant sont du vocabulaire. Un mot simplement difficile n'est
pas hors catégorie. Cette clé ne remplace pas la simplification : réponds aussi normalement.

## Réponse
UNIQUEMENT du JSON, sans texte autour. N'inclus dans "fields" que les champs RÉELLEMENT modifiés :
```json
{"reason": "ce qui rend la carte plus simple", "fields": {"Translation": "…"}, "kanji_help": "...",
 "category": {"type": "grammar", "reason": "suffixe verbal, pas un mot"}}
```
