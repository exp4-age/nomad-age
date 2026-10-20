"""Refresh of the chip plot after a magnetisation measurement was processed.

A chip (AGE_Sample, in the AGE Samples upload) shows the plot of its newest
magnetisation measurement in its archive. A measurement is processed in another
upload and cannot write the chip archive, so its processing asks NOMAD to process
the chip entry again: it starts NOMAD's ProcessEntryWorkflow for the chip without
waiting for it (the worker runs one activity at a time; waiting would deadlock).

The chip finds its measurements in the search index. NOMAD indexes an entry right
after processing it only the first time; reprocessed entries are indexed when their
whole upload is done. So the workflow id names the upload that triggered the
refresh, and a refresh that runs while that upload is still processing starts
itself again later, see postpone_while_source_busy.
"""

from datetime import timedelta
from types import SimpleNamespace
from typing import Optional

from nomad_age.utils.utils import as_utc, parse_reference

WORKFLOW_PREFIX = 'age-refresh-chip-'
# NOMAD ids are url-safe base64, without dots.
SOURCE_SEPARATOR = '.after-'
WAIT_SEPARATOR = '.wait-'
# Also covers the indexing at the end of the activity that triggers the refresh.
FIRST_DELAY = timedelta(seconds=10)
MAX_WAIT_DELAY = timedelta(minutes=10)
# Waits for a busy upload: 30 s doubling to 10 min, about 3.5 h in total.
MAX_WAITS = 24


def workflow_id(
    chip_entry_id: str, source_upload_id: Optional[str] = None, wait: int = 0
) -> str:
    """Id of the refresh workflow of a chip, triggered by `source_upload_id` (the
    manual repair command has none), `wait` the number of earlier postponements.
    Triggers by several measurements of one upload share the id, so the first
    one starts the refresh and the others find it pending."""
    workflow = f'{WORKFLOW_PREFIX}{chip_entry_id}'
    if source_upload_id:
        workflow += f'{SOURCE_SEPARATOR}{source_upload_id}'
        if wait:
            workflow += f'{WAIT_SEPARATOR}{wait}'
    return workflow


def parse_workflow_id(workflow: str) -> Optional[tuple]:
    """(chip entry id, source upload id or None, wait) of a refresh workflow id;
    None for other workflows."""
    if not workflow.startswith(WORKFLOW_PREFIX):
        return None
    chip, _, source = workflow[len(WORKFLOW_PREFIX) :].partition(SOURCE_SEPARATOR)
    source, _, wait = source.partition(WAIT_SEPARATOR)
    if not chip or (wait and not wait.isdigit()):
        return None
    return chip, source or None, int(wait or 0)


def wait_delay(wait: int) -> timedelta:
    return min(timedelta(seconds=30 * 2 ** (wait - 1)), MAX_WAIT_DELAY)


def _load_api() -> SimpleNamespace:
    """The NOMAD (Temporal processing, >= 1.4) and temporalio APIs of a refresh."""
    from nomad.actions import TaskQueue
    from nomad.actions.client import get_client
    from nomad.config import config
    from nomad.processing.data import Upload, run_async
    from nomad.workflows.shared_objects import ProcessEntryActivityInput
    from temporalio import activity
    from temporalio.common import RetryPolicy
    from temporalio.exceptions import WorkflowAlreadyStartedError

    def reset_runtime():
        """NOMAD processes entries in a process forked from the worker, which
        inherits the worker's Temporal runtime; Temporal runtimes do not work
        across forks. Give this process its own runtime."""
        import nomad.actions.client as nomad_client
        from temporalio.runtime import Runtime, TelemetryConfig

        with nomad_client._runtime_lock:
            nomad_client._runtime = Runtime(
                telemetry=TelemetryConfig(), worker_heartbeat_interval=None
            )

    return SimpleNamespace(
        reset_runtime=reset_runtime,
        temporal_enabled=config.temporal.enabled,
        activity=activity,
        get_client=get_client,
        run_async=run_async,
        Upload=Upload,
        ProcessEntryActivityInput=ProcessEntryActivityInput,
        TaskQueue=TaskQueue,
        RetryPolicy=RetryPolicy,
        WorkflowAlreadyStartedError=WorkflowAlreadyStartedError,
    )


def _api() -> Optional[SimpleNamespace]:
    """See _load_api; None without Temporal processing (NOMAD < 1.4)."""
    try:
        return _load_api()
    except ImportError:
        return None


def in_worker() -> bool:
    """Whether this runs in an activity of a NOMAD Temporal worker, the only
    processing that can start a refresh; not in tests or local processing."""
    api = _api()
    return bool(api and api.temporal_enabled and api.activity.in_activity())


def busy(upload) -> bool:
    return bool(upload.process_running or getattr(upload, 'workflow_ids', None))


