from typing import Dict, List, Union
import numpy as np

from nomad.datamodel import EntryArchive
from nomad.normalizing import Normalizer

import evaluix.utils.EvaluationFunctions as ef

class LMOKENormalizer(Normalizer):
    def normalize(
        self,
        archive: EntryArchive,
        logger=None,
    ) -> None:
        logger.info('LMOKENormalizer called')

        # Check if the archive has magnetic field and intensity data but no magnetization data
        if archive.data and 'magnetic_field' in archive.data and 'intensity' in archive.data:
            logger.info('Normalizing magnetization data')
            # Normalize the magnetization data
            archive.data.magnetization = self.normalize_magnetization(archive.data['magnetic_field'], archive.data['intensity'])

            evaluated_hysteresis = self.hyseval(archive.data['magnetic_field'], archive.data['magnetization'], 'tan_hyseval')
            if len(evaluated_hysteresis) == 1:
                params = evaluated_hysteresis
            elif len(evaluated_hysteresis) == 3:
                params = evaluated_hysteresis[1]
            else:
                params = {}

            if 'HEB' in params:
                archive.data.HEB = params['HEB']
                archive.data.dHEB = params['dHEB']
            if 'HC' in params:
                archive.data.HC = params['HC']
                archive.data.dHC = params['dHC']
            if 'MS' in params:
                archive.data.MS = params['MS']
                archive.data.dMS = params['dMS']
            if 'MR' in params: # Not yet in the official evaluix package. Once added, this will be updated to the lower case version
                archive.data.MR = params['MR']
                archive.data.dMR = params['dMR']
            if 'MHEB' in params: # Not yet in the official evaluix package. Once added, this will be updated to the lower case version
                archive.data.MHEB = params['MHEB']
                archive.data.dMHEB = params['dMHEB']
            if 'integral' in params:
                archive.data.integral = params['integral']
                archive.data.dintegral = params['dintegral']
            if 'saturation_fields' in params:
                archive.data.saturation_fields = params['saturation_fields']
                archive.data.dsaturation_fields = params['dsaturation_fields']
            if 'slope_atHC' in params:
                archive.data.slope_atHC = params['slope_atHC']
                archive.data.dslope_atHC = params['dslope_atHC']
            if 'slope_atHEB' in params:
                archive.data.slope_atHEB = params['slope_atHEB']
                archive.data.dslope_atHEB = params['dslope_atHEB']
            if 'alpha' in params:
                archive.data.alpha = params['alpha']
                archive.data.dalpha = params['dalpha']
            if 'rectangularity' in params:
                archive.data.rectangularity = params['rectangularity']
                archive.data.drectangularity = params['drectangularity']

            ### TODO: Activate once evaluix is updated. Delete the above if statements
            # for key in params.keys():
            #     if "d" + key in params: # quantities with uncertainties
            #         archive.data[key] = params[key]
            #         archive.data["d" + key] = params["d" + key]

            #     elif key in ["r_squared"]: # quantities without uncertainties, so far just r_squared
            #         archive.data[key] = params[key]

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
        magnetization = ef.slope_correction(magnetic_field, magnetization, sat_region=0.1, noise_threshold=3, branch_difference=0.3)
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