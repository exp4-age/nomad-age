from typing import Union

import evaluix.utils.EvaluationFunctions as ef
import numpy as np
from nomad.datamodel import EntryArchive
from nomad.normalizing import Normalizer


class LMOKENormalizer(Normalizer):
    def normalize(
        self,
        archive: EntryArchive,
        logger=None,
    ) -> None:
        logger.info('LMOKENormalizer called')

        # Check if the archive has magnetic field and intensity but
        # no magnetization data
        if (
            archive.data
            and 'magnetic_field' in archive.data
            and 'intensity' in archive.data
        ):
            logger.info('Normalizing magnetization data')
            # Normalize the magnetization data
            archive.data.magnetization = self.normalize_magnetization(
                archive.data['magnetic_field'], archive.data['intensity']
            )

            evaluated_hysteresis = self.hyseval(
                archive.data['magnetic_field'],
                archive.data['magnetization'],
                'tan_hyseval',
            )
            # depending if fitted (analytical) or calculated, the output is different
            NUMERICAL_LENGTH = 1
            ANALYTICAL_LENGTH = 3
            if len(evaluated_hysteresis) == NUMERICAL_LENGTH:
                params = evaluated_hysteresis
            elif len(evaluated_hysteresis) == ANALYTICAL_LENGTH:
                params = evaluated_hysteresis[1]
            else:
                params = {}

            # Add the evaluated hysteresis parameters to the archive
            for key in params.keys():
                if 'd' + key in params:  # quantities with uncertainties
                    dkey = 'd' + key

                    setattr(archive.data, key, params[key])
                    setattr(archive.data, dkey, params[dkey])

                elif key in ['r_squared']:  # quantities without uncertainties
                    # so far just r_squared
                    setattr(archive.data, key, params[key])

    def normalize_magnetization(
        self,
        magnetic_field: Union[list, np.array],
        intensity: Union[list, np.array],
    ):
        # Normalize the magnetization data
        magnetic_field = np.array(magnetic_field)
        intensity = np.array(intensity)

        magnetization = ef.del_outliers(intensity, threshold=3, neighbours=5)
        magnetization = ef.rmv_opening(magnetization, sat_region=0.1)
        magnetization = ef.slope_correction(
            magnetic_field,
            magnetization,
            sat_region=0.1,
            noise_threshold=3,
            branch_difference=0.3,
        )
        magnetization = ef.hys_norm(magnetic_field, magnetization, sat_region=0.1)

        return magnetization

    def hyseval(
        self,
        magnetic_field: Union[list, np.array],
        magnetization: Union[list, np.array],
        model: str,
    ):
        # Evaluate the hysteresis loop
        magnetic_field = np.array(magnetic_field)
        magnetization = np.array(magnetization)

        # check if model is available in EvaluationFunctions
        if hasattr(ef, model):
            evaluated_hysteresis = getattr(ef, model)(magnetic_field, magnetization)

        return evaluated_hysteresis
