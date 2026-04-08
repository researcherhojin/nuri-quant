"""Test helper functions for tests/api/.

Imported explicitly by test files (conftest.py only auto-loads fixtures).
"""
import asyncio
import json
import time as _time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
import yaml
from fastapi.testclient import TestClient

from nuri.core.db import get_db, init_db, upsert_macro, upsert_portfolio, upsert_prices


def _csv_file(content: str, filename: str = "test.csv"):
    """Helper: CSV UploadFile for import tests."""
    return {"file": (filename, content.encode("utf-8"), "text/csv")}
