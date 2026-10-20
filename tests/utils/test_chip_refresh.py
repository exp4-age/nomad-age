import logging

import pytest
from nomad.datamodel import EntryArchive, EntryMetadata

from nomad_age.schema_packages.age_schema import AGE_Sample_Reference
from nomad_age.schema_packages.LMOKEandVMOKESchema import LMOKEandVMOKESchema
from nomad_age.scripts import refresh_chip_plots
from nomad_age.utils import chip_refresh
from nomad_age.utils.utils import (
    AGE_MAGNETISATION_SCHEMA,
    AGE_SAMPLE_SCHEMA,
    as_utc,
    get_reference,
)

SAMPLES_UPLOAD = 'age_samples_upload'
MOKE_UPLOAD = 'moke_upload'
OLD = '2026-02-16T10:11:20+00:00'
NEW = '2026-03-02T08:30:00+00:00'


def ref(upload_id, entry_id) -> str:
    return f'{get_reference(upload_id, entry_id)}#data'


def stored_chip(entry_id=None, time=None) -> dict:
    chip = {'m_def': AGE_SAMPLE_SCHEMA, 'lab_id': '2023_0418_1'}
    if entry_id:
        chip['latest_magnetisation_measurement'] = ref(MOKE_UPLOAD, entry_id)
        chip['latest_magnetisation_time'] = time
    return chip


@pytest.fixture
def measure(tmp_path, stored_archives_context):
    """Normalize the L-MOKE measurement `entry_id` of the moke upload taken at
    `time` on the chip, whose stored archive shows `chip`; the chip of the
    AGE Samples upload is in `chips`."""

    def normalize(entry_id, time, chip, chips=('chip',), logger=None):
        archives = {(SAMPLES_UPLOAD, 'chip'): chip}
        measurement = LMOKEandVMOKESchema(
            measurement_time=as_utc(time),
            technique='L-MOKE',
            samples=[
                AGE_Sample_Reference(lab_id=c, reference=ref(SAMPLES_UPLOAD, c))
                for c in chips
            ],
        )
        archive = EntryArchive(
            m_context=stored_archives_context(tmp_path, archives),
            metadata=EntryMetadata(
                upload_id=MOKE_UPLOAD, entry_id=entry_id, mainfile=f'{entry_id}.txt'
            ),
            data=measurement,
        )
        measurement.normalize(archive, logger or logging.getLogger(__name__))

    return normalize


def test_newer_measurement_refreshes_its_chip_once(measure, temporal):
    measure('new', NEW, stored_chip('old', OLD))
    # another measurement of the upload, while the refresh is pending
    measure('newer', '2026-03-03T00:00:00+00:00', stored_chip('old', OLD))

    (started,) = temporal.started
    workflow = 'age-refresh-chip-chip.after-moke_upload'
    assert started['workflow'] == 'ProcessEntryWorkflow'
    assert started['id'] == workflow
    assert vars(started['arg']) == {
        'upload_id': SAMPLES_UPLOAD,
        'entry_id': 'chip',
        'workflow_id': workflow,
    }
    assert started['task_queue'] == 'nomad-internal'
    assert started['retry_policy'].maximum_attempts == 1
    assert started['start_delay'].total_seconds() == 10


@pytest.mark.parametrize(
    'entry_id, time, chip, refreshed',
    [
        ('old', OLD, stored_chip('new', NEW), False),
        # the chip shows it: its data may have changed
        ('new', NEW, stored_chip('new', NEW), True),
        ('old', OLD, stored_chip(), True),
        # same time: the chip shows the one with the larger entry id
        ('a_new', NEW, stored_chip('new', NEW), False),
        ('xnew', NEW, stored_chip('new', NEW), True),
    ],
)
def test_only_newer_measurements_refresh(
    measure, temporal, entry_id, time, chip, refreshed
):
    measure(entry_id, time, chip)

    assert bool(temporal.started) == refreshed


@pytest.mark.parametrize('state', ['busy_uploads', 'published_uploads'])
def test_busy_or_published_chip_upload_is_not_refreshed(measure, temporal, state):
    getattr(temporal, state).add(SAMPLES_UPLOAD)

    measure('new', NEW, stored_chip('old', OLD))

    assert not temporal.started


