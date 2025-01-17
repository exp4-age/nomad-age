import traceback
from typing import Union

import evaluix.utils.EvaluationFunctions as ef
import numpy as np
import pint
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
            magnetization = self.normalize_magnetization(
                archive.data['magnetic_field'], archive.data['intensity']
            )

            archive.data.magnetization = magnetization

            evaluated_hysteresis = self.hyseval(
                archive.data['magnetic_field'],
                archive.data['magnetization'],
                'tan_hyseval',
            )

            try:
                if archive.data.magnetization is not None:
                    archive.data.generate_hysteresis_plot(
                        x_name='magnetic_field', y_name='magnetization'
                    )
                else:
                    archive.data.generate_hysteresis_plot(
                        x_name='magnetic_field', y_name='intensity'
                    )
            except Exception as e:
                logger.error(f'Error generating hysteresis plot: {e}')
                logger.error(traceback.format_exc())

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
                if (
                    'd' + key in params.keys()
                ):  # if the uncertainty is present (+ 'd'), the value should be
                    # present as well
                    dkey = 'd' + key

                    setattr(archive.data, key, params[key])
                    setattr(archive.data, dkey, params[dkey])

                else:
                    setattr(archive.data, key, params[key])

    def normalize_magnetization(
        self,
        magnetic_field: Union[list, np.array],
        intensity: Union[list, np.array],
    ):
        # Normalize the magnetization data
        # magnetic_field = np.array(magnetic_field)
        # intensity = np.array(intensity)

        magnetization = ef.del_outliers(intensity.magnitude, threshold=3, neighbours=5)
        magnetization = ef.rmv_opening(magnetization, sat_region=0.1)
        magnetization = ef.slope_correction(
            magnetic_field.magnitude,
            magnetization,
            sat_region=0.1,
            noise_threshold=3,
            branch_difference=0.3,
        )
        magnetization = ef.hys_norm(
            magnetic_field.magnitude, magnetization, sat_region=0.1
        )

        # Convert the magnetization back to a pint.Quantity object
        magnetization_quantity = pint.Quantity(magnetization, intensity.units)

        return magnetization_quantity

        # return magnetization

    def hyseval(
        self,
        magnetic_field: Union[list, np.array, pint.Quantity],
        magnetization: Union[list, np.array, pint.Quantity],
        model: str,
    ):
        # Evaluate the hysteresis loop
        if isinstance(magnetic_field, pint.Quantity):
            _magnetic_field = magnetic_field.magnitude
        else:
            _magnetic_field = magnetic_field

        if isinstance(magnetization, pint.Quantity):
            _magnetization = magnetization.magnitude
        else:
            _magnetization = magnetization

        # check if model is available in EvaluationFunctions
        if hasattr(ef, model):
            evaluated_hysteresis = getattr(ef, model)(_magnetic_field, _magnetization)

        return evaluated_hysteresis
