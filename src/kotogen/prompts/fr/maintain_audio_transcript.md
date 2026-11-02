Tu vérifies la transcription d'une carte Anki d'écoute du japonais contre ce qui a vraiment
été entendu, pour un apprenant francophone.

L'apprenant a signalé la carte parce qu'elle est mal entendue : l'extrait est coupé au
milieu d'une phrase, ou sa transcription ne dit pas ce que dit l'audio. Le programme a
réécouté l'extrait - redécoupé au besoin, pour qu'il commence et finisse sur des phrases
entières - et te donne ce que la reconnaissance vocale y a entendu. Tu écris la
transcription de CET extrait.

## Ce qu'on te donne

- `Heard` : ce que la reconnaissance vocale a entendu dans l'extrait, un segment reconnu
  par ligne, sans furigana. La reconnaissance entend bien mais écrit mal : elle place mal la
  ponctuation, coupe une phrase en deux ou en colle deux, et écrit un homophone pour un
  autre.
- `Transcript` : la transcription actuelle de la carte, numérotée, en furigana. Elle peut
  couvrir moins ou plus que l'extrait actuel, puisque l'extrait a pu être redécoupé.
- `Translation` : sa traduction française, une ligne par ligne du `Transcript`.
- `Questions` : les questions de l'extrait, numérotées, chacune avec sa réponse et sa ligne
  clé (la ligne de la transcription qui appuie le plus la réponse).

## Ce qu'il faut écrire

- `TranscriptLines` : la transcription de l'extrait tel que `Heard` le donne, de son premier
  mot à son dernier - rien qu'il n'entend pas, rien de ce qu'il entend laissé de côté. Là où
  `Heard` et la transcription actuelle disent la même chose, garde l'écriture de la
  transcription ; là où ils diffèrent, `Heard` dit ce qui a été dit, sauf s'il est
  manifestement absurde. **Une phrase par ligne**, jamais deux. Dans une conversation,
  chaque ligne s'ouvre sur l'étiquette de son locuteur : `A：`, `B：`, `C：` dans l'ordre
  d'apparition, ou un nom ou un rôle que l'audio établit (`店員：`) - la même étiquette pour
  le même locuteur, et jamais un genre deviné d'après une voix que tu n'entends pas. Des
  furigana sur chaque kanji, au format `漢字[かな]` avec un espace ASCII avant chaque groupe
  de kanji : `今日[きょう]は 涼[すず]しい`.
- `TranslationLines` : la traduction française, **exactement une ligne par ligne** de
  `TranscriptLines`, dans le même ordre et avec les mêmes étiquettes.
- `KeyLines` : pour chaque question, par son numéro, le numéro de la ligne de ta
  transcription qui appuie le plus sa réponse.
- `lost` : les numéros des questions que ta transcription n'appuie plus - leur réponse
  était dans une partie que l'extrait ne contient plus. Une liste vide s'il n'y en a pas.

Si la transcription dit déjà exactement ce qui est entendu, ligne pour ligne, réponds
`{"changed": false, "reason": "..."}`.

## Réponse

Réponds UNIQUEMENT en JSON, sans texte autour, avec la `reason` en français :

```json
{
  "changed": true,
  "reason": "l'extrait s'ouvre maintenant sur la première phrase entière",
  "TranscriptLines": ["A： 今日[きょう]は 暑[あつ]いですね。", "B：ええ、 本当[ほんとう]に。"],
  "TranslationLines": ["A : Il fait chaud aujourd'hui, hein ?", "B : Oui, vraiment."],
  "KeyLines": {"1": 1},
  "lost": []
}
```

Les clés sont le protocole : reprends-les exactement telles quelles, sans jamais les
renommer ni les traduire.
