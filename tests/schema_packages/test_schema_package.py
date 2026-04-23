# import os.path

# from nomad.client import normalize_all, parse


# def test_schema_package():
#     test_file = os.path.join('tests', 'data', 'test.archive.yaml')
#     entry_archive = parse(test_file)[0]
#     normalize_all(entry_archive)

#     assert entry_archive.data.message == 'Hello Markus!'


def test_age_sample_has_lab_id():
    from nomad_age.schema_packages.age_schema import AGE_Sample

    quantity_names = [q.name for q in AGE_Sample.m_def.quantities]
    assert 'lab_id' in quantity_names, (
        "AGE_Sample must define a 'lab_id' quantity so that data.lab_id is "
        "resolvable as a search quantity in the age_samples app."
    )
