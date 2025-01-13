from nomad.config.models.plugins import SchemaPackageEntryPoint
from pydantic import Field


class NewSchemaPackageEntryPoint(SchemaPackageEntryPoint):
    parameter: int = Field(0, description='Custom configuration parameter')

    def load(self):
        from nomad_age.schema_packages.schema_package import m_package

        return m_package


schema_package_entry_point = NewSchemaPackageEntryPoint(
    name='NewSchemaPackage',
    description='New schema package entry point configuration.',
)


class LMOKEandVMOKESchemaEntryPoint(SchemaPackageEntryPoint):
    parameter: int = Field(0, description='Custom configuration parameter')

    def load(self):
        from nomad_age.schema_packages.LMOKEandVMOKESchema import lmoke_vmoke_package

        return lmoke_vmoke_package # Package with LMOKE and VMOKE schemas

lmokeandvmoke_schema_entry_point = LMOKEandVMOKESchemaEntryPoint(
    name = 'LMOKEandVMOKESchema',
    description = 'Entry Point for custom LMOKE and VMOKE schema.',
)