import importlib

import pytest

from nomad_age import apps

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
