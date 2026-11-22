"""Bounded, source-preserving MediaWiki block and inline parsing."""

from __future__ import annotations

import bisect
import html
import re
from dataclasses import dataclass

from .nodes import (
    Bold, BoldItalic, BulletList, Category, Code, Comment, Document, Entity,
    ExternalLink, FileLink, Fragment, Heading, HorizontalRule, InternalLink,
    Italic, Math, Nowiki, OrderedList, Paragraph, Pre, Reference, Section,
    SectionLink, Table, TableCell, TableRow, Tag, Template, Text,
)


@dataclass(frozen=True)
class SourceSpan:
    start: int
    end: int
    start_line: int
    start_column: int
    end_line: int
    end_column: int


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    span: SourceSpan
    severity: str = "info"


class ParseLimitError(ValueError):
    def __init__(self, diagnostic: Diagnostic):
        self.diagnostic = diagnostic
        super().__init__(diagnostic.message)


@dataclass(frozen=True)
class ParseOptions:
    max_characters: int = 2_000_000
    max_nesting: int = 64
    max_nodes: int = 100_000

    def __post_init__(self) -> None:
        for value in (self.max_characters, self.max_nesting, self.max_nodes):
            if type(value) is not int or value < 1:
                raise ValueError("Parser limits must be positive integers.")
        if self.max_nesting > 64:
            raise ValueError("Maximum supported nesting limit is 64.")


class _SourceMap:
    def __init__(self, source: str):
        self.source = source
        self.starts = [0, *(m.end() for m in re.finditer(r"\r\n|\r|\n", source))]

    def span(self, start: int, end: int) -> SourceSpan:
        left = bisect.bisect_right(self.starts, start) - 1
        right = bisect.bisect_right(self.starts, end) - 1
        left = max(0, left)
        right = max(0, right)
        return SourceSpan(start, end, left + 1, start - self.starts[left] + 1,
                          right + 1, end - self.starts[right] + 1)


