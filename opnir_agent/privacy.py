"""Which suppliers are individual people, so their names can be hidden.

opnirreikningar.is publishes self-employed people (those with a VAT number) by name. The data
is public, but an agent that answers "how much did Jón Jónsson get?" makes it easy to single
people out, so the names of people are replaced by MASK before the model sees anything
(db.py does the replacing; this module only decides who is a person).

The data has no ID numbers (kennitala), so the only evidence is the name itself. A name is
taken to be a person when it is shaped like a person's name (2-5 capitalised words, initials,
short forms like "Magnúsd.", particles like "de") and either ends in -son/-dóttir or has no
organisation word ("ehf", "klúbbur", "sveit", "Center", ...). E.g. (invented) "Hekla Pálsdóttir",
"Örvar Beekholt", "Marta Brunelli", "Pieter Jan de Wilde".

Firms named after their owner ("Egill Baldursson ehf.") are companies and are not masked.
The rule misses some people and flags some organisations; both were measured on a
hand-checked sample (DATA_NOTES.md), so the masking is a strong default, not a guarantee.
"""

import re

MASK = "[einstaklingur]"

_UPPER = "A-ZÁÐÉÍÓÚÝÞÆÖØÅÄÜ"
_LOWER = "a-záðéíóúýþæöøåäüéèëïçñćłńśźżčšžř"
_WORD = rf"[{_UPPER}][{_LOWER}]+(?:-[{_UPPER}][{_LOWER}]+)?"
_SHORT = rf"[{_UPPER}][{_LOWER}]*\.(?:[{_UPPER}]\.)*"  # "Magnúsd.", "Sch.", "A.K."
_PARTICLE = r"de|van|von|da|dos|del|la|le"

PERSON_SHAPE = re.compile(rf"^{_WORD}(?: (?:{_WORD}|{_SHORT}|[{_UPPER}]|{_PARTICLE})){{1,4}}$")
# "-son"/"-dóttir" at the end settles it even when a name contains an organisation word part,
# as "Garðarsson" (garð) or "Ásgerður Pálmadóttir" (gerð) do. No organisation name ends so.
PATRONYMIC_END = re.compile(r"(?:son|dóttir|dottir)$")

# Parts of organisation names. Matched anywhere in a word (case-insensitive), so Icelandic
# compounds like "Golfklúbbur" or "Björgunarsveitin" are caught by their parts.
ORG_PARTS = re.compile(
    # company forms
    r"ehf|\bhf\b|\bsf\b|slf|slhf|\bses\b|ohf|\bbs\b|svf|\bltd|\binc\b|gmbh|\bas\b|\bab\b|aps|"
    r"llc|\boy\b|\bbv\b|b\.v\.|\bsa\b|srl|corp|\bco\b|limited|\bplc\b|\bag\b|a/s|sp\.z|"
    # Icelandic organisation words
    r"stofn|ráðun|sjóð|félag|fél\b|samtök|samband|skól|sveit|bær|kaupstað|hrepp|byggð|þing\b|"
    r"ríki|bank|kirkj|sókn|prestak|þjónust|ísland|klúbb|deild|safn|setur|setr|ráð\b|ráðið|hús|"
    r"höll|kór|lúðra|nefnd|verk|smiðj|miðst|heimil|garð|stöð|veit[aiu]|gerð|búð|bakarí|hótel|gisti|"
    r"ferð|ferj|útgáf|blað|tíðind|bók|vernd|stúk|hátíð|lög|sýslu|embætt|kerfi|lausn|tækn|hafn|"
    r"samlag|hóp|stjór|stofa|eftirlit|gæsla|vinnu|söfn|krossinn|flokk|svæði|starfs|þekking|"
    r"sjálfsbj|hjartaheill|akóges|bónus|hagkaup|aðföng|alþingi|landspítal|markþing|stjórnvísi|"
    # foreign organisation words
    r"center|centre|group|international|service|solution|system|universit|institut|"
    r"association|foundation|society|company|nordic|europe|media|design|consult|travel|tour|"
    r"studio|agency|office|trust|partner|software|data|energy|labs?\b|press|publish|academ|"
    r"school|college|museum|council|network|club|veterin|anstalt|instituttet|alliance|mission|"
    r"sverige|norge|danmark|deutschland|iceland|royal|food|wine|polar|pelagic|copenhagen|"
    r"informatic", re.IGNORECASE)


def _clean(name: str) -> str:
    return name.replace("đ", "ð").replace("Đ", "Ð")  # the source garbles ð as đ in some names


def is_person(name: str) -> bool:
    name = _clean(name)
    if not PERSON_SHAPE.match(name):
        return False
    return PATRONYMIC_END.search(name) is not None or not ORG_PARTS.search(name)


def people(names: list[str]) -> set[str]:
    """The supplier names that the rule takes to be individual people."""
    return {n for n in names if is_person(n)}
