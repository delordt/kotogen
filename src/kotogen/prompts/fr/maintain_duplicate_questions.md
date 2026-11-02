Tu détermines quelles questions de compréhension demandent la MÊME chose qu'une question
cible, parmi les questions d'un même texte japonais (un texte de lecture ou la
transcription d'un extrait d'écoute), pour un apprenant francophone.

On te donne le texte, découpé en lignes numérotées, puis ses questions, numérotées, chacune
avec sa réponse et sa ligne clé (la ligne du texte qui appuie le plus la réponse). La cible
est nommée.

Deux questions sont des doublons quand répondre à l'une répond à l'autre : le même fait
demandé deux fois, en d'autres termes, ou par l'autre bout (« Où va-t-elle ? » / « Qu'y
a-t-il au parc ? » quand la réponse aux deux est « elle va au parc »). Deux questions sur la
même ligne qui demandent deux choses différentes ne sont pas des doublons.

Réponds UNIQUEMENT en JSON, avec la `reason` en français, en ne listant que les doublons de
la cible (une liste vide s'il n'y en a pas) :

```json
{"duplicates": [{"n": 3, "reason": "les deux demandent où elle va"}]}
```

Les clés sont le protocole : reprends-les exactement telles quelles, sans jamais les
renommer ni les traduire. `n` est le numéro d'une question, jamais celui de la cible.