class _Parser:
    def __init__(self, source: str, options: ParseOptions):
        self.source = source
        self.options = options
        self.mapping = _SourceMap(source)
        self.count = 0
        self.diagnostics: list[Diagnostic] = []

    def fail(self, code: str, message: str, start: int = 0, end: int | None = None) -> None:
        span = self.mapping.span(start, len(self.source) if end is None else end)
        raise ParseLimitError(Diagnostic(code, message, span, "error"))

    def locate(self, node, start: int, end: int):
        self.count += 1
        if self.count > self.options.max_nodes:
            self.fail("node-limit", "MediaWiki node limit exceeded.", start, end)
        object.__setattr__(node, "span", self.mapping.span(start, end))
        object.__setattr__(node, "source", self.source[start:end])
        object.__setattr__(node, "positions", tuple(range(start, end)))
        return node

    def split_template(self, body: str) -> tuple[str, tuple[tuple[str, str], ...]]:
        pieces, depth, current = [], 0, []
        for char in body:
            if char in "{[":
                depth += 1
            elif char in "}]":
                depth -= 1
            if char == "|" and depth == 0:
                pieces.append("".join(current)); current = []
            else:
                current.append(char)
        pieces.append("".join(current))
        name = pieces[0].strip()
        arguments = []
        for item in pieces[1:]:
            if "=" in item:
                key, value = item.split("=", 1)
                arguments.append((key.strip(), value.strip()))
            else:
                arguments.append(("", item.strip()))
        return name, tuple(arguments)

    def inline(self, text: str, base: int, depth: int = 0) -> tuple[tuple, int]:
        if depth > self.options.max_nesting:
            self.fail("nesting-limit", "MediaWiki nesting limit exceeded.", base, base + len(text))
        nodes, index, text_start = [], 0, 0
        special = re.compile(
            r"<!--|&(?:#\d+|#x[0-9A-Fa-f]+|[A-Za-z][A-Za-z0-9]+);"
            r"|'''|''|</?(?:ref|nowiki|pre|code|math|b|i|small|big|s|u|span)\b"
            r"|{{|\[\[|\[https?://|<[^>]+>",
            re.I,
        )
        def flush(end):
            nonlocal text_start
            if text_start < end:
                nodes.append(self.locate(Text(text[text_start:end]), base + text_start, base + end))

        while index < len(text):
            match = special.search(text, index)
            if not match:
                break
            if match.start() > index:
                index = match.start()
            start = match.start()
            if start > text_start:
                flush(start)
            token = match.group(0)
            if text.startswith("<!--", start):
                end = text.find("-->", start + 4)
                end = len(text) if end < 0 else end + 3
                nodes.append(self.locate(Comment(text[start + 4:end - 3]), base + start, base + end))
                text_start = index = end
            elif token.startswith("&"):
                end = text.find(";", start) + 1
                if end == 0:
                    end = start + len(token)
                value = text[start + 1:end - 1]
                nodes.append(self.locate(Entity(value), base + start, base + end))
                text_start = index = end
            elif text.startswith("{{", start):
                end = self.find_balanced(text, start, "{{", "}}")
                body = text[start + 2:end - 2]
                nested_count = body.count("{{")
                if depth + nested_count + 1 > self.options.max_nesting:
                    self.fail("nesting-limit", "MediaWiki nesting limit exceeded.",
                              base + start, base + end)
                name, arguments = self.split_template(body)
                nodes.append(self.locate(Template(name, arguments), base + start, base + end))
                text_start = index = end
            elif text.startswith("[[", start):
                end = text.find("]]", start + 2)
                end = len(text) if end < 0 else end + 2
                body = text[start + 2:end - 2]
                target, _, label = body.partition("|")
                if target.casefold().startswith("category:"):
                    name = target[len("Category:"):]
                    sort_key = label
                    category = Category(name, sort_key)
                    nodes.append(self.locate(category, base + start, base + end))
                elif target.casefold().startswith("file:") or target.casefold().startswith("image:"):
                    colon = target.find(":")
                    name = target[colon + 1:] if colon >= 0 else target
                    options = tuple(part for part in label.split("|") if part)
                    nodes.append(self.locate(FileLink(name, options=options), base + start, base + end))
                elif "#" in target:
                    nodes.append(self.locate(SectionLink(target, label), base + start, base + end))
                else:
                    anchor = ""
                    clean = target
                    if "#" in clean:
                        clean, anchor = clean.split("#", 1)
                    nodes.append(self.locate(InternalLink(clean, *(self.inline(label, base + start + 2, depth + 1)[0]) if label else (), anchor=anchor),
                                             base + start, base + end))
                text_start = index = end
            elif text[start:start + 1] == "[" and re.match(r"https?://", text[start + 1:start + 9], re.I):
                end = text.find("]", start + 1)
                end = len(text) if end < 0 else end + 1
                body = text[start + 1:end - 1]
                destination, _, label = body.partition(" ")
                nodes.append(self.locate(ExternalLink(destination, *(self.inline(label or destination, base + start + 1, depth + 1)[0])),
                                         base + start, base + end))
                text_start = index = end
            elif text.startswith("'''''", start):
                end = text.find("'''''", start + 5)
                end = len(text) if end < 0 else end + 5
                value = text[start + 5:end - 5]
                nodes.append(self.locate(BoldItalic(*self.inline(value, base + start + 5, depth + 1)[0]),
                                         base + start, base + end))
                text_start = index = end
            elif text.startswith("'''", start):
                end = text.find("'''", start + 3)
                end = len(text) if end < 0 else end + 3
                value = text[start + 3:end - 3]
                nodes.append(self.locate(Bold(*self.inline(value, base + start + 3, depth + 1)[0]),
                                         base + start, base + end))
                text_start = index = end
            elif text.startswith("''", start):
                end = text.find("''", start + 2)
                end = len(text) if end < 0 else end + 2
                value = text[start + 2:end - 2]
                nodes.append(self.locate(Italic(*self.inline(value, base + start + 2, depth + 1)[0]),
                                         base + start, base + end))
                text_start = index = end
            elif re.match(r"<(?:nowiki|pre|code|math)\b", text[start:start + 20], re.I):
                opening = re.match(r"<(nowiki|pre|code|math)\b[^>]*>", text[start:], re.I)
                if opening:
                    name = opening.group(1).casefold()
                    close_start = start + opening.end()
                    close = text.find("</"+name+">", close_start)
                    end = len(text) if close < 0 else close + len(name) + 3
                    value = text[close_start: close if close >= 0 else len(text)]
                    node = {"nowiki": Nowiki, "pre": Pre, "code": Code, "math": Math}[name](value)
                    nodes.append(self.locate(node, base + start, base + end))
                    text_start = index = end
                    continue
                index = start + 1
            elif re.match(r"<ref\b", text[start:start + 8], re.I):
                opening = re.match(r"<ref\b([^>]*)>", text[start:], re.I)
                if opening:
                    attrs = opening.group(1)
                    name_match = re.search(r'name=["\']([^"\']+)["\']', attrs)
                    name = name_match.group(1) if name_match else ""
                    close = text.find("</ref>", start + opening.end())
                    if close < 0:
                        end = len(text)
                        value = text[start + opening.end():]
                    else:
                        end = close + 6
                        value = text[start + opening.end():close]
                    nodes.append(self.locate(Reference(name, value), base + start, base + end))
                    text_start = index = end
                    continue
                index = start + 1
            else:
                opening = re.match(r"<([A-Za-z][A-Za-z0-9-]*)\b[^>]*>", text[start:], re.I)
                closing = re.match(r"</([A-Za-z][A-Za-z0-9-]*)>", text[start:], re.I)
                if opening:
                    name = opening.group(1)
                    close = text.find("</"+name+">", start + opening.end())
                    end = len(text) if close < 0 else close + len(name) + 3
                    value = text[start + opening.end(): close if close >= 0 else len(text)]
                    nodes.append(self.locate(Tag(name, *self.inline(value, base + start + opening.end(), depth + 1)[0]),
                                             base + start, base + end))
                    text_start = index = end
                elif closing:
                    index = start + closing.end()
                else:
                    index = start + 1
        flush(len(text))
        return tuple(nodes), index

    def find_balanced(self, text: str, start: int, opening: str, closing: str) -> int:
        depth = 1
        index = start + len(opening)
        while index < len(text):
            if text.startswith(opening, index):
                depth += 1
                index += len(opening)
            elif text.startswith(closing, index):
                depth -= 1
                index += len(closing)
                if depth == 0:
                    return index
            else:
                index += 1
        return len(text)

    def blocks(self, fragment: bool = False) -> Document | Fragment:
        source = self.source
        lines = source.splitlines(keepends=True)
        nodes = []
        index = 0
        offset = 0
        paragraph_lines: list[str] = []
        paragraph_start = 0

        def flush_paragraph() -> None:
            nonlocal paragraph_lines, paragraph_start
            if paragraph_lines:
                text = "".join(paragraph_lines)
                start = paragraph_start
                end = start + len(text)
                inline_nodes = self.inline(text, start)[0]
                nodes.append(self.locate(Paragraph(*inline_nodes), start, end))
                paragraph_lines = []

        while index < len(lines):
            line = lines[index]
            stripped = line.rstrip("\r\n")
            absolute = offset
            offset += len(line)
            if not stripped.strip():
                flush_paragraph()
                index += 1
                continue
            heading = re.fullmatch(r"\s*(={1,6})\s*(.*?)\s*\1\s*", stripped)
            if heading:
                flush_paragraph()
                level = len(heading.group(1))
                value = heading.group(2)
                children = self.inline(value, absolute + stripped.find(value) if value else absolute)[0]
                h = self.locate(Heading(level, *children), absolute, offset)
                nodes.append(h)
                index += 1
                continue
            if re.fullmatch(r"\s*-{4,}\s*", stripped):
                flush_paragraph()
                nodes.append(self.locate(HorizontalRule(), absolute, offset))
                index += 1
                continue
            if stripped.startswith("{|"):
                flush_paragraph()
                table_lines = [line]
                table_start = absolute
                index += 1
                while index < len(lines):
                    table_line = lines[index]
                    table_lines.append(table_line)
                    offset += len(table_line)
                    if table_line.strip().startswith("|}"):
                        index += 1
                        break
                    index += 1
                end = table_start + sum(map(len, table_lines))
                table = self.parse_table("".join(table_lines), table_start)
                nodes.append(self.locate(table, table_start, end))
                continue
            if re.match(r"^\*+\s", stripped):
                flush_paragraph()
                items, start = [], absolute
                while index < len(lines) and re.match(r"^\*+\s", lines[index].rstrip("\r\n")):
                    item_line = lines[index].rstrip("\r\n")
                    item_start = absolute if len(items) == 0 else sum(len(part) for part in lines[:index])
                    value = re.sub(r"^\*+\s?", "", item_line)
                    items.append(self.locate(Paragraph(*self.inline(value, item_start)[0]), item_start, item_start + len(value)))
                    index += 1
                    if index < len(lines):
                        offset = sum(len(part) for part in lines[:index])
                nodes.append(self.locate(BulletList(*items), start, offset))
                continue
            if re.match(r"^#+\s", stripped):
                flush_paragraph()
                items, start = [], absolute
                while index < len(lines) and re.match(r"^#+\s", lines[index].rstrip("\r\n")):
                    item_line = lines[index].rstrip("\r\n")
                    item_start = absolute if len(items) == 0 else sum(len(part) for part in lines[:index])
                    value = re.sub(r"^#+\s?", "", item_line)
                    items.append(self.locate(Paragraph(*self.inline(value, item_start)[0]), item_start, item_start + len(value)))
                    index += 1
                    if index < len(lines):
                        offset = sum(len(part) for part in lines[:index])
                nodes.append(self.locate(OrderedList(*items), start, offset))
                continue
            if not paragraph_lines:
                paragraph_start = absolute
            paragraph_lines.append(line)
            index += 1
        flush_paragraph()
        cls = Fragment if fragment else Document
        document = cls(*nodes)
        return self.locate(document, 0, len(source))

    def parse_table(self, source: str, base: int) -> Table:
        rows = []
        row = None
        caption = ""
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("{|"):
                continue
            if stripped.startswith("|+"):
                caption = stripped[2:].strip()
            elif stripped.startswith("|-"):
                if row is not None:
                    rows.append(row)
                row = TableRow()
            elif stripped.startswith(("|", "!")) and row is not None:
                header = stripped.startswith("!")
                value = stripped[1:].strip()
                if "||" in value or "!!" in value:
                    separator = "!!" if header else "||"
                    pieces = value.split(separator)
                else:
                    pieces = [value]
                cells = []
                for piece in pieces:
                    children = self.inline(piece.strip(), base)[0]
                    cells.append(TableCell(*children, header=header))
                row = TableRow(*row.children, *cells)
            elif stripped.startswith("|}"):
                break
        if row is not None:
            rows.append(row)
        if not rows:
            rows = [TableRow(TableCell(Text("")))]
        return Table(*rows, caption=caption)


