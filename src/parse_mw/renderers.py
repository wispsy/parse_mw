"""Safe typed HTML rendering for the MediaWiki AST."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape, unescape
import re
from typing import Literal
from urllib.parse import quote, unquote, urlsplit

from .nodes import (
    Bold, BoldItalic, BulletList, Category, Code, Comment, Container, Document,
    Entity, ExternalLink, FileLink, Fragment, Heading, HorizontalRule,
    InternalLink, Italic, Math, Node, Nowiki, OrderedList, Paragraph, Pre,
    Reference, Section, SectionLink, Table, TableCell, TableRow, Tag, Template,
    Text,
)


@dataclass(frozen=True)
class RendererContext:
    source_path: str | None = None
    trust: Literal["escape", "trusted"] = "escape"
    resolver: object | None = None
    file_resolver: object | None = None
    node_handlers: tuple = ()

    def __post_init__(self) -> None:
        if self.trust not in {"escape", "trusted"}:
            raise ValueError("Unknown HTML trust policy.")
        if self.source_path is not None and not isinstance(self.source_path, str):
            raise TypeError("Source path must be a string or None.")
        handlers = tuple(self.node_handlers.items()) if isinstance(self.node_handlers, dict) else tuple(self.node_handlers)
        seen = set()
        for kind, handler in handlers:
            if not isinstance(kind, type) or not issubclass(kind, Node) or not callable(handler) or kind in seen:
                raise ValueError("Register each node renderer type once with a callable.")
            seen.add(kind)
        object.__setattr__(self, "node_handlers", handlers)
        for selected in (self.resolver, self.file_resolver):
            if selected is not None and not callable(selected):
                raise TypeError("Context adapters must be callable.")


@dataclass(frozen=True)
class HeadingInfo:
    level: int
    title: str
    identifier: str
    span: object | None = None


@dataclass(frozen=True)
class RenderedMediaWiki:
    html: str
    headings: tuple[HeadingInfo, ...] = ()
    categories: tuple[str, ...] = ()


class MediaWikiRenderer:
    def render(self, node: Node, context: RendererContext | None = None) -> str:
        return self.render_document(node, context).html

    def render_document(self, node: Node, context: RendererContext | None = None) -> RenderedMediaWiki:
        context = context or RendererContext()
        headings: list[HeadingInfo] = []
        categories: list[str] = []

        def text(value: str) -> str:
            return escape(value, quote=False).replace('"', "&quot;")

        def safe_url(value: str) -> str:
            decoded = unquote(unescape(value)).strip()
            if any(ord(char) < 32 or ord(char) == 127 for char in decoded) or "\\" in decoded:
                return ""
            scheme = urlsplit(decoded).scheme.casefold()
            if scheme not in {"", "http", "https", "mailto"} or decoded.startswith("//"):
                return ""
            return text(quote(value, safe="/:?#@!$&'()*+,;=%-._~"))

        def plain(value: Node) -> str:
            if isinstance(value, Text):
                return value.value
            if isinstance(value, Entity):
                return unescape("&"+value.value+";")
            if isinstance(value, Container):
                return "".join(plain(child) for child in value.children)
            return value.to_mediawiki()

        def custom(current: Node):
            for kind, handler in context.node_handlers:
                if isinstance(current, kind):
                    value = handler(current, context)
                    if not isinstance(value, str):
                        raise TypeError("Node handlers must return HTML text.")
                    return value
            return None

        def inline(current: Node) -> str:
            selected = custom(current)
            if selected is not None:
                return selected
            if isinstance(current, Text):
                return text(current.value)
            if isinstance(current, Comment):
                return ""
            if isinstance(current, Entity):
                try:
                    if current.value.startswith("#x"):
                        return text(chr(int(current.value[2:], 16)))
                    if current.value.startswith("#"):
                        return text(chr(int(current.value[1:], 10)))
                except (ValueError, OverflowError):
                    pass
                return text(unescape("&"+current.value+";"))
            if isinstance(current, BoldItalic):
                return "<strong><em>" + "".join(inline(child) for child in current.children) + "</em></strong>"
            if isinstance(current, Bold):
                return "<strong>" + "".join(inline(child) for child in current.children) + "</strong>"
            if isinstance(current, Italic):
                return "<em>" + "".join(inline(child) for child in current.children) + "</em>"
            if isinstance(current, InternalLink):
                label = "".join(inline(child) for child in current.children)
                href = "#" + quote(current.anchor) if current.anchor else "/wiki/" + quote(current.target.replace(" ", "_"), safe="/:")
                resolved = None
                if context.resolver is not None:
                    resolved = context.resolver(current.target, context.source_path)
                    if resolved is not None and not isinstance(resolved, str):
                        raise TypeError("Resolvers must return a URL string or None.")
                    href = resolved or href
                return '<a href="' + safe_url(href) + '">' + label + "</a>"
            if isinstance(current, SectionLink):
                return '<a href="#' + quote(current.target.removeprefix("#")) + '">' + text(current.label or current.target) + "</a>"
            if isinstance(current, ExternalLink):
                href = safe_url(current.destination)
                label = "".join(inline(child) for child in current.children)
                return '<a rel="nofollow" href="' + href + '">' + (label or text(current.destination)) + "</a>" if href else label
            if isinstance(current, FileLink):
                selected = None
                if context.file_resolver is not None:
                    selected = context.file_resolver(current.target, context.source_path)
                    if selected is not None and not isinstance(selected, str):
                        raise TypeError("File resolvers must return a URL string or None.")
                if selected:
                    return '<img src="' + safe_url(selected) + '" alt="' + text(current.target) + '" />'
                return text(current.to_mediawiki())
            if isinstance(current, Template):
                return text(current.to_mediawiki())
            if isinstance(current, Nowiki):
                return text(current.value)
            if isinstance(current, Code):
                return "<code>" + text(current.value) + "</code>"
            if isinstance(current, Pre):
                return "<pre>" + text(current.value) + "</pre>"
            if isinstance(current, Math):
                return "<math>" + text(current.value) + "</math>"
            if isinstance(current, Reference):
                content = text(current.value)
                name = ' name="' + text(current.name) + '"' if current.name else ""
                return "<sup><ref"+name+">"+content+"</ref></sup>" if content or current.name else "<ref />"
            if isinstance(current, Category):
                if current.name not in categories:
                    categories.append(current.name)
                return ""
            if isinstance(current, Tag):
                allowed = {"b", "i", "s", "u", "small", "big", "span"}
                if context.trust == "trusted" or current.name.lower() in allowed:
                    name = current.name if re.fullmatch(r"[A-Za-z][A-Za-z0-9-]*", current.name) else "span"
                    content = "".join(inline(child) for child in current.children)
                    return "<"+name+">"+content+"</"+name+">"
                return text(current.to_mediawiki())
            if isinstance(current, Container):
                return "".join(inline(child) for child in current.children)
            return text(current.to_mediawiki())

        def slugify(value: str) -> str:
            value = re.sub(r"<[^>]+>", "", value)
            value = re.sub(r"[^\w\- ]", "", value, flags=re.UNICODE).strip().lower()
            return re.sub(r"\s+", "-", value) or "section"

        def block(current: Node, tight: bool = False) -> str:
            selected = custom(current)
            if selected is not None:
                return selected
            if isinstance(current, Heading):
                title = plain(current)
                identifier = slugify(title)
                headings.append(HeadingInfo(current.level, title, identifier, current.span))
                return "<h"+str(current.level)+' id="'+text(identifier)+'">'+ "".join(inline(child) for child in current.children)+"</h"+str(current.level)+">\n"
            if isinstance(current, Section):
                return block(current.heading) + "".join(block(child) for child in current.children)
            if isinstance(current, Paragraph):
                content = "".join(inline(child) for child in current.children)
                return content+"\n" if tight else "<p>"+content+"</p>\n"
            if isinstance(current, BulletList):
                return "<ul>\n"+"".join("<li>"+block(child, True).strip()+"</li>\n" for child in current.children)+"</ul>\n"
            if isinstance(current, OrderedList):
                return "<ol>\n"+"".join("<li>"+block(child, True).strip()+"</li>\n" for child in current.children)+"</ol>\n"
            if isinstance(current, Table):
                def row(table_row: TableRow):
                    cells = "".join(
                        "<th>"+"".join(inline(child) for child in cell.children)+"</th>\n"
                        if cell.header else
                        "<td>"+"".join(inline(child) for child in cell.children)+"</td>\n"
                        for cell in table_row.children
                        if isinstance(cell, TableCell)
                    )
                    return "<tr>\n"+cells+"</tr>\n"
                caption = "<caption>"+text(current.caption)+"</caption>\n" if current.caption else ""
                return "<table>\n"+caption+"".join(row(child) for child in current.children)+"</table>\n"
            if isinstance(current, HorizontalRule):
                return "<hr />\n"
            if isinstance(current, Comment):
                return ""
            if isinstance(current, (Document, Fragment)):
                return "".join(block(child) for child in current.children)
            if isinstance(current, Container):
                return "".join(inline(child) for child in current.children)+"\n"
            return text(current.to_mediawiki())+"\n"

        rendered = block(node)
        return RenderedMediaWiki(rendered.removesuffix("\n"), tuple(headings), tuple(categories))


TypedRenderer = MediaWikiRenderer


def render(source: str, *, context: RendererContext | None = None, options=None) -> RenderedMediaWiki:
    from .parser import parse
    return MediaWikiRenderer().render_document(parse(source, options=options), context)
