"""Earth Engine authentication wrapper."""

from __future__ import annotations

import os

import ee


def initialize(project: str | None = None) -> None:
    """Initialise Earth Engine.

    The user must have run ``earthengine authenticate`` at least once.
    A Cloud project ID is required for the new Earth Engine high-volume
    endpoint; it can be passed explicitly or via the ``EE_PROJECT``
    environment variable.
    """
    project = project or os.environ.get("EE_PROJECT")
    try:
        if project:
            ee.Initialize(project=project)
        else:
            ee.Initialize()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "Earth Engine initialisation failed. Run `earthengine authenticate` "
            "and set the EE_PROJECT environment variable to your Cloud project ID."
        ) from exc
