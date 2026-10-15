from nomad.config.models.plugins import AppEntryPoint
from nomad.config.models.ui import (
    App,
    Axis,
    Column,
    Columns,
    Dashboard,
    FilterMenu,
    FilterMenus,
    Format,
    Layout,
    Menu,
    MenuItemHistogram,
    MenuItemTerms,
    Pagination,
    SearchQuantities,
    WidgetHistogram,
    WidgetTerms,
)

app_entry_point = AppEntryPoint(
    name='NewApp',
    description='New app entry point configuration.',
    app=App(
        label='NewApp',
        path='app',
        category='simulation',
        columns=Columns(
            selected=['entry_id'],
            options={
                'entry_id': Column(),
            },
        ),
        filter_menus=FilterMenus(
            options={
                'material': FilterMenu(label='Material'),
            }
        ),
    ),
)

sample_schema = 'nomad_age.schema_packages.age_schema.AGE_Sample'
base_entity_schema = 'nomad.datamodel.metainfo.basesections.v1.BaseSection'
age_samples = AppEntryPoint(
    name='age_samples',
    description='AGE sample database.',
    app=App(
        label='AGE Samples',
        path='age_samples',
        category='Experiment',
        description='AGE samples database, used to find all our samples',
        search_quantities=SearchQuantities(
            include=[f'*#{sample_schema}', f'*#{base_entity_schema}']
        ),
        filters_locked={'section_defs.definition_qualified_name': [sample_schema]},
        columns=Columns(
            selected=['lab_id', 'state', 'entry_type'],
            options={
                'entry_type': Column(quantity='entry_type', label='Type'),
                'lab_id': Column(
                    quantity=f'data.lab_id#{base_entity_schema}', label='Sample ID'
                ),
                'state': Column(
                    quantity=f'data.state#{sample_schema}', label='Sample state'
                ),
            },
        ),
        menu=Menu(
            title='Sample',
            items=[
                MenuItemTerms(
                    quantity=f'data.lab_id#{base_entity_schema}',
                ),
                MenuItemTerms(
                    quantity=f'data.state#{sample_schema}',
                ),
                MenuItemTerms(
                    quantity=f'data.location#{sample_schema}',
                ),
            ],
        ),
        dashboard={
            'widgets': [
                {
                    'type': 'terms',
                    'search_quantity': f'data.lab_id#{base_entity_schema}',
                    'title': 'Sample ID',
                    'show_input': True,
                    'layout': {
                        'lg': {'minH': 5, 'minW': 3, 'h': 5, 'w': 4, 'x': 6, 'y': 0},
                    },
                    'query_mode': 'or',
                },
                {
                    'type': 'terms',
                    'search_quantity': f'data.state#{sample_schema}',
                    'title': 'Sample state',
                    'show_input': True,
                    'layout': {
                        'lg': {'minH': 5, 'minW': 3, 'h': 5, 'w': 4, 'x': 6, 'y': 0},
                    },
                },
                {
                    'type': 'terms',
                    'search_quantity': f'data.location#{sample_schema}',
                    'title': 'Sample location',
                    'show_input': True,
                    'layout': {
                        'lg': {'minH': 5, 'minW': 3, 'h': 5, 'w': 4, 'x': 6, 'y': 0},
                    },
                },
            ]
        },
    ),
)

tracking_schema = (
    'nomad_age.schema_packages.particle_tracking_schema.AGE_ParticleTracking'
)


def tracking(path: str) -> str:
    """Search quantity of a particle tracking measurement."""
    return f'data.{path}#{tracking_schema}'


count = Format(decimals=0, mode='standard')


def widget_layout(sm, md, lg, xl, xxl) -> dict:
    """Widget position (x, y, w, h) per breakpoint; the dashboard grid has
    12, 18, 24, 30 and 36 columns at the sm, md, lg, xl and xxl breakpoints."""
    return {
        breakpoint: Layout(x=x, y=y, w=w, h=h, minW=3, minH=3)
        for breakpoint, (x, y, w, h) in zip(
            ('sm', 'md', 'lg', 'xl', 'xxl'), (sm, md, lg, xl, xxl)
        )
    }


