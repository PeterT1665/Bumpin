"""Point every test run at a throwaway database and the fake LLM."""

import os
import tempfile

os.environ.setdefault("BUMPIN_DB", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.setdefault("LLM_PROVIDER", "fake")
os.environ.setdefault("LLM_CACHE", "off")
