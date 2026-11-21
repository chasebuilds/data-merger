"""data-merger: merge overlapping record lists into one traceable workbook."""

__version__ = "0.2.0"

from .config import Config, load_config  # noqa: E402
from .join import join_files, write_join_workbook  # noqa: E402
from .pipeline import MergeResult, merge_files  # noqa: E402
from .workbook import write_workbook  # noqa: E402

__all__ = [
    "Config", "MergeResult", "__version__", "join_files", "load_config", "merge_files",
    "write_join_workbook", "write_workbook",
]