particle_tracking = AppEntryPoint(
    name='particle_tracking',
    description='Search for particle tracking measurements.',
    app=App(
        label='Particle Tracking',
        path='particle_tracking',
        category='Experiment',
        description='Find particle tracking measurements by sample, objective and '
        'camera settings',
        readme=(
            'Particle tracking measurements of the AGE lab. Chips and particle '
            'batches are the samples of a measurement, objectives its instruments: '
            'filter by their IDs to find all recordings of a chip or particle '
            'batch. Particle and localization counts are read from the tracks '
            'file, the filtered counts from the filtered tracks file.'
        ),
        search_quantities=SearchQuantities(
            include=[
                f'*#{tracking_schema}',
                'authors.name',
                'upload_name',
                'datasets.dataset_name',
            ]
        ),
        filters_locked={'section_defs.definition_qualified_name': [tracking_schema]},
        pagination=Pagination(order_by=tracking('datetime')),
        columns=[
            Column(search_quantity='entry_name', title='Recording', selected=True),
            Column(
                search_quantity=tracking('datetime'), title='Recorded', selected=True
            ),
            Column(
                search_quantity=tracking('samples[*].lab_id'),
                title='Samples',
                selected=True,
            ),
            Column(
                search_quantity=tracking('instruments[*].lab_id'),
                title='Instruments',
                selected=True,
            ),
            Column(
                search_quantity=tracking('illumination'),
                title='Illumination',
                selected=True,
            ),
            Column(
                search_quantity=tracking('frame_rate'),
                title='Frame rate',
                unit='Hz',
                format=Format(decimals=1, mode='standard'),
                selected=True,
            ),
            Column(search_quantity=tracking('n_frames'), title='Frames', format=count),
            Column(
                search_quantity=tracking('n_particles'),
                title='Particles',
                format=count,
                selected=True,
            ),
            Column(
                search_quantity=tracking('n_particles_filtered'),
                title='Particles (filtered)',
                format=count,
            ),
            Column(
                search_quantity=tracking('n_localizations'),
                title='Localizations',
                format=count,
            ),
            Column(
                search_quantity=tracking('n_localizations_filtered'),
                title='Localizations (filtered)',
                format=count,
            ),
            Column(
                search_quantity=tracking('exposure_time'),
                title='Exposure time',
                unit='µs',
                format=Format(decimals=0, mode='standard'),
            ),
            Column(search_quantity=tracking('camera_model'), title='Camera'),
            Column(
                search_quantity=tracking('pixel_size'),
                title='Pixel size',
                unit='µm',
                format=Format(decimals=3, mode='standard'),
            ),
            Column(search_quantity='upload_name', title='Upload'),
            Column(search_quantity='authors', title='Authors'),
            Column(search_quantity='upload_create_time', title='Uploaded'),
        ],
        # No histograms for the frame, particle and localization counts: the GUI
        # bins integers with width 1, which exceeds the Elasticsearch bucket limit
        # for localizations. The counts can be sorted in the results table instead.
        menu=Menu(
            title='Particle tracking',
            items=[
                Menu(
                    title='Samples',
                    items=[
                        MenuItemTerms(
                            search_quantity=tracking('samples.lab_id'),
                            title='Sample ID',
                        ),
                    ],
                ),
                Menu(
                    title='Microscope',
                    items=[
                        MenuItemTerms(
                            search_quantity=tracking('instruments.lab_id'),
                            title='Instrument ID',
                        ),
                        MenuItemTerms(
                            search_quantity=tracking('illumination'),
                            show_input=False,
                        ),
                        MenuItemHistogram(
                            x=Axis(search_quantity=tracking('pixel_size'), unit='µm')
                        ),
                    ],
                ),
                Menu(
                    title='Camera',
                    items=[
                        MenuItemTerms(search_quantity=tracking('camera_model')),
                        MenuItemHistogram(
                            x=Axis(search_quantity=tracking('frame_rate'), unit='Hz')
                        ),
                        MenuItemHistogram(
                            x=Axis(search_quantity=tracking('exposure_time'), unit='µs')
                        ),
                    ],
                ),
                Menu(
                    title='Recording',
                    items=[
                        MenuItemHistogram(
                            x=Axis(search_quantity=tracking('datetime')),
                            title='Recorded',
                        ),
                        MenuItemTerms(search_quantity='authors.name'),
                        MenuItemTerms(search_quantity='upload_name'),
                        MenuItemTerms(search_quantity='datasets.dataset_name'),
                    ],
                ),
            ],
        ),
        dashboard=Dashboard(
            widgets=[
                WidgetTerms(
                    search_quantity=tracking('samples.lab_id'),
                    title='Samples',
                    layout=widget_layout(
                        sm=(0, 0, 12, 5),
                        md=(0, 0, 6, 5),
                        lg=(0, 0, 8, 5),
                        xl=(0, 0, 10, 5),
                        xxl=(0, 0, 12, 5),
                    ),
                ),
                WidgetTerms(
                    search_quantity=tracking('instruments.lab_id'),
                    title='Instruments',
                    layout=widget_layout(
                        sm=(0, 5, 12, 5),
                        md=(6, 0, 6, 5),
                        lg=(8, 0, 8, 5),
                        xl=(10, 0, 10, 5),
                        xxl=(12, 0, 12, 5),
                    ),
                ),
                WidgetTerms(
                    search_quantity=tracking('illumination'),
                    title='Illumination',
                    show_input=False,
                    layout=widget_layout(
                        sm=(0, 10, 12, 4),
                        md=(12, 0, 6, 5),
                        lg=(16, 0, 8, 5),
                        xl=(20, 0, 10, 5),
                        xxl=(24, 0, 12, 5),
                    ),
                ),
                WidgetHistogram(
                    x=Axis(search_quantity=tracking('datetime')),
                    title='Recorded',
                    n_bins=30,
                    autorange=True,
                    layout=widget_layout(
                        sm=(0, 14, 12, 5),
                        md=(0, 5, 18, 5),
                        lg=(0, 5, 24, 5),
                        xl=(0, 5, 30, 5),
                        xxl=(0, 5, 36, 5),
                    ),
                ),
            ]
        ),
    ),
)
