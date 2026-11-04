# Changelog

What changes from one release of kotogen to the next. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the versions follow
[Semantic Versioning](https://semver.org/).

A release may add a field or a card to a note type, never rename or remove one:
`kotogen deck install` creates what is missing in a collection that already
holds notes, and a rename would leave the content of the old field behind. Each
such change is listed under its own **Note types** heading, with what
`deck install` does about it.

## [Unreleased]

### Added

- A past-paper card with a figure is answered by the label the figure prints
  (`3`, `ウ`, `アウエ`), and a figure cut out for another item goes on no card:
  the figure goes with the call that writes the cards, which takes a model
  that reads images.

### Changed

- In automatic mode, the purple flag no longer names the other cards of a
  passage before the line that counts them.

### Fixed

- A past-paper card no longer holds the time given to read the options, nor
  the bell that closes it, when Whisper laid the first word of the
  conversation inside that blank: the sound opened ten seconds before the
  voice.
- The purple flag cuts out of a past-paper card the reading time and the bell
  left inside its extract, and lays its `Timecodes` again.
- The purple flag no longer cuts again in one span an extract made of pieces,
  which would have put back the exam question left out between them: such an
  extract is heard as it stands.
- The purple flag finds the recording of an extract whose name Anki
  lowercased.
- The figures of a scanned booklet no longer shift by one item when its
  reading numbers the example 「れい」 as item 1, and two figures claiming one
  item leave their section without any. A booklet read before is read again
  once.
- A text written on the deck no longer reports a する verb of the deck as left
  out when it uses it conjugated (運転して, 検討しています): the word counts as
  worked on, and no longer comes back as a target of the next texts.

## [1.0.0] - 2026-11-02

The first public release.

[Unreleased]: https://github.com/delordt/kotogen/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/delordt/kotogen/releases/tag/v1.0.0
