"""Bronze -> Silver -> Gold pipeline for poker hand histories in PHH format (PySpark).

    bronze  raw hand text, one row per hand, untouched + ingestion metadata
    silver  parsed tables: hands, player_hands, actions   (+ quarantine for bad hands)

Gold (the analytics layer) is built by dbt, in dbt/, on top of the silver tables.

Each run is a full refresh from the raw files, so running it twice gives the same result
(idempotent). Duplicate hands are dropped by (venue, hand_id) in silver.

    python -m poker_pipeline.pipeline --raw "data/raw/*.phhs" --lake data/lake      # files
    python -m poker_pipeline.pipeline --raw "<volume path>/*.phhs" --schema poker     # UC tables
"""
import argparse
import json
import os

from pyspark.sql import SparkSession, functions as F, types as T

from .parser import ParseError, parse_hand

PLAYER_T = T.StructType([
    T.StructField("seat", T.IntegerType()), T.StructField("name", T.StringType()),
    T.StructField("stack", T.DoubleType()), T.StructField("position", T.StringType()),
    T.StructField("invested", T.DoubleType()), T.StructField("collected", T.DoubleType()),
    T.StructField("vpip", T.BooleanType()), T.StructField("pfr", T.BooleanType()),
])
ACTION_T = T.StructType([
    T.StructField("seq", T.IntegerType()), T.StructField("street", T.StringType()),
    T.StructField("player", T.StringType()), T.StructField("action", T.StringType()),
    T.StructField("amount", T.DoubleType()),
])
PARSED_T = T.StructType([
    T.StructField("error", T.StringType()), T.StructField("hand_id", T.StringType()),
    T.StructField("venue", T.StringType()), T.StructField("played_date", T.StringType()),
    T.StructField("table_name", T.StringType()), T.StructField("small_blind", T.DoubleType()),
    T.StructField("big_blind", T.DoubleType()), T.StructField("n_players", T.IntegerType()),
    T.StructField("rake", T.DoubleType()), T.StructField("outcome_source", T.StringType()),
    T.StructField("players", T.ArrayType(PLAYER_T)), T.StructField("actions", T.ArrayType(ACTION_T)),
])
NO_HAND = (None,) * 11


class DataQualityError(RuntimeError):
    pass


def _parse(raw):
    try:
        h = parse_hand(raw)
    except ParseError as e:
        return (str(e),) + NO_HAND
    except Exception as e:  # never let one weird hand kill the job
        return (f"unexpected: {type(e).__name__}",) + NO_HAND
    players = [(p.seat, p.name, p.stack, p.position, p.invested, p.collected, p.vpip, p.pfr)
               for p in h.players]
    return (None, h.hand_id, h.venue, h.played_date, h.table_name, h.small_blind,
            h.big_blind, h.n_players, h.rake, h.outcome_source, players, h.actions)


parse_udf = F.udf(_parse, PARSED_T)


def get_spark(fmt="delta"):
    """Local session, or the existing session when running on Databricks."""
    builder = SparkSession.builder.appName("poker-lakehouse")
    if os.environ.get("DATABRICKS_RUNTIME_VERSION"):
        return builder.getOrCreate()
    builder = (builder.master("local[*]")
               .config("spark.sql.shuffle.partitions", "8")
               .config("spark.ui.showConsoleProgress", "false"))
    if fmt == "delta":
        from delta import configure_spark_with_delta_pip  # pip install delta-spark
        builder = (builder
                   .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
                   .config("spark.sql.catalog.spark_catalog",
                           "org.apache.spark.sql.delta.catalog.DeltaCatalog"))
        return configure_spark_with_delta_pip(builder).getOrCreate()
    return builder.getOrCreate()


class Store:
    """Where tables live: files under `lake/<layer>/<name>`, or Unity Catalog tables
    `<schema>.<layer>_<name>` when a schema is given (needed so dbt can read them)."""

    def __init__(self, spark, fmt, lake=None, schema=None):
        self.spark, self.fmt, self.lake, self.schema = spark, fmt, lake, schema

    def write(self, df, layer, name):
        w = df.write.format(self.fmt).mode("overwrite")
        if self.schema:
            w.saveAsTable(f"{self.schema}.{layer}_{name}")
        else:
            w.save(f"{self.lake}/{layer}/{name}")

    def read(self, layer, name):
        if self.schema:
            return self.spark.read.table(f"{self.schema}.{layer}_{name}")
        return self.spark.read.format(self.fmt).load(f"{self.lake}/{layer}/{name}")


