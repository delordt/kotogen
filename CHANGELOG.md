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

### Fixed

- A past-paper card no longer holds the time given to read the options, nor
  the bell that closes it, when Whisper laid the first word of the
  conversation inside that blank: the sound opened ten seconds before the
  voice.

## [1.0.0] - 2026-11-02

The first public release.

[Unreleased]: https://github.com/delordt/kotogen/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/delordt/kotogen/releases/tag/v1.0.0