def test_no_refresh_without_temporal_worker(measure, temporal, monkeypatch):
    temporal.in_activity = False  # local processing
    measure('new', NEW, stored_chip('old', OLD))

    def no_temporal():
        raise ImportError('nomad.actions')  # NOMAD without Temporal

    monkeypatch.setattr(chip_refresh, '_load_api', no_temporal)
    measure('new', NEW, stored_chip('old', OLD))

    assert not temporal.started


def test_refresh_errors_do_not_fail_the_measurement(
    measure, temporal, caplog, kwargs_logger
):
    with caplog.at_level(logging.WARNING):
        measure(
            'new', NEW, stored_chip(), chips=('deleted', 'chip'), logger=kwargs_logger
        )

    # the other chip is refreshed
    assert temporal.started_ids == ['age-refresh-chip-chip.after-moke_upload']
    (warning,) = [r.getMessage() for r in caplog.records]
    assert 'deleted' in warning


def test_workflow_ids_parse():
    for args in [('c-_1', None, 0), ('c', 'u-_2', 0), ('c', 'u', 3)]:
        assert chip_refresh.parse_workflow_id(chip_refresh.workflow_id(*args)) == args
    assert chip_refresh.parse_workflow_id('process-entry-c') is None


@pytest.fixture
def chips(fake_index, tmp_path, stored_archives_context):
    """Chip A shows an older measurement, B its newest, C a deleted one; the
    context loads their stored archives."""

    def doc(entry_id, upload_id, schemas, references=(), time=None, author=None):
        return {
            'entry_id': entry_id,
            'upload_id': upload_id,
            'main_author': {'user_id': author},
            'section_defs': [{'definition_qualified_name': s} for s in schemas],
            'entry_references': [{'target_entry_id': r} for r in references],
            'search_quantities': [
                {
                    'definition': f'{AGE_MAGNETISATION_SCHEMA}.measurement_time',
                    'datetime_value': time,
                }
            ],
        }

    lmoke = ['LMOKEandVMOKESchema', AGE_MAGNETISATION_SCHEMA]
    fake_index.docs = [
        doc(chip, SAMPLES_UPLOAD, [AGE_SAMPLE_SCHEMA], author='owner') for chip in 'ABC'
    ] + [
        doc('m1', MOKE_UPLOAD, lmoke, ['A'], OLD),
        doc('m2', MOKE_UPLOAD, lmoke, ['A'], NEW),
        doc('m3', MOKE_UPLOAD, lmoke, ['B'], OLD),
    ]
    archives = {
        (SAMPLES_UPLOAD, 'A'): stored_chip('m1', OLD),
        (SAMPLES_UPLOAD, 'B'): stored_chip('m3', OLD),
        (SAMPLES_UPLOAD, 'C'): stored_chip('deleted', NEW),
    }
    return stored_archives_context(tmp_path, archives)


def test_repair_lists_stale_chips(chips, temporal):
    logger = logging.getLogger(__name__)

    summary = refresh_chip_plots.refresh(chips, logger, dry_run=True)

    assert summary == '3 chips, 2 stale, dry run: nothing started'
    assert not temporal.started


def test_repair_refreshes_stale_chips(chips, temporal):
    temporal.in_activity = False  # a command, not processing

    summary = refresh_chip_plots.refresh(chips, logging.getLogger(__name__))

    assert summary == '3 chips, 2 stale, 2 refreshes started'
    assert temporal.started_ids == ['age-refresh-chip-A', 'age-refresh-chip-C']


def test_refresh_from_a_forked_process_gets_its_own_runtime(measure, temporal):
    """NOMAD processes entries in a fork of the worker; the inherited Temporal
    runtime refuses to create a client there."""
    temporal.forked_runtime = True

    measure('new', NEW, stored_chip('old', OLD))

    assert temporal.runtime_resets == 1
    assert temporal.started_ids == ['age-refresh-chip-chip.after-moke_upload']