def build_bronze(spark, raw_glob, store):
    files = spark.read.format("text").option("wholetext", "true").load(raw_glob)
    bronze = (
        files.select(
            F.col("_metadata.file_path").alias("source_file"),
            # a .phhs file holds many hands, each starting with a "[N]" header line
            F.explode(F.split("value", r"\n\s*\n(?=\[\d+\]\n)")).alias("raw_hand"),
        )
        .withColumn("raw_hand", F.trim("raw_hand"))
        .filter(F.length("raw_hand") > 0)
        .withColumn("hand_id", F.nullif(F.regexp_extract("raw_hand", r"(?m)^hand = (\d+)", 1), F.lit("")))
        .withColumn("ingested_at", F.current_timestamp())
    )
    store.write(bronze, "bronze", "raw_hands")


def build_silver(spark, store):
    bronze = store.read("bronze", "raw_hands")
    # Materialize the parse once (instead of .persist(), which serverless compute does not
    # support) so the UDF runs a single time however many tables are derived from it.
    store.write(bronze.withColumn("p", parse_udf("raw_hand")), "stage", "parsed")
    parsed = store.read("stage", "parsed")

    quarantine = (parsed.filter(F.col("p.error").isNotNull())
                  .select("hand_id", "source_file", "raw_hand",
                          F.col("p.error").alias("error"),
                          F.current_timestamp().alias("quarantined_at")))
    ok = parsed.filter(F.col("p.error").isNull()).select("source_file", "p.*")
    good = ok.dropDuplicates(["venue", "hand_id"])

    hands = good.select(
        "hand_id", "venue", F.to_date("played_date").alias("played_date"), "table_name",
        "small_blind", "big_blind", "n_players", "rake", "outcome_source", "source_file")
    player_hands = (good.select("hand_id", "venue", "big_blind", "outcome_source",
                                F.explode("players").alias("pl"))
                    .select("hand_id", "venue", "big_blind", "outcome_source", "pl.*")
                    .withColumnRenamed("name", "player")
                    .withColumn("net", F.round(F.col("collected") - F.col("invested"), 2))
                    .withColumn("net_bb", F.col("net") / F.col("big_blind")))
    actions = good.select("hand_id", "venue", F.explode("actions").alias("a")).select("hand_id", "venue", "a.*")

    for name, df in [("hands", hands), ("player_hands", player_hands),
                     ("actions", actions), ("quarantine", quarantine)]:
        store.write(df, "silver", name)


def run_pipeline(spark, raw_glob, lake=None, fmt="delta", max_quarantine_rate=0.10, schema=None):
    store = Store(spark, fmt, lake, schema)
    build_bronze(spark, raw_glob, store)
    build_silver(spark, store)

    rd = store.read
    bronze_n = rd("bronze", "raw_hands").count()
    hands = rd("silver", "hands")
    silver_n = hands.count()
    by_outcome = {r["outcome_source"]: r["count"] for r in hands.groupBy("outcome_source").count().collect()}
    quarantined = rd("silver", "quarantine").count()
    metrics = {
        "bronze_hands": bronze_n,
        "silver_hands": silver_n,
        "quarantined": quarantined,
        "duplicates_dropped": bronze_n - silver_n - quarantined,
        "quarantine_rate": round(quarantined / bronze_n, 4) if bronze_n else 0.0,
        "outcome_recorded": by_outcome.get("recorded", 0),
        "outcome_inferred_fold": by_outcome.get("inferred_fold", 0),
        "outcome_unknown": by_outcome.get("unknown", 0),
    }
    if bronze_n == 0:
        raise DataQualityError("no hands found in bronze: check the input path")
    if metrics["quarantine_rate"] > max_quarantine_rate:
        raise DataQualityError(f"quarantine rate {metrics['quarantine_rate']:.1%} "
                               f"exceeds limit {max_quarantine_rate:.0%}")
    return metrics


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw/*.phhs")
    ap.add_argument("--lake", default="data/lake", help="folder for file-based tables")
    ap.add_argument("--schema", help="write Unity Catalog tables to this schema instead (Databricks)")
    ap.add_argument("--format", default="delta", choices=["delta", "parquet"])
    ap.add_argument("--max-quarantine-rate", type=float, default=0.10)
    a = ap.parse_args()
    spark = get_spark(a.format)
    try:
        spark.sparkContext.setLogLevel("ERROR")
    except Exception:  # not available on serverless / Spark Connect
        pass
    print(json.dumps(run_pipeline(spark, a.raw, a.lake, a.format, a.max_quarantine_rate,
                                  a.schema), indent=2))


if __name__ == "__main__":
    main()
