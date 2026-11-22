from dataclasses import FrozenInstanceError

import pytest

from parse_mw import (
    Bold, Document, Heading, InternalLink, Paragraph, RendererContext, Text,
)


def test_nested_builders_are_deterministic_and_immutable():
    document = Document(Heading(2, "Example"), Paragraph("A ", Bold("bold"), " value."),
                        InternalLink("Target", "label"))
    assert document.to_mediawiki() == "== Example ==\n\nA '''bold''' value.\n\n[[Target|label]]"
    assert "<strong>bold</strong>" in document.to_html()
    assert document.to_html() == document.to_html()
    with pytest.raises(FrozenInstanceError):
        document.children = ()


def test_text_and_invalid_renderer_context_are_safe():
    document = Document(Paragraph("<script>x</script> '''safe'''"))
    assert "<script>" not in document.to_html()
    assert "&lt;script&gt;" in document.to_html()
    assert isinstance(Text("x"), Text)
    with pytest.raises(ValueError):
        RendererContext(trust="other")
