from parse_mw import render

result = render(
    "== Example ==\n\n"
    "'''Hello''' ''MediaWiki'' [[Target|label]] {{Infobox|value=1}}\n"
)
assert "<strong>Hello</strong>" in result.html
assert "<em>MediaWiki</em>" in result.html
print(result.html)
