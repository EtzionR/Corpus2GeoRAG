"""Small helpers shared by test files (not a test module itself)."""


def names_of(gi, name: str) -> set:
    return set(gi.groups[gi.group_of[name]])
