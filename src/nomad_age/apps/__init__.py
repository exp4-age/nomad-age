from nomad.config.models.plugins import AppEntryPoint
from nomad.config.models.ui import (
    App,
    Column,
    Columns,
    FilterMenu,
    FilterMenus,
    Menu,
    MenuItemTerms,
    SearchQuantities,
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


age_samples = AppEntryPoint(
    name='age_samples',
    description='AGE sample database.',
    app=App(
        label='AGE Samples',
        path='age_samples',
        category='Experiment',
        description='AGE samples database, used to find all our samples',
        search_quantities=SearchQuantities(
            include=['*nomad_age.schema_packages.age_schema.Sample']
        ),
        filters_locked={
            'section_defs.definition_qualified_name': [
                'nomad_age.schema_packages.age_schema.Sample'
            ]
        },
        columns=Columns(
            selected=['name', 'comment', 'state', 'entry_type'],
            options={
                'entry_type': Column(quantity='entry_type', label='Type'),
                'name': Column(quantity='data.name', label='Sample name'),
                'comment': Column(quantity='data.comment', label='Sample comment'),
                'state': Column(quantity='data.state', label='Sample state'),
            },
        ),
        menu=Menu(
            title='Sample',
            items=[
                MenuItemTerms(
                    quantity='data.name#nomad_age.schema_packages.age_schema.Sample',
                ),
                MenuItemTerms(
                    quantity='data.state#nomad_age.schema_packages.age_schema.Sample',
                ),
            ],
        ),
        dashboard={
            'widgets': [
                {
                    'type': 'terms',
                    'search_quantity':
                    'data.name#nomad_age.schema_packages.age_schema.Sample',
                    'title': 'Sample name',
                    'show_input': True,
                    'layout': {
                        'lg': {'minH': 3, 'minW': 3, 'h': 3, 'w': 6, 'x': 6, 'y': 0},
                    },
                    'query_mode': 'or',
                },
                {
                    'type': 'terms',
                    'search_quantity':
                    'data.state#nomad_age.schema_packages.age_schema.Sample',
                    'title': 'Sample state',
                    'show_input': True,
                    'layout': {
                        'lg': {'minH': 3, 'minW': 3, 'h': 3, 'w': 6, 'x': 6, 'y': 0},
                    },
                },
            ]
        },
    ),
)
