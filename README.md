# parse-mw

Bounded, source-preserving MediaWiki parsing and safe typed HTML rendering.
Python 3.14+, with no runtime dependencies.

```sh
python -m pip install parse-mw
```

```python
from parse_mw import parse, render

document = parse("== Heading ==\n\nHello '''bold''' [[Target|label]].")
assert document.to_mediawiki().startswith("== Heading ==")
assert "<strong>bold</strong>" in document.to_html()

result = render("{{Infobox|name=Example}}\n\n{| class=\"wikitable\"\n|-\n! A !! B\n|-\n| 1 || 2\n|}")
assert "<table>" in result.html
```

The parser preserves original source text and half-open code-point spans.
Documents and fragments expose immutable dataclass nodes for text, sections,
headings, lists, templates, tables, links, references, categories and MediaWiki
literal constructs. Unknown syntax remains source-preserving text.

HTML is escaped by default. `RendererContext(trust="trusted")` permits explicit
raw tags, but it is not sanitization. Links, file URLs and custom node output
are handled through caller-owned callbacks.

See [the API contract](docs/api.md). Defaults are 2,000,000 characters,
100,000 nodes and 64 nesting levels; limits fail explicitly with diagnostics
and never return partial documents.

Development and distribution qualification:

```sh
uv sync --locked
uv run --frozen python -m pytest
uv run --frozen python scripts/check_distribution.py --output-dir /tmp/parse-mw-candidate
```

`release.yaml` uses the `pypi` environment and verifies tag/version/main before
publication through Trusted Publishing.
