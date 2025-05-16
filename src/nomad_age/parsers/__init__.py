from nomad.config.models.plugins import ParserEntryPoint
from pydantic import Field


class NewParserEntryPoint(ParserEntryPoint):
    parameter: int = Field(0, description='Custom configuration parameter')

    def load(self):
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
        from nomad_age.parsers.field_cooling_parser import FieldCoolingParser

        return FieldCoolingParser(**self.dict())


field_cooling_parser_entry_point = FieldCoolingParserEntryPoint(
    name='FieldCoolingParser',
    description='Field Cooling parser entry point configuration.',
    mainfile_name_re=r'.*\.(DAT|dat)$',
    mainfile_contents_re=r'#\s+FC-Protokoll\s+#',
)
