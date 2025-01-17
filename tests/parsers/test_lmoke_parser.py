import logging

from nomad.datamodel import EntryArchive
from nomad_age.parsers.LMOKEparser import LMOKEParser


def test_lmoke_parser():
    parser = LMOKEParser()
    archive = EntryArchive()
    parser.parse(
        'tests/data/2023_0325_1_LMOKE_2023-11-07_14-09-15.txt',
        archive,
        logging.getLogger(),
    )

    assert archive.data.user == 'Arne Vereijken'
    assert archive.data.sample == '2023_0325_1'
    assert archive.data.device == 'LMOKE'
