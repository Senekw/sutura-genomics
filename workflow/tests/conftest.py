"""Make the workflow_recommend package importable when running tests in-place
(without installing), by putting the workflow/ directory on sys.path."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
