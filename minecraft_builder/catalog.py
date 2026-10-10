import gzip
import json
from functools import lru_cache
from pathlib import Path

from .core.palette import parse_document


@lru_cache(maxsize=1)
def bundled():
    with gzip.open(
        Path(__file__).parent / "data/bundled.json.gz", "rt", encoding="utf-8"
    ) as stream:
        return parse_document(json.load(stream))


def profiles(settings):
    result = dict(bundled())
    if settings.custom_palettes:
        result.update(parse_document(json.loads(settings.custom_palettes.as_string())))
    return result
