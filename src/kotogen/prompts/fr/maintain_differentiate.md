Deux cartes de vocabulaire japonais risquent d'être confondues. Propose une façon de les
DISTINGUER clairement, en ajustant le Context et/ou les Notes de l'une et de l'autre.

C'est le Context qui porte la distinction quand les deux cartes ont la MÊME traduction
française, et les Notes ce qui éclaire après la réponse. Au moins l'une des deux cartes
porte un Context qui la désigne - un badge de registre est au verso, et la question ne le
voit pas ; la plus ordinaire peut rester nue. Un Context déjà en place et qui fait son travail ne se retouche pas.

{{include:vocab_fields}}

Les noms de champs sont le schéma du type de notes : reprends-les exactement tels
quels, sans jamais les renommer ni les traduire. Ce que tu écris dessous est en
français.

Reste concis. Ne modifie PAS Expression ni Translation, sauf si une correction est
indispensable.

Cas particulier : quand l'une des deux cartes n'a PAS sa place dans le deck alors que
l'autre est bonne (mot inexistant ou mal formé, graphie fautive, traduction fausse,
fragment qui ne s'emploie pas seul, carte vide de contenu à réviser), n'invente pas une
distinction artificielle : demande sa suppression avec `"delete"` (1 ou 2). N'utilise
`"delete"` que si la carte gardée couvre déjà tout ce qu'il y a à apprendre ; deux mots
réellement distincts, deux nuances, deux registres, deux graphies toutes deux correctes
se distinguent, ils ne se suppriment pas. Dans le doute, distingue.

Réponds UNIQUEMENT en JSON, sous l'une des deux formes :

```json
{
  "reason": "ce qui les distingue, en une phrase",
  "card1": {"Context": "haut du corps"},
  "card2": {"Context": "sur la tête", "Notes": "…"}
}
```

```json
{
  "reason": "pourquoi cette carte n'a pas sa place, en une phrase",
  "delete": 2
}
```

N'inclus que les champs réellement modifiés ; omets card1 ou card2 si tu n'y touches pas.
