"""Stage 1: scan a target repo into an inventory of services and files (story S3).

Read in this order: walk.py, naming.py, groups.py, inventory.py, scan.py.
"""

from tc_detector.scanner.inventory import Inventory, Service
from tc_detector.scanner.scan import scan

__all__ = ["Inventory", "Service", "scan"]
