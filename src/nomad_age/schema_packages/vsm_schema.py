from typing import Optional

import numpy as np
import plotly.graph_objects as go
from nomad.config import config
from nomad.datamodel.data import EntryData
from nomad.datamodel.metainfo.annotations import ELNAnnotation, SectionProperties
from nomad.datamodel.metainfo.plot import PlotlyFigure, PlotSection
from nomad.metainfo import Quantity, SchemaPackage, Section

from nomad_age.schema_packages.age_schema import (
    AGE_FromRawFile,
    AGE_MagnetisationMeasurement,
    local_time,
)

configuration = config.get_plugin_entry_point(
    'nomad_age.schema_packages:vsm_schema_entry_point'
)

m_package = SchemaPackage(name='vsm_schema')

VSM_TECHNIQUE = 'VSM'
# Fewer points are no loop.
MIN_PLOT_POINTS = 3


def branch_split(field) -> int:
    """Index of the field minimum: the loop runs +Hmax -> -Hmax -> +Hmax, so the
    descending branch is [:index + 1] and the ascending one [index + 1:]."""
    return int(np.argmin(field))


class AGE_VSM(PlotSection, AGE_FromRawFile, AGE_MagnetisationMeasurement, EntryData):
    m_def = Section(
        label='VSM',
        description=(
            'A hysteresis loop of the home-built vibrating sample magnetometer '
            '(LabVIEW VSM_1.0beta), parsed from its <measurement no>_VSM_<chip>.asc '
            'file.'
        ),
        a_eln=ELNAnnotation(
            properties=SectionProperties(
                order=[
                    'name',
                    'sample',
                    'sample_state',
                    'measurement_time',
                    'measurement_number',
                    'sample_angle',
                    'HEB_left',
                    'HC_left',
                    'loop_shift_left',
                    'HEB_right',
                    'HC_right',
                    'loop_shift_right',
                    'user_id',
                    'comment',
                    'db_charge_id',
                    'db_chip_number',
                    'db_instrument_id',
                ],
            )
        ),
    )

    name = Quantity(
        type=str,
        description='Name of the measurement: VSM <measurement no> <chip> <state>.',
    )

    sample = Quantity(
        type=str,
        description='Lab id of the chip, from the file name.',
    )

    sample_state = Quantity(
        type=str,
        description=(
            'State of the chip at the measurement (Messzeitpunkt), e.g. as made, '
            'after FC, after IB.'
        ),
    )

    measurement_number = Quantity(
        type=int,
        description='Number of the measurement in the lab database (file name prefix).',
    )

    sample_angle = Quantity(
        type=float,
        unit='deg',
        description='Angle of the sample (Hys_Winkel).',
    )

    HEB_left = Quantity(
        type=float,
        unit='kA/m',
        description=(
            'Exchange bias field of the left loop component, H_EB = -loop_shift_left '
            '(sign convention H_EB = -(loop shift); the lab database stores the loop '
            'shift as HEB). None if the component is not fitted.'
        ),
    )

    HC_left = Quantity(
        type=float,
        unit='kA/m',
        description=(
            'Coercive field (half width) of the left loop component; a single-loop '
            'fit is written here. None if not fitted.'
        ),
    )

    loop_shift_left = Quantity(
        type=float,
        unit='kA/m',
        description=(
            'Centre of the left loop component as the VSM program writes it '
            '(Hys_HEB_links, called HEB in the lab database). None if not fitted.'
        ),
    )

    HEB_right = Quantity(
        type=float,
        unit='kA/m',
        description=(
            'Exchange bias field of the right loop component, H_EB = '
            '-loop_shift_right (sign convention H_EB = -(loop shift); the lab '
            'database stores the loop shift as HEB). None if the component is not '
            'fitted (single-loop fits).'
        ),
    )

    HC_right = Quantity(
        type=float,
        unit='kA/m',
        description=(
            'Coercive field (half width) of the right loop component. None if not '
            'fitted (single-loop fits).'
        ),
    )

    loop_shift_right = Quantity(
        type=float,
        unit='kA/m',
        description=(
            'Centre of the right loop component as the VSM program writes it '
            '(Hys_HEB_rechts, called HEB in the lab database). None if not fitted.'
        ),
    )

    user_id = Quantity(
        type=int,
        description='Id of the user in the user list of the VSM program (Hys_User).',
    )

    comment = Quantity(
        type=str,
        description='Comment of the measurement (Hys_Kom).',
    )

    db_charge_id = Quantity(
        type=int,
        description=(
            'Id of the sputter run in the lab database (ChargenID); the chip is '
            'named by the file name, not by this id.'
        ),
    )

    db_chip_number = Quantity(
        type=int,
        description='Number of the chip within its sputter run (ProbenID).',
    )

    db_instrument_id = Quantity(
        type=int,
        description='Id of the instrument in the lab database (AnlagenID; 3 = VSM).',
    )

    field_voltage = Quantity(
        type=float,
        shape=['*'],
        unit='V',
        description='Gaussmeter voltage (B-Feld [V]).',
    )

    signal = Quantity(
        type=float,
        shape=['*'],
        unit='V',
        description=(
            'Lock-in voltage (Ms-Probe [V]), proportional to the magnetic moment of '
            'the sample; not calibrated.'
        ),
    )

    magnetic_field = Quantity(
        type=float,
        shape=['*'],
        unit='kA/m',
        description='Magnetic field H (column B-Feld[kA/m]).',
    )

    def magnetisation_title(self) -> str:
        """Technique, lab date (the file has no time of day) and sample state."""
        parts = [self.technique or VSM_TECHNIQUE]
        if self.measurement_time is not None:
            parts.append(f'{local_time(self.measurement_time):%Y-%m-%d}')
        if self.sample_state:
            parts.append(self.sample_state)
        return ', '.join(parts)

    def magnetisation_figure(self) -> Optional[dict]:
        """Signal against the field, descending and ascending branch."""
        if self.magnetic_field is None or self.signal is None:
            return None
        field = np.asarray(self.magnetic_field.to('kA/m').magnitude, dtype=float)
        signal = np.asarray(self.signal.to('V').magnitude, dtype=float)
        if len(field) < MIN_PLOT_POINTS or len(field) != len(signal):
            return None
        split = branch_split(field) + 1
        figure = go.Figure(
            [
                go.Scatter(
                    x=field[:split].tolist(),
                    y=signal[:split].tolist(),
                    mode='lines+markers',
                    name='descending',
                ),
                go.Scatter(
                    x=field[split:].tolist(),
                    y=signal[split:].tolist(),
                    mode='lines+markers',
                    name='ascending',
                ),
            ]
        )
        figure.update_layout(
            title=self.magnetisation_title(),
            xaxis_title='H [kA/m]',
            yaxis_title='Signal [V]',
            xaxis_showgrid=True,
            xaxis_zeroline=True,
            xaxis_zerolinecolor='black',
            xaxis_zerolinewidth=2,
            yaxis_showgrid=True,
            yaxis_zeroline=True,
            yaxis_zerolinecolor='black',
            yaxis_zerolinewidth=2,
        )
        return figure.to_plotly_json()

    def normalize(self, archive, logger):
        self.technique = VSM_TECHNIQUE
        super().normalize(archive, logger)
        figure = self.magnetisation_figure()
        self.figures = (
            [PlotlyFigure(label='Hysteresis loop', figure=figure)] if figure else []
        )


m_package.__init_metainfo__()
