def test_field_cooling_parser():
    """This all does not work yet.
    There is a lot of database manipulation in the parser.
    the whole text parsing should probably be taken out into a TextParser"""
    pass
    # parser = FieldCoolingParser()
    # archive = EntryArchive(metadata=EntryMetadata(upload_id="test_upload_id"))

    # # Path to your test file in tests/data/fieldcooling
    # test_file = "tests/data/fieldcooling/2024.10.18-2024_0207, 2024_0208 2nd time.DAT"

    # # Run the parser
    # parser.parse(test_file, archive, logging.getLogger())

    # # Access parsed data through archive.data
    # entry = archive.data

    # # Test metadata parsing
    # # TODO: Samples
    # # assert isinstance(entry.samples, MSubSectionList)
    # # assert [sample.name for sample in entry.samples] == ['2024_0207', '2024_0208']
    # assert entry.datetime == datetime(2024, 10, 18, 17, 37, 59, tzinfo=timezone.utc)
    # assert entry.blocking_temperature == ureg.Quantity(350.0, ureg.degC)
    # assert entry.plateau_duration == ureg.Quantity(60.0, ureg.minute)
    # assert entry.cooling_rate == ureg.Quantity(50.0, ureg.delta_degC / ureg.minute)

    # # Test time series data
    # assert entry.time[0] == 0.0
    # assert entry.measured_temperature[0] == ureg.Quantity(44.7486074, ureg.degC)
    # assert entry.target_temperature[0] == ureg.Quantity(25.0, ureg.degC)
    # assert entry.pirani_pressure[0] == ureg.Quantity(0.2430133, ureg.mbar)
    # assert entry.penning_pressure[0] == ureg.Quantity(0.0000040, ureg.mbar)
    # assert len(entry.time) == 23682
