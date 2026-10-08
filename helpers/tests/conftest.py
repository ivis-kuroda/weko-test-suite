import os
import sys

HELPERS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HELPERS not in sys.path:
    sys.path.insert(0, HELPERS)
