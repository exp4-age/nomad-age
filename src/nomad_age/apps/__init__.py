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
    MenuItemVisibility,
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
coated_sample_schema = 'nomad_age.schema_packages.age_schema.AGE_CoatedSample'
spin_coating_schema = 'nomad_age.schema_packages.age_schema.AGE_SpinCoating'
base_entity_schema = 'nomad.datamodel.metainfo.basesections.v1.BaseSection'
sample_item_schema = 'nomad_age.schema_packages.age_schema.AGE_SampleItem'
age_samples = AppEntryPoint(
    name='age_samples',
    description='AGE sample database.',
    app=App(
        label='AGE Samples',
        path='age_samples',
        category='Experiment',
        description='AGE samples database, used to find all our samples',
        readme=(
            'Chips (AGE Sample), their coated states (Coated chip: one spacer '
            'layer, e.g. PMMA, with its thickness) and the spin coatings that '
            'made them. Filter by type to see only one of them.'
        ),
        search_quantities=SearchQuantities(
            include=[
                f'*#{sample_schema}',
                f'*#{coated_sample_schema}',
                f'*#{spin_coating_schema}',
                f'*#{base_entity_schema}',
                'entry_type',
            ]
        ),
        # One marker base section: a locked list of types matches only entries
        # of all of them, i.e. none.
        filters_locked={'section_defs.definition_qualified_name': [sample_item_schema]},
        columns=Columns(
            selected=['lab_id', 'state', 'entry_type', 'spacer_thickness'],
            options={
                'entry_type': Column(quantity='entry_type', label='Type'),
                'lab_id': Column(
                    quantity=f'data.lab_id#{base_entity_schema}', label='Sample ID'
                ),
                'state': Column(
                    quantity=f'data.state#{sample_schema}', label='Sample state'
                ),
                'spacer_material': Column(
                    search_quantity=f'data.spacer_material#{coated_sample_schema}',
                    title='Spacer material',
                ),
                'spacer_thickness': Column(
                    search_quantity=f'data.spacer_thickness#{coated_sample_schema}',
                    title='Spacer thickness',
                    unit='nm',
                    format=Format(decimals=0, mode='standard'),
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
                MenuItemTerms(search_quantity='entry_type', title='Type'),
                MenuItemTerms(
                    search_quantity=f'data.spacer_material#{coated_sample_schema}',
                    title='Spacer material',
                ),
                MenuItemHistogram(
                    x=Axis(
                        search_quantity=f'data.spacer_thickness#{coated_sample_schema}',
                        unit='nm',
                    ),
                    title='Spacer thickness',
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

age_schema = 'nomad_age.schema_packages.age_schema'
particles_schema = f'{age_schema}.AGE_Particles'
objective_schema = f'{age_schema}.AGE_Objective'
# All inventory entry types (lab equipment and consumables). A new type, e.g.
# cameras, magnets or chemicals, derives from AGE_InventoryItem and is added
# here: the AGE Inventory app includes every type in this tuple. Its own
# quantities get a column or menu item only where added explicitly below.
INVENTORY_SCHEMAS = (particles_schema, objective_schema)
inventory_item_schema = f'{age_schema}.AGE_InventoryItem'


def particles(path: str) -> str:
    """Search quantity of a particle batch."""
    return f'data.{path}#{particles_schema}'


def objective(path: str) -> str:
    """Search quantity of a microscope objective."""
    return f'data.{path}#{objective_schema}'


# name, lab_id and description are BaseSection quantities: NOMAD 1.4.3 registers
# them under BaseSection as well, which finds them in every inventory type
# (CompositeSystem- and Instrument-based alike).
def base_entity(path: str) -> str:
    """Search quantity of all inventory types."""
    return f'data.{path}#{base_entity_schema}'


age_inventory = AppEntryPoint(
    name='age_inventory',
    description='AGE inventory: lab equipment and consumables.',
    app=App(
        label='AGE Inventory',
        path='age_inventory',
        category='Experiment',
        description='Find the particle batches and objectives of the AGE lab',
        readme=(
            'Inventory of the AGE lab: particle batches (Particles: particle '
            'type, batch and batch date) and microscope objectives (Objective: '
            'magnification and numerical aperture). Filter by type to see only '
            'one of them. Recordings link particles under samples and objectives '
            'under instruments. To see where an item was used, open it: '
            "'Referenced by' in Entry References lists the recordings linking it."
        ),
        search_quantities=SearchQuantities(
            include=[
                *(f'*#{schema}' for schema in INVENTORY_SCHEMAS),
                f'*#{base_entity_schema}',
                'entry_type',
                'authors.name',
                'upload_name',
                'datasets.dataset_name',
            ]
        ),
        # One marker base section (all INVENTORY_SCHEMAS derive from it): a
        # locked list of types matches only entries of all of them, i.e. none.
        filters_locked={
            'section_defs.definition_qualified_name': [inventory_item_schema]
        },
        columns=[
            Column(search_quantity='entry_type', title='Type', selected=True),
            Column(search_quantity=base_entity('name'), title='Name', selected=True),
            Column(search_quantity=base_entity('lab_id'), title='ID', selected=True),
            Column(search_quantity=base_entity('description'), title='Description'),
            Column(
                search_quantity=particles('particle_type'),
                title='Particle type',
                selected=True,
            ),
            Column(search_quantity=particles('batch'), title='Batch', selected=True),
            Column(
                search_quantity=particles('batch_date'),
                title='Batch date',
                selected=True,
            ),
            Column(
                search_quantity=objective('magnification'),
                title='Magnification',
                selected=True,
            ),
            Column(
                search_quantity=objective('numerical_aperture'),
                title='NA',
                format=Format(decimals=2, mode='standard'),
                selected=True,
            ),
            Column(search_quantity='entry_create_time', title='Created', selected=True),
            Column(search_quantity='upload_create_time', title='Uploaded'),
            Column(search_quantity='upload_name', title='Upload'),
            Column(search_quantity='authors', title='Authors'),
        ],
        menu=Menu(
            title='Inventory',
            items=[
                MenuItemTerms(search_quantity='entry_type', title='Type'),
                MenuItemTerms(search_quantity=base_entity('name'), title='Name'),
                MenuItemTerms(search_quantity=base_entity('lab_id'), title='ID'),
                Menu(
                    title='Particles',
                    items=[
                        MenuItemTerms(
                            search_quantity=particles('particle_type'),
                            title='Particle type',
                        ),
                        MenuItemTerms(
                            search_quantity=particles('batch'), title='Batch'
                        ),
                        MenuItemHistogram(
                            x=Axis(search_quantity=particles('batch_date')),
                            title='Batch date',
                        ),
                    ],
                ),
                Menu(
                    title='Objectives',
                    # Histograms: NOMAD 1.4.3 has no terms aggregation for
                    # float quantities of a schema.
                    items=[
                        MenuItemHistogram(
                            x=Axis(search_quantity=objective('magnification')),
                            title='Magnification',
                        ),
                        MenuItemHistogram(
                            x=Axis(search_quantity=objective('numerical_aperture')),
                            title='Numerical aperture',
                        ),
                    ],
                ),
                Menu(
                    title='Author / Origin',
                    items=[
                        MenuItemTerms(search_quantity='authors.name'),
                        MenuItemTerms(search_quantity='upload_name'),
                        MenuItemTerms(search_quantity='datasets.dataset_name'),
                        MenuItemHistogram(
                            x=Axis(search_quantity='upload_create_time'),
                            title='Uploaded',
                        ),
                        MenuItemVisibility(),
                    ],
                ),
            ],
        ),
    ),
)

schema_package = 'nomad_age.schema_packages.particle_tracking_schema'
video_schema = f'{schema_package}.AGE_ParticleTransportVideo'


def video(path: str) -> str:
    """Search quantity of a particle transport video."""
    return f'data.{path}#{video_schema}'


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


def particle_transport_app(
    *,
    schema: str,
    label: str,
    path: str,
    description: str,
    readme: str,
    menu_title: str,
    columns: list,
) -> App:
    """Search app for one entry type of particle transport experiments.

    Videos and tracks share the recording quantities; `columns` are the
    type-specific ones, shown after the frame count. NOMAD 1.4.3 registers
    nested search quantities such as samples.lab_id only per entry type, so each
    type gets its own app.
    """

    def q(quantity: str) -> str:
        return f'data.{quantity}#{schema}'

    return App(
        label=label,
        path=path,
        category='Experiment',
        description=description,
        readme=readme,
        search_quantities=SearchQuantities(
            include=[
                f'*#{schema}',
                'authors.name',
                'upload_name',
                'datasets.dataset_name',
            ]
        ),
        filters_locked={'section_defs.definition_qualified_name': [schema]},
        pagination=Pagination(order_by=q('datetime')),
        columns=[
            Column(search_quantity='entry_name', title='Recording', selected=True),
            Column(search_quantity=q('datetime'), title='Recorded', selected=True),
            Column(search_quantity=q('lab_id'), title='Recording ID'),
            Column(
                search_quantity=q('samples[*].lab_id'), title='Samples', selected=True
            ),
            Column(
                search_quantity=q('particles[*].name'), title='Particles', selected=True
            ),
            Column(search_quantity=q('chips[*].name'), title='Chips'),
            Column(
                search_quantity=q('spacer_thickness'),
                title='Spacer thickness',
                unit='nm',
                format=Format(decimals=0, mode='standard'),
            ),
            Column(
                search_quantity=q('instruments[*].name'),
                title='Instruments',
                selected=True,
            ),
            Column(
                search_quantity=q('illumination'), title='Illumination', selected=True
            ),
            Column(
                search_quantity=q('frame_rate'),
                title='Frame rate',
                unit='Hz',
                format=Format(decimals=1, mode='standard'),
                selected=True,
            ),
            Column(search_quantity=q('n_frames'), title='Frames', format=count),
            *columns,
            Column(
                search_quantity=q('exposure_time'),
                title='Exposure time',
                unit='µs',
                format=Format(decimals=0, mode='standard'),
            ),
            Column(search_quantity=q('camera_model'), title='Camera'),
            Column(
                search_quantity=q('pixel_size'),
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
            title=menu_title,
            items=[
                Menu(
                    title='Samples',
                    items=[
                        MenuItemTerms(
                            search_quantity=q('particles.name'), title='Particles'
                        ),
                        MenuItemTerms(search_quantity=q('chips.name'), title='Chips'),
                        MenuItemHistogram(
                            x=Axis(search_quantity=q('spacer_thickness'), unit='nm'),
                            title='Spacer thickness',
                        ),
                        MenuItemTerms(
                            search_quantity=q('samples.lab_id'), title='Sample ID'
                        ),
                    ],
                ),
                Menu(
                    title='Microscope',
                    items=[
                        MenuItemTerms(
                            search_quantity=q('instruments.name'),
                            title='Instruments',
                        ),
                        MenuItemTerms(
                            search_quantity=q('instruments.lab_id'),
                            title='Instrument ID',
                        ),
                        MenuItemTerms(
                            search_quantity=q('illumination'), show_input=False
                        ),
                        MenuItemHistogram(
                            x=Axis(search_quantity=q('pixel_size'), unit='µm')
                        ),
                    ],
                ),
                Menu(
                    title='Camera',
                    items=[
                        MenuItemTerms(search_quantity=q('camera_model')),
                        MenuItemHistogram(
                            x=Axis(search_quantity=q('frame_rate'), unit='Hz')
                        ),
                        MenuItemHistogram(
                            x=Axis(search_quantity=q('exposure_time'), unit='µs')
                        ),
                    ],
                ),
                Menu(
                    title='Recording',
                    items=[
                        MenuItemTerms(
                            search_quantity=q('lab_id'),
                            title='Recording ID',
                            options=0,  # one value per recording: input only
                        ),
                        MenuItemHistogram(
                            x=Axis(search_quantity=q('datetime')), title='Recorded'
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
                    search_quantity=q('samples.lab_id'),
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
                    search_quantity=q('instruments.name'),
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
                    search_quantity=q('illumination'),
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
                    x=Axis(search_quantity=q('datetime')),
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
    )


particle_transport_videos = AppEntryPoint(
    name='particle_transport_videos',
    description='Search for particle transport videos.',
    app=particle_transport_app(
        schema=video_schema,
        label='Particle Transport Videos',
        path='particle_transport_videos',
        description='Find particle transport videos by recording ID, sample, '
        'objective and camera settings',
        readme=(
            'Camera videos of particle transport experiments, as saved by '
            'harvesters_pg; each entry shows the camera settings and the first '
            'frame. Chips (or coated chips) and particle batches are the samples, '
            'objectives the instruments; filter by particles, chips or the spacer '
            'thickness of a coated chip. The recording ID is the random id that '
            'the acquisition software gives each recording. The trajectories '
            'tracked from a video (with their particle and localization counts) '
            "are listed under 'Referenced by' in the video's Entry References."
        ),
        menu_title='Particle transport videos',
        columns=[
            Column(
                search_quantity=video('duration'),
                title='Duration',
                unit='s',
                format=Format(decimals=1, mode='standard'),
                selected=True,
            ),
            Column(search_quantity=video('frame_width'), title='Width', format=count),
            Column(search_quantity=video('frame_height'), title='Height', format=count),
        ],
    ),
)
