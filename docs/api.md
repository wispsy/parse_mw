# Parser and rendering contract

`parse(source, options=ParseOptions())` and `parse_document(source, options=...)`
return immutable `Document` nodes. `parse_fragment(source, options=...)` returns
a `Fragment`. `parse_sections(source, options=...)` groups heading-led content
into `Section` nodes.

Every node may carry exact original `source`, a half-open code-point `span`,
and source code-point positions. `Node.to_mediawiki()` uses original source
when attached; constructed nodes serialize in MediaWiki syntax.

The immutable public node types cover text, bold/italic, comments, entities,
internal/external/section/file links, templates, headings, sections, tables,
lists, code/pre/math/nowiki, tags, references and categories.

Defaults are 2,000,000 source characters, 100,000 nodes and 64 nesting levels.
Lower limits are supported. A limit failure raises `ParseLimitError` containing
a `Diagnostic` and source span; no partial document is returned.

`MediaWikiRenderer`/`Node.to_html()` escape raw HTML and text by default.
`RendererContext(trust="trusted")` permits explicit tag rendering but is not
sanitization. Internal and file links use caller callbacks:

| Callback | Arguments | Result |
| --- | --- | --- |
| resolver | target, source_path | URL string or None |
| file_resolver | target, source_path | URL string or None |
| node_handlers | node, context | caller-owned HTML text |

`render(source, context=..., options=...)` returns `RenderedMediaWiki` with
HTML, heading metadata and category names. Unsafe URL schemes, controls,
backslashes and protocol-relative URLs are not emitted.
