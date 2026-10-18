# Repository language

This fork uses English for documentation, comments, logs, UI labels, examples,
and developer tooling. Vendor model IDs, protocol fields, device IDs, service
names, and entity unique IDs retain their existing meaning.

Chinese text is permitted only when removing it would break compatibility or
remove a test of real vendor input. Examples include recognizing a vendor's
localized device names and classifying notifications received from the hub.
These are input values, not untranslated UI labels.

Every permitted line is listed in `english-language-exceptions.json` by file
and SHA-256, with an English explanation. This makes additions and changes
reviewable without granting a blanket exemption to an entire file.

Run the same check used by CI:

```bash
python tools/check_english.py
```

Translate new text instead of escaping Chinese characters as Unicode sequences.
Do not remove compatibility checks, discard captured protocol fixtures, or
weaken test coverage solely to make the language check pass.

The retained `zh-Hans.json` locale file deliberately contains the English
strings, so existing locale selection continues to resolve the same schema.
Product catalog descriptions are translated; all catalog identity keys and
record counts remain unchanged.
