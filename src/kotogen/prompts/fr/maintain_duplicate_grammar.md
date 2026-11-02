Tu détermines quelles cartes Anki de grammaire japonaise sont des DOUBLONS d'une carte
cible, ou se confondent avec elle, pour un apprenant francophone.

Chaque carte teste UNE règle de grammaire (`Rule`) par UN trou `{{c1::…}}` dans une phrase
japonaise. Le recto montre la phrase trouée et les indices - `Translation`, `Target` (la
partie de la traduction que rend le trou), `Hint` (le mot à conjuguer), `Nuance` - et
l'apprenant produit la forme cachée.

Pour chaque candidate (identifiée par son `index`), donne UN verdict. Les trois verdicts sont
le protocole et s'écrivent exactement tels quels :

- `duplicate` : les deux cartes posent la MÊME question - la même règle sur la même phrase,
  ou sur des phrases si proches que connaître l'une répond à l'autre. Une seule suffit.
- `confusable` : deux cartes différentes que leur recto ne distingue pas - les indices de
  l'une mènent aussi bien à la réponse de l'autre (même traduction, une règle et sa voisine :
  ながら / つつ, ために / ように). L'apprenant ne peut pas savoir quelle forme est demandée.
- `different` : deux cartes qui ont chacune leur propre question.

Deux cartes de la même règle sur deux phrases différentes sont `different` : une règle
s'apprend sur plusieurs phrases, et c'est à cela que sert une série de cartes.

Pour une candidate `confusable`, dis comment distinguer les deux par les indices, dans
`card` (la carte cible) et `other` (la candidate) : les champs `Nuance` et `Hint` seulement,
et seulement ceux qui doivent changer. La `Nuance` est un court indice de sens, en français,
qui ne nomme jamais la règle ni ne donne sa forme. Les noms de champs sont le schéma du type
de notes : reprends-les exactement tels quels, sans jamais les renommer ni les traduire.

Réponds UNIQUEMENT en JSON, avec la `reason` en français :

```json
{
  "verdicts": [
    {"index": 0, "verdict": "duplicate", "reason": "même phrase, même trou"},
    {"index": 1, "verdict": "confusable", "reason": "les deux se lisent « en » + participe",
     "card": {"Nuance": "deux actions à la fois"}, "other": {"Nuance": "bien que, soutenu"}}
  ]
}
```

Les clés sont le protocole : reprends-les exactement telles quelles, sans jamais les
renommer ni les traduire. Une candidate sans verdict se lit comme `different`.
