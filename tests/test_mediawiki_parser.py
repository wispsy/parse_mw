from dataclasses import FrozenInstanceError

import pytest

import parse_mw
from parse_mw import (
    Bold, BoldItalic, Category, Comment, Entity, ExternalLink, FileLink,
    Heading, InternalLink, Italic, ParseLimitError, ParseOptions,
    Reference, Table, Template, Text, parse, parse_fragment, parse_sections,
)


def test_full_inline_feature_round_trip():
    source = ("== Heading ==\n\n"
              "'''bold''' ''italic'' '''''both''''' [[Target|label]] "
              "[https://example.com example] {{Infobox|a=1}} "
              "<nowiki>[[literal]]</nowiki> &amp; <!--note--> "
              "<ref name=\"one\">citation</ref> [[Category:Example|K]]")
    document = parse(source)
    assert document.to_mediawiki() == source
    html = document.to_html()
    assert "<strong>bold</strong>" in html
    assert "<em>italic</em>" in html
    assert "<strong><em>both</em></strong>" in html
    assert 'href="/wiki/Target"' in html
    assert "citation" in html
    assert "Example" not in html


def test_nodes_links_templates_comments_entities_and_references():
    document = parse("{{T|x=1}} <!--x--> &amp; [[A#Section|A]] [https://example.org link]")
    kinds = {type(node).__name__ for node in document.children[0].children}
    assert {"Template", "Comment", "Entity", "SectionLink", "ExternalLink"} <= kinds
    assert Category("Example").to_mediawiki() == "[[Category:Example]]"
    assert Template("T", (("x", "1"),)).to_mediawiki() == "{{T|x=1}}"
    assert Reference("one", "text").to_mediawiki().startswith("<ref")


def test_table_list_heading_and_sections():
    source = ("== One ==\nText\n\n* one\n* [[two]]\n\n"
              "# first\n# second\n\n{| class=\"wikitable\"\n|- \n! A !! B\n|- \n| 1 || 2\n|}")
    document = parse(source)
    assert document.to_mediawiki() == source
    assert any(isinstance(child, Heading) for child in document.children)
    assert any(type(child).__name__ == "BulletList" for child in document.children)
    assert any(type(child).__name__ == "OrderedList" for child in document.children)
    assert any(isinstance(child, Table) for child in document.children)
    sections = parse_sections(source)
    assert len(sections) == 1
    assert sections[0].heading.level == 2


def test_fragment_document_and_exact_source_spans():
    source = "== Héading ==\r\n\r\n'''bold'''\r\n"
    document = parse(source)
    fragment = parse_fragment(source)
    assert fragment.to_mediawiki() == source
    assert document.to_mediawiki() == source
    for node in (document, *document.children):
        if node.span is not None:
            assert 0 <= node.span.start <= node.span.end <= len(source)
    heading = next(child for child in document.children if isinstance(child, Heading))
    assert heading.source == "== Héading ==\r\n"
    with pytest.raises(FrozenInstanceError):
        document.source = "changed"


@pytest.mark.parametrize("source,options,code", [
    ("x" * 101, ParseOptions(max_characters=100), "character-limit"),
    ("{{" * 20 + "x", ParseOptions(max_nesting=2), "nesting-limit"),
    ("plain", ParseOptions(max_nodes=1), "node-limit"),
])
def test_limits_fail_without_partial_output(source, options, code):
    with pytest.raises(ParseLimitError) as error:
        parse(source, options=options)
    assert error.value.diagnostic.code == code
