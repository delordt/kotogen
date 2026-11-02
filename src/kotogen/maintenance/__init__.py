"""Looking after cards already made: what to propose for each, and nothing more.

Its modules hold which question to ask the model about a card and what of the
answer holds, on cards shaped as `{"id", "fields", "tags"}`; they read and write
no collection. `kotogen maintain` puts them to work on the Anki deck
(`kotogen.anki.maintain`), `kotogen rework` on a JSON Lines file
(`kotogen.rework`). The package itself is cheap to import, for the parser and
the dialogue; its modules bring the AI client.
"""

# The tag that marks a leech, and the interval (in days) past which a card is
# mature and no longer one, whatever the tag says. The defaults of `--tag` and
# `--mature-ivl`, shared with the count the dialogue shows first
# (`interactive.maintain._maintain_counts`) so that both use one threshold.
DEFAULT_TAG = "leech"
IVL_MATURE = 21

# What `kotogen rework` can be asked to do to a file of cards, none of it needing
# a flag. Named here for the parser, built at every launch.
TASKS = ("simplify", "reading", "leech", "derive")
