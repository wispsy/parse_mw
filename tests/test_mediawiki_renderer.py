import subprocess
import sys
from dataclasses import dataclass

import pytest

from parse_mw import (
    Document, Node, Paragraph, RendererContext, render,
)


def test_rendered_metadata_and_html_escaping():
    result = render("== Hello ==\n\n&copy; [[Target|label]] [[Category:Docs]]")
    assert result.headings[0].identifier == "hello"
    assert result.categories == ("Docs",)
    assert "&copy;" not in result.html
    assert "©" in result.html
    assert 'href="/wiki/Target"' in result.html


def test_resolvers_and_custom_nodes_are_explicit():
    calls = []
    context = RendererContext(
        source_path="source.mw",
        resolver=lambda target, path: calls.append((target, path)) or "/resolved",
        file_resolver=lambda target, path: "/files/" + target,
    )
    result = render("[[Target]] [[File:Diagram.png|thumb]]", context=context)
    assert calls == [("Target", "source.mw")]
    assert 'href="/resolved"' in result.html
    assert 'src="/files/Diagram.png"' in result.html


@dataclass(frozen=True)
class Badge(Node):
    value: str

    def _mediawiki(self):
        return ":" + self.value + ":"


def test_custom_node_handler_is_copied_and_strict():
    from html import escape
    handlers = {Badge: lambda node, context: "<b>" + escape(node.value) + "</b>"}
    context = RendererContext(node_handlers=handlers)
    handlers.clear()
    document = Document(Paragraph(Badge("<safe>")))
    assert document.to_html(context=context) == "<p><b>&lt;safe&gt;</b></p>"
    with pytest.raises(TypeError):
        document.to_html(context=RendererContext(node_handlers={Badge: lambda node, context: 42}))


def test_import_has_no_optional_dependencies():
    subprocess.run([
        sys.executable, "-I", "-c",
        "import sys, parse_mw; "
        "assert not {'fastapi','pydantic','requests','markdown','beautifulsoup4'}"
        ".intersection(sys.modules)",
    ], check=True)
