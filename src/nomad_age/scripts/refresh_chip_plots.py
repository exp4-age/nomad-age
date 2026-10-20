"""Refresh the plots of chips that do not show their newest magnetisation
measurement, e.g. after a measurement was deleted or a refresh was missed.

    python -m nomad_age.scripts.refresh_chip_plots [--dry-run]

Run it in a NOMAD container of the Oasis (app or worker), with access to MongoDB,
Elasticsearch and Temporal.
"""

import argparse
import logging
from typing import Optional

from nomad_age.utils import chip_refresh
from nomad_age.utils.utils import AGE_SAMPLE_SCHEMA, newest_magnetisation_measurement

PAGE_SIZE = 1000


def list_chips() -> list:
    """entry_id, upload_id and main author user id of all chips (AGE_Sample)."""
    from nomad.search import MetadataPagination, MetadataRequired, search

    chips = []
    page_after_value: Optional[str] = None
    while True:
        results = search(
            owner=None,  # all entries
            query={'section_defs.definition_qualified_name': AGE_SAMPLE_SCHEMA},
            required=MetadataRequired(
                include=['entry_id', 'upload_id', 'main_author.user_id']
            ),
            pagination=MetadataPagination(
                page_size=PAGE_SIZE, page_after_value=page_after_value
            ),
        )
        chips.extend(
            {
                'entry_id': hit['entry_id'],
                'upload_id': hit['upload_id'],
                'user_id': (hit.get('main_author') or {}).get('user_id'),
            }
            for hit in results.data
        )
        page_after_value = results.pagination.next_page_after_value
        if not page_after_value or not results.data:
            return chips


def is_stale(chip: dict, context) -> bool:
    """Whether the stored chip shows another measurement (or time) than its
    newest referencing magnetisation measurement."""
    newest = newest_magnetisation_measurement(chip['entry_id'], chip['user_id'])
    expected = (
        (newest['entry_id'], newest['measurement_time']) if newest else (None, None)
    )
    stored = chip_refresh.stored_latest_magnetisation(
        context, chip['upload_id'], chip['entry_id']
    )
    return stored != expected


def refresh(context, logger, dry_run: bool = False) -> str:
    """Start the refresh of every stale chip; a one-line summary."""
    chips = list_chips()
    stale, started, failed = [], 0, 0
    for chip in chips:
        try:
            if not is_stale(chip, context):
                continue
            stale.append(chip)
            if dry_run:
                logger.info(f'Stale chip {chip["entry_id"]} ({chip["upload_id"]})')
            elif chip_refresh.start_refresh(
                chip['upload_id'], chip['entry_id'], logger
            ):
                started += 1
        except Exception as e:
            failed += 1
            logger.warning(f'Could not check chip {chip["entry_id"]}: {e!r}')
    summary = f'{len(chips)} chips, {len(stale)} stale'
    if dry_run:
        summary += ', dry run: nothing started'
    else:
        summary += f', {started} refreshes started'
    if failed:
        summary += f', {failed} failed'
    return summary


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument(
        '--dry-run', action='store_true', help='List stale chips, start nothing.'
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    logger = logging.getLogger('refresh_chip_plots')

    from nomad import infrastructure
    from nomad.config import config
    from nomad.datamodel.context import ServerContext

    config.load_plugins()
    infrastructure.setup_mongo()
    infrastructure.setup_elastic()
    print(refresh(ServerContext(), logger, dry_run=args.dry_run))


if __name__ == '__main__':
    main()
