import logging
from types import SimpleNamespace

import pytest

from nomad_age.utils import utils
from nomad_age.utils.utils import find_chip_reference, normalize_sample_id


@pytest.mark.parametrize(
    'lab_id, normalized',
    [
        ('2023_0418', '2023_0418_1'),  # a sputter run means its first sample
        ('2023_0418_1', '2023_0418_1'),
        ('2023_0418_2', '2023_0418_2'),
        ('2023_0418_1_2', '2023_0418_1_2'),  # broken chip
        (' 2026_0017 ', '2026_0017_1'),
        ('Dynabeads_M270_COOH', 'Dynabeads_M270_COOH'),
        ('2023_0418_PMMA2', '2023_0418_PMMA2'),
        ('12023_0418', '12023_0418'),
    ],
)
def test_normalize_sample_id(lab_id, normalized):
    assert normalize_sample_id(lab_id) == normalized


def archive(user_id='author'):
    return SimpleNamespace(
        metadata=SimpleNamespace(main_author=SimpleNamespace(user_id=user_id))
    )


def test_two_chips_with_one_lab_id_are_not_linked(monkeypatch, caplog):
    hits = [{'upload_id': 'u', 'entry_id': e} for e in ('a', 'b')]
    searched = []

    def search(lab_id, user_id=None):
        searched.append((lab_id, user_id))
        return SimpleNamespace(data=hits)

    monkeypatch.setattr(utils, 'find_existing_AGE_sample', search)

    with caplog.at_level(logging.ERROR):
        reference = find_chip_reference('2023_0418', archive(), logging.getLogger())

    assert reference is None
    assert searched == [('2023_0418_1', 'author')]
    (error,) = caplog.records
    assert error.levelno == logging.ERROR
    assert '2023_0418_1' in error.getMessage()
