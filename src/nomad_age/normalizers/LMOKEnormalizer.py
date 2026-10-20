import traceback
from typing import Union

import evaluix.utils.hysteresis_functions as ef
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
                'arctan_hyseval',
            )

            try:
                archive.data.generate_hysteresis_plot()
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

            # Add the evaluated hysteresis parameters to the archive.
            # evaluix suffixes per-loop results with the loop index ('HC_1');
            # raw fit parameters (a, b_1, ...) have no schema quantity and are skipped.
            quantities = archive.data.m_def.all_quantities
            for key, value in params.items():
                name = key.removesuffix('_1')
                quantity = quantities.get(name)
                if quantity is None:
                    continue
                if quantity.shape and np.ndim(value) == 0:
                    value = np.full(quantity.shape, value)
                setattr(archive.data, name, value)

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
