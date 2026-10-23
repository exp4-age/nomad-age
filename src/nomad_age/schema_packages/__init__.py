from nomad.config.models.plugins import SchemaPackageEntryPoint
from pydantic import Field

from nomad_age.utils.entry_hash import install as install_entry_hash


class AGESchemaEntryPoint(SchemaPackageEntryPoint):
    parameter: int = Field(0, description='Custom configuration parameter')

    def load(self):
        install_entry_hash()
        from nomad_age.schema_packages.age_schema import m_package

        return m_package  # Package with AGE wide schemata


age_schema_entry_point = AGESchemaEntryPoint(
    name='AGESchema',
    description='Entry Point for custom AGE schema.',
)


class LMOKEandVMOKESchemaEntryPoint(SchemaPackageEntryPoint):
    parameter: int = Field(0, description='Custom configuration parameter')

    def load(self):
        install_entry_hash()
        from nomad_age.schema_packages.LMOKEandVMOKESchema import lmoke_vmoke_package

        return lmoke_vmoke_package  # Package with LMOKE and VMOKE schemata


lmokeandvmoke_schema_entry_point = LMOKEandVMOKESchemaEntryPoint(
    name='LMOKEandVMOKESchema',
    description='Entry Point for custom LMOKE and VMOKE schema.',
)


class FieldCoolingSchemaEntryPoint(SchemaPackageEntryPoint):
    parameter: int = Field(0, description='Custom configuration parameter')

    def load(self):
        install_entry_hash()
        from nomad_age.schema_packages.field_cooling_schema import m_package

        return m_package  # Package with Field Cooling schemata


field_cooling_schema_entry_point = FieldCoolingSchemaEntryPoint(
    name='FieldCoolingSchema',
    description='Entry Point for custom Field Cooling schema.',
)


class ParticleTrackingSchemaEntryPoint(SchemaPackageEntryPoint):
    parameter: int = Field(0, description='Custom configuration parameter')

    def load(self):
        install_entry_hash()
        from nomad_age.schema_packages.particle_tracking_schema import m_package

        return m_package  # Package with particle tracking and focus sweep schemata


particle_tracking_schema_entry_point = ParticleTrackingSchemaEntryPoint(
    name='ParticleTrackingSchema',
    description='Entry Point for particle tracking and focus sweep schemata.',
)


class IonBombardmentSchemaEntryPoint(SchemaPackageEntryPoint):
    parameter: int = Field(0, description='Custom configuration parameter')

    def load(self):
        install_entry_hash()
        from nomad_age.schema_packages.ion_bombardment_schema import m_package

        return m_package  # Package with the helium ion bombardment schema


ion_bombardment_schema_entry_point = IonBombardmentSchemaEntryPoint(
    name='IonBombardmentSchema',
    description='Entry Point for the helium ion bombardment (ISA) schema.',
)
