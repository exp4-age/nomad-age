from nomad.config.models.plugins import NormalizerEntryPoint
from pydantic import Field

from nomad_age.utils.entry_hash import install as install_entry_hash


class NewNormalizerEntryPoint(NormalizerEntryPoint):
    parameter: int = Field(0, description='Custom configuration parameter')

    def load(self):
        install_entry_hash()
        from nomad_age.normalizers.normalizer import NewNormalizer

        return NewNormalizer(**self.dict())


normalizer_entry_point = NewNormalizerEntryPoint(
    name='NewNormalizer',
    description='New normalizer entry point configuration.',
)


class LMOKENormalizerEntryPoint(NormalizerEntryPoint):
    def load(self):
        install_entry_hash()
        from nomad_age.normalizers.LMOKEnormalizer import LMOKENormalizer

        return LMOKENormalizer(**self.dict())


lmokenormalizer_entry_point = LMOKENormalizerEntryPoint(
    name='LMOKE Magnetization Normalizer',
    description=(
        r'Normalizes the normalized magnetization data from LMOKE measurements. '
        r'Requires saturation in the outermost 10\% of the data.'
    ),
)
