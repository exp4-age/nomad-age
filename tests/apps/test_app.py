import importlib

import pytest
from nomad.datamodel.data import EntryData
from nomad.datamodel.metainfo.basesections import BaseSection

from nomad_age import apps
from nomad_age.schema_packages.age_schema import (
    AGE_InventoryItem,
)

APPS = [
    entry_point.app
    for entry_point in vars(apps).values()
    if isinstance(entry_point, apps.AppEntryPoint)
]


def search_quantities(value):
    """The search_quantity values of an app config dump, at any depth."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key == 'search_quantity' and isinstance(item, str):
                yield item
            else:
                yield from search_quantities(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from search_quantities(item)


def schema_quantities(app) -> list:
    """(path, section definition) of the quantities of this plugin's schemas
    that an app shows."""
    dump = getattr(app, 'model_dump', None) or app.dict
    quantities = []
    for search_quantity in dict.fromkeys(search_quantities(dump())):
        if (
            not search_quantity.startswith('data.')
            or '#nomad_age.' not in search_quantity
        ):
            continue
        path, qualified_name = search_quantity[len('data.') :].split('#')
        module, name = qualified_name.rsplit('.', 1)
        section = getattr(importlib.import_module(module), name)
        quantities.append((path, section.m_def))
    return quantities


@pytest.mark.parametrize('app', APPS, ids=lambda app: app.path)
def test_app_columns_menus_and_widgets_show_schema_quantities(app):
    for path, section_def in schema_quantities(app):
        *sub_sections, quantity = path.replace('[*]', '').split('.')
        for name in sub_sections:
            section_def = section_def.all_sub_sections[name].sub_section
        assert quantity in section_def.all_quantities, f'{path} of {section_def.name}'


def test_inventory_app_is_a_valid_registered_plugin():
    from nomad.config import config

    config.load_plugins()
    entry_point = config.get_plugin_entry_point('nomad_age.apps:age_inventory')
    assert entry_point.app.label == 'AGE Inventory'
    assert entry_point.app.category == 'Experiment'


def test_inventory_app_shows_every_inventory_type():
    """The inventory types are the AGE_Particles and AGE_Objective entries; the
    app locks to and includes exactly the types of INVENTORY_SCHEMAS, and the
    name, ID and description columns (BaseSection) apply to all of them."""
    types = []
    for qualified_name in apps.INVENTORY_SCHEMAS:
        module, name = qualified_name.rsplit('.', 1)
        types.append(getattr(importlib.import_module(module), name))
    assert {section.__name__ for section in types} >= {'AGE_Particles', 'AGE_Objective'}
    for section in types:
        assert issubclass(section, EntryData)
        assert issubclass(section, BaseSection)

    app = apps.age_inventory.app
    # locked to one marker base section: a list of types would match only
    # entries of all types at once, i.e. none
    assert app.filters_locked == {
        'section_defs.definition_qualified_name': [apps.inventory_item_schema]
    }
    assert apps.inventory_item_schema.endswith('.AGE_InventoryItem')
    for section in types:
        assert issubclass(section, AGE_InventoryItem)
    for qualified_name in apps.INVENTORY_SCHEMAS:
        assert f'*#{qualified_name}' in app.search_quantities.include
    # The app names the production (NOMAD 1.4) BaseSection, which differs from
    # the one of the nomad-lab version tests may run with.
    base_entity = f'#{apps.base_entity_schema}'
    assert {
        column.search_quantity
        for column in app.columns
        if column.search_quantity.endswith(base_entity)
    } == {f'data.{name}{base_entity}' for name in ('name', 'lab_id', 'description')}


def test_apps_lock_to_one_value_only():
    """NOMAD ANDs the values of a locked filter; with several types no entry
    matches (empty app)."""
    for app in (apps.age_inventory.app, apps.age_samples.app):
        for values in app.filters_locked.values():
            assert len(values) == 1


def test_sample_app_shows_chips_only():
    """Coated chips and spin coatings are reached from their chip (Referenced
    by), not listed in the samples app."""
    app = apps.age_samples.app
    assert app.filters_locked == {
        'section_defs.definition_qualified_name': [apps.sample_schema]
    }
    for schema in (apps.coated_sample_schema, apps.spin_coating_schema):
        assert f'*#{schema}' not in app.search_quantities.include
