"""Point every test run at a throwaway database and the fake LLM."""

import os
import tempfile

os.environ.setdefault("BUMPIN_DB", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.setdefault("LLM_PROVIDER", "fake")
os.environ.setdefault("LLM_CACHE", "off")
os.environ["JEV_API_KEY"] = ""  # tests never call Jev unless they patch it in
os.environ["TYPESAFE_API_KEY"] = ""
os.environ["IMAP_USER"] = ""  # tests never connect to a real mailbox
os.environ["IMAP_PASSWORD"] = ""
