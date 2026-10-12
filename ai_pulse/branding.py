"""Load the user's bundled AI Signal artwork for the dashboard."""

from base64 import b64encode
from functools import lru_cache

from ai_pulse.storage import ROOT


ARTWORK_PATH = ROOT / 'assets' / 'ai-signal.png'
MASCOT_PATH = ROOT / 'assets' / 'ai-signal-bot-waving.svg'


@lru_cache(maxsize=1)
def artwork_bytes() -> bytes:
    """Read the bundled PNG once without requesting an external image."""
    return ARTWORK_PATH.read_bytes()


def artwork_data_uri() -> str:
    """Embed the artwork in the dashboard without an external image request."""
    return 'data:image/png;base64,' + b64encode(artwork_bytes()).decode('ascii')


@lru_cache(maxsize=1)
def mascot_data_uri() -> str:
    """Embed the supplied animated bot as an image, without scripts or requests."""
    return 'data:image/svg+xml;base64,' + b64encode(MASCOT_PATH.read_bytes()).decode('ascii')
