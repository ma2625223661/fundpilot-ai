"""Keep provider fixture tests independent of the user's persistent evidence."""
import tempfile
from pathlib import Path
from unittest.mock import patch


def isolate_public_cache(test):
    folder = tempfile.TemporaryDirectory()
    test.addCleanup(folder.cleanup)
    for target, value in [('research_public_data._cache', {}),
                          ('research_public_data.CACHE_PATH', Path(folder.name) / 'public.json')]:
        patcher = patch(target, value)
        patcher.start()
        test.addCleanup(patcher.stop)
