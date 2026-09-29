"""Тесты кэша DataFrame."""

from infrastructure.storage import dataframe_cache
from infrastructure.storage.schema_reader import read_dataframe, invalidate_dataframe_cache


def test_dataframe_cache_hit(sample_csv, monkeypatch):
    dataframe_cache.clear_cache()
    df1 = read_dataframe(sample_csv, use_cache=True)
    df2 = read_dataframe(sample_csv, use_cache=True)
    assert df1.height == df2.height == 4
    assert df1.columns == df2.columns

    invalidate_dataframe_cache(sample_csv)
    df3 = read_dataframe(sample_csv, use_cache=True)
    assert df3.height == 4
