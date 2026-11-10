"""Resolve host process UIDs without inventing an owner."""

import logging
import pwd

logger = logging.getLogger(__name__)


def username_for_uid(uid: int) -> str:
    """Return a host username or an explicit marker for an unmapped UID."""
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        logger.warning("UID %s has no host username; reporting uid:%s", uid, uid)
        return f"uid:{uid}"