def start_refresh(
    chip_upload_id: str,
    chip_entry_id: str,
    logger,
    source_upload_id: Optional[str] = None,
    wait: int = 0,
) -> bool:
    """Start processing the chip entry again, as NOMAD's Entry.process_entry does,
    but without waiting for it and after a delay. True if started or already
    pending; False if the chip upload is processing or published (processing a
    single entry would not repack it) or there is no Temporal."""
    api = _api()
    if api is None:
        logger.warning('No Temporal processing; the chip plot is not refreshed.')
        return False
    upload = api.Upload.get(chip_upload_id)
    if busy(upload) or upload.published:
        logger.info(
            f'Upload {chip_upload_id} of chip {chip_entry_id} is processing or '
            'published; the chip plot is not refreshed now.'
        )
        return False
    workflow = workflow_id(chip_entry_id, source_upload_id, wait)
    delay = wait_delay(wait) if wait else FIRST_DELAY

    async def start():
        client = await api.get_client()
        await client.start_workflow(
            'ProcessEntryWorkflow',
            api.ProcessEntryActivityInput(
                upload_id=chip_upload_id,
                entry_id=chip_entry_id,
                workflow_id=workflow,
            ),
            id=workflow,
            task_queue=api.TaskQueue.NOMAD_INTERNAL_WORKFLOWS.value,
            retry_policy=api.RetryPolicy(maximum_attempts=1),
            start_delay=delay,
        )

    try:
        try:
            api.run_async(start())
        except AssertionError as error:
            if 'across forks' not in str(error):
                raise
            api.reset_runtime()
            api.run_async(start())
    except api.WorkflowAlreadyStartedError:
        logger.info(f'Refresh {workflow} of the chip plot is already pending.')
        return True
    logger.info(f'Started refresh {workflow} of the chip plot.')
    return True


def postpone_while_source_busy(chip_upload_id: str, chip_entry_id: str, logger):
    """In a refresh of the chip whose triggering upload is still processing (and
    not all of its measurements are indexed yet), start the refresh again later."""
    if not in_worker():
        return
    api = _api()
    parsed = parse_workflow_id(api.activity.info().workflow_id)
    if parsed is None or parsed[0] != chip_entry_id or parsed[1] is None:
        return
    _, source_upload_id, wait = parsed
    if not busy(api.Upload.get(source_upload_id)):
        return
    if wait >= MAX_WAITS:
        logger.warning(
            f'Upload {source_upload_id} is still processing; the plot of chip '
            f'{chip_entry_id} may miss its measurements. Run '
            'python -m nomad_age.scripts.refresh_chip_plots when it is done.'
        )
        return
    start_refresh(chip_upload_id, chip_entry_id, logger, source_upload_id, wait + 1)


def stored_latest_magnetisation(context, chip_upload_id: str, chip_entry_id: str):
    """(entry id, measurement time) of the newest magnetisation measurement that
    the stored chip archive shows; (None, None) if it shows none. The search index
    does not have it: NOMAD does not index entries that ProcessEntryWorkflow
    processes again."""
    chip = context.load_archive(chip_entry_id, chip_upload_id, None).data
    ids = parse_reference(chip.latest_magnetisation_measurement)
    return (ids[1] if ids else None), as_utc(chip.latest_magnetisation_time)


def refresh_needed(stored: tuple, entry_id: str, measurement_time) -> bool:
    """Whether the chip that shows the `stored` (entry id, time) measurement
    shows the measurement `entry_id` with `measurement_time` after a refresh, or
    shows it now and its data may have changed. Chips pick the newest by time,
    then entry id."""
    stored_id, stored_time = stored
    if stored_id == entry_id:
        return True
    if measurement_time is None:
        return False
    if stored_id is None or stored_time is None:
        return True
    return (measurement_time, entry_id) > (stored_time, stored_id)


def request_chip_refreshes(measurement, archive, logger) -> None:
    """Refresh the plots of the chips of the magnetisation `measurement` that
    show an older measurement (or this one) after its processing. Never fails."""
    try:
        if not measurement.samples or not in_worker():
            return
        chips = [parse_reference(sample.reference) for sample in measurement.samples]
    except Exception as e:
        logger.warning(f'Could not refresh the chip plots: {e!r}')
        return
    entry_id = archive.metadata.entry_id
    time = as_utc(measurement.measurement_time)
    for chip_upload_id, chip_entry_id in filter(None, chips):
        try:
            stored = stored_latest_magnetisation(
                archive.m_context, chip_upload_id, chip_entry_id
            )
            if refresh_needed(stored, entry_id, time):
                start_refresh(
                    chip_upload_id,
                    chip_entry_id,
                    logger,
                    source_upload_id=archive.metadata.upload_id,
                )
        except Exception as e:
            logger.warning(f'Could not refresh the plot of chip {chip_entry_id}: {e!r}')