def parse(source: str, *, options: ParseOptions | None = None) -> Document:
    if not isinstance(source, str):
        raise TypeError("MediaWiki source must be a string.")
    options = options or ParseOptions()
    if len(source) > options.max_characters:
        parser = _Parser(source, options)
        parser.fail("character-limit", "MediaWiki character limit exceeded.", 0, len(source))
    parser = _Parser(source, options)
    document = parser.blocks()
    object.__setattr__(document, "diagnostics", tuple(parser.diagnostics))
    return document


def parse_fragment(source: str, *, options: ParseOptions | None = None) -> Fragment:
    if not isinstance(source, str):
        raise TypeError("MediaWiki source must be a string.")
    options = options or ParseOptions()
    parser = _Parser(source, options)
    if len(source) > options.max_characters:
        parser.fail("character-limit", "MediaWiki character limit exceeded.", 0, len(source))
    return parser.blocks(fragment=True)


parse_document = parse
parse_blocks = parse


def parse_sections(source: str, *, options: ParseOptions | None = None) -> tuple[Section, ...]:
    """Group top-level AST children into sections beginning at headings."""
    document = parse(source, options=options)
    sections: list[Section] = []
    current_heading: Heading | None = None
    current_children: list = []
    intro: list = []
    for child in document.children:
        if isinstance(child, Heading):
            if current_heading is not None:
                sections.append(Section(current_heading, *current_children))
            current_heading = child
            current_children = []
        elif current_heading is None:
            intro.append(child)
        else:
            current_children.append(child)
    if current_heading is not None:
        sections.append(Section(current_heading, *current_children))
    if intro:
        if sections:
            sections.insert(0, Section(Heading(1, ""), *intro))
        else:
            sections = [Section(Heading(1, ""), *intro)]
    return tuple(sections)
