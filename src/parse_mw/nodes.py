"""Immutable MediaWiki values with exact source slices and spans."""

from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .parser import Diagnostic, SourceSpan


@dataclass(frozen=True, kw_only=True)
class Node:
    span: SourceSpan | None = field(default=None, compare=False, repr=False)
    source: str | None = field(default=None, compare=False, repr=False)
    positions: tuple[int, ...] | None = field(default=None, compare=False, repr=False)
    attributes: tuple[tuple[str, str], ...] = ()

    def to_mediawiki(self) -> str:
        return self.source if self.source is not None else self._mediawiki()

    def _mediawiki(self) -> str:
        raise NotImplementedError

    def to_html(self, *, renderer=None, context=None) -> str:
        from .renderers import MediaWikiRenderer, RendererContext
        return (renderer or MediaWikiRenderer()).render(self, context or RendererContext())


@dataclass(frozen=True)
class Text(Node):
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise TypeError("Text requires a string.")

    def _mediawiki(self) -> str:
        return self.value


@dataclass(frozen=True, init=False)
class Container(Node):
    children: tuple[Node, ...]

    def __init__(self, *children, span=None, source=None, positions=None, attributes=()):
        values = tuple(Text(child) if isinstance(child, str) else child for child in children)
        if any(not isinstance(child, Node) for child in values):
            raise TypeError("Children must be MediaWiki nodes or strings.")
        object.__setattr__(self, "children", values)
        object.__setattr__(self, "span", span)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "positions", positions)
        object.__setattr__(self, "attributes", tuple(attributes))

    def content(self) -> str:
        return "".join(child.to_mediawiki() for child in self.children)


@dataclass(frozen=True, init=False)
class Document(Container):
    diagnostics: tuple[Diagnostic, ...] = ()

    def _mediawiki(self) -> str:
        if self.source is not None:
            return self.source
        return "\n\n".join(child.to_mediawiki() for child in self.children)


@dataclass(frozen=True, init=False)
class Fragment(Container):
    def _mediawiki(self) -> str:
        return "".join(child.to_mediawiki() for child in self.children)


@dataclass(frozen=True, init=False)
class Paragraph(Container):
    def _mediawiki(self) -> str:
        return self.content()


@dataclass(frozen=True, init=False)
class Heading(Container):
    level: int

    def __init__(self, level, *children):
        if type(level) is not int or not 1 <= level <= 6:
            raise ValueError("Heading level must be an integer from 1 to 6.")
        super().__init__(*children)
        object.__setattr__(self, "level", level)

    def _mediawiki(self) -> str:
        mark = "=" * self.level
        return f"{mark} {self.content()} {mark}"


@dataclass(frozen=True, init=False)
class Section(Container):
    heading: Heading

    def __init__(self, heading, *children):
        if not isinstance(heading, Heading):
            raise TypeError("A section requires a Heading.")
        super().__init__(*children)
        object.__setattr__(self, "heading", heading)

    def _mediawiki(self) -> str:
        return self.heading.to_mediawiki() + "\n" + "".join(child.to_mediawiki() for child in self.children)


@dataclass(frozen=True, init=False)
class Bold(Container):
    def _mediawiki(self) -> str:
        return "'''" + self.content() + "'''"


@dataclass(frozen=True, init=False)
class Italic(Container):
    def _mediawiki(self) -> str:
        return "''" + self.content() + "''"


@dataclass(frozen=True, init=False)
class BoldItalic(Container):
    def _mediawiki(self) -> str:
        return "'''''"+self.content()+"'''''"


@dataclass(frozen=True)
class Comment(Node):
    value: str
    def _mediawiki(self) -> str:
        return "<!--" + self.value + "-->"


@dataclass(frozen=True)
class Entity(Node):
    value: str
    def _mediawiki(self) -> str:
        return "&"+self.value+";"


@dataclass(frozen=True)
class InternalLink(Container):
    target: str
    anchor: str = ""
    def __init__(self, target, *children, anchor=""):
        super().__init__(*(children or (target,)))
        object.__setattr__(self, "target", target)
        object.__setattr__(self, "anchor", anchor)
    def _mediawiki(self) -> str:
        return "[["+self.target + (("#"+self.anchor) if self.anchor else "") + ("|" + self.content() if self.content() != self.target else "") + "]]"


@dataclass(frozen=True)
class ExternalLink(Container):
    destination: str
    def __init__(self, destination, *children):
        super().__init__(*(children or (destination,)))
        object.__setattr__(self, "destination", destination)
    def _mediawiki(self) -> str:
        return "["+self.destination+" "+self.content()+"]"


