#!/usr/bin/env python3
"""Source-tree launcher used by the FT frontend; does not need editable install."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from phonomenal.cli import main
raise SystemExit(main())
