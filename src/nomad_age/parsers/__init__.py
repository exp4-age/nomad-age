from nomad.config.models.plugins import ParserEntryPoint
from pydantic import Field

from nomad_age.utils.entry_hash import install as install_entry_hash


class NewParserEntryPoint(ParserEntryPoint):
    parameter: int = Field(0, description='Custom configuration parameter')

    def load(self):
        install_entry_hash()
        from nomad_age.parsers.parser import NewParser

        return NewParser(**self.dict())


parser_entry_point = NewParserEntryPoint(
    name='NewParser',
    description='New parser entry point configuration.',
    mainfile_name_re=r'.*\.newmainfilename',
)


class LMOKEParserEntryPoint(ParserEntryPoint):
    parameter: int = Field(0, description='Custom configuration parameter')

    def load(self):
        install_entry_hash()
        from nomad_age.parsers.LMOKEparser import LMOKEParser

        return LMOKEParser(**self.dict())


lmoke_parser_entry_point = LMOKEParserEntryPoint(
    name='LMOKEParser',
    description='LMOKE parser entry point configuration.',
    mainfile_name_re=r'.*LMOKE.*\.txt',
    mainfile_contents_re=r'#\s+Meas\.\s+type\s+',
    # this is a regular expression that matches the contents of the mainfile
)


class FieldCoolingParserEntryPoint(ParserEntryPoint):
    parameter: int = Field(0, description='Custom configuration parameter')

    def load(self):
        install_entry_hash()
        from nomad_age.parsers.field_cooling_parser import FieldCoolingParser

        return FieldCoolingParser(**self.dict())


field_cooling_parser_entry_point = FieldCoolingParserEntryPoint(
    name='FieldCoolingParser',
    description='Field Cooling parser entry point configuration.',
    mainfile_name_re=r'.*\.(DAT|dat)$',
    mainfile_contents_re=r'#\s+FC-Protokoll\s+#',
)


class ParticleTrackingParserEntryPoint(ParserEntryPoint):
    parameter: int = Field(0, description='Custom configuration parameter')

    def load(self):
        install_entry_hash()
        from nomad_age.parsers.particle_tracking_parser import ParticleTrackingParser

        return ParticleTrackingParser(**self.dict())


particle_tracking_parser_entry_point = ParticleTrackingParserEntryPoint(
    name='ParticleTrackingParser',
    description=(
        'Parser for trackpy trajectory tables (*_trajs.h5) of particle tracking videos.'
    ),
    mainfile_name_re=r'.*_trajs\.h5$',
    mainfile_mime_re=r'application/x-hdf.*',
    mainfile_contents_dict={'__has_all_keys': ['trajs']},
)


class FocusSweepParserEntryPoint(ParserEntryPoint):
    parameter: int = Field(0, description='Custom configuration parameter')

    def load(self):
        install_entry_hash()
        from nomad_age.parsers.particle_tracking_parser import FocusSweepParser

        return FocusSweepParser(**self.dict())


focus_sweep_parser_entry_point = FocusSweepParserEntryPoint(
    name='FocusSweepParser',
    description='Parser for microscope focus sweeps (imgs, poss, tgs).',
    mainfile_name_re=r'.*\.h5$',
    mainfile_mime_re=r'application/x-hdf.*',
    mainfile_contents_dict={'__has_all_keys': ['imgs', 'poss', 'tgs']},
)


class ParticleTransportVideoParserEntryPoint(ParserEntryPoint):
    parameter: int = Field(0, description='Custom configuration parameter')

    def load(self):
        install_entry_hash()
        from nomad_age.parsers.particle_tracking_parser import (
            ParticleTransportVideoParser,
        )

        return ParticleTransportVideoParser(**self.dict())


particle_transport_video_parser_entry_point = ParticleTransportVideoParserEntryPoint(
    name='ParticleTransportVideoParser',
    description='Parser for particle transport videos (HDF5 with a frames dataset).',
    mainfile_name_re=r'.*\.h5$',
    mainfile_mime_re=r'application/x-hdf.*',
    mainfile_contents_dict={'__has_all_keys': ['frames']},
)
