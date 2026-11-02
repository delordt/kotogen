Plusieurs cartes de vocabulaire japonais partagent la MÊME traduction française. Au recto
Production, l'apprenant ne voit que cette traduction et le champ Context : tant qu'ils ne les
départagent pas, la question a plusieurs réponses justes et aucune n'est trouvable. Donne à
chaque carte le Context qui la désigne, elle et pas une autre.

Ce qui est propre à un lot :

- **Les Context se lisent ensemble** : aucun ne doit pouvoir désigner deux cartes du lot.
  Relis-les les uns contre les autres avant de répondre.
- **Un badge de registre ne départage pas.** Une carte suivie de `Tags=` porte un registre
  (`Register::改まった語`, `Speaker::男性語`...) que la carte affiche au verso, avec la
  réponse : la question ne le voit pas. Quand c'est ce registre qui départage la carte,
  son Context le dit en nommant l'autre carte (*plus soutenu que 友達*), et un Context
  qui le dit déjà se garde.
- Un Context déjà en place et qui fait son travail ne se retouche pas, et une comparaison
  déjà en place (*plus soutenu que 今*) se garde telle quelle. Retouche un Context qui vaut
  aussi bien pour une autre carte du lot, reprends-le s'il n'apprend rien.
- **Une traduction trop large se corrige, elle ne se départage pas.** Une carte qui n'est
  dans le lot que parce que sa traduction est inexacte ou tronquée reçoit sa `Translation`
  juste, en 1 à 3 mots, sans « ; », « / » ni parenthèse : 要点 n'est pas `Essentiel` mais
  `Point essentiel`. Elle sort alors du lot, et son Context se vide. Ne retraduis jamais
  pour départager deux mots qui se traduisent vraiment pareil : ceux-là gardent leur
  traduction et reçoivent un Context. Une précision entre parenthèses (`Tante (d'autrui)`)
  n'est pas une traduction : c'est un Context passé dans la question.
- **Des Notes qui départagent déjà la carte** (*pour les êtres animés*) contiennent son
  Context sans le dire : fais-en le Context et retire ce passage des Notes, en gardant le
  reste tel quel. Ce que dit le Context sort des Notes même tourné autrement (Context
  *précipitations*, Notes *Pour la pluie, la neige*). Les Notes que tu renvoies remplacent
  tout le champ.

Et ce qui vaut pour toute carte de vocabulaire :

{{include:vocab_fields}}

Les noms de champs sont le schéma du type de notes : reprends-les exactement tels
quels, sans jamais les renommer ni les traduire. Ce que tu écris dessous est en
français.

Reste concis. Ne modifie jamais l'Expression, et la Translation seulement pour la raison dite plus haut.

Si deux cartes du lot sont en fait le MÊME mot (même mot japonais sous deux graphies ou
deux découpages de furigana), ne leur invente pas deux contextes : signale-les dans
`duplicates`. Un même kanji lu de deux façons (末[すえ], 末[まつ]) fait deux mots. Deux mots réellement distincts se départagent, ils ne se signalent pas ; dans
le doute, départage.

Réponds UNIQUEMENT en JSON. Les clés sont le protocole et se reprennent
exactement telles quelles :

```json
{
  "reason": "ce qui départage le lot, en une phrase",
  "cards": [
    {"n": 1, "Context": "emploi salarié"},
    {"n": 2, "Context": "tâche à accomplir", "Notes": "…"},
    {"n": 3, "Context": ""},
    {"n": 4, "Translation": "Point essentiel", "Context": ""}
  ],
  "duplicates": [[5, 6]]
}
```

`n` est le numéro de la carte dans la liste. N'inclus dans `cards` que les cartes
réellement modifiées, et omets `duplicates` s'il n'y en a pas.
