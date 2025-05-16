from nomad.config.models.plugins import SchemaPackageEntryPoint
from pydantic import Field


class AGESchemaEntryPoint(SchemaPackageEntryPoint):
    parameter: int = Field(0, description='Custom configuration parameter')

    def load(self):
        from nomad_age.schema_packages.age_schema import m_package

        return m_package  # Package with AGE wide schemata


age_schema_entry_point = AGESchemaEntryPoint(
    name='AGESchema',
    description='Entry Point for custom AGE schema.',
)


class LMOKEandVMOKESchemaEntryPoint(SchemaPackageEntryPoint):
    parameter: int = Field(0, description='Custom configuration parameter')

    def load(self):
        from nomad_age.schema_packages.LMOKEandVMOKESchema import lmoke_vmoke_package

        return lmoke_vmoke_package  # Package with LMOKE and VMOKE schemata


lmokeandvmoke_schema_entry_point = LMOKEandVMOKESchemaEntryPoint(
    name='LMOKEandVMOKESchema',
    description='Entry Point for custom LMOKE and VMOKE schema.',
)


class FieldCoolingSchemaEntryPoint(SchemaPackageEntryPoint):
    parameter: int = Field(0, description='Custom configuration parameter')

    def load(self):
        from nomad_age.schema_packages.field_cooling_schema import m_package

        return m_package  # Package with Field Cooling schemata


field_cooling_schema_entry_point = FieldCoolingSchemaEntryPoint(
    name='FieldCoolingSchema',
    description='Entry Point for custom Field Cooling schema.',
)
