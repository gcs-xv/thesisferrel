import tempfile
import unittest
from pathlib import Path

from core import (
    derive_map,
    derive_outcome24,
    derive_score,
    final_outcome,
)
from data_dictionary import DATA_DICTIONARY
from database import episodes, get_all_episodes, get_engine, upsert_episode


class DerivationTests(unittest.TestCase):
    def test_map_uses_sbp_and_dbp(self):
        self.assertEqual(derive_map(120, 80), 93.3)
        self.assertIsNone(derive_map(120, None))

    def test_score_is_na_when_any_domain_is_missing(self):
        self.assertEqual(derive_score([1, 0, 1, 0, 1, 0]), (0, 3))
        self.assertEqual(derive_score([1, 0, None, 0, 1, 0]), (1, None))

    def test_unverified_outcome_is_not_forced_to_zero(self):
        self.assertIsNone(derive_outcome24([0, 0, None, 0], outcome_complete=0))
        self.assertIsNone(derive_outcome24([0, 0, 0, 0], outcome_complete=0))
        self.assertEqual(derive_outcome24([0, 0, 0, 0], outcome_complete=1), 0)
        self.assertEqual(derive_outcome24([0, None, 1, None], outcome_complete=0), 1)

    def test_adjudication_overrides_raw_outcome(self):
        self.assertEqual(final_outcome(0, 1), 1)
        self.assertEqual(final_outcome(1, None), 1)


class SchemaTests(unittest.TestCase):
    def test_dictionary_covers_every_database_column_once(self):
        dictionary_variables = [row["variable"] for row in DATA_DICTIONARY]
        self.assertEqual(len(dictionary_variables), len(set(dictionary_variables)))
        self.assertEqual(set(dictionary_variables), set(episodes.c.keys()))

    def test_sqlite_upsert_preserves_single_row_per_episode(self):
        with tempfile.TemporaryDirectory() as tmp:
            database_url = f"sqlite:///{Path(tmp) / 'test.db'}"
            engine = get_engine(database_url)
            upsert_episode(engine, {"id_studi": "ABC-001", "site": 1})
            upsert_episode(engine, {"id_studi": "ABC-001", "site": 2})
            rows = get_all_episodes(engine)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["site"], 2)


if __name__ == "__main__":
    unittest.main()
