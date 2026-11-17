"""The kinds of document a World holds, as the app's pages name them.

The left side is the word in a page's address; the right is the document type
in the file format and what to call a list of them.
"""

KINDS = {
    "campaigns": ("campaign", "Campaigns"),
    "events": ("event", "Events"),
    "mods": ("mod", "Mods"),
    "plots": ("plot", "Plots"),
    "npcs": ("npc", "NPCs"),
    "factions": ("faction", "Factions"),
    "locations": ("location", "Locations"),
    "pcs": ("pc", "PCs"),
    "reports": ("after-action", "After-Action Reports"),
    "interludes": ("interlude-changes", "Interlude Changes"),
    "timeline": ("timeline", "Timeline"),
}

ADDRESS_OF = {doc_type: address for address, (doc_type, _label) in KINDS.items()}


def has_page(doc_type):
    """Whether documents of this type have pages of their own here."""
    return doc_type in ADDRESS_OF
