# Source provenance

`parse-mw` is an original implementation for wispsy/parse_mw. It has no
runtime dependencies and does not import or copy the implementations of
parse_md or parse_html5.

The package API follows the wispsy package conventions established by those
projects: immutable typed nodes, exact source slices and spans, explicit
bounded parser options, and typed HTML rendering with caller-owned callbacks.
Generic package metadata, workflow structure and distribution checks are
adapted to this repository.
