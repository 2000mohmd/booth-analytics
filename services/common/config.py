"""Config-loading helpers shared by every service's entrypoint - previously each service's
main.py re-implemented the same load_yaml() and re-declared the same DB_PATH/BOOTH_CONFIG/
BOOTH_ID env-var names and defaults independently. Centralized here since all of them were
already byte-identical across services (same names, same defaults) - this changes nothing
about runtime behavior, only where the one copy of each lives.
"""
import os
import string
from pathlib import Path

import yaml

DEFAULT_DB_PATH = "data/events.db"
DEFAULT_BOOTH_CONFIG = "configs/booth.yaml"
DEFAULT_BOOTH_ID = "booth-01"


def load_yaml(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def load_dotenv_if_present(dotenv_path: str = ".env") -> None:
    """Loads .env into os.environ if the file exists - a no-op otherwise (deployments that
    don't use a .env file, e.g. Docker Compose's own environment: block, are unaffected).
    Import is local so python-dotenv is only required by whatever actually calls this."""
    if not Path(dotenv_path).exists():
        return
    from dotenv import load_dotenv

    load_dotenv(dotenv_path)


def expand_env_placeholders(text: str) -> str:
    """${VAR}-style substitution against os.environ, via stdlib string.Template - deliberately
    not os.path.expandvars, whose placeholder syntax differs between POSIX ($VAR/${VAR}) and
    Windows (%VAR%). Used to keep secrets (e.g. NVR camera credentials) out of booth.yaml and
    in the environment/.env instead - see configs/booth.yaml's camera `source:` fields."""
    return string.Template(text).safe_substitute(os.environ)
