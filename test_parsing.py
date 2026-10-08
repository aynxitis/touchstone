"""Token-free parsing checks. Run: .venv/bin/python test_parsing.py"""
from check_numbers import resolve_footnotes, segments


def cited(path):
    return [(t, u) for t, u in segments(open(path, encoding="utf-8").read()) if u]


# report2 is the tuning set: its 29 cited claims must never shift.
assert len(cited("report2.txt")) == 29

# [n] markers + "Sources:" list; "[1][2]," is one citation; a numbered body list stays text.
c = cited("samples/footnotes_perplexity.txt")
assert [u.rsplit("/", 1)[1] for _, u in c] == [
    "magstartup-10-startups", "magstartup-10-startups", "startup-dz-stats", "asf-capital", "volz-series-a"]
assert c[1][0] == "More than 7,800 ventures are registered on startup.dz,"
assert not any(t in (",", ".") for t, _ in segments(open("samples/footnotes_perplexity.txt").read()))
assert ("Register on startup.dz", None) in segments(open("samples/footnotes_perplexity.txt").read())

# [^1]: markdown footnotes and ChatGPT's 【1】.
c = cited("samples/footnotes_markdown.txt")
assert [u.rsplit("/", 1)[1] for _, u in c] == ["asf-portfolio", "yassir-series-b", "moustachir-ipo"]

# A source list with names only, a Sources list without markers, or no links at all:
# nothing can be checked, and source entries never become claims.
text = open("samples/names_only.txt").read()
assert cited("samples/names_only.txt") == [] and resolve_footnotes(text)[1] == 3
assert all("Wamda" not in t for t, _ in segments(text))
assert cited("samples/sources_no_markers.txt") == []
assert cited("samples/no_links.txt") == []

print("parsing checks passed")
