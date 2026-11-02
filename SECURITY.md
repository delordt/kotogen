# Security

## Reporting a vulnerability

Do not open a public issue for a vulnerability. Report it privately through
GitHub: the **Security** tab of the repository, then **Report a
vulnerability**. Only the maintainer sees what you write there, and the fix is
prepared in a private advisory until it is published.

Kotogen is maintained by one person, in their own time. A report is read as
soon as possible, and you get an answer once the problem has been reproduced,
or an explanation of why it could not be.

### Encrypting the report

The advisory is private, but GitHub can read it. To make the report readable by
the maintainer alone, encrypt it with [age](https://github.com/FiloSottile/age)
to the SSH key of the maintainer's GitHub account, and paste the result into the
report:

```bash
curl -s -o delordt.keys https://github.com/delordt.keys
age -R delordt.keys -a -o report.age report.md
```

`-a` writes the encrypted report as text, from a
`-----BEGIN AGE ENCRYPTED FILE-----` line to its `END` line, which the form
accepts as it is. On Windows, type `curl.exe`: in Windows PowerShell, `curl` is
an alias for `Invoke-WebRequest`. Install age with
`winget install --id FiloSottile.age`, `brew install age`, or the package
manager of most Linux distributions.

There is no fingerprint to compare: the key comes from GitHub itself, over
HTTPS, and belongs to the account that owns the repository. Encrypting to an
SSH key writes a short tag of that public key into the file, so the file shows
who it is for, but not what it says.

## What counts

Kotogen runs on your machine, with your API key and your Anki collection, and
reads what you point it at on the web. A vulnerability is a way for someone
other than you to turn that against you:

- an API key read from anywhere but your environment and kotogen's own
  settings files, written anywhere but the file kotogen keeps keys in (the
  `.env` at the root of the repository, or `secrets.env`, mode `0600`), or sent
  anywhere but the provider it belongs to;
- text from a source (a page, a feed, subtitles, a PDF) or from a model that
  reaches a card as HTML or as script;
- `ask` or `maintain` led to read or change notes outside the decks they are
  given, or to delete a note without being asked;
- the local preview server answering a page other than its own;
- a file on your machine read and sent somewhere you did not ask for, or a file
  written outside the folders the program announces;
- a command run, or a package installed, on the word of anything but your own
  settings and your own command line.

What does not count, and where to report it instead:

- a flaw in Anki, AnkiConnect, yt-dlp, FFmpeg, Playwright or a model provider
  itself: report it to that project. How kotogen uses them is in scope;
- a model that answers wrong, or that a page talks into writing a wrong card.
  The program keeps what a model writes from running on a card or reaching
  notes it was not given, but it cannot make the model right. That is a bug:
  report it in an issue.

## Supported versions

Only the latest version is supported: no older release is maintained beside
it. Kotogen is installed from its repository and updated with
`kotogen update`. A fix lands on the default branch, and the version to run is
the latest one there.

## Once it is fixed

The advisory is published with the fix, and the change gets its line under
**Security** in the [changelog](CHANGELOG.md). The reporter is credited there,
unless they would rather not be named.
