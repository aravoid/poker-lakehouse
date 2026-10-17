"""End-to-end tests on synthetic data. Uses parquet so no Delta jars are needed in CI."""
import pytest
from pyspark.sql import SparkSession

from poker_pipeline.pipeline import DataQualityError, run_pipeline
from poker_pipeline.simulator import write_files


@pytest.fixture(scope="module")
def spark():
    s = (SparkSession.builder.master("local[2]").appName("tests")
         .config("spark.sql.shuffle.partitions", "4").config("spark.ui.enabled", "false")
         .getOrCreate())
    yield s
    s.stop()


@pytest.fixture()
def raw(tmp_path):
    stats = write_files(tmp_path / "raw", n_hands=400, n_files=3, seed=11,
                        corrupt_rate=0.05, dup_rate=0.05)
    return str(tmp_path / "raw" / "*.phhs"), stats


def test_counts_reconcile_with_what_the_generator_injected(spark, tmp_path, raw):
    glob, stats = raw
    m = run_pipeline(spark, glob, str(tmp_path / "lake"), fmt="parquet")
    assert m["quarantined"] == stats["corrupted"] > 0
    assert m["duplicates_dropped"] == stats["duplicates"] > 0
    assert m["silver_hands"] == stats["hands"] - stats["corrupted"]
    assert m["bronze_hands"] == m["silver_hands"] + m["quarantined"] + m["duplicates_dropped"]


def test_outcome_sources_match_the_ground_truth(spark, tmp_path, raw):
    glob, stats = raw
    m = run_pipeline(spark, glob, str(tmp_path / "lake"), fmt="parquet")
    for kind in ("recorded", "inferred_fold", "unknown"):
        assert m[f"outcome_{kind}"] == stats[kind] > 0


def test_rerun_is_idempotent(spark, tmp_path, raw):
    glob, _ = raw
    lake = str(tmp_path / "lake")
    assert run_pipeline(spark, glob, lake, fmt="parquet") == run_pipeline(spark, glob, lake, fmt="parquet")


def test_no_duplicate_hand_ids_in_silver(spark, tmp_path, raw):
    glob, _ = raw
    lake = str(tmp_path / "lake")
    run_pipeline(spark, glob, lake, fmt="parquet")
    hands = spark.read.parquet(f"{lake}/silver/hands")
    assert hands.count() == hands.select("venue", "hand_id").distinct().count()


def test_quality_gate_fails_when_too_many_bad_hands(spark, tmp_path):
    write_files(tmp_path / "raw", n_hands=200, n_files=2, seed=3, corrupt_rate=0.5, dup_rate=0)
    with pytest.raises(DataQualityError):
        run_pipeline(spark, str(tmp_path / "raw" / "*.phhs"), str(tmp_path / "lake"),
                     fmt="parquet", max_quarantine_rate=0.10)