@dataclass(frozen=True)
class SectionLink(Node):
    target: str
    label: str = ""
    def _mediawiki(self) -> str:
        return "[["+self.target+("|"+self.label if self.label else "")+"]]"


@dataclass(frozen=True)
class FileLink(Container):
    target: str
    options: tuple[str, ...] = ()
    def __init__(self, target, *children, options=()):
        super().__init__(*children)
        object.__setattr__(self, "target", target)
        object.__setattr__(self, "options", tuple(options))
    def _mediawiki(self) -> str:
        parts=[self.target,*self.options,*[child.to_mediawiki() for child in self.children]]
        return "[["+("|".join(parts))+"]]"


@dataclass(frozen=True)
class Template(Node):
    name: str
    arguments: tuple[tuple[str, str], ...] = ()
    def _mediawiki(self) -> str:
        parts=[self.name]+[("=" .join(pair) if pair[0] else pair[1]) for pair in self.arguments]
        return "{{"+("|".join(parts))+"}}"


@dataclass(frozen=True)
class Tag(Container):
    name: str
    def __init__(self, name, *children):
        super().__init__(*children)
        object.__setattr__(self, "name", name)
    def _mediawiki(self) -> str:
        return "<"+self.name+">"+self.content()+"</"+self.name+">"


@dataclass(frozen=True)
class Nowiki(Node):
    value: str
    def _mediawiki(self) -> str:
        return "<nowiki>"+self.value+"</nowiki>"


@dataclass(frozen=True)
class Math(Node):
    value: str
    def _mediawiki(self) -> str:
        return "<math>"+self.value+"</math>"


@dataclass(frozen=True)
class Pre(Node):
    value: str
    def _mediawiki(self) -> str:
        return "<pre>"+self.value+"</pre>"


@dataclass(frozen=True)
class Code(Node):
    value: str
    def _mediawiki(self) -> str:
        return "<code>"+self.value+"</code>"


@dataclass(frozen=True)
class Reference(Node):
    name: str = ""
    value: str = ""
    def _mediawiki(self) -> str:
        attrs = (" name=" + repr(self.name) if self.name else "")
        return "<ref"+attrs+">"+self.value+"</ref>" if self.value or not self.name else "<ref name="+repr(self.name)+" />"


@dataclass(frozen=True)
class Category(Node):
    name: str
    sort_key: str = ""
    def _mediawiki(self) -> str:
        return "[[Category:"+self.name+(("|"+self.sort_key) if self.sort_key else "")+"]]"


@dataclass(frozen=True)
class TableCell(Container):
    header: bool = False
    def __init__(self, *children, header=False):
        super().__init__(*children)
        object.__setattr__(self, "header", header)
    def _mediawiki(self) -> str:
        return ("!" if self.header else "| ") + self.content()


@dataclass(frozen=True, init=False)
class TableRow(Container):
    def _mediawiki(self) -> str:
        return "|-\n" + "\n".join(child.to_mediawiki() for child in self.children)


@dataclass(frozen=True, init=False)
class Table(Container):
    caption: str = ""
    def __init__(self, *rows, caption=""):
        if any(not isinstance(row, TableRow) for row in rows):
            raise TypeError("Tables contain TableRow values.")
        super().__init__(*rows)
        object.__setattr__(self, "caption", caption)
    def _mediawiki(self) -> str:
        body=("|+"+self.caption+"\n") if self.caption else ""
        return "{|\n"+body+"\n".join(row.to_mediawiki() for row in self.children)+"\n|}"


@dataclass(frozen=True, init=False)
class ListItem(Container):
    def _mediawiki(self) -> str:
        return "".join(child.to_mediawiki() for child in self.children)


@dataclass(frozen=True, init=False)
class BulletList(Container):
    def __init__(self, *items):
        super().__init__(*(item if isinstance(item, ListItem) else ListItem(item) for item in items))
    def _mediawiki(self) -> str:
        return "\n".join("* "+item.to_mediawiki() for item in self.children)


@dataclass(frozen=True, init=False)
class OrderedList(Container):
    def __init__(self, *items):
        super().__init__(*(item if isinstance(item, ListItem) else ListItem(item) for item in items))
    def _mediawiki(self) -> str:
        return "\n".join("# "+item.to_mediawiki() for item in self.children)


@dataclass(frozen=True)
class HorizontalRule(Node):
    def _mediawiki(self) -> str:
        return "----"
