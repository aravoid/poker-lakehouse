import os
import pathlib

# Spark's Python workers are separate processes: make sure they can import the package
# even if it was not pip-installed (pip install -e . is still the recommended way).
SRC = str(pathlib.Path(__file__).resolve().parents[1] / "src")
os.environ["PYTHONPATH"] = SRC + os.pathsep + os.environ.get("PYTHONPATH", "")
