**Context : ce qui départage deux mots de même traduction.** Plusieurs mots japonais
partagent une traduction : 着る, 被る et 履く se traduisent tous « Porter ». La carte
`Production` ne montre que « Porter » : la question a trois réponses justes, et le Context
est ce qui manque pour qu'elle n'en ait plus qu'une. Il s'affiche avec la question, sous la
traduction : il aide à retrouver le mot japonais, jamais ne le donne.

- Il répond à « **lequel ?** », jamais à « ça veut dire quoi ? ». Syntagme nominal de 1 à 4
  mots, sans verbe conjugué ni phrase. OUI `Porter` + *haut du corps* (着る) / *sur la
  tête* (被る). NON *mettre un vêtement sur le torse* : une définition redonne la réponse.
- Rempli UNIQUEMENT si le mot a un rival de même traduction. Sinon `""`. Parmi les rivaux,
  la carte la plus ordinaire reste sans Context : ce que portent les autres la désigne
  (`Sang` : 血 nu, 血液 *terme médical*). Jamais deux cartes d'un lot sans rien pour les
  départager, jamais deux Context identiques.
- **Jamais de précision entre parenthèses dans la Translation** (« Couler (liquide) ») :
  c'est un Context qui ne dit pas son nom. Elle va dans le Context si le mot a un rival, et
  nulle part sinon.
- Ce qui départage bien : un domaine (*terme médical*), une restriction d'emploi (*pour les
  êtres animés*), la transitivité, un emprunt face au mot japonais (*emprunt*), un emploi
  figuré. Jamais un mot qui irait à n'importe quelle carte (*terme courant*, *standard*,
  *neutre*) : il n'apprend rien.
- **Un registre ne s'écrit jamais seul** (*formel*, *familier*, *soutenu*) : il ne dit pas
  par rapport à quoi. Quand c'est lui qui départage le mot d'un rival de même traduction,
  le Context le dit en nommant l'autre : 航空機 *plus soutenu que 飛行機*. Quand deux
  cartes s'écrivent pareil, l'autre se nomme par sa lecture : *plus familier que
  しおからい*.
  NON *terme formel*, *terme familier*, *registre soutenu*, *forme polie* : 食物 → *plus
  soutenu que 食べ物*, 風呂屋 → *plus familier que 銭湯*. Un registre RESTREINT est en
  plus un tag (voir plus bas), et son badge s'affiche au verso, avec la réponse : la
  question ne le voit pas, et un mot qu'il est seul à départager garde donc son Context.
  召し上がる `Manger` avec `Register::敬語::尊敬語` → *honorifique de 食べる*.
- Deux mots qui ne veulent pas dire la même chose ne se comparent pas par le registre :
  文章 est un texte, 文 une phrase. Leur différence est le sens, et c'est la traduction qui
  la porte.

**Notes : vides par défaut**, et c'est le cas de la plupart des cartes. Elles se lisent
après la réponse, à chaque révision. Une Note ne s'écrit que si elle apprend ce que la
traduction, le Context et le badge ne disent pas, pour l'une de ces raisons :
- une réalité que la traduction ne fait pas connaître : `Yukata` → *Kimono d'été en coton* ;
- un second sens que la traduction cache : 下ろす `Descendre` → *Aussi : retirer (de
  l'argent)* ;
- un piège d'emploi : 全然 `Pas du tout` → *Familier : peut aussi renforcer une
  affirmation* ; une comparaison qui nomme un mot : *≠ 赤ちゃん*.

JAMAIS : une définition qui redit la traduction (`Retenir` → *Empêcher quelqu'un de
partir*), ce que dit déjà le Context ou le badge (badge 口 et *Familier*), ce que la
traduction contient (`Pas du tout` → *S'emploie avec une négation*), une étiquette
grammaticale que les Tags portent. Un mot japonais qu'une Note nomme (*≠ 行く*, *de
どちら*) se garde : il dit à quel mot se mesurer. Une ligne, 50 caractères environ.

**Registre, locuteur, dialecte : des tags**, seulement quand l'emploi du mot est RESTREINT
à cet usage. Un mot qui sert dans tous les registres, pour tout le monde et partout n'en
porte aucun, et c'est le cas de la plupart :
- `Register::敬語::尊敬語` honorifique (いらっしゃる) | `Register::敬語::謙譲語` humble (参る,
  拝見) | `Register::丁寧語` poli par nature (ございます)
- `Register::改まった語` formel, raide dans une conversation ordinaire (友人, 本日) |
  `Register::文章語` écrit ou littéraire (即ち) | `Register::口語` familier (やっぱ) |
  `Register::俗語` argot | `Register::蔑称` péjoratif | `Register::古語` vieilli (便所)
- `Speaker::男性語` (俺, 僕) | `Speaker::女性語` (あたし)
- `Dialect::関西弁` (ほんまに)

Un tag de registre est un tag à part, séparé des autres par une espace, jamais accroché à
un autre : `Verb::五段動詞 Register::敬語::尊敬語`, pas `Verb::五段動詞::Register::敬語::尊敬語`.
Un mot peut en porter deux : 俺 a `Register::口語` et `Speaker::男性語`. Trois tests avant
d'en poser un, parce que ce sont eux qu'on pose à tort :
- `Register::改まった語` ou `Register::文章語` : un Japonais le dirait-il à un ami sans que
  ça sonne guindé ou écrit ? Si oui, aucun tag. 危険, 準備, 女性, 機会, 行う, 朝食 sont
  des mots sino-japonais ordinaires, pas un registre.
- `Register::口語` : le mot sonnerait-il déplacé dans une lettre ou devant un supérieur ?
  Si non, aucun tag. みんな, さっき, つもり, 久しぶり n'en ont pas. Un mot dont UN SEUL
  emploi est familier n'a pas le tag : 全然 se dit partout avec une négation, et son emploi
  affirmatif familier est une Note.
- `Register::蔑称` est un terme qui insulte ou rabaisse quelqu'un (貧乏人), pas un mot au
  sens négatif (くだらない, 理屈).
